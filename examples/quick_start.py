"""Quick start example — run this first to see coordination-metrics in action.

Usage:
    python examples/quick_start.py
"""

from pathlib import Path

from coordination_metrics import (
    build_trajectory,
    compute_trajectory_slope,
    extract_clash_points,
    detect_recurrences,
)

# Path to sample data
DATA = Path(__file__).parent / "sample_data"

# --- Metric 1: Clash Trajectory ---
print("=" * 60)
print("METRIC 1: Hard Clash Trajectory Slope")
print("=" * 60)

exports = sorted(DATA.glob("clash_round*.xml"))
summaries = build_trajectory(exports)

for s in summaries:
    print(f"  {s.round_label}: {s.total} total ({s.new} new, {s.resolved} resolved)")

result = compute_trajectory_slope(summaries)
print(f"\n  Slope: {result['slope']:+.2f} clashes/day")
print(f"  R-squared: {result['r_squared']:.4f}")
print(f"  Health: {result['health_level']}")
print(f"  {result['interpretation']}")

# --- Metric 2: Recurring Clashes ---
print("\n" + "=" * 60)
print("METRIC 2: Recurring Clash Rate")
print("=" * 60)

prev = extract_clash_points(DATA / "clash_round1.xml")
curr = extract_clash_points(DATA / "clash_round2.xml")
recurrence = detect_recurrences(prev, curr, threshold_mm=500)

print(f"  Resolved clashes checked: {recurrence['resolved_count']}")
print(f"  Recurring: {recurrence['recurring_count']}")
print(f"  Rate: {recurrence['recurrence_rate_pct']:.1f}%")
print(f"  Health: {recurrence['health_level']}")

if recurrence["recurring_pairs"]:
    print("  Recurring pairs:")
    for prev_id, curr_id, dist in recurrence["recurring_pairs"]:
        print(f"    {prev_id} -> {curr_id} ({dist:.0f} mm)")

print(f"\n  {recurrence['interpretation']}")
print("\nDone! Run examples/full_dashboard.py for all 5 metrics.")
