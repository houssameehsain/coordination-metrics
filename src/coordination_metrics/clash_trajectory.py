"""Metric 1: Hard Clash Trajectory Slope.

Tracks how total hard clashes evolve across successive detection rounds.
A positive slope means clashes are accumulating faster than they are being
resolved -- the single strongest leading indicator of coordination failure.

Note: Clash detection tools produce significant false positive rates --
studies suggest up to 60% of detected clashes may not require action.
Consider filtering to actionable clashes before running trajectory analysis.

Industry context:
    GIRI research shows 70 % of construction defects originate in design.
    Monitoring the *slope* of the clash curve -- not just the absolute count --
    gives teams a 4-8 week early warning before problems cascade to site.

Models:
    - **Exponential decay**: N(t) = N0 * exp(-lambda*t), the primary model.
      lambda > 0.5 = healthy, 0.2-0.5 = slowing, < 0.2 = stalled.
    - **Linear regression**: kept as a secondary metric for backward compat.
    - **Changepoint detection**: flags rounds where clash count spikes >20%
      above the prior round (e.g. new design scope introduced).
    - **Zero-clash projection**: estimates when clashes will reach a
      configurable threshold (default 5).

Usage:
    >>> from coordination_metrics import build_trajectory, compute_trajectory_slope
    >>> summaries = build_trajectory(["round1.xml", "round2.xml", "round3.xml"])
    >>> result = compute_trajectory_slope(summaries)
    >>> print(f"Decay rate: {result['decay_rate']:.3f}")
"""

from __future__ import annotations

import math
import warnings
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path
from typing import Sequence, Union

import numpy as np

from coordination_metrics.core import ClashRoundSummary, HealthLevel


def _parse_round_from_xml(xml_path: Union[str, Path]) -> ClashRoundSummary:
    """Parse a single Navisworks Clash Detective XML export.

    Args:
        xml_path: Path to the XML file.

    Returns:
        A ClashRoundSummary with counts by status.
    """
    xml_path = Path(xml_path)
    tree = ET.parse(xml_path)
    root = tree.getroot()

    counts: dict[str, int] = {"new": 0, "active": 0, "reviewed": 0, "resolved": 0}

    for result in root.iter("clashresult"):
        status = (result.get("status") or "new").lower()
        if status in counts:
            counts[status] += 1
        else:
            counts["active"] += 1  # unknown statuses count as active

    # Try to extract date from the XML; fall back to file modification time
    round_date_str = root.get("date") or root.get("created")
    if round_date_str:
        try:
            round_date = date.fromisoformat(round_date_str[:10])
        except ValueError:
            round_date = date.fromtimestamp(xml_path.stat().st_mtime)
    else:
        round_date = date.fromtimestamp(xml_path.stat().st_mtime)

    return ClashRoundSummary.from_counts(
        round_date=round_date,
        round_label=f"{xml_path.stem} -- {round_date.isoformat()}",
        **counts,
    )


def build_trajectory(
    round_exports: Sequence[Union[str, Path]],
) -> list[ClashRoundSummary]:
    """Build an ordered trajectory from multiple clash-round exports.

    Args:
        round_exports: Paths to Navisworks XML exports, one per round.
            They will be sorted by date automatically.

    Returns:
        List of ClashRoundSummary objects sorted chronologically.
    """
    summaries = [_parse_round_from_xml(p) for p in round_exports]
    summaries.sort(key=lambda s: s.round_date)
    return summaries


# ---------------------------------------------------------------------------
# Exponential decay fitting
# ---------------------------------------------------------------------------

def _fit_exponential_decay(
    days: np.ndarray,
    totals: np.ndarray,
) -> tuple[float, float, float] | None:
    """Fit N(t) = N0 * exp(-lambda * t) using log-linearisation.

    Returns (N0, decay_rate, r_squared) or None if fitting fails.
    """
    # Need positive values for log
    if np.any(totals <= 0):
        return None
    if len(totals) < 2:
        return None

    log_totals = np.log(totals)

    # Linear regression on log(N) = log(N0) - lambda * t
    try:
        coeffs = np.polyfit(days, log_totals, 1)
    except (np.linalg.LinAlgError, ValueError):
        return None

    neg_lambda = float(coeffs[0])
    log_n0 = float(coeffs[1])
    n0 = math.exp(log_n0)
    decay_rate = -neg_lambda  # positive lambda means decay

    # R-squared in log space
    predicted = np.polyval(coeffs, days)
    ss_res = float(np.sum((log_totals - predicted) ** 2))
    ss_tot = float(np.sum((log_totals - log_totals.mean()) ** 2))
    r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    return n0, decay_rate, r_squared


def detect_changepoints(
    summaries: Sequence[ClashRoundSummary],
    spike_threshold: float = 0.20,
) -> list[dict]:
    """Identify rounds where the clash count spikes above the prior round.

    A changepoint is flagged when the current round's total is more than
    ``spike_threshold`` (default 20%) higher than the previous round.

    Args:
        summaries: Chronologically ordered clash round summaries.
        spike_threshold: Fractional increase to trigger a changepoint
            (0.20 = 20%).

    Returns:
        List of dicts with keys: round_index, round_label, round_date,
        previous_total, current_total, pct_increase.
    """
    changepoints: list[dict] = []
    for i in range(1, len(summaries)):
        prev_total = summaries[i - 1].total
        curr_total = summaries[i].total
        if prev_total > 0 and curr_total > prev_total * (1 + spike_threshold):
            pct_inc = ((curr_total - prev_total) / prev_total) * 100.0
            changepoints.append({
                "round_index": i,
                "round_label": summaries[i].round_label,
                "round_date": summaries[i].round_date.isoformat(),
                "previous_total": prev_total,
                "current_total": curr_total,
                "pct_increase": round(pct_inc, 1),
            })
    return changepoints


def projected_zero_date(
    summaries: Sequence[ClashRoundSummary],
    threshold: int = 5,
) -> dict:
    """Project when clashes will reach near-zero using exponential decay.

    Uses the formula: t_zero = -ln(threshold / N0) / lambda

    Args:
        summaries: Chronologically ordered clash round summaries.
        threshold: Clash count considered "near zero" (default 5).

    Returns:
        Dictionary with projected_date, days_from_last_round, model_used,
        and a warning if the model does not fit well.
    """
    if len(summaries) < 2:
        return {
            "projected_date": None,
            "days_from_last_round": None,
            "model_used": None,
            "warning": "Need at least 2 rounds for projection.",
        }

    base_date = summaries[0].round_date
    days = np.array([(s.round_date - base_date).days for s in summaries], dtype=float)
    totals = np.array([s.total for s in summaries], dtype=float)

    if days[-1] - days[0] == 0:
        return {
            "projected_date": None,
            "days_from_last_round": None,
            "model_used": None,
            "warning": "All rounds on the same day.",
        }

    fit = _fit_exponential_decay(days, totals)
    if fit is not None:
        n0, decay_rate, r_sq = fit
        if decay_rate > 0 and n0 > threshold:
            try:
                t_zero = -math.log(threshold / n0) / decay_rate
            except (ValueError, ZeroDivisionError):
                t_zero = None

            if t_zero is not None and t_zero >= 0:
                proj_date = base_date + timedelta(days=int(t_zero))
                days_from_last = (proj_date - summaries[-1].round_date).days
                return {
                    "projected_date": proj_date.isoformat(),
                    "days_from_last_round": max(0, days_from_last),
                    "model_used": "exponential_decay",
                    "decay_rate": round(decay_rate, 4),
                    "n0": round(n0, 1),
                    "r_squared": round(r_sq, 4),
                    "warning": None,
                }

    # Fallback: linear projection
    coeffs = np.polyfit(days, totals, 1)
    slope = float(coeffs[0])
    intercept = float(coeffs[1])
    if slope < 0:
        t_zero_lin = (threshold - intercept) / slope
        if t_zero_lin >= 0:
            proj_date = base_date + timedelta(days=int(t_zero_lin))
            days_from_last = (proj_date - summaries[-1].round_date).days
            return {
                "projected_date": proj_date.isoformat(),
                "days_from_last_round": max(0, days_from_last),
                "model_used": "linear",
                "slope": round(slope, 4),
                "warning": "Exponential fit failed; using linear projection.",
            }

    return {
        "projected_date": None,
        "days_from_last_round": None,
        "model_used": None,
        "warning": "Clashes are not decreasing -- cannot project zero date.",
    }


def compute_trajectory_slope(
    summaries: Sequence[ClashRoundSummary],
) -> dict:
    """Compute trajectory metrics using exponential decay (primary) and
    linear regression (secondary).

    Args:
        summaries: Chronologically ordered clash round summaries.

    Returns:
        Dictionary with:
            slope: Linear clashes per day (backward compat).
            intercept: Linear projected count at day 0.
            r_squared: Linear R-squared.
            decay_rate: Exponential lambda (positive = decaying).
            decay_n0: Exponential N0.
            decay_r_squared: Exponential R-squared.
            decay_health: "healthy" / "slowing" / "stalled" based on lambda.
            changepoints: List of detected scope-change rounds.
            health_level: Traffic-light classification.
            rounds: Number of data points used.
            interpretation: Human-readable assessment.
    """
    if len(summaries) < 2:
        return {
            "slope": 0.0,
            "intercept": summaries[0].total if summaries else 0,
            "r_squared": 0.0,
            "decay_rate": None,
            "decay_n0": None,
            "decay_r_squared": None,
            "decay_health": None,
            "changepoints": [],
            "health_level": HealthLevel.AT_RISK.value,
            "rounds": len(summaries),
            "interpretation": "Insufficient data -- need at least 2 rounds.",
        }

    base_date = summaries[0].round_date
    days = np.array([(s.round_date - base_date).days for s in summaries], dtype=float)
    totals = np.array([s.total for s in summaries], dtype=float)

    # Handle case where all rounds are on the same day
    if days[-1] - days[0] == 0:
        return {
            "slope": 0.0,
            "intercept": float(totals.mean()),
            "r_squared": 0.0,
            "decay_rate": None,
            "decay_n0": None,
            "decay_r_squared": None,
            "decay_health": None,
            "changepoints": [],
            "health_level": HealthLevel.AT_RISK.value,
            "rounds": len(summaries),
            "interpretation": "All rounds on the same day -- cannot compute slope.",
        }

    # ---- Linear regression (backward compat) ----
    coeffs = np.polyfit(days, totals, 1)
    slope, intercept = float(coeffs[0]), float(coeffs[1])
    predicted = np.polyval(coeffs, days)
    ss_res = float(np.sum((totals - predicted) ** 2))
    ss_tot = float(np.sum((totals - totals.mean()) ** 2))
    r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    # ---- Exponential decay fit ----
    fit = _fit_exponential_decay(days, totals)
    if fit is not None:
        decay_n0, decay_rate, decay_r_sq = fit
    else:
        decay_n0 = None
        decay_rate = None
        decay_r_sq = None

    # ---- Decay health classification ----
    if decay_rate is not None and decay_rate > 0:
        if decay_rate > 0.5:
            decay_health = "healthy"
        elif decay_rate >= 0.2:
            decay_health = "slowing"
        else:
            decay_health = "stalled"
    else:
        decay_health = None

    # ---- Changepoint detection ----
    changepoints = detect_changepoints(summaries)

    # ---- Overall health classification (considers both models) ----
    if decay_health == "healthy":
        health = HealthLevel.HEALTHY
        interpretation = (
            f"Exponential decay rate {decay_rate:.3f} (healthy) -- "
            f"clashes converging rapidly."
        )
    elif decay_health == "slowing":
        health = HealthLevel.AT_RISK
        interpretation = (
            f"Exponential decay rate {decay_rate:.3f} (slowing) -- "
            f"resolution pace needs attention."
        )
    elif slope <= -1.0:
        health = HealthLevel.HEALTHY
        interpretation = (
            f"Clashes decreasing at {abs(slope):.1f}/day -- "
            f"coordination is effective."
        )
    elif slope <= 2.0:
        health = HealthLevel.AT_RISK
        interpretation = (
            f"Clashes roughly stable ({slope:+.1f}/day) -- "
            f"monitor closely for drift."
        )
    else:
        health = HealthLevel.CRITICAL
        interpretation = (
            f"Clashes increasing at {slope:.1f}/day -- "
            f"coordination process needs urgent review."
        )

    if changepoints:
        interpretation += (
            f" {len(changepoints)} changepoint(s) detected -- "
            f"possible scope changes."
        )

    return {
        "slope": slope,
        "intercept": intercept,
        "r_squared": round(r_squared, 4),
        "decay_rate": round(decay_rate, 4) if decay_rate is not None else None,
        "decay_n0": round(decay_n0, 1) if decay_n0 is not None else None,
        "decay_r_squared": round(decay_r_sq, 4) if decay_r_sq is not None else None,
        "decay_health": decay_health,
        "changepoints": changepoints,
        "health_level": health.value,
        "rounds": len(summaries),
        "interpretation": interpretation,
    }


def trajectory_to_score(slope: float) -> float:
    """Convert a trajectory slope to a 0-100 health score.

    Args:
        slope: Clashes per day (from compute_trajectory_slope).

    Returns:
        Score where 100 = strongly decreasing, 0 = rapidly increasing.
    """
    # Map slope from [-5, +10] to [100, 0], clamped
    score = 100.0 - (slope + 5.0) * (100.0 / 15.0)
    return max(0.0, min(100.0, score))
