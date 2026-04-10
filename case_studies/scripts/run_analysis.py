#!/usr/bin/env python3
"""Run the full coordination-metrics analysis pipeline on a case study project.

Applies all 5 metrics + ECV + cross-correlations + benchmarks to the
project data and generates HTML dashboard, JSON export, and chart images.

Usage:
    python run_analysis.py --project wbdg_duplex
    python run_analysis.py --project schependomlaan --output-format all
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

# Add parent package to path for development
PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from coordination_metrics import (
    CoordinationHealthDashboard,
    build_trajectory,
    compute_trajectory_slope,
    detect_recurrences,
    extract_clash_points,
    compute_approval_rates,
    analyse_rfi_distribution,
    parse_meeting_csv,
    compute_attendance_decision_correlation,
    discover_cross_correlations,
    compare_to_benchmark,
    generate_benchmark_report,
)
from coordination_metrics.core import ClashRoundSummary, CoordinationHealth
from coordination_metrics.ecv import ECVConfig, compute_ecv
from coordination_metrics.exporters import export_to_json, export_to_html, export_charts


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROJECTS = {
    "wbdg_duplex": PROJECT_ROOT / "wbdg_duplex",
    "wbdg_clinic": PROJECT_ROOT / "wbdg_clinic",
    "schependomlaan": PROJECT_ROOT / "schependomlaan",
}


def run_full_analysis(project_name: str, output_formats: list[str]) -> dict:
    """Run the complete analysis pipeline and return results."""
    project_dir = PROJECTS[project_name]
    data_dir = project_dir / "data"
    output_dir = project_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"=" * 60)
    print(f"COORDINATION METRICS ANALYSIS: {project_name}")
    print(f"=" * 60)

    # --- Step 1: Run the unified dashboard ---
    print("\n[1/6] Running unified health dashboard...")
    clash_dir = data_dir / "clashes"

    dashboard = CoordinationHealthDashboard(
        data_dir=str(data_dir),
        clash_exports=sorted(clash_dir.glob("clash_round_*.xml")) if clash_dir.exists() else None,
    )
    health = dashboard.run()
    summary = health.summary()

    print(f"  Overall Health: {summary['overall_health']} ({summary['health_level']})")
    for metric, score in summary["metrics"].items():
        status = "HEALTHY" if score >= 70 else "AT RISK" if score >= 45 else "CRITICAL"
        print(f"  {metric}: {score} [{status}]")

    # --- Step 2: Detailed clash trajectory analysis ---
    print("\n[2/6] Detailed clash trajectory analysis...")
    clash_xmls = sorted(clash_dir.glob("clash_round_*.xml")) if clash_dir.exists() else []
    trajectory_detail: dict = {}
    if len(clash_xmls) >= 2:
        summaries = build_trajectory(clash_xmls)
        traj = compute_trajectory_slope(summaries)
        trajectory_detail = {
            "rounds": len(summaries),
            "slope": traj.get("slope"),
            "r_squared": traj.get("r_squared"),
            "health": traj.get("health"),
            "round_totals": [s.total for s in summaries],
            "round_new": [s.new for s in summaries],
            "round_resolved": [s.resolved for s in summaries],
        }
        print(f"  Rounds: {len(summaries)}")
        print(f"  Slope: {traj.get('slope', 'N/A')}")
        print(f"  Health: {traj.get('health', 'N/A')}")

        # Recurrence analysis between last two rounds
        if len(clash_xmls) >= 2:
            prev_points = extract_clash_points(clash_xmls[-2])
            curr_points = extract_clash_points(clash_xmls[-1])
            recurrence = detect_recurrences(prev_points, curr_points)
            trajectory_detail["recurrence"] = recurrence
            print(f"  Recurring clash rate: {recurrence.get('recurrence_rate_pct', 'N/A')}%")

    # --- Step 3: ECV calculation ---
    print("\n[3/6] Computing Earned Coordination Value (ECV)...")
    ecv_detail: dict = {}
    if clash_xmls:
        try:
            import pandas as pd

            all_summaries = build_trajectory(clash_xmls)
            initial_clashes = all_summaries[0].total if all_summaries else 100
            latest = all_summaries[-1] if all_summaries else None

            # Net resolution: how many of the original problem are no longer active
            # (not raw resolution count, which double-counts recurring clashes)
            remaining_active = (latest.new + latest.active + latest.reviewed) if latest else 0
            net_clashes_resolved = max(0, initial_clashes - remaining_active)

            # Derive expected values from actual generated data
            rfi_path = data_dir / "rfi_register.csv"
            total_rfis, rfis_answered = 0, 0
            if rfi_path.exists():
                rfi_df = pd.read_csv(rfi_path)
                total_rfis = len(rfi_df)
                rfis_answered = int(rfi_df["date_responded"].notna().sum())

            sub_path = data_dir / "submittal_register.csv"
            total_submittals, submittals_approved = 0, 0
            if sub_path.exists():
                sub_df = pd.read_csv(sub_path)
                total_submittals = len(sub_df)
                approved = {"Approved", "Approved as Noted"}
                submittals_approved = int(sub_df["status"].isin(approved).sum())

            mtg_path = data_dir / "meeting_minutes.csv"
            total_meetings, decisions_made, total_agenda_items = 0, 0, 0
            if mtg_path.exists():
                mtg_df = pd.read_csv(mtg_path)
                total_meetings = len(mtg_df)
                if "decided_items" in mtg_df.columns:
                    decisions_made = int(mtg_df["decided_items"].sum())
                if "total_items" in mtg_df.columns:
                    total_agenda_items = int(mtg_df["total_items"].sum())

            # Use last round date as measurement point
            measurement_date = all_summaries[-1].round_date

            ecv_config = ECVConfig(
                project_start=date(2025, 6, 1),
                coordination_deadline=date(2025, 12, 31),
                total_expected_clashes=initial_clashes,
                total_expected_rfis=max(total_rfis, 1),
                total_expected_submittals=max(total_submittals, 1),
                total_expected_meetings=max(total_meetings, 1),
            )
            # Pass actual total agenda items as expected decisions
            ecv_config.total_expected_decisions = max(total_agenda_items, 1)

            ecv = compute_ecv(
                config=ecv_config,
                measurement_date=measurement_date,
                clashes_resolved=net_clashes_resolved,
                rfis_answered=rfis_answered,
                submittals_approved=submittals_approved,
                decisions_made=decisions_made,
            )
            ecv_detail = {
                "planned_value": ecv.planned_value,
                "earned_value": ecv.earned_value,
                "cpi": ecv.cpi,
                "spi": ecv.spi,
                "status": ecv.status,
                "eac_date": ecv.eac_date.isoformat() if ecv.eac_date else None,
            }
            print(f"  CPI: {ecv.cpi} (Coordination Performance Index)")
            print(f"  SPI: {ecv.spi} (Schedule Performance Index)")
            print(f"  Status: {ecv.status}")
        except Exception as e:
            print(f"  ECV calculation error: {e}")

    # --- Step 4: Benchmark comparison ---
    print("\n[4/6] Comparing against industry benchmarks...")
    benchmark_results = []
    details = health.details

    if "recurring_clashes" in details and isinstance(details["recurring_clashes"], dict):
        rate = details["recurring_clashes"].get("recurrence_rate_pct")
        if rate is not None:
            bench = compare_to_benchmark("recurring_clash_rate", rate)
            benchmark_results.append(bench)
            print(f"  {bench.get('insight', '')}")

    if "rfi_distribution" in details and isinstance(details["rfi_distribution"], dict):
        overall = details["rfi_distribution"].get("overall", {})
        if isinstance(overall, dict):
            p90 = overall.get("p90_days")
            if p90 is not None:
                bench = compare_to_benchmark("rfi_response_p90_days", p90)
                benchmark_results.append(bench)
                print(f"  {bench.get('insight', '')}")

    # --- Step 5: Cross-correlations ---
    print("\n[5/6] Discovering cross-metric correlations...")
    correlations = discover_cross_correlations(
        clash_trajectory_data=details.get("clash_trajectory", {}),
        recurrence_data=details.get("recurring_clashes", {}),
        approval_data=details.get("approval_rates", {}),
        rfi_data=details.get("rfi_distribution", {}),
        meeting_data=details.get("meeting_decisions", {}),
    )
    for corr in correlations:
        tag = " [ACTIONABLE]" if corr.actionable else ""
        print(f"  {corr.metric_a} <-> {corr.metric_b}: {corr.insight}{tag}")

    # --- Step 6: Export results ---
    print("\n[6/6] Exporting results...")

    if "html" in output_formats or "all" in output_formats:
        html_path = output_dir / "coordination_report.html"
        export_to_html(health, output_path=str(html_path))
        print(f"  HTML dashboard: {html_path}")

    if "json" in output_formats or "all" in output_formats:
        json_path = output_dir / "coordination_report.json"
        export_to_json(health, output_path=str(json_path))
        print(f"  JSON export: {json_path}")

    if "charts" in output_formats or "all" in output_formats:
        charts_dir = output_dir / "charts"
        try:
            generated = export_charts(health, charts_dir)
            for chart_path in generated:
                print(f"  Chart: {chart_path}")
        except Exception as e:
            print(f"  Chart export error: {e}")

    # Write comprehensive analysis JSON
    full_results = {
        "project": project_name,
        "analysis_date": date.today().isoformat(),
        "health_summary": summary,
        "trajectory_detail": trajectory_detail,
        "ecv": ecv_detail,
        "benchmarks": benchmark_results,
        "cross_correlations": [
            {
                "metric_a": c.metric_a,
                "metric_b": c.metric_b,
                "correlation": c.correlation,
                "direction": c.direction,
                "insight": c.insight,
                "actionable": c.actionable,
            }
            for c in correlations
        ],
    }

    analysis_path = output_dir / "full_analysis.json"
    analysis_path.write_text(json.dumps(full_results, indent=2, default=str))
    print(f"  Full analysis: {analysis_path}")

    print(f"\n{'=' * 60}")
    print(f"ANALYSIS COMPLETE")
    print(f"Overall Health: {summary['overall_health']} / 100 ({summary['health_level']})")
    print(f"Results in: {output_dir}")
    print(f"{'=' * 60}")

    return full_results


def main():
    parser = argparse.ArgumentParser(
        description="Run full coordination-metrics analysis on a case study"
    )
    parser.add_argument(
        "--project", required=True, choices=list(PROJECTS.keys()),
        help="Project to analyse"
    )
    parser.add_argument(
        "--output-format", nargs="+", default=["all"],
        choices=["html", "json", "charts", "all"],
        help="Output formats (default: all)"
    )
    args = parser.parse_args()

    run_full_analysis(args.project, args.output_format)


if __name__ == "__main__":
    main()
