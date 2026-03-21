"""Shared fixtures for coordination-metrics tests."""

from __future__ import annotations

import csv
import io
import textwrap
from datetime import date
from pathlib import Path

import pytest

from coordination_metrics.core import ClashPoint, ClashRoundSummary, MeetingSummary

SAMPLE_DATA = Path(__file__).parent.parent / "examples" / "sample_data"


@pytest.fixture
def sample_data_dir() -> Path:
    """Path to the sample data directory."""
    return SAMPLE_DATA


@pytest.fixture
def clash_round1_xml(sample_data_dir: Path) -> Path:
    return sample_data_dir / "clash_round1.xml"


@pytest.fixture
def clash_round2_xml(sample_data_dir: Path) -> Path:
    return sample_data_dir / "clash_round2.xml"


@pytest.fixture
def clash_round3_xml(sample_data_dir: Path) -> Path:
    return sample_data_dir / "clash_round3.xml"


@pytest.fixture
def all_clash_xmls(sample_data_dir: Path) -> list[Path]:
    return sorted(sample_data_dir.glob("clash_round*.xml"))


@pytest.fixture
def submittal_register(sample_data_dir: Path) -> Path:
    return sample_data_dir / "submittal_register.csv"


@pytest.fixture
def rfi_register(sample_data_dir: Path) -> Path:
    return sample_data_dir / "rfi_register.csv"


@pytest.fixture
def meeting_register(sample_data_dir: Path) -> Path:
    return sample_data_dir / "meeting_minutes.csv"


@pytest.fixture
def three_round_summaries() -> list[ClashRoundSummary]:
    """Three rounds showing a clearly decreasing trajectory."""
    return [
        ClashRoundSummary.from_counts(
            round_date=date(2026, 1, 15),
            round_label="Round 1",
            new=20, active=10, reviewed=5, resolved=0,
        ),
        ClashRoundSummary.from_counts(
            round_date=date(2026, 1, 29),
            round_label="Round 2",
            new=8, active=5, reviewed=2, resolved=9,
        ),
        ClashRoundSummary.from_counts(
            round_date=date(2026, 2, 12),
            round_label="Round 3",
            new=2, active=2, reviewed=1, resolved=8,
        ),
    ]


@pytest.fixture
def increasing_summaries() -> list[ClashRoundSummary]:
    """Three rounds showing an increasing trajectory."""
    return [
        ClashRoundSummary.from_counts(
            round_date=date(2026, 1, 15),
            round_label="Round 1",
            new=5, active=2, reviewed=1, resolved=0,
        ),
        ClashRoundSummary.from_counts(
            round_date=date(2026, 1, 29),
            round_label="Round 2",
            new=15, active=6, reviewed=3, resolved=2,
        ),
        ClashRoundSummary.from_counts(
            round_date=date(2026, 2, 12),
            round_label="Round 3",
            new=25, active=12, reviewed=5, resolved=3,
        ),
    ]


@pytest.fixture
def sample_clash_points_resolved() -> list[ClashPoint]:
    """Resolved clash points from a prior round."""
    return [
        ClashPoint("C1", 1000, 2000, 3000, "resolved", "Test-A"),
        ClashPoint("C2", 5000, 6000, 7000, "resolved", "Test-A"),
        ClashPoint("C3", 9000, 1000, 4000, "resolved", "Test-B"),
    ]


@pytest.fixture
def sample_clash_points_current() -> list[ClashPoint]:
    """Current round clash points — C4 is near C1 (recurrence), C5 is far away."""
    return [
        ClashPoint("C4", 1050, 2050, 3050, "new", "Test-A"),   # ~87mm from C1
        ClashPoint("C5", 20000, 20000, 20000, "new", "Test-B"), # far from everything
        ClashPoint("C6", 5100, 6100, 7100, "active", "Test-A"), # ~173mm from C2
    ]


@pytest.fixture
def sample_meetings() -> list[MeetingSummary]:
    """Sample meeting summaries for testing."""
    return [
        MeetingSummary(
            meeting_date=date(2026, 1, 15),
            total_items=6,
            decided_items=4,
            deferred_items=2,
            disciplines_required={"Architecture", "Structural", "Mechanical", "Electrical", "Hydraulic"},
            disciplines_present={"Architecture", "Structural", "Mechanical", "Electrical", "Hydraulic"},
        ),
        MeetingSummary(
            meeting_date=date(2026, 1, 22),
            total_items=7,
            decided_items=5,
            deferred_items=2,
            disciplines_required={"Architecture", "Structural", "Mechanical", "Electrical", "Hydraulic"},
            disciplines_present={"Architecture", "Structural", "Mechanical", "Electrical"},
        ),
        MeetingSummary(
            meeting_date=date(2026, 1, 29),
            total_items=5,
            decided_items=4,
            deferred_items=1,
            disciplines_required={"Structural", "Mechanical", "Electrical", "Hydraulic"},
            disciplines_present={"Structural", "Mechanical", "Electrical", "Hydraulic"},
        ),
    ]


@pytest.fixture
def empty_csv(tmp_path: Path) -> Path:
    """An empty CSV file with headers only."""
    p = tmp_path / "empty.csv"
    p.write_text("submittal_id,discipline,revision,status,date_submitted\n")
    return p
