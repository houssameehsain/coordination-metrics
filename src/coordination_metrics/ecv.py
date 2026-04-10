"""Earned Coordination Value (ECV).

A novel composite metric that answers: "Are we resolving coordination issues
fast enough to meet the project milestone?"

Analogous to EVM:
- Planned Value (PV): Expected coordination resolution by this date
- Earned Value (EV): Actual coordination resolution achieved
- Coordination Performance Index (CPI): EV / PV
- Estimate at Completion (EAC): Projected total resolution effort

The coordination "work" being measured:
- Clashes resolved (weighted by severity)
- RFIs answered
- Submittals approved
- Decisions made in meetings

Each is weighted and normalized to produce a single CPI number.
CPI > 1.0 = ahead of schedule
CPI = 1.0 = on track
CPI < 1.0 = behind schedule
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta


@dataclass
class ECVSnapshot:
    """A point-in-time ECV measurement."""

    date: date
    planned_value: float  # Expected cumulative resolution (0-100%)
    earned_value: float  # Actual cumulative resolution (0-100%)
    cpi: float  # Coordination Performance Index (EV/PV)
    spi: float  # Schedule Performance Index
    eac_date: date | None = None  # Estimated completion date

    @property
    def variance(self) -> float:
        return self.earned_value - self.planned_value

    @property
    def status(self) -> str:
        if self.cpi >= 1.05:
            return "ahead"
        elif self.cpi >= 0.95:
            return "on_track"
        elif self.cpi >= 0.8:
            return "at_risk"
        else:
            return "behind"


@dataclass
class ECVConfig:
    """Configuration for ECV calculation."""

    project_start: date
    coordination_deadline: date  # When coordination should be complete
    total_expected_clashes: int = 0  # Baseline clash count from first round
    total_expected_rfis: int = 0  # Estimated total RFIs
    total_expected_submittals: int = 0
    total_expected_meetings: int = 0

    # Weights for each coordination component
    clash_weight: float = 0.35
    rfi_weight: float = 0.25
    submittal_weight: float = 0.25
    meeting_weight: float = 0.15


def compute_ecv(
    config: ECVConfig,
    measurement_date: date,
    clashes_resolved: int,
    rfis_answered: int,
    submittals_approved: int,
    decisions_made: int,
) -> ECVSnapshot:
    """Compute Earned Coordination Value at a point in time.

    Args:
        config: Project ECV configuration
        measurement_date: Date of measurement
        clashes_resolved: Cumulative clashes resolved to date
        rfis_answered: Cumulative RFIs answered to date
        submittals_approved: Cumulative submittals approved (first pass)
        decisions_made: Cumulative meeting decisions made
    """
    # Calendar progress (0-1)
    total_days = (config.coordination_deadline - config.project_start).days
    elapsed_days = (measurement_date - config.project_start).days
    calendar_progress = (
        min(1.0, max(0.0, elapsed_days / total_days)) if total_days > 0 else 0
    )

    # Planned value: assume S-curve (slow start, ramp up, tail off)
    # Using a simple logistic curve: PV = 100 / (1 + exp(-10*(t-0.5)))
    pv = 100 / (1 + math.exp(-10 * (calendar_progress - 0.5)))

    # Earned value: weighted sum of actual resolution percentages
    components = []

    if config.total_expected_clashes > 0:
        clash_pct = min(100, clashes_resolved / config.total_expected_clashes * 100)
        components.append(clash_pct * config.clash_weight)

    if config.total_expected_rfis > 0:
        rfi_pct = min(100, rfis_answered / config.total_expected_rfis * 100)
        components.append(rfi_pct * config.rfi_weight)

    if config.total_expected_submittals > 0:
        sub_pct = min(
            100, submittals_approved / config.total_expected_submittals * 100
        )
        components.append(sub_pct * config.submittal_weight)

    if config.total_expected_meetings > 0:
        # Use actual total expected decisions if available (total_items sum),
        # otherwise estimate ~5 decisions per meeting as fallback
        expected_decisions = getattr(config, "total_expected_decisions", 0)
        if expected_decisions <= 0:
            expected_decisions = config.total_expected_meetings * 5
        meet_pct = min(100, decisions_made / expected_decisions * 100)
        components.append(meet_pct * config.meeting_weight)

    # Normalize EV to 0-100 scale
    total_weight = sum(
        [
            config.clash_weight if config.total_expected_clashes > 0 else 0,
            config.rfi_weight if config.total_expected_rfis > 0 else 0,
            config.submittal_weight if config.total_expected_submittals > 0 else 0,
            config.meeting_weight if config.total_expected_meetings > 0 else 0,
        ]
    )

    ev = sum(components) / total_weight if total_weight > 0 else 0
    ev = min(100, ev)

    # Performance indices
    cpi = ev / pv if pv > 0 else 1.0
    # SPI = (EV/100) / calendar_progress
    # Measures: fraction of coordination work completed vs fraction of time elapsed
    # SPI > 1 = ahead of schedule, SPI < 1 = behind schedule
    spi = (ev / 100) / calendar_progress if calendar_progress > 0 else 1.0

    # Estimate at Completion date
    eac_date = None
    if cpi > 0 and ev < 100:
        remaining_pv = 100 - ev
        remaining_days = (
            remaining_pv / (ev / max(1, elapsed_days)) if ev > 0 else total_days
        )
        eac_date = measurement_date + timedelta(days=int(remaining_days))

    return ECVSnapshot(
        date=measurement_date,
        planned_value=round(pv, 1),
        earned_value=round(ev, 1),
        cpi=round(cpi, 2),
        spi=round(spi, 2),
        eac_date=eac_date,
    )


def compute_ecv_trend(
    config: ECVConfig,
    snapshots: list[dict],
) -> list[ECVSnapshot]:
    """Compute ECV trend from a series of measurement snapshots.

    Args:
        config: Project ECV configuration
        snapshots: List of dicts with keys:
            date, clashes_resolved, rfis_answered, submittals_approved, decisions_made
    """
    results = []
    for snap in snapshots:
        ecv = compute_ecv(
            config=config,
            measurement_date=snap["date"],
            clashes_resolved=snap.get("clashes_resolved", 0),
            rfis_answered=snap.get("rfis_answered", 0),
            submittals_approved=snap.get("submittals_approved", 0),
            decisions_made=snap.get("decisions_made", 0),
        )
        results.append(ecv)
    return results
