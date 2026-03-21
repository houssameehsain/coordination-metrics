"""Unified coordination health dashboard.

Combines all metrics into a single health assessment, with traffic-light
classification and an optional HTML report.

Usage:
    >>> from coordination_metrics import CoordinationHealthDashboard
    >>> dashboard = CoordinationHealthDashboard(data_dir="./project_data/")
    >>> health = dashboard.run()
    >>> print(health.summary())
    >>> dashboard.generate_html_report(health, output_path="report.html")
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Union

from coordination_metrics.core import CoordinationHealth, HealthLevel


class CoordinationHealthDashboard:
    """Runs all 5 coordination metrics and produces a unified health assessment.

    The dashboard discovers data files in a project directory using
    conventional naming, or accepts explicit file paths.

    Args:
        data_dir: Directory containing project data files.
        clash_exports: Explicit list of Navisworks XML paths (overrides discovery).
        submittal_register: Explicit path to submittal register.
        rfi_register: Explicit path to RFI register.
        meeting_register: Explicit path to meeting minutes.
    """

    def __init__(
        self,
        data_dir: Optional[Union[str, Path]] = None,
        *,
        clash_exports: Optional[list[Union[str, Path]]] = None,
        submittal_register: Optional[Union[str, Path]] = None,
        rfi_register: Optional[Union[str, Path]] = None,
        meeting_register: Optional[Union[str, Path]] = None,
    ):
        self.data_dir = Path(data_dir) if data_dir else None
        self._clash_exports = clash_exports
        self._submittal_register = submittal_register
        self._rfi_register = rfi_register
        self._meeting_register = meeting_register

    def _discover_files(self) -> dict[str, object]:
        """Auto-discover data files in the data directory."""
        found: dict[str, object] = {}
        if not self.data_dir or not self.data_dir.exists():
            return found

        # Clash exports: XML files with "clash" or "round" in the name
        xmls = sorted(self.data_dir.glob("*.xml"))
        clash_xmls = [f for f in xmls if any(k in f.stem.lower() for k in ("clash", "round"))]
        if not clash_xmls:
            clash_xmls = xmls  # fall back to all XMLs
        if clash_xmls:
            found["clash_exports"] = clash_xmls

        # BCF files
        bcf_files = sorted(
            list(self.data_dir.glob("*.bcf"))
            + list(self.data_dir.glob("*.bcfzip"))
        )
        if bcf_files:
            found["bcf_exports"] = bcf_files

        # Registers: CSV/Excel files with keywords
        for ext in ("*.csv", "*.xlsx", "*.xls"):
            for f in self.data_dir.glob(ext):
                name = f.stem.lower()
                if "submittal" in name and "submittal_register" not in found:
                    found["submittal_register"] = f
                elif "rfi" in name and "rfi_register" not in found:
                    found["rfi_register"] = f
                elif "meeting" in name and "meeting_register" not in found:
                    found["meeting_register"] = f

        return found

    def run(self) -> CoordinationHealth:
        """Execute all metrics and return a unified health assessment.

        Metrics that cannot run (missing data) are scored at 50 (neutral)
        with a note in the details.

        Returns:
            CoordinationHealth with all scores populated.
        """
        # Lazy imports to avoid circular dependencies
        from coordination_metrics.clash_trajectory import (
            build_trajectory,
            compute_trajectory_slope,
            projected_zero_date,
            trajectory_to_score,
        )
        from coordination_metrics.recurring_clashes import (
            detect_recurrences,
            extract_clash_points,
            recurrence_to_score,
        )
        from coordination_metrics.approval_rates import (
            approval_to_score,
            compute_approval_rates,
        )
        from coordination_metrics.rfi_distribution import (
            analyse_rfi_distribution,
            rfi_to_score,
        )
        from coordination_metrics.meeting_decisions import (
            compute_attendance_decision_correlation,
            meeting_to_score,
            parse_meeting_csv,
        )

        discovered = self._discover_files()
        details: dict = {}
        health = CoordinationHealth()

        # --- Metric 1: Clash Trajectory ---
        clash_exports = self._clash_exports or discovered.get("clash_exports")
        if clash_exports and len(clash_exports) >= 2:
            try:
                summaries = build_trajectory(clash_exports)
                traj_result = compute_trajectory_slope(summaries)
                # Add zero-clash projection
                projection = projected_zero_date(summaries)
                traj_result["zero_clash_projection"] = projection
                health.clash_trajectory_score = trajectory_to_score(traj_result["slope"])
                details["clash_trajectory"] = traj_result
            except Exception as e:
                health.clash_trajectory_score = 50.0
                details["clash_trajectory"] = {"error": str(e)}
        else:
            health.clash_trajectory_score = 50.0
            details["clash_trajectory"] = {"note": "Need >= 2 clash export XMLs."}

        # --- Metric 2: Recurring Clashes ---
        if clash_exports and len(clash_exports) >= 2:
            try:
                prev_points = extract_clash_points(clash_exports[-2])
                curr_points = extract_clash_points(clash_exports[-1])
                recur_result = detect_recurrences(prev_points, curr_points)
                health.recurring_clash_score = recurrence_to_score(
                    recur_result["recurrence_rate_pct"]
                )
                details["recurring_clashes"] = recur_result
            except Exception as e:
                health.recurring_clash_score = 50.0
                details["recurring_clashes"] = {"error": str(e)}
        else:
            health.recurring_clash_score = 50.0
            details["recurring_clashes"] = {"note": "Need >= 2 clash export XMLs."}

        # --- Metric 3: Approval Rates ---
        sub_path = self._submittal_register or discovered.get("submittal_register")
        if sub_path:
            try:
                rates = compute_approval_rates(sub_path)
                health.approval_rate_score = approval_to_score(rates)
                details["approval_rates"] = rates.to_dict(orient="records")
            except Exception as e:
                health.approval_rate_score = 50.0
                details["approval_rates"] = {"error": str(e)}
        else:
            health.approval_rate_score = 50.0
            details["approval_rates"] = {"note": "No submittal register found."}

        # --- Metric 4: RFI Distribution ---
        rfi_path = self._rfi_register or discovered.get("rfi_register")
        if rfi_path:
            try:
                rfi_result = analyse_rfi_distribution(
                    rfi_path, include_open_rfis=True
                )
                health.rfi_response_score = rfi_to_score(rfi_result)
                details["rfi_distribution"] = rfi_result
            except Exception as e:
                health.rfi_response_score = 50.0
                details["rfi_distribution"] = {"error": str(e)}
        else:
            health.rfi_response_score = 50.0
            details["rfi_distribution"] = {"note": "No RFI register found."}

        # --- Metric 5: Meeting Decisions ---
        mtg_path = self._meeting_register or discovered.get("meeting_register")
        if mtg_path:
            try:
                meetings = parse_meeting_csv(mtg_path)
                mtg_result = compute_attendance_decision_correlation(meetings)
                health.meeting_decision_score = meeting_to_score(mtg_result)
                details["meeting_decisions"] = mtg_result
            except Exception as e:
                health.meeting_decision_score = 50.0
                details["meeting_decisions"] = {"error": str(e)}
        else:
            health.meeting_decision_score = 50.0
            details["meeting_decisions"] = {"note": "No meeting register found."}

        # --- ECV (if sufficient data) ---
        try:
            from coordination_metrics.ecv import ECVConfig, compute_ecv

            clash_traj = details.get("clash_trajectory", {})
            rfi_dist = details.get("rfi_distribution", {})
            approval_det = details.get("approval_rates", {})
            mtg_det = details.get("meeting_decisions", {})

            has_ecv_data = (
                isinstance(clash_traj, dict)
                and "slope" in clash_traj
                and isinstance(rfi_dist, dict)
                and "overall" in rfi_dist
            )
            if has_ecv_data:
                details["ecv"] = {"note": "ECV available — use compute_ecv() with project config."}
            else:
                details["ecv"] = {"note": "Insufficient data for ECV calculation."}
        except Exception:
            details["ecv"] = {"note": "ECV module not available."}

        # --- Benchmark comparisons ---
        try:
            from coordination_metrics.benchmarks import generate_benchmark_report

            bench_metrics: dict[str, float] = {}
            if isinstance(details.get("recurring_clashes"), dict):
                rate = details["recurring_clashes"].get("recurrence_rate_pct")
                if rate is not None:
                    bench_metrics["recurring_clash_rate"] = rate
            if isinstance(details.get("rfi_distribution"), dict):
                overall = details["rfi_distribution"].get("overall", {})
                if isinstance(overall, dict):
                    p90 = overall.get("p90_days")
                    if p90 is not None:
                        bench_metrics["rfi_response_p90_days"] = p90
                    no_resp = overall.get("no_response_pct")
                    if no_resp is not None:
                        bench_metrics["rfi_no_response_rate"] = no_resp
            if isinstance(details.get("meeting_decisions"), dict):
                avg_dr = details["meeting_decisions"].get("avg_decision_rate_pct")
                if avg_dr is not None:
                    bench_metrics["meeting_decision_rate"] = avg_dr

            if bench_metrics:
                details["benchmarks"] = generate_benchmark_report(bench_metrics)
            else:
                details["benchmarks"] = {"note": "No metrics available for benchmarking."}
        except Exception:
            details["benchmarks"] = {"note": "Benchmark module not available."}

        # --- Cross-correlations ---
        try:
            from coordination_metrics.cross_correlation import discover_cross_correlations

            correlations = discover_cross_correlations(
                clash_trajectory_data=details.get("clash_trajectory", {}),
                recurrence_data=details.get("recurring_clashes", {}),
                approval_data=details.get("approval_rates", {}),
                rfi_data=details.get("rfi_distribution", {}),
                meeting_data=details.get("meeting_decisions", {}),
            )
            if correlations:
                details["cross_correlations"] = [
                    {
                        "metric_a": c.metric_a,
                        "metric_b": c.metric_b,
                        "correlation": c.correlation,
                        "direction": c.direction,
                        "insight": c.insight,
                        "actionable": c.actionable,
                    }
                    for c in correlations
                ]
            else:
                details["cross_correlations"] = []
        except Exception:
            details["cross_correlations"] = []

        health.details = details
        return health

    def generate_html_report(
        self,
        health: CoordinationHealth,
        output_path: Optional[Union[str, Path]] = None,
    ) -> str:
        """Generate an HTML dashboard report.

        Args:
            health: CoordinationHealth from run().
            output_path: Optional path to write the HTML file.

        Returns:
            HTML string.
        """
        html = _render_html(health)
        if output_path:
            Path(output_path).write_text(html, encoding="utf-8")
        return html


def _health_color(level: str) -> str:
    """Map health level to CSS color."""
    return {
        "healthy": "#22c55e",
        "at_risk": "#f59e0b",
        "critical": "#ef4444",
    }.get(level, "#6b7280")


def _render_html(health: CoordinationHealth) -> str:
    """Render the coordination health dashboard as HTML."""
    summary = health.summary()
    level = summary["health_level"]
    color = _health_color(level)
    metrics = summary["metrics"]

    metric_cards = ""
    labels = {
        "clash_trajectory": "Clash Trajectory",
        "recurring_clashes": "Recurring Clashes",
        "approval_rate": "Approval Rate",
        "rfi_response": "RFI Response",
        "meeting_decisions": "Meeting Decisions",
    }

    for key, label in labels.items():
        score = metrics[key]
        if score >= 70:
            card_color = "#22c55e"
        elif score >= 45:
            card_color = "#f59e0b"
        else:
            card_color = "#ef4444"

        metric_cards += f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-score" style="color: {card_color}">{score}</div>
            <div class="metric-bar">
                <div class="metric-fill" style="width: {score}%; background: {card_color}"></div>
            </div>
        </div>"""

    details = summary.get("details", {})

    # --- Extra detail sections for new models ---
    extra_detail_cards = ""

    # Exponential decay info
    traj_details = details.get("clash_trajectory", {})
    if isinstance(traj_details, dict):
        decay_rate = traj_details.get("decay_rate")
        decay_health = traj_details.get("decay_health")
        projection = traj_details.get("zero_clash_projection", {})
        changepoints = traj_details.get("changepoints", [])

        if decay_rate is not None:
            decay_color = _health_color(
                "healthy" if decay_health == "healthy"
                else "at_risk" if decay_health == "slowing"
                else "critical"
            )
            proj_text = ""
            if isinstance(projection, dict) and projection.get("projected_date"):
                proj_text = (
                    f"<br>Near-zero projected: <strong>{projection['projected_date']}</strong> "
                    f"({projection.get('days_from_last_round', '?')}d from last round)"
                )
            cp_text = ""
            if changepoints:
                cp_text = f"<br>Changepoints: {len(changepoints)} scope change(s)"
            extra_detail_cards += f"""
            <div class="insight-card">
                <div class="insight-metrics">Exponential Decay Model</div>
                <div class="insight-text">
                    Decay rate: <strong style="color: {decay_color}">{decay_rate}</strong>
                    ({decay_health}){proj_text}{cp_text}
                </div>
            </div>"""

    # Survival analysis info
    rfi_details = details.get("rfi_distribution", {})
    if isinstance(rfi_details, dict):
        rfi_overall = rfi_details.get("overall", {})
        km_p50 = rfi_overall.get("km_p50") if isinstance(rfi_overall, dict) else None
        km_p90 = rfi_overall.get("km_p90") if isinstance(rfi_overall, dict) else None
        if km_p50 is not None or km_p90 is not None:
            open_count = rfi_overall.get("open_rfis", 0) if isinstance(rfi_overall, dict) else 0
            extra_detail_cards += f"""
            <div class="insight-card">
                <div class="insight-metrics">RFI Survival Analysis (Kaplan-Meier)</div>
                <div class="insight-text">
                    Censored P50: <strong>{km_p50}</strong> biz days,
                    Censored P90: <strong>{km_p90}</strong> biz days
                    ({open_count} open RFIs as right-censored)
                </div>
            </div>"""

    # Correlation significance
    mtg_details = details.get("meeting_decisions", {})
    if isinstance(mtg_details, dict):
        pearson_r = mtg_details.get("pearson_r")
        p_value = mtg_details.get("p_value")
        significant = mtg_details.get("significant")
        if pearson_r is not None:
            sig_text = "Significant" if significant else "Not significant"
            sig_color = "#22c55e" if significant else "#f59e0b"
            extra_detail_cards += f"""
            <div class="insight-card">
                <div class="insight-metrics">Attendance-Decision Correlation</div>
                <div class="insight-text">
                    r={pearson_r}, p={p_value}
                    <strong style="color: {sig_color}">({sig_text})</strong>
                </div>
            </div>"""

    extra_section = ""
    if extra_detail_cards:
        extra_section = f"""
        <div class="section-header">Statistical Models</div>
        <div class="insights-list">{extra_detail_cards}
        </div>"""

    # --- Benchmark comparison section ---
    benchmark_section = ""
    benchmarks = summary.get("details", {}).get("benchmarks", [])
    if isinstance(benchmarks, list) and benchmarks:
        benchmark_cards = ""
        for b in benchmarks:
            pct = b.get("percentile_rank", 50)
            comp = b.get("comparison", "average")
            b_color = {
                "above_average": "#22c55e",
                "average": "#f59e0b",
                "below_average": "#f97316",
                "critical": "#ef4444",
            }.get(comp, "#6b7280")
            benchmark_cards += f"""
            <div class="benchmark-card">
                <div class="metric-label">{b.get('metric', '')}</div>
                <div class="metric-score" style="color: {b_color}">{pct:.0f}th</div>
                <div class="benchmark-insight">{b.get('insight', '')}</div>
            </div>"""
        benchmark_section = f"""
        <div class="section-header">Industry Benchmarks</div>
        <div class="metrics-grid">{benchmark_cards}
        </div>"""

    # --- Cross-correlation insights section ---
    insights_section = ""
    cross_corr = summary.get("details", {}).get("cross_correlations", [])
    if isinstance(cross_corr, list) and cross_corr:
        insight_items = ""
        for cc in cross_corr:
            actionable_tag = ' <span class="actionable-tag">ACTIONABLE</span>' if cc.get("actionable") else ""
            insight_items += f"""
            <div class="insight-card">
                <div class="insight-metrics">{cc.get('metric_a', '')} &harr; {cc.get('metric_b', '')}</div>
                <div class="insight-text">{cc.get('insight', '')}{actionable_tag}</div>
            </div>"""
        insights_section = f"""
        <div class="section-header">Cross-Metric Insights</div>
        <div class="insights-list">{insight_items}
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Coordination Health Dashboard</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f172a;
            color: #e2e8f0;
            padding: 2rem;
        }}
        .dashboard {{
            max-width: 900px;
            margin: 0 auto;
        }}
        .header {{
            text-align: center;
            margin-bottom: 2rem;
        }}
        .header h1 {{
            font-size: 1.8rem;
            margin-bottom: 0.5rem;
        }}
        .overall-score {{
            font-size: 4rem;
            font-weight: 800;
            color: {color};
            margin: 1rem 0;
        }}
        .health-badge {{
            display: inline-block;
            padding: 0.4rem 1.2rem;
            border-radius: 2rem;
            background: {color}22;
            color: {color};
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 1rem;
            margin-top: 2rem;
        }}
        .metric-card {{
            background: #1e293b;
            border-radius: 0.75rem;
            padding: 1.2rem;
            text-align: center;
        }}
        .metric-label {{
            font-size: 0.8rem;
            color: #94a3b8;
            margin-bottom: 0.5rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}
        .metric-score {{
            font-size: 2rem;
            font-weight: 700;
            margin-bottom: 0.5rem;
        }}
        .metric-bar {{
            height: 4px;
            background: #334155;
            border-radius: 2px;
            overflow: hidden;
        }}
        .metric-fill {{
            height: 100%;
            border-radius: 2px;
            transition: width 0.6s ease;
        }}
        .section-header {{
            font-size: 1.2rem;
            font-weight: 600;
            margin-top: 2.5rem;
            margin-bottom: 1rem;
            color: #cbd5e1;
            border-bottom: 1px solid #334155;
            padding-bottom: 0.5rem;
        }}
        .benchmark-card {{
            background: #1e293b;
            border-radius: 0.75rem;
            padding: 1.2rem;
            text-align: center;
        }}
        .benchmark-insight {{
            font-size: 0.75rem;
            color: #94a3b8;
            margin-top: 0.5rem;
        }}
        .insights-list {{
            display: flex;
            flex-direction: column;
            gap: 0.75rem;
        }}
        .insight-card {{
            background: #1e293b;
            border-radius: 0.75rem;
            padding: 1rem 1.2rem;
            border-left: 3px solid #3b82f6;
        }}
        .insight-metrics {{
            font-size: 0.75rem;
            color: #64748b;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 0.4rem;
        }}
        .insight-text {{
            font-size: 0.9rem;
            color: #e2e8f0;
            line-height: 1.5;
        }}
        .actionable-tag {{
            display: inline-block;
            font-size: 0.65rem;
            background: #22c55e22;
            color: #22c55e;
            padding: 0.1rem 0.5rem;
            border-radius: 1rem;
            font-weight: 600;
            margin-left: 0.5rem;
            vertical-align: middle;
        }}
        .footer {{
            text-align: center;
            margin-top: 2rem;
            color: #64748b;
            font-size: 0.85rem;
        }}
    </style>
</head>
<body>
    <div class="dashboard">
        <div class="header">
            <h1>Coordination Health Dashboard</h1>
            <p>Generated {date.today().isoformat()}</p>
            <div class="overall-score">{summary['overall_health']}</div>
            <span class="health-badge">{level.replace('_', ' ')}</span>
        </div>
        <div class="metrics-grid">{metric_cards}
        </div>{extra_section}{benchmark_section}{insights_section}
        <div class="footer">
            <p>coordination-metrics v0.1.0 | Metrics that predict design coordination failure</p>
        </div>
    </div>
</body>
</html>"""
