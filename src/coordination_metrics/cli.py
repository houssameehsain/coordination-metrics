"""Command-line interface for coordination-metrics.

Usage:
    coord-metrics report ./data/ --output report.html
    coord-metrics clashes ./exports/
    coord-metrics rfis ./rfi_register.csv
"""

from __future__ import annotations

import argparse
import json
import sys


def main() -> None:
    """Entry point for the coord-metrics CLI."""
    parser = argparse.ArgumentParser(
        prog="coord-metrics",
        description="5 metrics that predict design coordination failure before it hits site.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # report command
    report_parser = subparsers.add_parser("report", help="Generate a full coordination health report")
    report_parser.add_argument("data_dir", help="Directory containing project data files")
    report_parser.add_argument("--output", "-o", default="coordination_report.html",
                               help="Output file path (default: coordination_report.html)")
    report_parser.add_argument("--json", action="store_true", help="Output as JSON instead of HTML")

    # clashes command
    clash_parser = subparsers.add_parser("clashes", help="Analyse clash trajectory")
    clash_parser.add_argument("exports_dir", help="Directory containing Navisworks XML exports")

    # rfis command
    rfi_parser = subparsers.add_parser("rfis", help="Analyse RFI response distribution")
    rfi_parser.add_argument("register_path", help="Path to RFI register (CSV or Excel)")

    # submittals command
    sub_parser = subparsers.add_parser("submittals", help="Analyse submittal approval rates")
    sub_parser.add_argument("register_path", help="Path to submittal register (CSV or Excel)")

    # meetings command
    mtg_parser = subparsers.add_parser("meetings", help="Analyse meeting decision rates")
    mtg_parser.add_argument("register_path", help="Path to meeting minutes (CSV or Excel)")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    if args.command == "report":
        _cmd_report(args)
    elif args.command == "clashes":
        _cmd_clashes(args)
    elif args.command == "rfis":
        _cmd_rfis(args)
    elif args.command == "submittals":
        _cmd_submittals(args)
    elif args.command == "meetings":
        _cmd_meetings(args)


def _cmd_report(args: argparse.Namespace) -> None:
    from coordination_metrics.dashboard import CoordinationHealthDashboard
    from coordination_metrics.exporters import export_to_json, export_to_html

    dashboard = CoordinationHealthDashboard(data_dir=args.data_dir)
    health = dashboard.run()

    if args.json:
        output = export_to_json(health, output_path=args.output)
        print(output)
    else:
        export_to_html(health, output_path=args.output)
        print(f"Report written to {args.output}")

    summary = health.summary()
    print(f"\nOverall Health: {summary['overall_health']} ({summary['health_level']})")


def _cmd_clashes(args: argparse.Namespace) -> None:
    from pathlib import Path
    from coordination_metrics.clash_trajectory import build_trajectory, compute_trajectory_slope

    exports = sorted(Path(args.exports_dir).glob("*.xml"))
    if len(exports) < 2:
        print(f"Error: Need at least 2 XML exports, found {len(exports)}", file=sys.stderr)
        sys.exit(1)

    summaries = build_trajectory(exports)
    result = compute_trajectory_slope(summaries)
    print(json.dumps(result, indent=2, default=str))


def _cmd_rfis(args: argparse.Namespace) -> None:
    from coordination_metrics.rfi_distribution import analyse_rfi_distribution
    result = analyse_rfi_distribution(args.register_path)
    print(json.dumps(result, indent=2, default=str))


def _cmd_submittals(args: argparse.Namespace) -> None:
    from coordination_metrics.approval_rates import compute_approval_rates
    rates = compute_approval_rates(args.register_path)
    print(rates.to_string(index=False))


def _cmd_meetings(args: argparse.Namespace) -> None:
    from coordination_metrics.meeting_decisions import (
        parse_meeting_csv,
        compute_attendance_decision_correlation,
    )
    meetings = parse_meeting_csv(args.register_path)
    result = compute_attendance_decision_correlation(meetings)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
