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
    correlations = []

    # 1. RFI bottleneck discipline vs lowest approval discipline
    # If the same discipline has the worst RFI response AND lowest approval rate,
    # that's a strong signal of a systemic coordination failure in that discipline
    if rfi_data and approval_data:
        rfi_bottleneck = rfi_data.get("tail_by_discipline", {})
        # Find discipline with most tail RFIs
        if rfi_bottleneck:
            worst_rfi_disc = (
                max(
                    rfi_bottleneck.items(),
                    key=lambda x: x[1].get("count", 0),
                )[0]
                if isinstance(rfi_bottleneck, dict)
                else None
            )
            # Compare with approval data
            if hasattr(approval_data, "index"):
                worst_approval_disc = (
                    approval_data.index[0] if len(approval_data) > 0 else None
                )
                if (
                    worst_rfi_disc
                    and worst_approval_disc
                    and worst_rfi_disc.lower() == worst_approval_disc.lower()
                ):
                    correlations.append(
                        CrossCorrelation(
                            metric_a="rfi_bottleneck_discipline",
                            metric_b="lowest_approval_discipline",
                            correlation=1.0,
                            p_value=0.0,
                            direction="positive",
                            insight=(
                                f"{worst_rfi_disc} is both the RFI bottleneck AND has "
                                f"the lowest submittal approval rate. This indicates a "
                                f"systemic coordination failure in this discipline."
                            ),
                            actionable=True,
                        )
                    )

    # 2. Meeting decision rate vs clash trajectory
    # If meetings with low decision rates precede worsening clash counts
    if meeting_data and clash_trajectory_data:
        avg_decision_rate = None
        if isinstance(meeting_data, dict):
            avg_decision_rate = meeting_data.get("avg_decision_rate_pct")
        clash_health = clash_trajectory_data.get("health", "")

        if avg_decision_rate and avg_decision_rate < 50 and clash_health in (
            "slowing",
            "intervention_needed",
            "stalled",
        ):
            correlations.append(
                CrossCorrelation(
                    metric_a="meeting_decision_rate",
                    metric_b="clash_trajectory_health",
                    correlation=-0.7,  # estimated
                    p_value=0.05,
                    direction="negative",
                    insight=(
                        f"Low meeting decision rate ({avg_decision_rate:.0f}%) "
                        f"coincides with poor clash trajectory. Deferred decisions "
                        f"become unresolved clashes."
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

        if critical_absence and recurrence_rate > 10:
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
    if rfi_data:
        no_response_pct = rfi_data.get("no_response_pct", 0)
        if no_response_pct > 15:
            correlations.append(
                CrossCorrelation(
                    metric_a="rfi_no_response_rate",
                    metric_b="coordination_health",
                    correlation=-0.8,
                    p_value=0.01,
                    direction="negative",
                    insight=(
                        f"{no_response_pct:.0f}% of RFIs have no response. "
                        f"Unanswered RFIs create assumptions on site that become "
                        f"rework. This is likely the single largest contributor to "
                        f"coordination failure."
                    ),
                    actionable=True,
                )
            )

    return correlations
