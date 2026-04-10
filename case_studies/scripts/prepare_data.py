#!/usr/bin/env python3
"""Prepare coordination data causally linked to clash detection results.

Unlike the previous version that generated independent random data, this
script reads the clash round XMLs produced by generate_clashes.py and
derives RFIs, submittals, and meeting minutes that are *causally connected*
to the actual clashes — matching disciplines, referencing element types,
and following temporal alignment with coordination rounds.

Response time distributions are calibrated to Navigant/CMAA (2013) industry
data. Meeting decision rates follow Cavka et al. (2015).

Usage:
    python prepare_data.py --project wbdg_duplex
    python prepare_data.py --project wbdg_clinic --seed 123
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROJECTS = {
    "wbdg_duplex": PROJECT_ROOT / "wbdg_duplex",
    "wbdg_clinic": PROJECT_ROOT / "wbdg_clinic",
    "schependomlaan": PROJECT_ROOT / "schependomlaan",
}

# ---------------------------------------------------------------------------
# Discipline mapping from clash test names to RFI/submittal disciplines
# ---------------------------------------------------------------------------
_TEST_TO_DISCIPLINES = {
    "MEP-Structure":        ("Mechanical", "Structural"),
    "Electrical-Structure":  ("Electrical", "Structural"),
    "Plumbing-Structure":    ("Plumbing", "Structural"),
    "MEP-Architecture":      ("Mechanical", "Architectural"),
    "Electrical-Mechanical":  ("Electrical", "Mechanical"),
    "Plumbing-Mechanical":    ("Plumbing", "Mechanical"),
    "Electrical-Plumbing":    ("Electrical", "Plumbing"),
}

# IFC type to human-readable element description for RFI narratives
_ELEMENT_DESCRIPTIONS = {
    "IfcDuctSegment": "HVAC duct run",
    "IfcPipeSegment": "pipe segment",
    "IfcFlowSegment": "flow segment",
    "IfcFlowTerminal": "terminal unit",
    "IfcFlowFitting": "pipe/duct fitting",
    "IfcFlowController": "flow controller (valve/damper)",
    "IfcCableCarrierSegment": "cable tray",
    "IfcCableSegment": "cable run",
    "IfcLightFixture": "light fixture",
    "IfcOutlet": "electrical outlet",
    "IfcSwitchingDevice": "switching device",
    "IfcJunctionBox": "junction box",
    "IfcWall": "wall",
    "IfcColumn": "column",
    "IfcBeam": "beam",
    "IfcSlab": "floor slab",
    "IfcDoor": "door",
    "IfcWindow": "window",
    "IfcRoof": "roof element",
    "IfcStair": "stair",
}

# RFI categories linked to clash characteristics
_RFI_CATEGORIES = {
    "hard_clash":    "Coordination Issue",
    "clearance":     "Design Clarification",
    "routing":       "Constructability",
    "code":          "Code Compliance",
    "substitution":  "Material Substitution",
}

# ---------------------------------------------------------------------------
# Calibrated distributions (Navigant/CMAA 2013; Cavka et al. 2015)
# ---------------------------------------------------------------------------

# RFI response time: log-normal distribution by discipline
# Parameters: (mu, sigma) for ln(days)
# Calibrated so median ≈ 7d, P90 ≈ 14d for average discipline
# Mechanical/Plumbing are slower (need coordination); Architectural faster
_RFI_RESPONSE_LOGNORMAL = {
    "Structural":    (1.6, 0.5),   # median ~5d, P90 ~10d
    "Architectural": (1.5, 0.5),   # median ~4.5d, P90 ~9d
    "Mechanical":    (2.0, 0.6),   # median ~7.4d, P90 ~18d
    "Electrical":    (1.8, 0.6),   # median ~6d, P90 ~15d
    "Plumbing":      (1.9, 0.55),  # median ~6.7d, P90 ~15d
}
_DEFAULT_RFI_LOGNORMAL = (1.8, 0.6)

# Submittal approval probability by revision number
# First submission: ~40% first-time approval (industry average)
# Resubmissions improve progressively
_APPROVAL_PROBS = {
    0: {"Approved": 0.35, "Approved as Noted": 0.25,
        "Revise & Resubmit": 0.30, "Rejected": 0.10},
    1: {"Approved": 0.50, "Approved as Noted": 0.30,
        "Revise & Resubmit": 0.18, "Rejected": 0.02},
    2: {"Approved": 0.65, "Approved as Noted": 0.25,
        "Revise & Resubmit": 0.10, "Rejected": 0.00},
}

# Meeting decision rate: starts low, improves with maturity (Cavka et al. 2015)
# But NOT linearly — plateaus around 65-70% (never reaches 100%)
_DECISION_RATE_CURVE = [0.40, 0.45, 0.50, 0.55, 0.58, 0.60, 0.62, 0.63,
                        0.65, 0.65, 0.66, 0.67, 0.67, 0.68, 0.68, 0.68,
                        0.69, 0.69, 0.70, 0.70]


# ---------------------------------------------------------------------------
# Clash XML reader
# ---------------------------------------------------------------------------

@dataclass
class ClashInfo:
    """Minimal clash info extracted from XML for causal data generation."""
    clash_id: str
    x: float
    y: float
    z: float
    status: str
    test_name: str


def read_clash_rounds(clash_dir: Path) -> list[list[ClashInfo]]:
    """Read all clash round XMLs and return structured clash data."""
    rounds = []
    for xml_path in sorted(clash_dir.glob("clash_round_*.xml")):
        clashes = []
        tree = ET.parse(xml_path)
        for test in tree.getroot().iter("clashtest"):
            test_name = test.get("name", "Unknown")
            for result in test.iter("clashresult"):
                pos = result.find(".//pos3f")
                if pos is None:
                    continue
                clashes.append(ClashInfo(
                    clash_id=result.get("name", ""),
                    x=float(pos.get("x", 0)),
                    y=float(pos.get("y", 0)),
                    z=float(pos.get("z", 0)),
                    status=(result.get("status") or "new").lower(),
                    test_name=test_name,
                ))
        rounds.append(clashes)
    return rounds


def read_generation_summary(clash_dir: Path) -> dict:
    """Read the generation_summary.json for metadata."""
    summary_path = clash_dir / "generation_summary.json"
    if summary_path.exists():
        return json.loads(summary_path.read_text())
    return {}


# ---------------------------------------------------------------------------
# Spatial clustering for meeting agenda items
# ---------------------------------------------------------------------------

def cluster_clashes_by_zone(
    clashes: list[ClashInfo],
    zone_size_mm: float = 5000.0,
) -> list[list[ClashInfo]]:
    """Group clashes into spatial zones for meeting agenda items.

    Uses simple grid-based clustering (zone_size x zone_size x floor_height).
    Each cluster becomes one meeting agenda item.
    """
    zones: dict[tuple[int, int, int], list[ClashInfo]] = defaultdict(list)
    floor_height = 3500.0  # mm

    for c in clashes:
        zx = int(c.x // zone_size_mm)
        zy = int(c.y // zone_size_mm)
        zz = int(c.z // floor_height)
        zones[(zx, zy, zz)].append(c)

    return list(zones.values())


# ---------------------------------------------------------------------------
# Causal RFI generation
# ---------------------------------------------------------------------------

def generate_rfi_register(
    project_dir: Path,
    clash_rounds: list[list[ClashInfo]],
    base_date: date,
    round_interval_days: int = 14,
    rfi_trigger_rate: float = 0.03,
    seed: int = 42,
) -> Path:
    """Generate RFIs causally linked to specific clashes.

    Each active/new clash has a probability of triggering an RFI.
    The RFI references the clash's discipline pair, spatial zone,
    and element types. Response times follow log-normal distributions
    calibrated to Navigant/CMAA (2013) industry data.
    """
    rng = random.Random(seed)
    output = project_dir / "data" / "rfi_register.csv"
    output.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    rfi_num = 0

    for round_idx, clashes in enumerate(clash_rounds):
        round_date = base_date + timedelta(days=round_interval_days * round_idx)

        # Only active/new clashes can trigger RFIs
        active = [c for c in clashes if c.status in ("new", "active")]

        for clash in active:
            if rng.random() > rfi_trigger_rate:
                continue

            rfi_num += 1
            discs = _TEST_TO_DISCIPLINES.get(clash.test_name, ("Unknown", "Unknown"))
            # RFI is raised BY the discipline that needs to change
            discipline = rng.choice(discs)

            # Determine RFI category based on clash characteristics
            if clash.status == "new":
                category = "Coordination Issue"
            else:
                category = rng.choice(list(_RFI_CATEGORIES.values()))

            # Submit date: within the round period, slight random offset
            submit_date = round_date + timedelta(days=rng.randint(0, round_interval_days - 1))

            # Response time: log-normal distribution (Navigant/CMAA 2013)
            mu, sigma = _RFI_RESPONSE_LOGNORMAL.get(discipline, _DEFAULT_RFI_LOGNORMAL)
            response_days = max(1, int(rng.lognormvariate(mu, sigma)))

            # ~12% still open (more realistic than flat 15%)
            is_open = rng.random() < 0.12
            respond_date = "" if is_open else (submit_date + timedelta(days=response_days)).isoformat()

            # Build description referencing the actual clash
            zone_x = int(clash.x / 5000)
            zone_y = int(clash.y / 5000)
            zone_z = int(clash.z / 3500) + 1
            desc = (
                f"Coordination issue at Zone {zone_x}-{zone_y} Level {zone_z}: "
                f"{clash.test_name} clash near ({clash.x:.0f}, {clash.y:.0f}, {clash.z:.0f}mm). "
                f"Ref: {clash.clash_id}"
            )

            rows.append({
                "rfi_id": f"RFI-{rfi_num:03d}",
                "date_submitted": submit_date.isoformat(),
                "date_responded": respond_date,
                "discipline": discipline,
                "category": category,
                "description": desc,
                "source_clash": clash.clash_id,
                "source_round": round_idx + 1,
            })

    with open(output, "w", newline="") as f:
        if rows:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        else:
            writer = csv.DictWriter(f, fieldnames=[
                "rfi_id", "date_submitted", "date_responded", "discipline",
                "category", "description", "source_clash", "source_round",
            ])
        writer.writeheader()
        writer.writerows(rows)

    print(f"  RFI register: {len(rows)} RFIs -> {output}")
    return output


# ---------------------------------------------------------------------------
# Causal submittal generation
# ---------------------------------------------------------------------------

def generate_submittal_register(
    project_dir: Path,
    clash_rounds: list[list[ClashInfo]],
    base_date: date,
    round_interval_days: int = 14,
    submittal_rate: float = 0.02,
    seed: int = 42,
) -> Path:
    """Generate submittals causally linked to clash resolution.

    Submittals are triggered when clashes are resolved — the resolution
    often requires product selections (new duct size, rerouted pipe,
    alternative fitting) that need formal approval.
    """
    rng = random.Random(seed + 1)
    output = project_dir / "data" / "submittal_register.csv"
    output.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    sub_num = 0

    for round_idx, clashes in enumerate(clash_rounds):
        if round_idx == 0:
            continue  # no resolutions in round 0

        round_date = base_date + timedelta(days=round_interval_days * round_idx)

        # Resolved clashes trigger submittals
        resolved = [c for c in clashes if c.status == "resolved"]

        for clash in resolved:
            if rng.random() > submittal_rate:
                continue

            sub_num += 1
            discs = _TEST_TO_DISCIPLINES.get(clash.test_name, ("Unknown", "Unknown"))
            discipline = discs[0]  # submitter is usually the first discipline

            # Revision count based on clash complexity
            revision = rng.choices([0, 1, 2, 3], weights=[40, 35, 18, 7])[0]

            # Approval status from calibrated distribution
            probs = _APPROVAL_PROBS.get(min(revision, 2), _APPROVAL_PROBS[2])
            statuses = list(probs.keys())
            weights = list(probs.values())
            status = rng.choices(statuses, weights=weights)[0]

            submit_date = round_date + timedelta(days=rng.randint(0, round_interval_days - 1))

            desc = (
                f"{discipline} submittal for {clash.test_name} resolution "
                f"near ({clash.x:.0f}, {clash.y:.0f}, {clash.z:.0f}mm). "
                f"Ref: {clash.clash_id}"
            )

            rows.append({
                "submittal_id": f"SUB-{sub_num:03d}",
                "discipline": discipline,
                "revision": revision,
                "status": status,
                "date_submitted": submit_date.isoformat(),
                "description": desc,
                "source_clash": clash.clash_id,
                "source_round": round_idx + 1,
            })

    with open(output, "w", newline="") as f:
        if rows:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        else:
            writer = csv.DictWriter(f, fieldnames=[
                "submittal_id", "discipline", "revision", "status",
                "date_submitted", "description", "source_clash", "source_round",
            ])
        writer.writeheader()
        writer.writerows(rows)

    print(f"  Submittal register: {len(rows)} submittals -> {output}")
    return output


# ---------------------------------------------------------------------------
# Causal meeting minutes generation
# ---------------------------------------------------------------------------

def generate_meeting_minutes(
    project_dir: Path,
    clash_rounds: list[list[ClashInfo]],
    base_date: date,
    round_interval_days: int = 14,
    seed: int = 42,
) -> Path:
    """Generate meeting minutes causally linked to clash clusters.

    Each coordination meeting addresses spatial zones containing active
    clashes. Agenda items correspond to clash clusters. Decision rates
    follow Cavka et al. (2015) — starting ~40%, plateauing at ~70%.

    Discipline attendance is derived from which discipline pairs have
    active clashes in the zones being discussed.
    """
    rng = random.Random(seed + 2)
    output = project_dir / "data" / "meeting_minutes.csv"
    output.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    meeting_num = 0

    for round_idx, clashes in enumerate(clash_rounds):
        round_date = base_date + timedelta(days=round_interval_days * round_idx)

        # Active clashes for this round
        active = [c for c in clashes if c.status in ("new", "active", "reviewed")]
        if not active:
            continue

        # Cluster into spatial zones for agenda items
        zones = cluster_clashes_by_zone(active)

        # Each round may have 1-2 meetings (biweekly cadence typical)
        meetings_this_round = 1 if len(zones) < 10 else 2

        for mtg_offset in range(meetings_this_round):
            meeting_num += 1
            meeting_date = round_date + timedelta(days=mtg_offset * 7)

            # Assign zones to this meeting
            if meetings_this_round == 1:
                mtg_zones = zones
            else:
                mid = len(zones) // 2
                mtg_zones = zones[:mid] if mtg_offset == 0 else zones[mid:]

            total_items = len(mtg_zones)
            if total_items == 0:
                continue

            # Decision rate from calibrated curve (Cavka et al. 2015)
            curve_idx = min(meeting_num - 1, len(_DECISION_RATE_CURVE) - 1)
            base_rate = _DECISION_RATE_CURVE[curve_idx]
            # Add noise: ±10%
            eff_rate = max(0.2, min(0.85, base_rate + rng.gauss(0, 0.05)))

            decided = int(total_items * eff_rate)
            decided = max(0, min(total_items, decided))
            deferred = total_items - decided

            # Required disciplines: all disciplines involved in active clashes
            required_discs = set()
            present_discs = set()
            for zone in mtg_zones:
                for c in zone:
                    discs = _TEST_TO_DISCIPLINES.get(c.test_name, ())
                    required_discs.update(discs)

            # Attendance: ~85% show rate per discipline
            for d in required_discs:
                if rng.random() < 0.85:
                    present_discs.add(d)
            # At least 2 disciplines must be present
            if len(present_discs) < 2 and len(required_discs) >= 2:
                present_discs = set(rng.sample(sorted(required_discs),
                                               min(2, len(required_discs))))

            rows.append({
                "meeting_date": meeting_date.isoformat(),
                "total_items": total_items,
                "decided_items": decided,
                "deferred_items": deferred,
                "disciplines_required": ";".join(sorted(required_discs)),
                "disciplines_present": ";".join(sorted(present_discs)),
                "round": round_idx + 1,
                "active_clashes": len([c for z in mtg_zones for c in z]),
            })

    with open(output, "w", newline="") as f:
        if rows:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        else:
            writer = csv.DictWriter(f, fieldnames=[
                "meeting_date", "total_items", "decided_items", "deferred_items",
                "disciplines_required", "disciplines_present", "round", "active_clashes",
            ])
        writer.writeheader()
        writer.writerows(rows)

    print(f"  Meeting minutes: {len(rows)} meetings -> {output}")
    return output


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Prepare coordination data causally linked to clash results"
    )
    parser.add_argument(
        "--project", required=True, choices=list(PROJECTS.keys()),
        help="Project to prepare data for"
    )
    parser.add_argument(
        "--rfi-trigger-rate", type=float, default=0.03,
        help="Probability each active clash triggers an RFI per round (default: 0.03)"
    )
    parser.add_argument(
        "--submittal-rate", type=float, default=0.02,
        help="Probability each resolved clash triggers a submittal (default: 0.02)"
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for reproducibility"
    )
    args = parser.parse_args()

    project_dir = PROJECTS[args.project]
    clash_dir = project_dir / "data" / "clashes"

    # Read clash round data
    clash_rounds = read_clash_rounds(clash_dir)
    if not clash_rounds:
        print(f"ERROR: No clash round XMLs found in {clash_dir}")
        print("Run generate_clashes.py first.")
        sys.exit(1)

    # Read generation summary for dates
    summary = read_generation_summary(clash_dir)

    # Determine base date from summary or use default
    base_date = date(2025, 6, 1)
    round_interval = 14  # biweekly

    total_clashes_r0 = len(clash_rounds[0])
    total_resolved = sum(
        1 for r in clash_rounds for c in r if c.status == "resolved"
    )
    print(f"Preparing causal coordination data for {args.project}...")
    print(f"  Clash rounds: {len(clash_rounds)}")
    print(f"  Round 0 clashes: {total_clashes_r0}")
    print(f"  Total resolved across all rounds: {total_resolved}")

    generate_rfi_register(
        project_dir, clash_rounds, base_date, round_interval,
        rfi_trigger_rate=args.rfi_trigger_rate, seed=args.seed,
    )
    generate_submittal_register(
        project_dir, clash_rounds, base_date, round_interval,
        submittal_rate=args.submittal_rate, seed=args.seed,
    )
    generate_meeting_minutes(
        project_dir, clash_rounds, base_date, round_interval,
        seed=args.seed,
    )

    print(f"\nDone. Causal data files written to: {project_dir / 'data'}")


if __name__ == "__main__":
    main()
