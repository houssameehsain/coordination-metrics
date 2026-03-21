# coordination-metrics

**Metrics That Predict Design Coordination Failure Before It Hits Site**

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![PyPI](https://img.shields.io/badge/PyPI-coordination--metrics-orange.svg)](https://pypi.org/project/coordination-metrics/)

A Python toolkit that extracts leading indicators of coordination failure from standard AEC project data — Navisworks clash exports, submittal registers, RFI logs, and meeting minutes. Designed for BIM managers, design coordinators, and digital engineering leads who need to catch problems weeks before they reach site.

## Why These Metrics

Design coordination on complex buildings is where projects are won or lost:

- **70% of construction defects originate in design** (GIRI, 2019) — most are coordination failures between disciplines, not individual design errors.
- **Rework costs 5-15% of total project value** (CII) — and the majority traces back to information that was available but never surfaced at the right time.

The standard practice of counting open clashes tells you where you are, not where you're heading. These metrics are the *derivatives* — they tell you whether coordination is improving or deteriorating, while there's still time to act.

## Quick Start

```bash
pip install coordination-metrics
```

```python
from coordination_metrics import build_trajectory, compute_trajectory_slope

summaries = build_trajectory(["round1.xml", "round2.xml", "round3.xml"])
result = compute_trajectory_slope(summaries)
print(f"Slope: {result['slope']:+.1f} clashes/day — {result['interpretation']}")
```

## Core Metrics

| # | Metric | What It Measures | Healthy | Critical |
|---|--------|-----------------|---------|----------|
| 1 | **Clash Trajectory Slope** | Rate of change in total hard clashes across detection rounds | Negative slope (clashes decreasing) | Positive slope > 2/day |
| 2 | **Recurring Clash Rate** | Percentage of resolved clashes that reappear near the same location | < 10% | > 25% |
| 3 | **First-Submission Approval Rate** | Submittals approved on the first attempt, by discipline | > 75% | < 50% |
| 4 | **RFI Response Time P90** | 90th percentile response time — exposes the long tail | P90 < 7 days | P90 > 14 days |
| 5 | **Meeting Decision Rate** | Fraction of agenda items that reach a decision, correlated with attendance | > 70% | < 45% |

## Metric Maturity

| Metric | Status | Notes |
|--------|--------|-------|
| Clash Trajectory | **Stable** | Exponential decay model validated against sample data |
| Recurring Clashes | **Beta** | Works well with BCF/GUID data; spatial matching has known limitations in dense MEP zones |
| Approval Rates | **Stable** | Requires column mapping for your specific platform export |
| RFI Distribution | **Stable** | Most reliable metric; survival analysis handles open RFIs |
| Meeting Decisions | **Experimental** | Requires custom CSV data; <10% of teams produce this format today |
| ECV | **Beta** | Novel metric; S-curve shape is configurable but defaults may not suit all project types |
| Benchmarks | **Indicative** | Based on published research + author estimates; not empirical percentile distributions |

## Full Dashboard

```python
from coordination_metrics import CoordinationHealthDashboard

dashboard = CoordinationHealthDashboard(data_dir="./project_data/")
health = dashboard.run()

print(f"Overall: {health.overall_health:.0f}/100 ({health.health_level.value})")
dashboard.generate_html_report(health, output_path="report.html")
```

## Data Sources

| Source | Format | Metrics Supported |
|--------|--------|-------------------|
| **Navisworks** Clash Detective | XML export | Clash trajectory, recurring clashes |
| **Solibri** | BCF / CSV results | Clash-based metrics |
| **BIM 360 / ACC** | CSV export | Clashes, issues (as RFIs) |
| **Procore** | CSV export | Submittals, RFIs |
| **Aconex** | CSV export | Submittals, RFIs, correspondence |
| **Manual registers** | CSV / Excel | All metrics |

## AI Integration (MCP Server)

Connect to Claude Code as an MCP server for natural-language analysis:

```bash
claude mcp add --scope project coordination-metrics -- \
    python -m coordination_metrics.mcp_server
```

Then ask Claude:

> "Analyse the clash trajectory from the exports in `./data/` and tell me which
> disciplines are falling behind."

Available tools: `analyse_clash_trajectory`, `detect_recurring_clashes`, `analyse_submittal_rates`, `analyse_rfi_distribution`, `analyse_meeting_decisions`, `generate_coordination_health_report`, `compute_earned_coordination_value`, `compare_to_benchmarks`, `discover_cross_correlations_tool`.

## Earned Coordination Value (ECV)

A novel composite metric analogous to Earned Value Management (EVM), adapted for design coordination. It answers: "Are we resolving coordination issues fast enough to meet the project milestone?"

```python
from datetime import date
from coordination_metrics.ecv import ECVConfig, compute_ecv

config = ECVConfig(
    project_start=date(2026, 1, 1),
    coordination_deadline=date(2026, 7, 1),
    total_expected_clashes=200,
    total_expected_rfis=100,
    total_expected_submittals=80,
    total_expected_meetings=24,
)

ecv = compute_ecv(
    config=config,
    measurement_date=date(2026, 4, 1),
    clashes_resolved=120,
    rfis_answered=55,
    submittals_approved=45,
    decisions_made=60,
)
print(f"CPI: {ecv.cpi:.2f} — {ecv.status}")
# CPI > 1.0 = ahead, CPI = 1.0 = on track, CPI < 1.0 = behind
```

## Benchmark Comparisons

Compare your project's metrics against industry benchmarks derived from published research (Navigant, GIRI, CII, Chahrour et al.):

```python
from coordination_metrics.benchmarks import compare_to_benchmark

result = compare_to_benchmark("recurring_clash_rate", 12.5)
print(f"{result['insight']}")
# "Your Recurring clash rate (%) of 12.5 is at the 55th percentile."
```

Supported benchmarks: `clash_reduction_rate_per_round`, `recurring_clash_rate`, `first_submission_approval_rate`, `rfi_response_p90_days`, `rfi_no_response_rate`, `meeting_decision_rate`.

## Cross-Metric Correlations

The correlation engine discovers relationships between metrics that reveal systemic coordination failures:

```python
from coordination_metrics.cross_correlation import discover_cross_correlations

insights = discover_cross_correlations(
    clash_trajectory_data={"health": "stalled"},
    recurrence_data={"recurrence_rate_pct": 18.0},
    approval_data={},
    rfi_data={"no_response_pct": 25},
    meeting_data={"avg_decision_rate_pct": 40, "critical_absence": "Mechanical"},
)
for i in insights:
    print(f"[{'ACTION' if i.actionable else 'INFO'}] {i.insight}")
```

## Architecture

```
coordination_metrics/
  core.py                # Data models: ClashRoundSummary, CoordinationHealth, etc.
  clash_trajectory.py    # Metric 1: slope + exponential decay + zero-clash projection
  recurring_clashes.py   # Metric 2: 3D spatial recurrence detection
  approval_rates.py      # Metric 3: first-submission approval by discipline
  rfi_distribution.py    # Metric 4: response time P90 + bottleneck flagging
  meeting_decisions.py   # Metric 5: decision rate + attendance correlation
  ecv.py                 # Earned Coordination Value (CPI for coordination)
  benchmarks.py          # Industry benchmark database and comparison
  cross_correlation.py   # Cross-metric correlation engine
  dashboard.py           # Unified health score + benchmark + insight integration
  visualizations.py      # Dark-themed matplotlib charts
  exporters.py           # HTML report, JSON, chart images
  mcp_server.py          # FastMCP server for Claude Code integration
  cli.py                 # Command-line interface
  parsers/
    navisworks.py        # Navisworks Clash Detective XML parser
    solibri.py           # Solibri BCF/results parser
    bim360.py            # BIM 360 / ACC export parser
    csv_register.py      # Generic CSV/Excel with auto-detection
```

## Installation

```bash
# Core (pandas, numpy, matplotlib)
pip install coordination-metrics

# With MCP server support
pip install "coordination-metrics[mcp]"

# Everything (MCP + scipy + openpyxl)
pip install "coordination-metrics[all]"
```

## Command-Line Interface

```bash
# Full health report
coord-metrics report ./data/ --output report.html

# Individual metrics
coord-metrics clashes ./exports/
coord-metrics rfis ./rfi_register.csv
coord-metrics submittals ./submittal_register.csv
coord-metrics meetings ./meeting_minutes.csv
```

## Examples

See the [`examples/`](examples/) directory:

- **`quick_start.py`** — Parse clash exports and compute trajectory in 10 lines.
- **`full_dashboard.py`** — Run all 5 metrics and generate an HTML report.
- **`navisworks_workflow.py`** — Navisworks-specific workflow with charts.

## References

- GIRI (Get It Right Initiative). *Literature Review, Revision 3*. 2019.
- Construction Industry Institute. *Research Summary 153-1*. Rework costs 5-15% of project value.
- Navigant/CMAA. *Construction Industry Survey*. 2013. ~1M RFIs across 1,362 projects.
- Chahrour, R. et al. *Cost-benefit analysis of BIM-enabled design clash detection and resolution*. 2020. 20% cost savings.
- Cavka, H.B. et al. *Developing owner information requirements for BIM-enabled project delivery*. 2015.
- Leite, F. et al. *Analysis of modeling effort and impact of different levels of detail in building information models*. Automation in Construction, 2011.
- Eastman, C. et al. *BIM Handbook*. Wiley, 2018.

## Contributing

Contributions welcome. Please open an issue first for major changes.

## License

[MIT](LICENSE) — Houssame E. Hsain, 2026.
