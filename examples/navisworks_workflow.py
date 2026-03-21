"""Navisworks-specific workflow — parse clash exports and generate charts.

Usage:
    python examples/navisworks_workflow.py
"""

from pathlib import Path

from coordination_metrics import (
    build_trajectory,
    compute_trajectory_slope,
    extract_clash_points,
    detect_recurrences,
)
from coordination_metrics.parsers.navisworks import parse_navisworks_xml
from coordination_metrics.visualizations import (
    plot_clash_trajectory,
    plot_recurring_clashes,
)

DATA = Path(__file__).parent / "sample_data"
OUTPUT = Path(__file__).parent / "output"
OUTPUT.mkdir(exist_ok=True)

# Step 1: Parse individual XML files
print("Step 1: Parsing Navisworks XML exports...")
for xml_file in sorted(DATA.glob("clash_round*.xml")):
    result = parse_navisworks_xml(xml_file)
    print(f"\n  {xml_file.name}:")
    print(f"    Total clashes: {result['totals']['total']}")
    for test in result["tests"]:
        print(f"    - {test['name']}: {test['total']} ({test['new']} new, {test['resolved']} resolved)")

# Step 2: Build trajectory
print("\nStep 2: Computing clash trajectory...")
exports = sorted(DATA.glob("clash_round*.xml"))
summaries = build_trajectory(exports)
slope_result = compute_trajectory_slope(summaries)

print(f"  Slope: {slope_result['slope']:+.2f} clashes/day")
print(f"  {slope_result['interpretation']}")

# Step 3: Detect recurrences between consecutive rounds
print("\nStep 3: Detecting recurring clashes...")
for i in range(len(exports) - 1):
    prev = extract_clash_points(exports[i])
    curr = extract_clash_points(exports[i + 1])
    result = detect_recurrences(prev, curr, threshold_mm=500)
    print(f"\n  {exports[i].stem} -> {exports[i + 1].stem}:")
    print(f"    Recurrence rate: {result['recurrence_rate_pct']:.1f}%")
    print(f"    {result['interpretation']}")

# Step 4: Generate charts
print("\nStep 4: Generating charts...")

fig_traj = plot_clash_trajectory(summaries)
traj_path = OUTPUT / "clash_trajectory.png"
fig_traj.savefig(traj_path, dpi=150, bbox_inches="tight", facecolor=fig_traj.get_facecolor())
print(f"  Saved: {traj_path}")

# Recurrence donut for the latest pair
prev_points = extract_clash_points(exports[-2])
curr_points = extract_clash_points(exports[-1])
recurrence = detect_recurrences(prev_points, curr_points)

if recurrence["resolved_count"] > 0:
    fig_recur = plot_recurring_clashes(
        recurrence["resolved_count"], recurrence["recurring_count"]
    )
    recur_path = OUTPUT / "recurring_clashes.png"
    fig_recur.savefig(recur_path, dpi=150, bbox_inches="tight",
                      facecolor=fig_recur.get_facecolor())
    print(f"  Saved: {recur_path}")

print("\nDone!")
