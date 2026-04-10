"""Export coordination health results to various formats.

Supports:
    - HTML report (standalone, no dependencies)
    - JSON (machine-readable)
    - PDF (requires matplotlib for chart rendering)
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Optional, Union

from coordination_metrics.core import CoordinationHealth


def export_to_json(
    health: CoordinationHealth,
    output_path: Optional[Union[str, Path]] = None,
    *,
    indent: int = 2,
) -> str:
    """Export coordination health to JSON.

    Args:
        health: CoordinationHealth from dashboard.run().
        output_path: Optional path to write the JSON file.
        indent: JSON indentation level.

    Returns:
        JSON string.
    """
    data = health.summary()
    data["generated_date"] = date.today().isoformat()
    data["version"] = "0.2.0"

    # Make sure all values are JSON-serialisable
    json_str = json.dumps(data, indent=indent, default=str)

    if output_path:
        Path(output_path).write_text(json_str, encoding="utf-8")

    return json_str


def export_to_html(
    health: CoordinationHealth,
    output_path: Optional[Union[str, Path]] = None,
) -> str:
    """Export coordination health to a standalone HTML report.

    This is a convenience wrapper around
    ``CoordinationHealthDashboard.generate_html_report()``.

    Args:
        health: CoordinationHealth from dashboard.run().
        output_path: Optional path to write the HTML file.

    Returns:
        HTML string.
    """
    from coordination_metrics.dashboard import CoordinationHealthDashboard

    dashboard = CoordinationHealthDashboard()
    return dashboard.generate_html_report(health, output_path=output_path)


def export_charts(
    health: CoordinationHealth,
    output_dir: Union[str, Path],
    *,
    dpi: int = 150,
    fmt: str = "png",
) -> list[Path]:
    """Export all available metric charts as image files.

    Args:
        health: CoordinationHealth from dashboard.run().
        output_dir: Directory to write chart images.
        dpi: Resolution for rasterised formats.
        fmt: Image format (png, svg, pdf).

    Returns:
        List of paths to generated chart files.
    """
    from coordination_metrics.visualizations import (
        plot_approval_rates,
        plot_clash_trajectory,
        plot_meeting_decisions,
        plot_recurring_clashes,
        plot_rfi_distribution,
    )
    from coordination_metrics.core import ClashRoundSummary

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []
    details = health.details

    # Clash trajectory chart
    if "clash_trajectory" in details and "error" not in details["clash_trajectory"]:
        traj = details["clash_trajectory"]
        if "rounds" in traj and traj["rounds"] >= 2:
            # We need the summaries which aren't stored — skip if not available
            pass

    # Recurring clashes donut
    if "recurring_clashes" in details and "error" not in details["recurring_clashes"]:
        rc = details["recurring_clashes"]
        if rc.get("resolved_count", 0) > 0:
            fig = plot_recurring_clashes(rc["resolved_count"], rc["recurring_count"])
            path = output_dir / f"recurring_clashes.{fmt}"
            fig.savefig(path, dpi=dpi, bbox_inches="tight", facecolor=fig.get_facecolor())
            plt_close(fig)
            generated.append(path)

    # Approval rates
    if "approval_rates" in details and isinstance(details["approval_rates"], list):
        fig = plot_approval_rates(details["approval_rates"])
        path = output_dir / f"approval_rates.{fmt}"
        fig.savefig(path, dpi=dpi, bbox_inches="tight", facecolor=fig.get_facecolor())
        plt_close(fig)
        generated.append(path)

    # RFI distribution
    if "rfi_distribution" in details and "error" not in details.get("rfi_distribution", {}):
        rfi = details["rfi_distribution"]
        overall = rfi.get("overall", {})
        if overall.get("p90_days") is not None:
            # We'd need raw response days — approximate from per-discipline data
            pass

    # Meeting decisions
    if "meeting_decisions" in details and "error" not in details.get("meeting_decisions", {}):
        mtg = details["meeting_decisions"]
        if mtg.get("per_meeting"):
            fig = plot_meeting_decisions(mtg["per_meeting"])
            path = output_dir / f"meeting_decisions.{fmt}"
            fig.savefig(path, dpi=dpi, bbox_inches="tight", facecolor=fig.get_facecolor())
            plt_close(fig)
            generated.append(path)

    return generated


def plt_close(fig) -> None:
    """Close a matplotlib figure to free memory."""
    import matplotlib.pyplot as plt
    plt.close(fig)
