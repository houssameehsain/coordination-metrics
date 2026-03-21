"""Tests for Metric 2: Recurring Clash Rate."""

from pathlib import Path

import pytest

from coordination_metrics.core import ClashPoint
from coordination_metrics.recurring_clashes import (
    detect_recurrences,
    extract_clash_points,
    recurrence_to_score,
)


class TestExtractClashPoints:
    """Tests for extract_clash_points()."""

    def test_extracts_points_from_round1(self, clash_round1_xml: Path):
        points = extract_clash_points(clash_round1_xml)
        assert len(points) == 20  # 10 + 5 + 5
        assert all(isinstance(p, ClashPoint) for p in points)

    def test_coordinates_populated(self, clash_round1_xml: Path):
        points = extract_clash_points(clash_round1_xml)
        for p in points:
            assert p.x != 0 or p.y != 0 or p.z != 0

    def test_status_populated(self, clash_round1_xml: Path):
        points = extract_clash_points(clash_round1_xml)
        statuses = {p.status for p in points}
        assert "new" in statuses
        assert "active" in statuses

    def test_test_name_populated(self, clash_round1_xml: Path):
        points = extract_clash_points(clash_round1_xml)
        test_names = {p.test_name for p in points}
        assert "MEP-Structure" in test_names


class TestDetectRecurrences:
    """Tests for detect_recurrences()."""

    def test_detects_spatial_recurrence(
        self, sample_clash_points_resolved, sample_clash_points_current
    ):
        result = detect_recurrences(
            sample_clash_points_resolved,
            sample_clash_points_current,
            threshold_mm=500,
        )
        assert result["recurring_count"] >= 1
        assert result["resolved_count"] == 3

    def test_no_recurrence_with_tight_threshold(
        self, sample_clash_points_resolved, sample_clash_points_current
    ):
        result = detect_recurrences(
            sample_clash_points_resolved,
            sample_clash_points_current,
            threshold_mm=10,  # Very tight
        )
        assert result["recurring_count"] == 0

    def test_empty_previous(self, sample_clash_points_current):
        result = detect_recurrences([], sample_clash_points_current)
        assert result["recurrence_rate_pct"] == 0.0
        assert result["health_level"] == "healthy"

    def test_no_resolved_in_previous(self, sample_clash_points_current):
        active_only = [
            ClashPoint("A1", 1000, 2000, 3000, "active", "Test-A"),
        ]
        result = detect_recurrences(active_only, sample_clash_points_current)
        assert result["resolved_count"] == 0
        assert result["recurring_count"] == 0

    def test_with_sample_data(self, clash_round1_xml, clash_round2_xml):
        prev = extract_clash_points(clash_round1_xml)
        curr = extract_clash_points(clash_round2_xml)
        result = detect_recurrences(prev, curr, threshold_mm=500)
        assert "recurrence_rate_pct" in result
        assert "health_level" in result

    def test_health_levels(self):
        # 0% recurrence = healthy
        resolved = [ClashPoint("R1", 0, 0, 0, "resolved", "T")]
        no_match = [ClashPoint("N1", 99999, 99999, 99999, "new", "T")]
        result = detect_recurrences(resolved, no_match)
        assert result["health_level"] == "healthy"


class TestRecurrenceToScore:
    """Tests for recurrence_to_score()."""

    def test_zero_recurrence(self):
        assert recurrence_to_score(0.0) == 100.0

    def test_full_recurrence(self):
        assert recurrence_to_score(100.0) == 0.0

    def test_partial_recurrence(self):
        score = recurrence_to_score(25.0)
        assert score == 75.0
