"""Core data models for coordination metrics.

All metric modules produce and consume these models, ensuring a consistent
interface across parsers, analysers, and visualisations.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


class HealthLevel(enum.Enum):
    """Traffic-light health classification for coordination metrics."""

    HEALTHY = "healthy"
    AT_RISK = "at_risk"
    CRITICAL = "critical"


@dataclass
class ClashRoundSummary:
    """Aggregated clash counts from a single detection round.

    Attributes:
        round_date: Date the clash detection was run.
        round_label: Human-readable label (e.g. "Round 3 — 2026-02-01").
        new: Number of newly detected clashes.
        active: Number of still-open clashes carried from prior rounds.
        reviewed: Number of clashes under review.
        resolved: Number of clashes marked resolved this round.
        total: Total clashes in the round (new + active + reviewed + resolved).
    """

    round_date: date
    round_label: str
    new: int
    active: int
    reviewed: int
    resolved: int
    total: int

    @classmethod
    def from_counts(
        cls,
        round_date: date,
        round_label: str,
        *,
        new: int = 0,
        active: int = 0,
        reviewed: int = 0,
        resolved: int = 0,
    ) -> ClashRoundSummary:
        """Create a summary, automatically computing the total."""
        return cls(
            round_date=round_date,
            round_label=round_label,
            new=new,
            active=active,
            reviewed=reviewed,
            resolved=resolved,
            total=new + active + reviewed + resolved,
        )


@dataclass
class ClashPoint:
    """A single clash with its 3-D location and metadata.

    Used for spatial recurrence detection across rounds.

    Attributes:
        clash_id: Unique identifier from the clash tool.
        x: X-coordinate in model units (millimetres).
        y: Y-coordinate in model units (millimetres).
        z: Z-coordinate in model units (millimetres).
        status: Current status string (new, active, reviewed, resolved, approved).
        test_name: Name of the clash test (e.g. "MEP-Structure").
        description: Optional free-text description.
    """

    clash_id: str
    x: float
    y: float
    z: float
    status: str
    test_name: str = ""
    description: str = ""
    guid: Optional[str] = None


@dataclass
class SubmittalRecord:
    """A single submittal line item.

    Attributes:
        submittal_id: Unique submittal identifier.
        discipline: Discipline responsible (e.g. "Structural", "Mechanical").
        revision: Revision number (0 = first submission).
        status: Review outcome (Approved, Revise & Resubmit, Rejected, etc.).
        date_submitted: Date the submittal was lodged.
    """

    submittal_id: str
    discipline: str
    revision: int
    status: str
    date_submitted: date


@dataclass
class RFIRecord:
    """A single RFI line item.

    Attributes:
        rfi_id: Unique RFI identifier.
        date_submitted: Date the RFI was raised.
        date_responded: Date the response was received (None if still open).
        discipline: Discipline the RFI was raised against.
        category: Classification (Design Clarification, Coordination, etc.).
        response_days: Computed business days to respond (None if still open).
    """

    rfi_id: str
    date_submitted: date
    date_responded: Optional[date]
    discipline: str
    category: str = ""
    response_days: Optional[float] = None


@dataclass
class MeetingSummary:
    """Aggregated record of a single coordination meeting.

    Attributes:
        meeting_date: Date of the meeting.
        total_items: Total agenda items discussed.
        decided_items: Items that reached a decision.
        deferred_items: Items deferred to a future meeting.
        disciplines_required: Set of disciplines that should have attended.
        disciplines_present: Set of disciplines that actually attended.
    """

    meeting_date: date
    total_items: int
    decided_items: int
    deferred_items: int
    disciplines_required: set[str] = field(default_factory=set)
    disciplines_present: set[str] = field(default_factory=set)

    @property
    def decision_rate(self) -> float:
        """Fraction of items that reached a decision (0.0-1.0)."""
        if self.total_items == 0:
            return 0.0
        return self.decided_items / self.total_items

    @property
    def attendance_rate(self) -> float:
        """Fraction of required disciplines that attended (0.0-1.0)."""
        if not self.disciplines_required:
            return 0.0
        return len(self.disciplines_present & self.disciplines_required) / len(
            self.disciplines_required
        )


@dataclass
class CoordinationHealth:
    """Unified health assessment across all metrics.

    Each metric score is 0-100 (higher = healthier). The overall_health
    property returns a weighted composite.

    Attributes:
        clash_trajectory_score: 100 if slope is negative, scaled down for positive slopes.
        recurring_clash_score: 100 minus the recurrence rate percentage.
        approval_rate_score: First-submission approval rate as a percentage.
        rfi_response_score: 100 minus the fraction of RFIs exceeding the P90 threshold.
        meeting_decision_score: Average decision rate as a percentage.
        details: Optional dict with supporting data for each metric.
    """

    clash_trajectory_score: float = 0.0
    recurring_clash_score: float = 0.0
    approval_rate_score: float = 0.0
    rfi_response_score: float = 0.0
    meeting_decision_score: float = 0.0
    details: dict = field(default_factory=dict)

    @property
    def overall_health(self) -> float:
        """Weighted composite score (0-100).

        Weights:
            Clash trajectory: 25%
            Recurring clashes: 20%
            Approval rate: 20%
            RFI response: 20%
            Meeting decisions: 15%
        """
        return (
            self.clash_trajectory_score * 0.25
            + self.recurring_clash_score * 0.20
            + self.approval_rate_score * 0.20
            + self.rfi_response_score * 0.20
            + self.meeting_decision_score * 0.15
        )

    @property
    def health_level(self) -> HealthLevel:
        """Traffic-light classification based on overall score."""
        score = self.overall_health
        if score >= 70:
            return HealthLevel.HEALTHY
        elif score >= 45:
            return HealthLevel.AT_RISK
        else:
            return HealthLevel.CRITICAL

    def summary(self) -> dict:
        """Return a JSON-serialisable summary."""
        return {
            "overall_health": round(self.overall_health, 1),
            "health_level": self.health_level.value,
            "metrics": {
                "clash_trajectory": round(self.clash_trajectory_score, 1),
                "recurring_clashes": round(self.recurring_clash_score, 1),
                "approval_rate": round(self.approval_rate_score, 1),
                "rfi_response": round(self.rfi_response_score, 1),
                "meeting_decisions": round(self.meeting_decision_score, 1),
            },
            "details": self.details,
        }
