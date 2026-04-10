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
                # Store per-round data for charting
                traj_result["_round_data"] = [
                    {
                        "round_label": s.round_label,
                        "round_date": s.round_date.isoformat(),
                        "total": s.total,
                        "new": s.new,
                        "active": s.active,
                        "reviewed": s.reviewed,
                        "resolved": s.resolved,
                    }
                    for s in summaries
                ]
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
    """Render the coordination health dashboard as interactive HTML with ECharts."""
    summary = health.summary()
    level = summary["health_level"]
    color = _health_color(level)
    metrics = summary["metrics"]
    details = summary.get("details", {})

    # --- Prepare chart data as JSON for ECharts ---
    # Radar data
    radar_indicators = []
    radar_values = []
    labels = {
        "clash_trajectory": "Clash Trajectory",
        "recurring_clashes": "Recurring Clashes",
        "approval_rate": "Approval Rate",
        "rfi_response": "RFI Response",
        "meeting_decisions": "Meeting Decisions",
    }
    for key, label in labels.items():
        radar_indicators.append({"name": label, "max": 100})
        radar_values.append(metrics[key])

    # Trajectory data
    traj_details = details.get("clash_trajectory", {})
    round_data = traj_details.get("_round_data", []) if isinstance(traj_details, dict) else []
    traj_labels = [r["round_date"] for r in round_data]
    traj_totals = [r["total"] for r in round_data]
    traj_new = [r["new"] for r in round_data]
    traj_resolved = [r["resolved"] for r in round_data]

    # Meeting data
    mtg_details = details.get("meeting_decisions", {})
    per_meeting = mtg_details.get("per_meeting", []) if isinstance(mtg_details, dict) else []
    mtg_dates = [m["meeting_date"] for m in per_meeting]
    mtg_decision = [m["decision_rate_pct"] for m in per_meeting]
    mtg_attendance = [m["attendance_rate_pct"] for m in per_meeting]

    # Approval data
    approval_list = details.get("approval_rates", [])
    approval_discs = []
    approval_pcts = []
    if isinstance(approval_list, list):
        for d in approval_list:
            approval_discs.append(d.get("discipline", ""))
            approval_pcts.append(d.get("first_submission_approval_pct", 0))

    # RFI data
    rfi_details = details.get("rfi_distribution", {})
    rfi_by_disc = rfi_details.get("by_discipline", []) if isinstance(rfi_details, dict) else []
    rfi_discs = []
    rfi_medians = []
    rfi_p90s = []
    if isinstance(rfi_by_disc, list):
        for d in rfi_by_disc:
            rfi_discs.append(d.get("discipline", ""))
            rfi_medians.append(d.get("median_days", 0))
            rfi_p90s.append(d.get("p90_days", 0))

    # Recurring clash data
    recur_details = details.get("recurring_clashes", {})
    recur_count = recur_details.get("recurring_count", 0) if isinstance(recur_details, dict) else 0
    resolved_count = recur_details.get("resolved_count", 0) if isinstance(recur_details, dict) else 0
    held_count = max(0, resolved_count - recur_count)

    # Benchmark data
    benchmarks = details.get("benchmarks", [])
    bench_data = []
    if isinstance(benchmarks, list):
        for b in benchmarks:
            bench_data.append({
                "metric": b.get("metric", ""),
                "rank": b.get("percentile_rank", 50),
                "comparison": b.get("comparison", "average"),
                "insight": b.get("insight", ""),
            })

    # Cross-correlation data
    cross_corr = details.get("cross_correlations", [])

    # Serialize all chart data
    chart_data = json.dumps({
        "radar": {"indicators": radar_indicators, "values": radar_values},
        "trajectory": {"labels": traj_labels, "totals": traj_totals,
                        "new": traj_new, "resolved": traj_resolved},
        "meetings": {"dates": mtg_dates, "decision": mtg_decision,
                      "attendance": mtg_attendance},
        "approval": {"disciplines": approval_discs, "pcts": approval_pcts},
        "rfi": {"disciplines": rfi_discs, "medians": rfi_medians, "p90s": rfi_p90s},
        "recurrence": {"recurring": recur_count, "held": held_count,
                        "rate": recur_details.get("recurrence_rate_pct", 0)
                        if isinstance(recur_details, dict) else 0},
    }, default=str)

    # Build insight cards HTML
    insight_cards_html = ""
    if isinstance(cross_corr, list) and cross_corr:
        for cc in cross_corr:
            tag = ' <span class="tag tag-action">ACTIONABLE</span>' if cc.get("actionable") else ""
            insight_cards_html += f"""
            <div class="card insight-card">
                <div class="card-label">{cc.get('metric_a', '')} &harr; {cc.get('metric_b', '')}</div>
                <div class="insight-text">{cc.get('insight', '')}{tag}</div>
            </div>"""

    # Build benchmark cards HTML
    bench_cards_html = ""
    if bench_data:
        for b in bench_data:
            bc = {"above_average": "#22c55e", "average": "#f59e0b",
                  "below_average": "#f97316", "critical": "#ef4444"}.get(b["comparison"], "#6b7280")
            bench_cards_html += f"""
            <div class="card" style="text-align:center">
                <div class="card-label">{b['metric']}</div>
                <div style="font-size:2rem;font-weight:700;color:{bc}">{b['rank']:.0f}<span style="font-size:1rem">th</span></div>
                <div style="font-size:0.75rem;color:#94a3b8;margin-top:0.5rem">{b['insight']}</div>
            </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Coordination Health Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0f172a;color:#e2e8f0;padding:1.5rem}}
.dash{{max-width:1200px;margin:0 auto}}
.header{{text-align:center;margin-bottom:1.5rem}}
.header h1{{font-size:1.6rem;margin-bottom:0.3rem;color:#cbd5e1}}
.score{{font-size:4.5rem;font-weight:800;color:{color};margin:0.5rem 0}}
.badge{{display:inline-block;padding:0.3rem 1rem;border-radius:2rem;background:{color}22;color:{color};font-weight:600;text-transform:uppercase;letter-spacing:0.05em;font-size:0.85rem}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-top:1.5rem}}
.grid3{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1rem;margin-top:1rem}}
.card{{background:#1e293b;border-radius:0.75rem;padding:1rem;min-height:60px}}
.card-label{{font-size:0.7rem;color:#94a3b8;text-transform:uppercase;letter-spacing:0.05em;margin-bottom:0.4rem}}
.chart-container{{width:100%;height:380px}}
.chart-wide{{width:100%;height:420px}}
.section{{margin-top:2rem}}
.section h2{{font-size:1.1rem;font-weight:600;color:#cbd5e1;border-bottom:1px solid #334155;padding-bottom:0.4rem;margin-bottom:1rem}}
.insight-card{{border-left:3px solid #3b82f6}}
.insight-text{{font-size:0.85rem;line-height:1.5}}
.tag{{display:inline-block;font-size:0.6rem;padding:0.1rem 0.5rem;border-radius:1rem;font-weight:600;margin-left:0.4rem;vertical-align:middle}}
.tag-action{{background:#22c55e22;color:#22c55e}}
.footer{{text-align:center;margin-top:2rem;color:#475569;font-size:0.8rem}}
@media(max-width:768px){{.grid2{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<div class="dash">
  <div class="header">
    <h1>Coordination Health Dashboard</h1>
    <p style="color:#64748b;font-size:0.85rem">Generated {date.today().isoformat()}</p>
    <div class="score">{summary['overall_health']}</div>
    <span class="badge">{level.replace('_', ' ')}</span>
  </div>

  <!-- Row 1: Radar + Trajectory -->
  <div class="grid2">
    <div class="card"><div class="card-label">Health Radar</div><div id="radar" class="chart-container"></div></div>
    <div class="card"><div class="card-label">Clash Trajectory</div><div id="trajectory" class="chart-container"></div></div>
  </div>

  <!-- Row 2: Meeting Decisions + Approval Rates -->
  <div class="grid2">
    <div class="card"><div class="card-label">Meeting Decisions &amp; Attendance</div><div id="meetings" class="chart-container"></div></div>
    <div class="card"><div class="card-label">Approval Rates &amp; RFI Response</div><div id="approval" class="chart-container"></div></div>
  </div>

  <!-- Row 3: Recurring Clashes (single) -->
  <div class="grid2">
    <div class="card"><div class="card-label">Recurring Clash Rate</div><div id="recurrence" class="chart-container"></div></div>
    <div class="card"><div class="card-label">RFI Response by Discipline</div><div id="rfi" class="chart-container"></div></div>
  </div>

  <!-- Benchmarks -->
  {"" if not bench_cards_html else f'''<div class="section"><h2>Industry Benchmarks</h2><div class="grid3">{bench_cards_html}</div></div>'''}

  <!-- Cross-Metric Insights -->
  {"" if not insight_cards_html else f'''<div class="section"><h2>Cross-Metric Insights</h2><div style="display:flex;flex-direction:column;gap:0.75rem">{insight_cards_html}</div></div>'''}

  <div class="footer">coordination-metrics v0.1.1 | Metrics that predict design coordination failure</div>
</div>

<script>
var D = {chart_data};
var BG = '#1e293b';
var TXT = '#e2e8f0';
var GRID = '#334155';
var GREEN = '#22c55e';
var AMBER = '#f59e0b';
var RED = '#ef4444';
var BLUE = '#3b82f6';
var PURPLE = '#a855f7';

function init(id) {{
  var el = document.getElementById(id);
  if (!el) return null;
  return echarts.init(el, null, {{renderer:'canvas'}});
}}

// 1. Radar
var r = init('radar');
if (r) r.setOption({{
  backgroundColor: BG,
  radar: {{
    center: ['50%','55%'], radius: '65%',
    indicator: D.radar.indicators,
    axisName: {{color: TXT, fontSize: 11}},
    splitLine: {{lineStyle: {{color: GRID}}}},
    splitArea: {{areaStyle: {{color: ['transparent','transparent']}}}},
    axisLine: {{lineStyle: {{color: GRID}}}}
  }},
  series: [{{
    type: 'radar',
    data: [{{
      value: D.radar.values,
      areaStyle: {{color: 'rgba(59,130,246,0.15)'}},
      lineStyle: {{color: BLUE, width: 2}},
      itemStyle: {{color: BLUE}},
      symbol: 'circle', symbolSize: 6
    }}]
  }}]
}});

// 2. Trajectory
var t = init('trajectory');
if (t && D.trajectory.labels.length > 0) t.setOption({{
  backgroundColor: BG,
  tooltip: {{trigger:'axis', backgroundColor:'#1e293b', borderColor:GRID, textStyle:{{color:TXT}}}},
  legend: {{data:['Total','New','Resolved'], textStyle:{{color:TXT}}, top:0}},
  grid: {{top:40, bottom:80, left:65, right:20, containLabel:true}},
  xAxis: {{type:'category', data:D.trajectory.labels, axisLabel:{{color:TXT,rotate:20,fontSize:10}}, axisLine:{{lineStyle:{{color:GRID}}}}}},
  yAxis: {{type:'value', name:'Clashes', nameTextStyle:{{color:TXT}}, axisLabel:{{color:TXT}}, splitLine:{{lineStyle:{{color:GRID,type:'dashed'}}}}}},
  series: [
    {{name:'Total', type:'bar', data:D.trajectory.totals, itemStyle:{{color:'rgba(59,130,246,0.4)'}}, barWidth:'40%'}},
    {{name:'New', type:'line', data:D.trajectory.new, itemStyle:{{color:RED}}, lineStyle:{{width:2}}, symbol:'circle', symbolSize:6}},
    {{name:'Resolved', type:'line', data:D.trajectory.resolved, itemStyle:{{color:GREEN}}, lineStyle:{{width:2}}, symbol:'rect', symbolSize:6}}
  ]
}});

// 3. Meeting Decisions
var m = init('meetings');
if (m && D.meetings.dates.length > 0) m.setOption({{
  backgroundColor: BG,
  tooltip: {{trigger:'axis', backgroundColor:'#1e293b', borderColor:GRID, textStyle:{{color:TXT}}}},
  legend: {{data:['Decision Rate','Attendance'], textStyle:{{color:TXT}}, top:0}},
  grid: {{top:40, bottom:80, left:60, right:60, containLabel:true}},
  xAxis: {{type:'category', data:D.meetings.dates, axisLabel:{{color:TXT,rotate:20,fontSize:10}}, axisLine:{{lineStyle:{{color:GRID}}}}}},
  yAxis: [
    {{type:'value', name:'Decision %', min:0, max:100, nameTextStyle:{{color:TXT}}, axisLabel:{{color:TXT}}, splitLine:{{lineStyle:{{color:GRID,type:'dashed'}}}}}},
    {{type:'value', name:'Attendance %', min:0, max:100, nameTextStyle:{{color:TXT}}, axisLabel:{{color:TXT}}, splitLine:{{show:false}}}}
  ],
  series: [
    {{name:'Decision Rate', type:'bar', data:D.meetings.decision, itemStyle:{{color:'rgba(59,130,246,0.7)'}}, barWidth:'35%'}},
    {{name:'Attendance', type:'line', yAxisIndex:1, data:D.meetings.attendance, itemStyle:{{color:PURPLE}}, lineStyle:{{width:2}}, symbol:'diamond', symbolSize:7}}
  ]
}});

// 4. Approval + RFI combo
var a = init('approval');
if (a && D.approval.disciplines.length > 0) a.setOption({{
  backgroundColor: BG,
  tooltip: {{trigger:'axis', backgroundColor:'#1e293b', borderColor:GRID, textStyle:{{color:TXT}}}},
  legend: {{data:['Approval %'], textStyle:{{color:TXT}}, top:0}},
  grid: {{top:40, bottom:15, left:10, right:40, containLabel:true}},
  xAxis: {{type:'value', min:0, max:100, axisLabel:{{color:TXT}}, splitLine:{{lineStyle:{{color:GRID,type:'dashed'}}}}}},
  yAxis: {{type:'category', data:D.approval.disciplines, axisLabel:{{color:TXT}}}},
  series: [{{
    name:'Approval %', type:'bar', data:D.approval.pcts.map(function(v){{
      return {{value:v, itemStyle:{{color: v>=70?GREEN:v>=50?AMBER:RED}}}};
    }}),
    label: {{show:true, position:'right', color:TXT, formatter:'{{c}}%'}}
  }}],
  visualMap: {{show:false}}
}});

// 5. Recurrence donut
var rc = init('recurrence');
if (rc && (D.recurrence.recurring + D.recurrence.held) > 0) rc.setOption({{
  backgroundColor: BG,
  tooltip: {{trigger:'item', backgroundColor:'#1e293b', borderColor:GRID, textStyle:{{color:TXT}}}},
  title: {{text: D.recurrence.rate.toFixed(1)+'%', subtext:'recurrence', left:'center', top:'center',
    textStyle:{{color:D.recurrence.rate>25?RED:D.recurrence.rate>10?AMBER:GREEN, fontSize:28, fontWeight:700}},
    subtextStyle:{{color:TXT, fontSize:12}}}},
  series: [{{
    type:'pie', radius:['55%','80%'],
    data:[
      {{value:D.recurrence.recurring, name:'Recurring', itemStyle:{{color:RED}}}},
      {{value:D.recurrence.held, name:'Held', itemStyle:{{color:GREEN}}}}
    ],
    label:{{show:true, color:TXT, formatter:'{{b}}: {{c}}'}},
    emphasis:{{itemStyle:{{shadowBlur:10, shadowColor:'rgba(0,0,0,0.5)'}}}}
  }}]
}});

// 6. RFI by discipline
var rf = init('rfi');
if (rf && D.rfi.disciplines.length > 0) rf.setOption({{
  backgroundColor: BG,
  tooltip: {{trigger:'axis', backgroundColor:'#1e293b', borderColor:GRID, textStyle:{{color:TXT}}}},
  legend: {{data:['Median','P90'], textStyle:{{color:TXT}}, top:0}},
  grid: {{top:40, bottom:15, left:10, right:40, containLabel:true}},
  xAxis: {{type:'value', name:'Days', nameTextStyle:{{color:TXT}}, axisLabel:{{color:TXT}}, splitLine:{{lineStyle:{{color:GRID,type:'dashed'}}}}}},
  yAxis: {{type:'category', data:D.rfi.disciplines, axisLabel:{{color:TXT}}}},
  series: [
    {{name:'Median', type:'bar', data:D.rfi.medians, itemStyle:{{color:BLUE}}, barWidth:'30%'}},
    {{name:'P90', type:'bar', data:D.rfi.p90s, itemStyle:{{color:AMBER}}, barWidth:'30%'}}
  ]
}});

// Responsive resize
window.addEventListener('resize', function(){{
  [r,t,m,a,rc,rf].forEach(function(c){{ if(c) c.resize(); }});
}});
</script>
</body>
</html>"""
