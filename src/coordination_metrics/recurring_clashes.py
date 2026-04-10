"""Metric 2: Recurring Clash Rate.

Detects clashes that reappear at or near previously-resolved locations.
A high recurrence rate signals that the root cause was not addressed --
the discipline either did not receive the resolution or ignored it.

Matching strategies (in priority order):
    1. **GUID match**: If clash points carry BCF persistent IDs (``guid``
       field), exact GUID matching is attempted first.
    2. **Hungarian algorithm**: Optimal bipartite matching via
       ``scipy.optimize.linear_sum_assignment`` on the full distance matrix.
       Falls back to greedy nearest-neighbour if scipy is unavailable.
    3. **Coordinate shift detection**: Before spatial matching, the median
       shift vector between resolved and new centroids is computed. If the
       median shift exceeds 100 mm, a warning is emitted and the shift is
       corrected before matching.

Usage:
    >>> from coordination_metrics import extract_clash_points, detect_recurrences
    >>> prev = extract_clash_points("round1.xml")
    >>> curr = extract_clash_points("round2.xml")
    >>> result = detect_recurrences(prev, curr, threshold_mm=500)
    >>> print(f"Recurrence rate: {result['recurrence_rate_pct']:.1f}%")
"""

from __future__ import annotations

import math
import warnings
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Sequence, Union

import numpy as np

from coordination_metrics.core import ClashPoint, HealthLevel

# Try to import scipy for optimal matching; fall back to greedy
try:
    from scipy.optimize import linear_sum_assignment as _scipy_lsa

    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False


def extract_clash_points(xml_path: Union[str, Path]) -> list[ClashPoint]:
    """Extract individual clash points with 3-D coordinates from a Navisworks XML.

    Args:
        xml_path: Path to a Navisworks Clash Detective XML export.

    Returns:
        List of ClashPoint objects with populated coordinates.
    """
    xml_path = Path(xml_path)
    tree = ET.parse(xml_path)
    root = tree.getroot()
    points: list[ClashPoint] = []

    for test in root.iter("clashtest"):
        test_name = test.get("name", "Unknown")
        for result in test.iter("clashresult"):
            clash_id = result.get("name", "")
            status = (result.get("status") or "new").lower()
            description = result.get("description", "")
            guid = result.get("guid") or result.get("Guid") or None

            # Extract position from clashpoint/pos3f
            pos = result.find(".//pos3f")
            if pos is not None:
                x = float(pos.get("x", 0))
                y = float(pos.get("y", 0))
                z = float(pos.get("z", 0))
            else:
                # Fall back to gridlocation or skip
                continue

            points.append(
                ClashPoint(
                    clash_id=clash_id,
                    x=x,
                    y=y,
                    z=z,
                    status=status,
                    test_name=test_name,
                    description=description,
                    guid=guid,
                )
            )

    return points


def _euclidean_distance(a: ClashPoint, b: ClashPoint) -> float:
    """Compute 3-D Euclidean distance between two clash points."""
    return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2)


# ---------------------------------------------------------------------------
# Coordinate shift detection
# ---------------------------------------------------------------------------

def _points_to_array(points: Sequence[ClashPoint]) -> np.ndarray:
    """Convert clash points to (N, 3) numpy array."""
    return np.array([[p.x, p.y, p.z] for p in points], dtype=np.float64)


def _compute_median_shift(
    resolved: Sequence[ClashPoint],
    new_or_active: Sequence[ClashPoint],
    threshold_mm: float = 500.0,
) -> tuple[np.ndarray, float]:
    """Compute the median shift vector from nearest-neighbour pairs.

    Uses vectorized numpy distance computation for O(n*m) with fast
    C-level operations instead of Python loops.

    Returns:
        (shift_vector [3], shift_magnitude_mm)
    """
    if not resolved or not new_or_active:
        return np.zeros(3), 0.0

    max_pair_dist = threshold_mm * 10
    res_pts = _points_to_array(resolved)    # (n, 3)
    new_pts = _points_to_array(new_or_active)  # (m, 3)

    # Vectorized nearest-neighbour: try scipy KDTree first, fallback to numpy
    try:
        from scipy.spatial import cKDTree
        tree = cKDTree(new_pts)
        dists, indices = tree.query(res_pts)  # O(n log m)
    except ImportError:
        # Numpy fallback: compute pairwise distances in chunks
        dists = np.empty(len(res_pts))
        indices = np.empty(len(res_pts), dtype=int)
        CHUNK = 1000
        for i0 in range(0, len(res_pts), CHUNK):
            i1 = min(i0 + CHUNK, len(res_pts))
            diff = res_pts[i0:i1, None, :] - new_pts[None, :, :]  # (chunk, m, 3)
            d = np.sqrt((diff ** 2).sum(axis=2))  # (chunk, m)
            indices[i0:i1] = d.argmin(axis=1)
            dists[i0:i1] = d.min(axis=1)

    mask = dists <= max_pair_dist
    if not mask.any():
        return np.zeros(3), 0.0

    deltas = new_pts[indices[mask]] - res_pts[mask]  # (k, 3)
    median_shift = np.median(deltas, axis=0)
    magnitude = float(np.linalg.norm(median_shift))
    return median_shift, magnitude


def _apply_shift_correction(
    new_or_active: Sequence[ClashPoint],
    shift: np.ndarray,
) -> list[ClashPoint]:
    """Return a copy of clash points with the shift subtracted."""
    corrected = []
    for p in new_or_active:
        corrected.append(ClashPoint(
            clash_id=p.clash_id,
            x=p.x - float(shift[0]),
            y=p.y - float(shift[1]),
            z=p.z - float(shift[2]),
            status=p.status,
            test_name=p.test_name,
            description=p.description,
            guid=p.guid,
        ))
    return corrected


# ---------------------------------------------------------------------------
# GUID matching
# ---------------------------------------------------------------------------

def _match_by_guid(
    resolved: list[ClashPoint],
    new_or_active: list[ClashPoint],
) -> tuple[list[tuple[str, str, float]], set[str], set[str]]:
    """Match clashes by GUID. Returns (pairs, matched_resolved_ids, matched_current_ids)."""
    pairs: list[tuple[str, str, float]] = []
    matched_resolved: set[str] = set()
    matched_current: set[str] = set()

    # Build GUID -> point maps
    resolved_by_guid: dict[str, ClashPoint] = {}
    for p in resolved:
        if p.guid:
            resolved_by_guid[p.guid] = p

    current_by_guid: dict[str, ClashPoint] = {}
    for p in new_or_active:
        if p.guid:
            current_by_guid[p.guid] = p

    for guid, res_pt in resolved_by_guid.items():
        if guid in current_by_guid:
            cur_pt = current_by_guid[guid]
            dist = _euclidean_distance(res_pt, cur_pt)
            pairs.append((res_pt.clash_id, cur_pt.clash_id, round(dist, 1)))
            matched_resolved.add(res_pt.clash_id)
            matched_current.add(cur_pt.clash_id)

    return pairs, matched_resolved, matched_current


# ---------------------------------------------------------------------------
# Spatial matching: Hungarian (optimal) or greedy (fallback)
# ---------------------------------------------------------------------------

def _build_distance_matrix(
    resolved: list[ClashPoint],
    new_or_active: list[ClashPoint],
) -> np.ndarray:
    """Build the full distance matrix between resolved and current points.

    Uses vectorized numpy computation. Falls back to scipy.spatial.distance.cdist
    when available for optimal performance on large sets.
    """
    res_pts = _points_to_array(resolved)    # (n, 3)
    new_pts = _points_to_array(new_or_active)  # (m, 3)

    try:
        from scipy.spatial.distance import cdist
        return cdist(res_pts, new_pts)  # (n, m), Euclidean
    except ImportError:
        # Numpy fallback: chunked to control memory
        n_res = len(resolved)
        n_cur = len(new_or_active)
        dist = np.empty((n_res, n_cur), dtype=np.float64)
        CHUNK = 500
        for i0 in range(0, n_res, CHUNK):
            i1 = min(i0 + CHUNK, n_res)
            diff = res_pts[i0:i1, None, :] - new_pts[None, :, :]
            dist[i0:i1] = np.sqrt((diff ** 2).sum(axis=2))
        return dist


def _hungarian_matching(
    resolved: list[ClashPoint],
    new_or_active: list[ClashPoint],
    threshold_mm: float,
) -> list[tuple[str, str, float]]:
    """Optimal bipartite matching using the Hungarian algorithm."""
    if not resolved or not new_or_active:
        return []

    dist_matrix = _build_distance_matrix(resolved, new_or_active)

    # Replace inf with a large value for scipy (it doesn't handle inf well)
    large_val = threshold_mm * 100
    safe_matrix = np.where(np.isinf(dist_matrix), large_val, dist_matrix)

    row_ind, col_ind = _scipy_lsa(safe_matrix)

    pairs: list[tuple[str, str, float]] = []
    for r, c in zip(row_ind, col_ind):
        d = float(dist_matrix[r, c])
        if d <= threshold_mm:
            pairs.append((resolved[r].clash_id, new_or_active[c].clash_id, round(d, 1)))

    return pairs


def _greedy_matching(
    resolved: list[ClashPoint],
    new_or_active: list[ClashPoint],
    threshold_mm: float,
) -> list[tuple[str, str, float]]:
    """Greedy nearest-neighbour matching (fallback when scipy unavailable)."""
    if not resolved or not new_or_active:
        return []

    pairs: list[tuple[str, str, float]] = []
    matched_current: set[str] = set()

    for prev_clash in resolved:
        best_dist = float("inf")
        best_match: ClashPoint | None = None

        for curr_clash in new_or_active:
            if curr_clash.clash_id in matched_current:
                continue
            dist = _euclidean_distance(prev_clash, curr_clash)
            if dist < best_dist:
                best_dist = dist
                best_match = curr_clash

        if best_match is not None and best_dist <= threshold_mm:
            pairs.append(
                (prev_clash.clash_id, best_match.clash_id, round(best_dist, 1))
            )
            matched_current.add(best_match.clash_id)

    return pairs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_recurrences(
    previous: Sequence[ClashPoint],
    current: Sequence[ClashPoint],
    threshold_mm: float = 500.0,
    model_units: str = "mm",
) -> dict:
    """Detect clashes in the current round that recur near previously-resolved locations.

    Matching priority:
        1. GUID-based exact matching (if ``guid`` fields present).
        2. Spatial matching via Hungarian algorithm (optimal) or greedy
           nearest-neighbour (fallback).
        3. Coordinate shift detection with automatic correction.

    Args:
        previous: Clash points from the earlier round.
        current: Clash points from the later round.
        threshold_mm: Maximum distance (mm) to consider a recurrence.
        model_units: Hint for model units (default "mm"). If "m", coordinates
            are scaled to mm internally.

    Returns:
        Dictionary with:
            recurrence_rate_pct: Percentage of resolved clashes that recurred.
            recurring_count: Number of recurrences found.
            resolved_count: Number of resolved clashes checked.
            recurring_pairs: List of (previous_id, current_id, distance_mm) tuples.
            matching_method: "guid", "hungarian", or "greedy".
            shift_detected: Whether a coordinate shift was detected.
            shift_magnitude_mm: Magnitude of detected shift (0 if none).
            shift_warning: Warning message if shift > 100mm.
            health_level: Traffic-light classification.
            interpretation: Human-readable assessment.
    """
    # Unit conversion
    unit_scale = 1.0
    if model_units.lower() == "m":
        unit_scale = 1000.0
    elif model_units.lower() == "ft":
        unit_scale = 304.8

    if unit_scale != 1.0:
        previous = [
            ClashPoint(p.clash_id, p.x * unit_scale, p.y * unit_scale,
                       p.z * unit_scale, p.status, p.test_name, p.description, p.guid)
            for p in previous
        ]
        current = [
            ClashPoint(p.clash_id, p.x * unit_scale, p.y * unit_scale,
                       p.z * unit_scale, p.status, p.test_name, p.description, p.guid)
            for p in current
        ]

    resolved = [p for p in previous if p.status == "resolved"]
    new_or_active = [c for c in current if c.status in ("new", "active")]

    if not resolved:
        return {
            "recurrence_rate_pct": 0.0,
            "recurring_count": 0,
            "resolved_count": 0,
            "recurring_pairs": [],
            "matching_method": None,
            "shift_detected": False,
            "shift_magnitude_mm": 0.0,
            "shift_warning": None,
            "health_level": HealthLevel.HEALTHY.value,
            "interpretation": "No resolved clashes to check for recurrence.",
        }

    # ---- Phase 1: GUID matching ----
    guid_pairs, matched_res_ids, matched_cur_ids = _match_by_guid(
        resolved, new_or_active
    )

    # Filter out already-matched points for spatial phase
    remaining_resolved = [p for p in resolved if p.clash_id not in matched_res_ids]
    remaining_current = [p for p in new_or_active if p.clash_id not in matched_cur_ids]

    # ---- Phase 2: Coordinate shift detection ----
    shift_vec, shift_mag = _compute_median_shift(
        remaining_resolved, remaining_current, threshold_mm
    )
    shift_detected = shift_mag > 100.0
    shift_warning: str | None = None

    if shift_detected:
        shift_warning = (
            f"Median coordinate shift of {shift_mag:.0f}mm detected -- "
            f"models may have been repositioned. Applying correction."
        )
        warnings.warn(shift_warning, UserWarning, stacklevel=2)
        remaining_current = _apply_shift_correction(remaining_current, shift_vec)

    # ---- Phase 3: Spatial matching ----
    matching_method: str
    if remaining_resolved and remaining_current:
        if _HAS_SCIPY:
            spatial_pairs = _hungarian_matching(
                remaining_resolved, remaining_current, threshold_mm
            )
            matching_method = "hungarian" if not guid_pairs else "guid+hungarian"
        else:
            spatial_pairs = _greedy_matching(
                remaining_resolved, remaining_current, threshold_mm
            )
            matching_method = "greedy" if not guid_pairs else "guid+greedy"
            if not guid_pairs:
                warnings.warn(
                    "scipy not available -- using greedy matching. "
                    "Install scipy for optimal Hungarian algorithm matching.",
                    UserWarning,
                    stacklevel=2,
                )
    else:
        spatial_pairs = []
        matching_method = "guid" if guid_pairs else "none"

    all_pairs = guid_pairs + spatial_pairs
    recurrence_rate = (len(all_pairs) / len(resolved)) * 100.0

    if recurrence_rate <= 10:
        health = HealthLevel.HEALTHY
        interpretation = (
            f"{recurrence_rate:.0f}% recurrence rate -- "
            f"resolutions are holding."
        )
    elif recurrence_rate <= 25:
        health = HealthLevel.AT_RISK
        interpretation = (
            f"{recurrence_rate:.0f}% recurrence rate -- "
            f"some disciplines may not be actioning resolutions."
        )
    else:
        health = HealthLevel.CRITICAL
        interpretation = (
            f"{recurrence_rate:.0f}% recurrence rate -- "
            f"coordination feedback loop is broken."
        )

    return {
        "recurrence_rate_pct": round(recurrence_rate, 1),
        "recurring_count": len(all_pairs),
        "resolved_count": len(resolved),
        "recurring_pairs": all_pairs,
        "matching_method": matching_method,
        "shift_detected": shift_detected,
        "shift_magnitude_mm": round(shift_mag, 1),
        "shift_warning": shift_warning,
        "health_level": health.value,
        "interpretation": interpretation,
    }


def recurrence_to_score(recurrence_rate_pct: float) -> float:
    """Convert a recurrence rate to a 0-100 health score.

    Args:
        recurrence_rate_pct: Recurrence rate as a percentage (0-100).

    Returns:
        Score where 100 = no recurrences, 0 = all resolved clashes recurred.
    """
    return max(0.0, min(100.0, 100.0 - recurrence_rate_pct))
