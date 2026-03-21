# Coordination Metrics — Claude Code Instructions

> **Note**: Move this file to `.claude/CLAUDE.md` for Claude Code to auto-detect it.

This package provides 5 design coordination metrics for AEC projects. When the user asks about coordination quality, clash detection, RFI analysis, or submittal tracking, use the coordination-metrics MCP tools.

## Quick Setup
```bash
claude mcp add --scope project coordination-metrics -- python -m coordination_metrics.mcp_server
```

## Available Tools
- `analyse_clash_trajectory`: Parse Navisworks XML exports and compute the trajectory slope of hard clashes over successive detection rounds.
- `detect_recurring_clashes`: Spatial recurrence detection — finds clashes that reappear near previously-resolved locations.
- `analyse_submittal_rates`: Compute first-submission approval rates by discipline from a submittal register.
- `analyse_rfi_distribution`: Analyse RFI response time distribution and identify bottleneck disciplines by P90.
- `analyse_meeting_decisions`: Analyse coordination meeting decision rates and attendance-decision correlation.
- `generate_coordination_health_report`: Run all 5 metrics from a project data directory and produce a unified health score.

## Data Formats
The tools accept file paths to standard exports from:
- **Navisworks** Clash Detective XML exports (`.xml`)
- **BIM 360 / ACC** clash and issue CSV exports
- **Solibri** BCF or tabular results
- **Procore / Aconex / Generic** CSV or Excel registers

## Column Requirements
- **Submittal register**: `submittal_id`, `discipline`, `revision`, `status`, `date_submitted`
- **RFI register**: `rfi_id`, `date_submitted`, `date_responded`, `discipline`, `category`
- **Meeting minutes**: `meeting_date`, `item_number`, `item_description`, `status`, `disciplines_required`, `disciplines_present`

## Running Tests
```bash
pip install -e ".[all]"
pytest tests/ -v
```

## Architecture
```
coordination_metrics/
  core.py              # Data models (ClashRoundSummary, CoordinationHealth, etc.)
  clash_trajectory.py  # Metric 1: slope of hard clash totals over rounds
  recurring_clashes.py # Metric 2: spatial recurrence detection
  approval_rates.py    # Metric 3: first-submission approval by discipline
  rfi_distribution.py  # Metric 4: response time P90 by discipline
  meeting_decisions.py # Metric 5: decision rate + attendance correlation
  dashboard.py         # Unified health assessment combining all 5
  visualizations.py    # Dark-themed matplotlib charts
  exporters.py         # HTML, JSON, chart image export
  mcp_server.py        # FastMCP server for AI tool integration
  parsers/             # Navisworks XML, BIM 360 CSV, Solibri BCF, generic CSV
```
