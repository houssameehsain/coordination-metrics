"""Full dashboard example — runs all 5 metrics and generates an HTML report.

Usage:
    python examples/full_dashboard.py
"""

from pathlib import Path

from coordination_metrics.dashboard import CoordinationHealthDashboard
from coordination_metrics.exporters import export_to_json, export_to_html

DATA = Path(__file__).parent / "sample_data"
OUTPUT = Path(__file__).parent / "output"
OUTPUT.mkdir(exist_ok=True)

# Create dashboard with auto-discovery
dashboard = CoordinationHealthDashboard(
    data_dir=DATA,
    clash_exports=sorted(DATA.glob("clash_round*.xml")),
    submittal_register=DATA / "submittal_register.csv",
    rfi_register=DATA / "rfi_register.csv",
    meeting_register=DATA / "meeting_minutes.csv",
)

# Run all 5 metrics
health = dashboard.run()
summary = health.summary()

# Print results
print("=" * 60)
print("COORDINATION HEALTH DASHBOARD")
print("=" * 60)
print(f"\n  Overall Health: {summary['overall_health']}/100")
print(f"  Status: {summary['health_level'].upper()}")
print(f"\n  Metric Scores:")
for metric, score in summary["metrics"].items():
    label = metric.replace("_", " ").title()
    bar = "#" * int(score / 5) + "-" * (20 - int(score / 5))
    print(f"    {label:.<25} [{bar}] {score}")

# Generate HTML report
html_path = OUTPUT / "coordination_report.html"
export_to_html(health, output_path=html_path)
print(f"\n  HTML report: {html_path}")

# Generate JSON export
json_path = OUTPUT / "coordination_report.json"
export_to_json(health, output_path=json_path)
print(f"  JSON export: {json_path}")

# Show details for any critical metrics
print("\n" + "-" * 60)
print("DETAIL: Metrics requiring attention")
print("-" * 60)

details = summary.get("details", {})

# Clash trajectory
ct = details.get("clash_trajectory", {})
if "slope" in ct:
    print(f"\n  Clash Trajectory: {ct.get('interpretation', '')}")

# RFI bottlenecks
rfi = details.get("rfi_distribution", {})
if "by_discipline" in rfi:
    bottlenecks = [d for d in rfi["by_discipline"] if d.get("is_bottleneck")]
    if bottlenecks:
        print(f"\n  RFI Bottleneck disciplines:")
        for b in bottlenecks:
            print(f"    - {b['discipline']}: P90 = {b['p90_days']} days")

# Meeting decisions
mtg = details.get("meeting_decisions", {})
if "correlation_strength" in mtg:
    print(f"\n  Meeting attendance-decision correlation: {mtg['correlation_strength']}")
    print(f"  {mtg.get('interpretation', '')}")

print("\nDone!")
