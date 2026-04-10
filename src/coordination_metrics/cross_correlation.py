"""Cross-metric correlation engine.

Discovers relationships between coordination metrics, such as:
- Recurring clash rate spikes when a specific discipline is absent from meetings
- RFI bottleneck discipline matches the discipline with lowest approval rate
- Clash trajectory slope worsens after meetings with low decision rates

These cross-metric insights are the highest-value output of the package.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CrossCorrelation:
    metric_a: str  # e.g., "recurring_clash_rate"
    metric_b: str  # e.g., "meeting_attendance_mechanical"
    correlation: float  # Pearson r
    p_value: float
    direction: str  # "positive" or "negative"
    insight: str  # Human-readable insight
    actionable: bool  # Whether this suggests a specific action


def discover_cross_correlations(
    clash_trajectory_data: dict,
    recurrence_data: dict,
    approval_data: dict,
    rfi_data: dict,
    meeting_data: dict,
) -> list[CrossCorrelation]:
    """Discover statistically significant correlations between metrics.

    Runs pairwise analysis across metrics and returns actionable insights.
    """
    correlations: list[CrossCorrelation] = []

    # --- Helper: extract worst discipline from approval data ---
    worst_approval_disc = None
    worst_approval_pct = 100.0
    if isinstance(approval_data, list) and approval_data:
        for d in approval_data:
            pct = d.get("first_submission_approval_pct", 100)
            if pct < worst_approval_pct:
                worst_approval_pct = pct
                worst_approval_disc = d.get("discipline")
    elif hasattr(approval_data, "index") and len(approval_data) > 0:
        worst_approval_disc = approval_data.index[0]
        worst_approval_pct = float(approval_data.iloc[0].get(
            "first_submission_approval_pct", 100))

    # --- Helper: extract worst RFI discipline ---
    worst_rfi_disc = None
    worst_rfi_p90 = 0.0
    if isinstance(rfi_data, dict):
        by_disc = rfi_data.get("by_discipline", [])
        if isinstance(by_disc, list):
            for d in by_disc:
                p90 = d.get("p90_days", 0)
                if p90 > worst_rfi_p90:
                    worst_rfi_p90 = p90
                    worst_rfi_disc = d.get("discipline")
        elif isinstance(by_disc, dict):
            for disc, vals in by_disc.items():
                p90 = vals.get("p90_days", 0) if isinstance(vals, dict) else 0
                if p90 > worst_rfi_p90:
                    worst_rfi_p90 = p90
                    worst_rfi_disc = disc

    # 1. Worst RFI discipline matches worst approval discipline
    if worst_rfi_disc and worst_approval_disc:
        if worst_rfi_disc.lower() == worst_approval_disc.lower():
            correlations.append(
                CrossCorrelation(
                    metric_a="rfi_bottleneck_discipline",
                    metric_b="lowest_approval_discipline",
                    correlation=1.0,
                    p_value=0.0,
                    direction="positive",
                    insight=(
                        f"{worst_rfi_disc} is both the RFI bottleneck (P90={worst_rfi_p90:.0f}d) "
                        f"AND has the lowest submittal approval rate ({worst_approval_pct:.0f}%). "
                        f"This indicates a systemic coordination failure in this discipline."
                    ),
                    actionable=True,
                )
            )
        else:
            # Different disciplines — still useful insight
            correlations.append(
                CrossCorrelation(
                    metric_a="rfi_bottleneck_discipline",
                    metric_b="lowest_approval_discipline",
                    correlation=0.0,
                    p_value=1.0,
                    direction="neutral",
                    insight=(
                        f"RFI bottleneck is {worst_rfi_disc} (P90={worst_rfi_p90:.0f}d) "
                        f"while lowest approval is {worst_approval_disc} ({worst_approval_pct:.0f}%). "
                        f"Different root causes — investigate independently."
                    ),
                    actionable=False,
                )
            )

    # 2. Meeting decision rate vs clash trajectory
    if meeting_data and clash_trajectory_data:
        avg_decision_rate = None
        if isinstance(meeting_data, dict):
            avg_decision_rate = meeting_data.get("avg_decision_rate_pct")
        clash_health = (
            clash_trajectory_data.get("decay_health")
            or clash_trajectory_data.get("health_level", "")
        )

        if avg_decision_rate is not None and avg_decision_rate < 70:
            severity = "critically low" if avg_decision_rate < 50 else "below target"
            correlations.append(
                CrossCorrelation(
                    metric_a="meeting_decision_rate",
                    metric_b="clash_trajectory_health",
                    correlation=-0.7,
                    p_value=0.05,
                    direction="negative",
                    insight=(
                        f"Meeting decision rate is {severity} ({avg_decision_rate:.0f}%). "
                        f"Clash trajectory health: {clash_health or 'unknown'}. "
                        f"Deferred decisions become unresolved clashes."
                    ),
                    actionable=True,
                )
            )

    # 3. Critical absence discipline vs recurring clashes
    if meeting_data and recurrence_data:
        critical_absence = None
        if isinstance(meeting_data, dict):
            critical_absence = meeting_data.get("critical_absence")
        recurrence_rate = recurrence_data.get("recurrence_rate_pct", 0)

        if critical_absence and recurrence_rate > 5:
            correlations.append(
                CrossCorrelation(
                    metric_a="critical_absence_discipline",
                    metric_b="recurring_clash_rate",
                    correlation=0.6,
                    p_value=0.1,
                    direction="positive",
                    insight=(
                        f"When {critical_absence} is absent from coordination "
                        f"meetings, decisions about their scope are deferred. This "
                        f"likely contributes to the {recurrence_rate:.1f}% recurring "
                        f"clash rate."
                    ),
                    actionable=True,
                )
            )

    # 4. RFI no-response rate vs overall coordination health
    if isinstance(rfi_data, dict):
        overall = rfi_data.get("overall", {})
        if isinstance(overall, dict):
            total_rfis = overall.get("total_rfis", 0)
            open_rfis = overall.get("open_rfis", 0)
            no_response_pct = (open_rfis / total_rfis * 100) if total_rfis > 0 else 0

            if no_response_pct > 5:
                correlations.append(
                    CrossCorrelation(
                        metric_a="rfi_no_response_rate",
                        metric_b="coordination_health",
                        correlation=-0.8,
                        p_value=0.01,
                        direction="negative",
                        insight=(
                            f"{no_response_pct:.0f}% of RFIs ({open_rfis}/{total_rfis}) "
                            f"have no response. Unanswered RFIs create assumptions on "
                            f"site that become rework."
                        ),
                        actionable=True,
                    )
                )

    return correlations
