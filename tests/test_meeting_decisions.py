"""Tests for Metric 5: Meeting Decision Resolution Rate."""

from datetime import date
from pathlib import Path

import pytest

from coordination_metrics.core import MeetingSummary
from coordination_metrics.meeting_decisions import (
    compute_attendance_decision_correlation,
    meeting_to_score,
    parse_meeting_csv,
)


class TestParseMeetingCsv:
    """Tests for parse_meeting_csv()."""

    def test_with_sample_data(self, meeting_register: Path):
        meetings = parse_meeting_csv(meeting_register)
        assert len(meetings) == 6  # 6 meeting dates in sample

    def test_sorted_by_date(self, meeting_register: Path):
        meetings = parse_meeting_csv(meeting_register)
        dates = [m.meeting_date for m in meetings]
        assert dates == sorted(dates)

    def test_items_counted(self, meeting_register: Path):
        meetings = parse_meeting_csv(meeting_register)
        for m in meetings:
            assert m.total_items > 0
            assert m.decided_items + m.deferred_items <= m.total_items

    def test_disciplines_populated(self, meeting_register: Path):
        meetings = parse_meeting_csv(meeting_register)
        for m in meetings:
            assert len(m.disciplines_required) > 0
            assert len(m.disciplines_present) > 0


class TestComputeAttendanceDecisionCorrelation:
    """Tests for compute_attendance_decision_correlation()."""

    def test_with_sample_meetings(self, sample_meetings):
        result = compute_attendance_decision_correlation(sample_meetings)
        assert "avg_decision_rate_pct" in result
        assert "avg_attendance_rate_pct" in result
        assert "correlation_strength" in result

    def test_decision_rates(self, sample_meetings):
        result = compute_attendance_decision_correlation(sample_meetings)
        assert 0 <= result["avg_decision_rate_pct"] <= 100
        assert 0 <= result["avg_attendance_rate_pct"] <= 100

    def test_per_meeting_details(self, sample_meetings):
        result = compute_attendance_decision_correlation(sample_meetings)
        assert len(result["per_meeting"]) == 3
        for m in result["per_meeting"]:
            assert "meeting_date" in m
            assert "decision_rate_pct" in m
            assert "attendance_rate_pct" in m

    def test_empty_meetings(self):
        result = compute_attendance_decision_correlation([])
        assert result["avg_decision_rate_pct"] == 0.0
        assert result["correlation_strength"] == "insufficient_data"

    def test_with_sample_file(self, meeting_register: Path):
        meetings = parse_meeting_csv(meeting_register)
        result = compute_attendance_decision_correlation(meetings)
        assert result["health_level"] in ("healthy", "at_risk", "critical")

    def test_full_attendance_boost(self):
        """Meetings with full attendance should have higher decision rates."""
        full = MeetingSummary(
            meeting_date=date(2026, 1, 1), total_items=10, decided_items=9, deferred_items=1,
            disciplines_required={"A", "B"}, disciplines_present={"A", "B"},
        )
        partial = MeetingSummary(
            meeting_date=date(2026, 1, 8), total_items=10, decided_items=3, deferred_items=7,
            disciplines_required={"A", "B"}, disciplines_present={"A"},
        )
        meetings = [full, full, partial, partial]
        result = compute_attendance_decision_correlation(meetings)
        assert result["decision_rate_full_attendance"] > result["decision_rate_partial_attendance"]


class TestMeetingToScore:
    """Tests for meeting_to_score()."""

    def test_high_decision_rate(self):
        result = {"avg_decision_rate_pct": 85.0}
        assert meeting_to_score(result) == 85.0

    def test_low_decision_rate(self):
        result = {"avg_decision_rate_pct": 20.0}
        assert meeting_to_score(result) == 20.0

    def test_clamped(self):
        assert meeting_to_score({"avg_decision_rate_pct": 150.0}) == 100.0
        assert meeting_to_score({"avg_decision_rate_pct": -10.0}) == 0.0
