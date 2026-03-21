"""Visualisations for coordination metrics.

All plots use a consistent dark theme suitable for dashboards and
presentations. Each function returns a matplotlib Figure that can
be saved, displayed, or embedded in reports.

Usage:
    >>> from coordination_metrics.visualizations import plot_clash_trajectory
    >>> fig = plot_clash_trajectory(summaries)
    >>> fig.savefig("clash_trajectory.png", dpi=150, bbox_inches="tight")
"""

from __future__ import annotations

from typing import Sequence

import matplotlib.pyplot as plt
import numpy as np

from coordination_metrics.core import ClashRoundSummary


# Consistent dark theme
_DARK_BG = "#0f172a"
_CARD_BG = "#1e293b"
_TEXT_COLOR = "#e2e8f0"
_GRID_COLOR = "#334155"
_ACCENT_GREEN = "#22c55e"
_ACCENT_AMBER = "#f59e0b"
_ACCENT_RED = "#ef4444"
_ACCENT_BLUE = "#3b82f6"
_ACCENT_PURPLE = "#a855f7"


def _apply_dark_theme(ax: plt.Axes, fig: plt.Figure) -> None:
    """Apply the dark theme to a figure and axes."""
    fig.patch.set_facecolor(_DARK_BG)
    ax.set_facecolor(_CARD_BG)
    ax.tick_params(colors=_TEXT_COLOR, which="both")
    ax.xaxis.label.set_color(_TEXT_COLOR)
    ax.yaxis.label.set_color(_TEXT_COLOR)
    ax.title.set_color(_TEXT_COLOR)
    for spine in ax.spines.values():
        spine.set_color(_GRID_COLOR)
    ax.grid(True, color=_GRID_COLOR, alpha=0.3, linestyle="--")


def plot_clash_trajectory(
    summaries: Sequence[ClashRoundSummary],
    *,
    show_trend: bool = True,
    figsize: tuple[float, float] = (10, 5),
) -> plt.Figure:
    """Plot clash count trajectory with optional trend line.

    Args:
        summaries: Chronologically ordered clash round summaries.
        show_trend: Whether to overlay a linear trend line.
        figsize: Figure dimensions in inches.

    Returns:
        Matplotlib Figure.
    """
    fig, ax = plt.subplots(figsize=figsize)
    _apply_dark_theme(ax, fig)

    labels = [s.round_label for s in summaries]
    x = range(len(summaries))
    totals = [s.total for s in summaries]
    new_counts = [s.new for s in summaries]
    resolved = [s.resolved for s in summaries]

    ax.bar(x, totals, color=_ACCENT_BLUE, alpha=0.3, label="Total", width=0.6)
    ax.plot(x, new_counts, "o-", color=_ACCENT_RED, linewidth=2, label="New", markersize=6)
    ax.plot(x, resolved, "s-", color=_ACCENT_GREEN, linewidth=2, label="Resolved", markersize=6)

    if show_trend and len(summaries) >= 2:
        z = np.polyfit(list(x), totals, 1)
        trend_y = np.polyval(z, list(x))
        trend_color = _ACCENT_RED if z[0] > 0 else _ACCENT_GREEN
        ax.plot(x, trend_y, "--", color=trend_color, linewidth=1.5, alpha=0.7,
                label=f"Trend ({z[0]:+.1f}/round)")

    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
    ax.set_ylabel("Clash Count")
    ax.set_title("Hard Clash Trajectory")
    ax.legend(loc="upper left", fontsize=8, facecolor=_CARD_BG, edgecolor=_GRID_COLOR,
              labelcolor=_TEXT_COLOR)

    fig.tight_layout()
    return fig


def plot_rfi_distribution(
    response_days: Sequence[float],
    p90: float,
    *,
    figsize: tuple[float, float] = (10, 5),
) -> plt.Figure:
    """Plot RFI response time distribution with P90 line.

    Args:
        response_days: List of response times in days.
        p90: 90th percentile value to highlight.
        figsize: Figure dimensions in inches.

    Returns:
        Matplotlib Figure.
    """
    fig, ax = plt.subplots(figsize=figsize)
    _apply_dark_theme(ax, fig)

    ax.hist(response_days, bins=20, color=_ACCENT_BLUE, alpha=0.7, edgecolor=_CARD_BG)
    ax.axvline(p90, color=_ACCENT_RED, linestyle="--", linewidth=2, label=f"P90 = {p90:.0f} days")
    median = float(np.median(response_days))
    ax.axvline(median, color=_ACCENT_GREEN, linestyle="--", linewidth=2,
               label=f"Median = {median:.0f} days")

    ax.set_xlabel("Response Time (days)")
    ax.set_ylabel("Number of RFIs")
    ax.set_title("RFI Response Time Distribution")
    ax.legend(fontsize=9, facecolor=_CARD_BG, edgecolor=_GRID_COLOR, labelcolor=_TEXT_COLOR)

    fig.tight_layout()
    return fig


def plot_approval_rates(
    rates_data: list[dict],
    *,
    figsize: tuple[float, float] = (10, 5),
) -> plt.Figure:
    """Plot first-submission approval rates by discipline.

    Args:
        rates_data: List of dicts with 'discipline' and 'first_submission_approval_pct'.
        figsize: Figure dimensions in inches.

    Returns:
        Matplotlib Figure.
    """
    fig, ax = plt.subplots(figsize=figsize)
    _apply_dark_theme(ax, fig)

    disciplines = [d["discipline"] for d in rates_data]
    pcts = [d["first_submission_approval_pct"] for d in rates_data]

    colors = []
    for p in pcts:
        if p >= 75:
            colors.append(_ACCENT_GREEN)
        elif p >= 50:
            colors.append(_ACCENT_AMBER)
        else:
            colors.append(_ACCENT_RED)

    bars = ax.barh(disciplines, pcts, color=colors, height=0.6, alpha=0.85)

    # Add percentage labels
    for bar, pct in zip(bars, pcts):
        ax.text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2,
                f"{pct:.0f}%", va="center", color=_TEXT_COLOR, fontsize=9)

    ax.axvline(75, color=_ACCENT_GREEN, linestyle=":", alpha=0.5, label="Target (75%)")
    ax.set_xlabel("First-Submission Approval Rate (%)")
    ax.set_title("Submittal Approval Rates by Discipline")
    ax.set_xlim(0, 105)
    ax.legend(fontsize=9, facecolor=_CARD_BG, edgecolor=_GRID_COLOR, labelcolor=_TEXT_COLOR)

    fig.tight_layout()
    return fig


def plot_meeting_decisions(
    per_meeting: list[dict],
    *,
    figsize: tuple[float, float] = (10, 5),
) -> plt.Figure:
    """Plot meeting decision rates over time with attendance overlay.

    Args:
        per_meeting: List of per-meeting dicts from compute_attendance_decision_correlation().
        figsize: Figure dimensions in inches.

    Returns:
        Matplotlib Figure.
    """
    fig, ax1 = plt.subplots(figsize=figsize)
    _apply_dark_theme(ax1, fig)

    dates = [m["meeting_date"] for m in per_meeting]
    decision_rates = [m["decision_rate_pct"] for m in per_meeting]
    attendance_rates = [m["attendance_rate_pct"] for m in per_meeting]

    x = range(len(dates))

    ax1.bar(x, decision_rates, color=_ACCENT_BLUE, alpha=0.7, label="Decision Rate %", width=0.5)
    ax1.set_ylabel("Decision Rate (%)", color=_TEXT_COLOR)
    ax1.set_ylim(0, 105)

    ax2 = ax1.twinx()
    ax2.plot(x, attendance_rates, "D-", color=_ACCENT_PURPLE, linewidth=2, markersize=6,
             label="Attendance Rate %")
    ax2.set_ylabel("Attendance Rate (%)", color=_ACCENT_PURPLE)
    ax2.set_ylim(0, 105)
    ax2.tick_params(axis="y", colors=_ACCENT_PURPLE)
    ax2.spines["right"].set_color(_ACCENT_PURPLE)

    ax1.set_xticks(list(x))
    ax1.set_xticklabels(dates, rotation=30, ha="right", fontsize=8)
    ax1.set_title("Meeting Decision Rate vs Attendance")

    # Combine legends
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="lower left", fontsize=8,
               facecolor=_CARD_BG, edgecolor=_GRID_COLOR, labelcolor=_TEXT_COLOR)

    fig.tight_layout()
    return fig


def plot_recurring_clashes(
    resolved_count: int,
    recurring_count: int,
    *,
    figsize: tuple[float, float] = (6, 6),
) -> plt.Figure:
    """Plot a donut chart showing recurring vs non-recurring resolved clashes.

    Args:
        resolved_count: Total resolved clashes checked.
        recurring_count: Number that recurred.
        figsize: Figure dimensions in inches.

    Returns:
        Matplotlib Figure.
    """
    fig, ax = plt.subplots(figsize=figsize)
    fig.patch.set_facecolor(_DARK_BG)

    non_recurring = resolved_count - recurring_count
    sizes = [recurring_count, non_recurring]
    colors = [_ACCENT_RED, _ACCENT_GREEN]
    labels = [f"Recurring ({recurring_count})", f"Held ({non_recurring})"]

    wedges, texts, autotexts = ax.pie(
        sizes, labels=labels, colors=colors, autopct="%1.0f%%",
        startangle=90, pctdistance=0.75,
        wedgeprops={"width": 0.4, "edgecolor": _DARK_BG, "linewidth": 2},
    )
    for t in texts + autotexts:
        t.set_color(_TEXT_COLOR)
        t.set_fontsize(10)

    ax.set_title("Recurring Clash Rate", color=_TEXT_COLOR, fontsize=14, pad=20)

    fig.tight_layout()
    return fig
