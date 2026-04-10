#!/usr/bin/env python3
"""Generate publication-quality visualizations from case study results.

Produces charts suitable for both the arXiv paper and LinkedIn content,
using matplotlib with the coordination-metrics dark theme.

Usage:
    python generate_visuals.py --project wbdg_duplex
    python generate_visuals.py --project wbdg_duplex --format svg --dpi 300
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# Add parent package to path
PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from coordination_metrics.visualizations import (
    plot_clash_trajectory,
    plot_rfi_distribution,
    plot_approval_rates,
    plot_meeting_decisions,
    plot_recurring_clashes,
    _apply_dark_theme,
    _DARK_BG, _CARD_BG, _TEXT_COLOR, _GRID_COLOR,
    _ACCENT_GREEN, _ACCENT_AMBER, _ACCENT_RED, _ACCENT_BLUE, _ACCENT_PURPLE,
)
from coordination_metrics.core import ClashRoundSummary


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROJECTS = {
    "wbdg_duplex": PROJECT_ROOT / "wbdg_duplex",
    "wbdg_clinic": PROJECT_ROOT / "wbdg_clinic",
}


def plot_ecv_timeline(ecv_data: dict, figsize=(10, 5)) -> plt.Figure:
    """Plot Earned Coordination Value S-curve."""
    fig, ax = plt.subplots(figsize=figsize)
    _apply_dark_theme(ax, fig)

    pv = ecv_data.get("planned_value", 0)
    ev = ecv_data.get("earned_value", 0)
    cpi = ecv_data.get("cpi", 1.0)

    # Generate S-curve points
    import math
    t = np.linspace(0, 1, 100)
    pv_curve = 100 / (1 + np.exp(-10 * (t - 0.5)))

    # Scale EV curve based on CPI
    ev_curve = pv_curve * cpi
    ev_curve = np.clip(ev_curve, 0, 100)

    ax.plot(t * 100, pv_curve, "-", color=_ACCENT_BLUE, linewidth=2, label="Planned Value")
    ax.plot(t * 100, ev_curve, "-", color=_ACCENT_GREEN if cpi >= 0.95 else _ACCENT_RED,
            linewidth=2, label="Earned Value")
    ax.fill_between(t * 100, pv_curve, ev_curve, alpha=0.15,
                    color=_ACCENT_GREEN if cpi >= 0.95 else _ACCENT_RED)

    # Mark current position
    calendar_pct = 43  # ~mid project
    ax.axvline(calendar_pct, color=_TEXT_COLOR, linestyle=":", alpha=0.5)
    ax.scatter([calendar_pct], [pv], color=_ACCENT_BLUE, s=80, zorder=5)
    ax.scatter([calendar_pct], [ev], color=_ACCENT_GREEN if cpi >= 0.95 else _ACCENT_RED,
               s=80, zorder=5)

    ax.set_xlabel("Project Timeline (%)")
    ax.set_ylabel("Coordination Value (%)")
    ax.set_title(f"Earned Coordination Value (CPI = {cpi})")
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 105)
    ax.legend(fontsize=9, facecolor=_CARD_BG, edgecolor=_GRID_COLOR, labelcolor=_TEXT_COLOR)

    fig.tight_layout()
    return fig


def plot_discipline_risk_matrix(health_details: dict, figsize=(8, 6)) -> plt.Figure:
    """Plot discipline risk matrix: approval rate vs RFI response time."""
    fig, ax = plt.subplots(figsize=figsize)
    _apply_dark_theme(ax, fig)

    # Extract per-discipline data
    approval_data = health_details.get("approval_rates", [])
    rfi_data = health_details.get("rfi_distribution", {})
    rfi_by_disc_raw = rfi_data.get("by_discipline", []) if isinstance(rfi_data, dict) else []
    # Normalise: list-of-dicts → dict keyed by discipline name
    if isinstance(rfi_by_disc_raw, list):
        rfi_by_disc = {d["discipline"]: d for d in rfi_by_disc_raw if isinstance(d, dict) and "discipline" in d}
    else:
        rfi_by_disc = rfi_by_disc_raw if isinstance(rfi_by_disc_raw, dict) else {}

    if isinstance(approval_data, list):
        for d in approval_data:
            disc = d.get("discipline", "")
            approval_pct = d.get("first_submission_approval_pct", 50)
            n_submittals = d.get("first_submissions", d.get("total_submittals", 0))

            # Get RFI P90 for this discipline
            disc_rfi = rfi_by_disc.get(disc, {})
            rfi_p90 = disc_rfi.get("p90_days", 14) if isinstance(disc_rfi, dict) else 14

            # Color by risk
            if approval_pct >= 70 and rfi_p90 <= 14:
                color = _ACCENT_GREEN
            elif approval_pct < 50 or rfi_p90 > 21:
                color = _ACCENT_RED
            else:
                color = _ACCENT_AMBER

            # Sparse data: hollow markers for disciplines with few data points
            if n_submittals < 5:
                ax.scatter(rfi_p90, approval_pct, s=200, facecolors='none',
                           edgecolors=color, linewidths=2, alpha=0.6, zorder=5)
                ax.annotate(f"{disc}\n(n={n_submittals})", (rfi_p90, approval_pct),
                            textcoords="offset points", xytext=(8, 5),
                            color=_TEXT_COLOR, fontsize=8, fontstyle="italic")
            else:
                ax.scatter(rfi_p90, approval_pct, s=200, color=color, alpha=0.8, zorder=5)
                ax.annotate(disc, (rfi_p90, approval_pct), textcoords="offset points",
                            xytext=(8, 5), color=_TEXT_COLOR, fontsize=9)

    # Add quadrant lines
    ax.axhline(70, color=_GRID_COLOR, linestyle="--", alpha=0.5)
    ax.axvline(14, color=_GRID_COLOR, linestyle="--", alpha=0.5)

    ax.set_xlabel("RFI P90 Response Time (days)")
    ax.set_ylabel("First-Submission Approval Rate (%)")
    ax.set_title("Discipline Risk Matrix")

    fig.tight_layout()
    return fig


def plot_health_radar(metrics: dict, figsize=(7, 7)) -> plt.Figure:
    """Plot radar chart of all 5 health metrics."""
    fig, ax = plt.subplots(figsize=figsize, subplot_kw=dict(polar=True))
    fig.patch.set_facecolor(_DARK_BG)
    ax.set_facecolor(_CARD_BG)

    labels = list(metrics.keys())
    values = list(metrics.values())

    # Close the polygon
    angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False).tolist()
    values_closed = values + [values[0]]
    angles_closed = angles + [angles[0]]

    ax.plot(angles_closed, values_closed, "o-", color=_ACCENT_BLUE, linewidth=2, markersize=6)
    ax.fill(angles_closed, values_closed, color=_ACCENT_BLUE, alpha=0.15)

    # Reference circles
    for level in [25, 50, 75]:
        circle = [level] * (len(labels) + 1)
        ax.plot(angles_closed, circle, "--", color=_GRID_COLOR, alpha=0.3, linewidth=0.8)

    ax.set_xticks(angles)
    ax.set_xticklabels([l.replace("_", "\n") for l in labels], color=_TEXT_COLOR, fontsize=8)
    ax.set_ylim(0, 100)
    ax.set_yticks([25, 50, 75, 100])
    ax.set_yticklabels(["25", "50", "75", "100"], color=_TEXT_COLOR, fontsize=7)
    ax.tick_params(colors=_TEXT_COLOR)
    ax.spines["polar"].set_color(_GRID_COLOR)
    ax.set_title("Coordination Health Radar", color=_TEXT_COLOR, fontsize=14, pad=20)

    fig.tight_layout()
    return fig


def main():
    parser = argparse.ArgumentParser(description="Generate publication-quality visualizations")
    parser.add_argument("--project", required=True, choices=list(PROJECTS.keys()))
    parser.add_argument("--format", default="png", choices=["png", "svg", "pdf"])
    parser.add_argument("--dpi", type=int, default=200)
    args = parser.parse_args()

    project_dir = PROJECTS[args.project]
    output_dir = project_dir / "output" / "figures"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load analysis results
    analysis_path = project_dir / "output" / "full_analysis.json"
    if not analysis_path.exists():
        print(f"ERROR: Run run_analysis.py first to generate {analysis_path}")
        sys.exit(1)

    results = json.loads(analysis_path.read_text())
    fmt = args.format
    dpi = args.dpi

    print(f"Generating figures for {args.project}...")

    # 1. Health radar
    metrics = results["health_summary"]["metrics"]
    fig = plot_health_radar(metrics)
    path = output_dir / f"health_radar.{fmt}"
    fig.savefig(path, dpi=dpi, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"  {path}")

    # 2. ECV timeline
    if results.get("ecv"):
        fig = plot_ecv_timeline(results["ecv"])
        path = output_dir / f"ecv_timeline.{fmt}"
        fig.savefig(path, dpi=dpi, bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close(fig)
        print(f"  {path}")

    # 3. Discipline risk matrix
    if results["health_summary"].get("details"):
        fig = plot_discipline_risk_matrix(results["health_summary"]["details"])
        path = output_dir / f"discipline_risk_matrix.{fmt}"
        fig.savefig(path, dpi=dpi, bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close(fig)
        print(f"  {path}")

    # 4. Clash trajectory (from XML data directly)
    clash_dir = project_dir / "data" / "clashes"
    clash_xmls = sorted(clash_dir.glob("clash_round_*.xml")) if clash_dir.exists() else []
    if len(clash_xmls) >= 2:
        from coordination_metrics.clash_trajectory import build_trajectory
        summaries = build_trajectory(clash_xmls)
        fig = plot_clash_trajectory(summaries)
        path = output_dir / f"clash_trajectory.{fmt}"
        fig.savefig(path, dpi=dpi, bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close(fig)
        print(f"  {path}")

    print(f"\nDone. Figures in: {output_dir}")


if __name__ == "__main__":
    main()
