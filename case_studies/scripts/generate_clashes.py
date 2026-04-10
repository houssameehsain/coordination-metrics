#!/usr/bin/env python3
"""Generate clash detection data from IFC models.

Uses IfcOpenShell to perform bounding-box clash detection between
discipline pairs (e.g., MEP vs Structure). Outputs Navisworks-compatible
XML format that coordination-metrics can parse directly.

Usage:
    python generate_clashes.py --project wbdg_duplex
    python generate_clashes.py --project schependomlaan --tolerance 25
    python generate_clashes.py --project wbdg_duplex --rounds 5
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

# IfcOpenShell is optional - fall back to geometry-free mode
try:
    import ifcopenshell
    import ifcopenshell.geom
    HAS_IFC = True
except ImportError:
    HAS_IFC = False
    print("WARNING: ifcopenshell not installed. Using bounding-box estimation mode.")
    print("Install with: pip install ifcopenshell")

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROJECTS = {
    "wbdg_duplex": PROJECT_ROOT / "wbdg_duplex",
    "wbdg_clinic": PROJECT_ROOT / "wbdg_clinic",
    "schependomlaan": PROJECT_ROOT / "schependomlaan",
}

# Discipline detection from IFC filename or schema
DISCIPLINE_KEYWORDS = {
    "architectural": "ARC",
    "architecture": "ARC",
    "arc": "ARC",
    "structural": "STR",
    "structure": "STR",
    "str": "STR",
    "mechanical": "MEP",
    "mech": "MEP",
    "mep": "MEP",
    "hvac": "MEP",
    "electrical": "ELE",
    "elec": "ELE",
    "ele": "ELE",
    "plumbing": "PLB",
    "plumb": "PLB",
    "plb": "PLB",
    "fire": "FPR",
    "sprinkler": "FPR",
}

# Clash test pairs (discipline A vs discipline B)
CLASH_TEST_PAIRS = [
    ("MEP", "STR", "MEP-Structure"),
    ("ELE", "STR", "Electrical-Structure"),
    ("PLB", "STR", "Plumbing-Structure"),
    ("MEP", "ARC", "MEP-Architecture"),
    ("ELE", "MEP", "Electrical-Mechanical"),
    ("PLB", "MEP", "Plumbing-Mechanical"),
    ("ELE", "PLB", "Electrical-Plumbing"),
]


@dataclass
class BBox:
    """Axis-aligned bounding box."""
    min_x: float
    min_y: float
    min_z: float
    max_x: float
    max_y: float
    max_z: float
    element_id: str = ""
    element_type: str = ""

    def intersects(self, other: "BBox", tolerance: float = 0.0) -> bool:
        """Check if two bounding boxes overlap within tolerance (mm)."""
        return (
            self.min_x - tolerance <= other.max_x
            and self.max_x + tolerance >= other.min_x
            and self.min_y - tolerance <= other.max_y
            and self.max_y + tolerance >= other.min_y
            and self.min_z - tolerance <= other.max_z
            and self.max_z + tolerance >= other.min_z
        )

    @property
    def center(self) -> tuple[float, float, float]:
        return (
            (self.min_x + self.max_x) / 2,
            (self.min_y + self.max_y) / 2,
            (self.min_z + self.max_z) / 2,
        )


# Single-letter discipline codes used as standalone tokens in filenames
# (e.g., "Duplex_A_20110907.ifc" where _A_ = Architectural)
_TOKEN_DISCIPLINES = {
    "a": "ARC",
    "s": "STR",
    "m": "MEP",
    "e": "ELE",
    "p": "PLB",
}


def detect_discipline(filepath: Path) -> str:
    """Detect discipline from filename.

    Checks substring keywords first, then falls back to single-letter
    token matching (split on underscores/hyphens) for naming conventions
    like the WBDG ``Duplex_A_20110907.ifc`` format.
    """
    name = filepath.stem.lower()
    for keyword, disc in DISCIPLINE_KEYWORDS.items():
        if keyword in name:
            return disc
    # Fall back to single-letter token matching
    tokens = set(name.replace("-", "_").split("_"))
    for token, disc in _TOKEN_DISCIPLINES.items():
        if token in tokens:
            return disc
    return "UNK"


def extract_bboxes_ifcopenshell(ifc_path: Path) -> list[BBox]:
    """Extract bounding boxes from IFC file using IfcOpenShell geometry.

    Uses DISABLE_TRIANGULATION for 10-50x speedup — we only need
    bounding boxes, not full mesh geometry.
    """
    if not HAS_IFC:
        return []

    model = ifcopenshell.open(str(ifc_path))
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)
    # Skip full mesh triangulation — only need bounding box extents
    try:
        settings.set(settings.DISABLE_TRIANGULATION, True)
    except AttributeError:
        pass  # older ifcopenshell versions may not have this flag

    bboxes = []
    scale = 1000.0  # m -> mm

    # Process physical building elements + distribution elements (MEP)
    element_types = ["IfcBuildingElement", "IfcDistributionElement",
                     "IfcFlowSegment", "IfcFlowTerminal", "IfcFlowFitting",
                     "IfcFlowController"]
    seen_ids: set[str] = set()

    for etype in element_types:
        for product in model.by_type(etype):
            gid = product.GlobalId
            if gid in seen_ids:
                continue
            seen_ids.add(gid)
            try:
                shape = ifcopenshell.geom.create_shape(settings, product)
                verts = shape.geometry.verts
                if not verts:
                    continue

                xs = verts[0::3]
                ys = verts[1::3]
                zs = verts[2::3]

                bbox = BBox(
                    min_x=min(xs) * scale,
                    min_y=min(ys) * scale,
                    min_z=min(zs) * scale,
                    max_x=max(xs) * scale,
                    max_y=max(ys) * scale,
                    max_z=max(zs) * scale,
                    element_id=gid,
                    element_type=product.is_a(),
                )
                bboxes.append(bbox)
            except Exception:
                continue

    return bboxes


def extract_bboxes_placement(ifc_path: Path) -> list[BBox]:
    """Extract approximate bounding boxes from IFC placement data (no geometry processing).

    Fallback when IfcOpenShell geometry engine is unavailable.
    Uses ObjectPlacement coordinates and assigns default element sizes by type.
    """
    if not HAS_IFC:
        return []

    model = ifcopenshell.open(str(ifc_path))

    # Default element sizes (half-dimensions in mm) by IFC type
    DEFAULT_SIZES = {
        "IfcWall": (100, 3000, 1500),
        "IfcColumn": (200, 200, 1500),
        "IfcBeam": (150, 3000, 250),
        "IfcSlab": (5000, 5000, 150),
        "IfcDoor": (500, 50, 1050),
        "IfcWindow": (600, 50, 600),
        "IfcPipeSegment": (50, 50, 1000),
        "IfcDuctSegment": (200, 200, 1000),
        "IfcCableCarrierSegment": (100, 50, 1000),
        "IfcFlowTerminal": (200, 200, 200),
        "IfcFlowSegment": (50, 50, 1000),
    }
    DEFAULT_HALF = (300, 300, 300)  # fallback

    bboxes = []
    for product in model.by_type("IfcProduct"):
        placement = product.ObjectPlacement
        if placement is None:
            continue
        try:
            # Extract placement coordinates
            loc = placement.RelativePlacement.Location.Coordinates
            x, y, z = float(loc[0]) * 1000, float(loc[1]) * 1000, float(loc[2]) * 1000

            ifc_type = product.is_a()
            half = DEFAULT_SIZES.get(ifc_type, DEFAULT_HALF)

            bbox = BBox(
                min_x=x - half[0], min_y=y - half[1], min_z=z - half[2],
                max_x=x + half[0], max_y=y + half[1], max_z=z + half[2],
                element_id=product.GlobalId,
                element_type=ifc_type,
            )
            bboxes.append(bbox)
        except (AttributeError, TypeError, IndexError):
            continue

    return bboxes


def run_clash_detection(
    bboxes_a: list[BBox],
    bboxes_b: list[BBox],
    test_name: str,
    tolerance_mm: float = 10.0,
) -> list[dict]:
    """Detect clashes between two sets of bounding boxes.

    Uses numpy-vectorized AABB intersection for O(n+m) memory and
    ~50x speedup over the naive O(n*m) Python loop.
    """
    if not bboxes_a or not bboxes_b:
        return []

    n_a, n_b = len(bboxes_a), len(bboxes_b)

    # Build numpy arrays of bbox bounds: [min_x, min_y, min_z, max_x, max_y, max_z]
    arr_a = np.array(
        [[b.min_x, b.min_y, b.min_z, b.max_x, b.max_y, b.max_z] for b in bboxes_a],
        dtype=np.float64,
    )
    arr_b = np.array(
        [[b.min_x, b.min_y, b.min_z, b.max_x, b.max_y, b.max_z] for b in bboxes_b],
        dtype=np.float64,
    )

    # Vectorized AABB intersection test:
    # For each axis: a.min - tol <= b.max AND a.max + tol >= b.min
    # Process in chunks to control memory (avoid n*m matrix for large sets)
    CHUNK = 2000  # process 2000 rows of A at a time
    clashes = []
    seen: set[tuple[str, str]] = set()

    for i0 in range(0, n_a, CHUNK):
        i1 = min(i0 + CHUNK, n_a)
        chunk_a = arr_a[i0:i1]  # shape (chunk, 6)

        # Broadcast intersection: chunk_a[:, None, :] vs arr_b[None, :, :]
        # min_a <= max_b + tol  AND  max_a >= min_b - tol  for each axis
        # chunk_a[:, :3] are mins, chunk_a[:, 3:] are maxes
        overlap = (
            (chunk_a[:, None, 0] - tolerance_mm <= arr_b[None, :, 3])
            & (chunk_a[:, None, 3] + tolerance_mm >= arr_b[None, :, 0])
            & (chunk_a[:, None, 1] - tolerance_mm <= arr_b[None, :, 4])
            & (chunk_a[:, None, 4] + tolerance_mm >= arr_b[None, :, 1])
            & (chunk_a[:, None, 2] - tolerance_mm <= arr_b[None, :, 5])
            & (chunk_a[:, None, 5] + tolerance_mm >= arr_b[None, :, 2])
        )  # shape (chunk, n_b), bool

        # Extract (i, j) pairs where overlap is True
        hit_i, hit_j = np.where(overlap)

        for idx in range(len(hit_i)):
            ai = i0 + int(hit_i[idx])
            bj = int(hit_j[idx])
            a = bboxes_a[ai]
            b = bboxes_b[bj]

            pair_key = (min(a.element_id, b.element_id),
                        max(a.element_id, b.element_id))
            if pair_key in seen:
                continue
            seen.add(pair_key)

            cx = (max(a.min_x, b.min_x) + min(a.max_x, b.max_x)) / 2
            cy = (max(a.min_y, b.min_y) + min(a.max_y, b.max_y)) / 2
            cz = (max(a.min_z, b.min_z) + min(a.max_z, b.max_z)) / 2

            clash_id = hashlib.md5(f"{pair_key}".encode()).hexdigest()[:12]

            clashes.append({
                "id": f"Clash-{clash_id}",
                "x": round(cx, 1),
                "y": round(cy, 1),
                "z": round(cz, 1),
                "element_a": a.element_id,
                "element_b": b.element_id,
                "type_a": a.element_type,
                "type_b": b.element_type,
                "test_name": test_name,
                "status": "new",
            })

    return clashes


# ---------------------------------------------------------------------------
# Literature-calibrated coordination simulation
# ---------------------------------------------------------------------------
#
# Resolution rates by discipline pair (Chahrour et al. 2021; Hu et al. 2019):
#   - Clashes involving rigid elements (structure) resolve faster because
#     the MEP side must reroute — clear ownership.
#   - MEP-MEP clashes are slower (shared ownership, negotiation needed).
#   - ARC clashes are moderate (layout flexibility).
_RESOLUTION_RATES_BY_TEST = {
    "MEP-Structure":        0.45,  # clear ownership: MEP reroutes
    "Electrical-Structure":  0.45,
    "Plumbing-Structure":    0.40,
    "MEP-Architecture":      0.35,  # moderate: layout negotiation
    "Electrical-Mechanical":  0.25,  # slow: shared MEP ownership
    "Plumbing-Mechanical":    0.25,
    "Electrical-Plumbing":    0.20,  # slowest: both must negotiate
}
_DEFAULT_RESOLUTION_RATE = 0.30

# Recurrence rates (Akponeware & Adamu 2017): 15-30% per project,
# translates to ~5-12% per round (some resolved clashes come back).
_RECURRENCE_RATES_BY_TEST = {
    "MEP-Structure":        0.05,  # low: structural resolution is final
    "Electrical-Structure":  0.05,
    "Plumbing-Structure":    0.06,
    "MEP-Architecture":      0.08,
    "Electrical-Mechanical":  0.12,  # high: scope changes, shared systems
    "Plumbing-Mechanical":    0.10,
    "Electrical-Plumbing":    0.10,
}
_DEFAULT_RECURRENCE_RATE = 0.08

# New discovery curve: non-monotonic (Chahrour et al. 2021)
# Peaks at round 2-3 as model maturity reveals hidden interfaces,
# then decays. Expressed as fraction of initial clash count.
_DISCOVERY_CURVE = [0.0, 0.08, 0.12, 0.10, 0.06, 0.03, 0.02, 0.01]

# Spatial batch resolution radius (mm): resolving one clash often
# fixes nearby clashes on the same run/route.
_BATCH_RADIUS_MM = 1500.0


def _spatial_distance(a: dict, b: dict) -> float:
    """Euclidean distance between two clash dicts."""
    return math.sqrt(
        (a["x"] - b["x"]) ** 2
        + (a["y"] - b["y"]) ** 2
        + (a["z"] - b["z"]) ** 2
    )


def simulate_coordination_rounds(
    initial_clashes: list[dict],
    num_rounds: int = 5,
    resolution_rate: float = 0.35,
    new_discovery_rate: float = 0.10,
    recurrence_rate: float = 0.08,
    seed: int = 42,
) -> list[list[dict]]:
    """Simulate coordination rounds with discipline-aware, spatially-correlated behaviour.

    Calibrated to published empirical data:
    - Discipline-specific resolution rates (Chahrour et al. 2021)
    - Spatial batch resolution: nearby clashes on same system co-resolve
    - Non-monotonic discovery curve: peaks at round 2-3, then decays
    - Recurrence with realistic spatial shifts (500-2000mm rerouting,
      not 50mm jitter) and discipline-specific rates (Akponeware & Adamu 2017)
    - ``resolution_rate`` and ``recurrence_rate`` args act as global
      multipliers on the per-test defaults (1.0 = use literature values)

    Returns list of clash lists, one per round.
    """
    rng = random.Random(seed)
    rounds = [initial_clashes]

    # Pre-compute spatial index for batch resolution: group by test
    initial_by_test: dict[str, list[dict]] = {}
    for c in initial_clashes:
        initial_by_test.setdefault(c["test_name"], []).append(c)

    # Normalise user-facing rate args to multipliers on the per-test defaults
    res_multiplier = resolution_rate / _DEFAULT_RESOLUTION_RATE
    rec_multiplier = recurrence_rate / _DEFAULT_RECURRENCE_RATE

    for round_num in range(1, num_rounds):
        prev = rounds[-1]
        current: list[dict] = []
        just_resolved: list[dict] = []  # track for batch co-resolution

        # Phase 1: Process each clash individually
        for clash in prev:
            test = clash["test_name"]
            base_res = _RESOLUTION_RATES_BY_TEST.get(test, _DEFAULT_RESOLUTION_RATE)
            eff_res = min(0.80, base_res * res_multiplier)

            base_rec = _RECURRENCE_RATES_BY_TEST.get(test, _DEFAULT_RECURRENCE_RATE)
            eff_rec = min(0.30, base_rec * rec_multiplier)

            if clash["status"] in ("new", "active"):
                if rng.random() < eff_res:
                    current.append({**clash, "status": "resolved"})
                    just_resolved.append(clash)
                elif rng.random() < 0.15:
                    current.append({**clash, "status": "reviewed"})
                else:
                    current.append({**clash, "status": "active"})

            elif clash["status"] == "reviewed":
                # Reviewed clashes resolve faster (already triaged)
                if rng.random() < min(0.85, eff_res * 1.5):
                    current.append({**clash, "status": "resolved"})
                    just_resolved.append(clash)
                else:
                    current.append({**clash, "status": "active"})

            elif clash["status"] == "resolved":
                if rng.random() < eff_rec:
                    # Recurrence with realistic spatial shift (rerouting)
                    # 500-2000mm shift represents actual design change,
                    # not the 50mm jitter that was tautological with 500mm
                    # detection threshold
                    shift = rng.uniform(800, 2500)
                    angle = rng.uniform(0, 2 * math.pi)
                    current.append({
                        **clash,
                        "status": "new",
                        "x": clash["x"] + shift * math.cos(angle),
                        "y": clash["y"] + shift * math.sin(angle),
                        "z": clash["z"] + rng.uniform(-300, 300),
                        "id": f"{clash['id']}-R{round_num}",
                    })
                # else: resolved clash drops off (stays resolved)

        # Phase 2: Spatial batch co-resolution (vectorized with numpy)
        # Clashes near a just-resolved clash get a resolution boost
        active_indices = [i for i, c in enumerate(current)
                          if c["status"] in ("new", "active")]
        if just_resolved and active_indices:
            # Group by test_name for efficient matching
            resolved_by_test: dict[str, np.ndarray] = {}
            for r in just_resolved:
                t = r["test_name"]
                if t not in resolved_by_test:
                    resolved_by_test[t] = []
                resolved_by_test[t].append([r["x"], r["y"], r["z"]])
            for t in resolved_by_test:
                resolved_by_test[t] = np.array(resolved_by_test[t])

            try:
                from scipy.spatial import cKDTree
                # Build KD-trees per test for O(n log n) nearest-neighbour
                trees = {t: cKDTree(coords) for t, coords in resolved_by_test.items()}
                for idx in active_indices:
                    c = current[idx]
                    tree = trees.get(c["test_name"])
                    if tree is None:
                        continue
                    dist, _ = tree.query([c["x"], c["y"], c["z"]])
                    if dist <= _BATCH_RADIUS_MM and rng.random() < 0.60:
                        current[idx] = {**c, "status": "resolved"}
            except ImportError:
                # Fallback: numpy vectorized distance (no scipy)
                for idx in active_indices:
                    c = current[idx]
                    coords = resolved_by_test.get(c["test_name"])
                    if coords is None or len(coords) == 0:
                        continue
                    pt = np.array([c["x"], c["y"], c["z"]])
                    dists = np.sqrt(((coords - pt) ** 2).sum(axis=1))
                    if dists.min() <= _BATCH_RADIUS_MM and rng.random() < 0.60:
                        current[idx] = {**c, "status": "resolved"}

        # Phase 3: New clash discoveries (non-monotonic curve)
        if round_num < len(_DISCOVERY_CURVE):
            discovery_frac = _DISCOVERY_CURVE[round_num]
        else:
            discovery_frac = 0.01  # minimal tail

        # Scale by user-facing discovery rate
        discovery_frac *= (new_discovery_rate / 0.10)
        num_new = max(0, int(len(initial_clashes) * discovery_frac))

        for i in range(num_new):
            template = rng.choice(initial_clashes)
            # New discoveries are genuinely new locations (not near old ones)
            current.append({
                **template,
                "status": "new",
                "id": f"New-R{round_num}-{i:03d}",
                "x": template["x"] + rng.uniform(-3000, 3000),
                "y": template["y"] + rng.uniform(-3000, 3000),
                "z": template["z"] + rng.uniform(-500, 500),
            })

        rounds.append(current)

    return rounds


def clashes_to_navisworks_xml(
    clashes: list[dict],
    round_label: str,
    output_path: Path,
    round_date: date | None = None,
) -> None:
    """Write clashes to Navisworks-compatible XML format.

    The output follows the Clash Detective XML schema that
    coordination-metrics parsers expect.
    """
    exchange = ET.Element("exchange")
    if round_date is not None:
        exchange.set("date", round_date.isoformat())
    batchtest = ET.SubElement(exchange, "batchtest")
    clashtests = ET.SubElement(batchtest, "clashtests")

    # Group clashes by test name
    by_test: dict[str, list[dict]] = {}
    for c in clashes:
        by_test.setdefault(c["test_name"], []).append(c)

    for test_name, test_clashes in by_test.items():
        clashtest = ET.SubElement(clashtests, "clashtest", name=test_name)
        clashresults = ET.SubElement(clashtest, "clashresults")

        for c in test_clashes:
            result = ET.SubElement(
                clashresults, "clashresult",
                name=c["id"],
                status=c["status"],
            )
            clashpoint = ET.SubElement(result, "clashpoint")
            ET.SubElement(
                clashpoint, "pos3f",
                x=str(c["x"]),
                y=str(c["y"]),
                z=str(c["z"]),
            )

    tree = ET.ElementTree(exchange)
    ET.indent(tree, space="  ")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(str(output_path), encoding="unicode", xml_declaration=True)


def main():
    parser = argparse.ArgumentParser(
        description="Generate clash detection data from IFC models"
    )
    parser.add_argument(
        "--project", required=True, choices=list(PROJECTS.keys()),
        help="Project to process"
    )
    parser.add_argument(
        "--tolerance", type=float, default=10.0,
        help="Clash tolerance in mm (default: 10)"
    )
    parser.add_argument(
        "--rounds", type=int, default=5,
        help="Number of coordination rounds to simulate (default: 5)"
    )
    parser.add_argument(
        "--resolution-rate", type=float, default=0.35,
        help="Fraction of clashes resolved per round (default: 0.35)"
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for simulation reproducibility"
    )
    parser.add_argument(
        "--fast", action="store_true",
        help="Use placement-based extraction only (faster, less precise)"
    )
    parser.add_argument(
        "--max-geom-mb", type=float, default=30.0,
        help="Max file size (MB) for full geometry extraction; larger files "
             "use placement-based fallback (default: 30)"
    )
    args = parser.parse_args()

    project_dir = PROJECTS[args.project]
    ifc_dir = project_dir / "data" / "ifc"
    clash_dir = project_dir / "data" / "clashes"

    # Find IFC files (skip ZIPs and non-IFC files)
    ifc_files = sorted(ifc_dir.glob("*.ifc")) + sorted(ifc_dir.glob("*.IFC"))
    if not ifc_files:
        print(f"ERROR: No IFC files found in {ifc_dir}")
        print(f"Download the dataset and place IFC files in: {ifc_dir}")
        sys.exit(1)

    # Deduplicate: when multiple files map to the same discipline, prefer
    # "optimized" variants (smaller, same geometry) and skip unknowns.
    disc_to_file: dict[str, Path] = {}
    for f in ifc_files:
        disc = detect_discipline(f)
        if disc == "UNK":
            print(f"  SKIP {f.name} (unknown discipline)")
            continue
        existing = disc_to_file.get(disc)
        if existing is None:
            disc_to_file[disc] = f
        elif "optimized" in f.stem.lower() and "optimized" not in existing.stem.lower():
            disc_to_file[disc] = f  # prefer optimized
        # else keep the first one found
    ifc_files = list(disc_to_file.values())

    print(f"Using {len(ifc_files)} IFC files (1 per discipline):")
    for f in ifc_files:
        disc = detect_discipline(f)
        print(f"  {f.name} -> {disc}")

    # Extract bounding boxes per discipline
    max_geom_bytes = args.max_geom_mb * 1024 * 1024
    disc_bboxes: dict[str, list[BBox]] = {}
    for ifc_file in ifc_files:
        disc = detect_discipline(ifc_file)
        file_mb = ifc_file.stat().st_size / 1024 / 1024
        print(f"\nProcessing {ifc_file.name} ({disc}, {file_mb:.1f} MB)...")

        bboxes: list[BBox] = []
        use_placement = args.fast or ifc_file.stat().st_size > max_geom_bytes

        if use_placement:
            reason = "--fast mode" if args.fast else f">{args.max_geom_mb:.0f}MB"
            print(f"  Using placement-based extraction ({reason})...")
            bboxes = extract_bboxes_placement(ifc_file)
        else:
            bboxes = extract_bboxes_ifcopenshell(ifc_file)
            if not bboxes:
                print(f"  Full geometry failed, trying placement-based extraction...")
                bboxes = extract_bboxes_placement(ifc_file)

        if bboxes:
            disc_bboxes.setdefault(disc, []).extend(bboxes)
            print(f"  Extracted {len(bboxes)} bounding boxes")
        else:
            print(f"  WARNING: No elements extracted from {ifc_file.name}")

    # Run clash detection for each discipline pair
    all_clashes = []
    for disc_a, disc_b, test_name in CLASH_TEST_PAIRS:
        if disc_a in disc_bboxes and disc_b in disc_bboxes:
            print(f"\nRunning {test_name} ({disc_a} vs {disc_b})...")
            clashes = run_clash_detection(
                disc_bboxes[disc_a],
                disc_bboxes[disc_b],
                test_name,
                args.tolerance,
            )
            all_clashes.extend(clashes)
            print(f"  Found {len(clashes)} clashes")

    if not all_clashes:
        print("\nWARNING: No clashes detected. Try increasing --tolerance")
        print("Generating synthetic example data for pipeline testing...")
        # Generate minimal synthetic data so the analysis pipeline can still run
        all_clashes = _generate_synthetic_clashes(args.project)

    print(f"\nTotal initial clashes: {len(all_clashes)}")

    # Simulate coordination rounds
    print(f"\nSimulating {args.rounds} coordination rounds...")
    rounds = simulate_coordination_rounds(
        all_clashes,
        num_rounds=args.rounds,
        resolution_rate=args.resolution_rate,
        seed=args.seed,
    )

    # Write each round to XML
    base_date = date(2025, 6, 1)
    for i, round_clashes in enumerate(rounds):
        round_date = base_date + timedelta(weeks=2 * i)
        label = f"Round {i+1} -- {round_date.isoformat()}"
        output_path = clash_dir / f"clash_round_{i+1:02d}.xml"
        clashes_to_navisworks_xml(round_clashes, label, output_path, round_date=round_date)

        # Count by status
        status_counts: dict[str, int] = {}
        for c in round_clashes:
            status_counts[c["status"]] = status_counts.get(c["status"], 0) + 1

        print(f"  Round {i+1} ({round_date}): {len(round_clashes)} clashes -- {status_counts}")

    # Write summary
    summary = {
        "project": args.project,
        "ifc_files": [f.name for f in ifc_files],
        "disciplines": list(disc_bboxes.keys()),
        "tolerance_mm": args.tolerance,
        "initial_clashes": len(all_clashes),
        "rounds": args.rounds,
        "resolution_rate": args.resolution_rate,
        "seed": args.seed,
    }
    summary_path = clash_dir / "generation_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))

    print(f"\nDone. Clash XMLs written to: {clash_dir}")
    print(f"Summary: {summary_path}")


def _generate_synthetic_clashes(project: str) -> list[dict]:
    """Generate synthetic clash data for pipeline testing when no real IFC data available."""
    rng = random.Random(42)
    clashes = []

    test_configs = [
        ("MEP-Structure", 45),
        ("Electrical-Structure", 20),
        ("Plumbing-Structure", 15),
        ("MEP-Architecture", 25),
        ("Electrical-Mechanical", 12),
    ]

    for test_name, count in test_configs:
        for i in range(count):
            clashes.append({
                "id": f"Synth-{test_name[:3]}-{i:03d}",
                "x": rng.uniform(0, 20000),
                "y": rng.uniform(0, 15000),
                "z": rng.uniform(0, 4000),
                "element_a": f"elem-a-{rng.randint(1000, 9999)}",
                "element_b": f"elem-b-{rng.randint(1000, 9999)}",
                "type_a": rng.choice(["IfcDuctSegment", "IfcPipeSegment", "IfcCableCarrierSegment"]),
                "type_b": rng.choice(["IfcBeam", "IfcColumn", "IfcSlab"]),
                "test_name": test_name,
                "status": "new",
            })

    return clashes


if __name__ == "__main__":
    main()
