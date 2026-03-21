"""MCP server for coordination metrics — integrate with Claude Code and other AI tools.

Usage:
    claude mcp add --scope project coordination-metrics -- python -m coordination_metrics.mcp_server

Then ask Claude: "Analyse my clash trajectory from the exports in ./data/"

The server exposes 6 tools that map to the 5 coordination metrics plus
a unified health dashboard.
"""

from __future__ import annotations

from pathlib import Path

try:
    from fastmcp import FastMCP
except ImportError:
    raise ImportError(
        "FastMCP is required for the MCP server. "
        "Install with: pip install coordination-metrics[mcp]"
    )

mcp = FastMCP(
    "coordination-metrics",
    instructions=(
        "Design coordination metrics for AEC projects. "
        "Analyse clash detection exports, submittal registers, RFI logs, "
        "and meeting minutes to assess coordination health."
    ),
)


@mcp.tool()
def analyse_clash_trajectory(exports_dir: str) -> dict:
    """Analyse clash trajectory from Navisworks XML exports in a directory.

    Finds all .xml files in the directory, parses them as Navisworks
    Clash Detective exports, and computes the trajectory slope.

    Args:
        exports_dir: Path to directory containing Navisworks XML exports.

    Returns:
        Trajectory analysis with slope, R-squared, and health assessment.
    """
    from coordination_metrics.clash_trajectory import build_trajectory, compute_trajectory_slope

    exports_path = Path(exports_dir)
    xmls = sorted(exports_path.glob("*.xml"))
    if len(xmls) < 2:
        return {"error": f"Need at least 2 XML exports, found {len(xmls)} in {exports_dir}"}

    summaries = build_trajectory(xmls)
    result = compute_trajectory_slope(summaries)
    result["rounds_parsed"] = [
        {"label": s.round_label, "total": s.total, "new": s.new, "resolved": s.resolved}
        for s in summaries
    ]
    return result


@mcp.tool()
def detect_recurring_clashes(
    round1_path: str,
    round2_path: str,
    threshold_mm: float = 500.0,
) -> dict:
    """Detect clashes that reappear near previously-resolved locations.

    Compares two consecutive clash rounds and finds spatial recurrences
    within the given threshold distance.

    Args:
        round1_path: Path to the earlier Navisworks XML export.
        round2_path: Path to the later Navisworks XML export.
        threshold_mm: Maximum distance (mm) to consider a recurrence.

    Returns:
        Recurrence analysis with rate, pairs, and health assessment.
    """
    from coordination_metrics.recurring_clashes import (
        detect_recurrences,
        extract_clash_points,
    )

    prev = extract_clash_points(round1_path)
    curr = extract_clash_points(round2_path)
    return detect_recurrences(prev, curr, threshold_mm=threshold_mm)


@mcp.tool()
def analyse_submittal_rates(register_path: str) -> dict:
    """Compute first-submission approval rates by discipline.

    Reads a submittal register (CSV or Excel) and calculates the
    percentage of submittals approved on the first submission for
    each discipline.

    Args:
        register_path: Path to the submittal register file.

    Returns:
        Per-discipline approval rates with health classification.
    """
    from coordination_metrics.approval_rates import compute_approval_rates

    rates = compute_approval_rates(register_path)
    return {
        "by_discipline": rates.to_dict(orient="records"),
        "overall_first_submission_approval_pct": round(
            rates["first_submission_approval_pct"].mean(), 1
        ) if not rates.empty else 0.0,
    }


@mcp.tool()
def analyse_rfi_distribution(register_path: str) -> dict:
    """Analyse RFI response time distribution and identify bottleneck disciplines.

    Reads an RFI register and computes median, P90, and mean response
    times overall and by discipline. Flags bottleneck disciplines whose
    P90 exceeds the threshold.

    Args:
        register_path: Path to the RFI register file.

    Returns:
        Distribution analysis with overall and per-discipline statistics.
    """
    from coordination_metrics.rfi_distribution import (
        analyse_rfi_distribution as _analyse,
    )

    return _analyse(register_path)


@mcp.tool()
def analyse_meeting_decisions(meetings_path: str) -> dict:
    """Analyse coordination meeting decision rates and attendance correlation.

    Reads a meeting minutes register and computes decision rates,
    attendance rates, and the correlation between the two.

    Args:
        meetings_path: Path to the meeting minutes file.

    Returns:
        Meeting analysis with per-meeting stats and correlation assessment.
    """
    from coordination_metrics.meeting_decisions import (
        compute_attendance_decision_correlation,
        parse_meeting_csv,
    )

    meetings = parse_meeting_csv(meetings_path)
    return compute_attendance_decision_correlation(meetings)


@mcp.tool()
def generate_coordination_health_report(data_dir: str) -> dict:
    """Run all 5 metrics and generate a unified coordination health assessment.

    Auto-discovers data files in the given directory:
    - XML files -> clash trajectory + recurring clashes
    - submittal*.csv -> approval rates
    - rfi*.csv -> RFI distribution
    - meeting*.csv -> meeting decisions

    Args:
        data_dir: Path to directory containing project data files.

    Returns:
        Unified health assessment with overall score and per-metric details.
    """
    from coordination_metrics.dashboard import CoordinationHealthDashboard

    dashboard = CoordinationHealthDashboard(data_dir=data_dir)
    health = dashboard.run()
    return health.summary()


@mcp.tool()
def compute_earned_coordination_value(config_json: str, snapshot_json: str) -> dict:
    """Compute Earned Coordination Value (ECV) — a CPI-like index for coordination.

    Answers: "Are we resolving coordination issues fast enough to meet the
    project milestone?" CPI > 1.0 = ahead, CPI < 1.0 = behind.

    Args:
        config_json: JSON string with keys: project_start, coordination_deadline,
            total_expected_clashes, total_expected_rfis, total_expected_submittals,
            total_expected_meetings, and optional weights (clash_weight, rfi_weight,
            submittal_weight, meeting_weight).
        snapshot_json: JSON string with keys: date, clashes_resolved,
            rfis_answered, submittals_approved, decisions_made.

    Returns:
        ECV snapshot with planned_value, earned_value, CPI, SPI, EAC date, status.
    """
    import json
    from datetime import date as date_cls

    from coordination_metrics.ecv import ECVConfig, compute_ecv

    cfg = json.loads(config_json)
    snap = json.loads(snapshot_json)

    config = ECVConfig(
        project_start=date_cls.fromisoformat(cfg["project_start"]),
        coordination_deadline=date_cls.fromisoformat(cfg["coordination_deadline"]),
        total_expected_clashes=cfg.get("total_expected_clashes", 0),
        total_expected_rfis=cfg.get("total_expected_rfis", 0),
        total_expected_submittals=cfg.get("total_expected_submittals", 0),
        total_expected_meetings=cfg.get("total_expected_meetings", 0),
        clash_weight=cfg.get("clash_weight", 0.35),
        rfi_weight=cfg.get("rfi_weight", 0.25),
        submittal_weight=cfg.get("submittal_weight", 0.25),
        meeting_weight=cfg.get("meeting_weight", 0.15),
    )

    result = compute_ecv(
        config=config,
        measurement_date=date_cls.fromisoformat(snap["date"]),
        clashes_resolved=snap.get("clashes_resolved", 0),
        rfis_answered=snap.get("rfis_answered", 0),
        submittals_approved=snap.get("submittals_approved", 0),
        decisions_made=snap.get("decisions_made", 0),
    )

    return {
        "date": result.date.isoformat(),
        "planned_value": result.planned_value,
        "earned_value": result.earned_value,
        "cpi": result.cpi,
        "spi": result.spi,
        "variance": round(result.variance, 1),
        "status": result.status,
        "eac_date": result.eac_date.isoformat() if result.eac_date else None,
    }


@mcp.tool()
def compare_to_benchmarks(metrics_json: str) -> list[dict]:
    """Compare project metrics against industry benchmarks.

    Supported metrics: clash_reduction_rate_per_round, recurring_clash_rate,
    first_submission_approval_rate, rfi_response_p90_days, rfi_no_response_rate,
    meeting_decision_rate.

    Args:
        metrics_json: JSON string mapping metric names to values,
            e.g. '{"recurring_clash_rate": 12.5, "meeting_decision_rate": 55}'.

    Returns:
        List of benchmark comparisons with percentile rank, classification, insight.
    """
    import json

    from coordination_metrics.benchmarks import generate_benchmark_report

    metrics = json.loads(metrics_json)
    return generate_benchmark_report(metrics)


@mcp.tool()
def discover_cross_correlations_tool(data_json: str) -> list[dict]:
    """Discover cross-metric correlations and actionable insights.

    Finds relationships between the 5 coordination metrics, such as:
    - Same discipline is both RFI bottleneck and lowest approval rate
    - Low decision rates correlate with worsening clash trajectory
    - Absent disciplines correlate with recurring clashes

    Args:
        data_json: JSON string with keys: clash_trajectory_data, recurrence_data,
            approval_data, rfi_data, meeting_data. Each is a dict of metric results.

    Returns:
        List of cross-correlations with insight text and actionability flag.
    """
    import json

    from coordination_metrics.cross_correlation import discover_cross_correlations

    data = json.loads(data_json)
    results = discover_cross_correlations(
        clash_trajectory_data=data.get("clash_trajectory_data", {}),
        recurrence_data=data.get("recurrence_data", {}),
        approval_data=data.get("approval_data", {}),
        rfi_data=data.get("rfi_data", {}),
        meeting_data=data.get("meeting_data", {}),
    )
    return [
        {
            "metric_a": c.metric_a,
            "metric_b": c.metric_b,
            "correlation": c.correlation,
            "p_value": c.p_value,
            "direction": c.direction,
            "insight": c.insight,
            "actionable": c.actionable,
        }
        for c in results
    ]


if __name__ == "__main__":
    mcp.run()
