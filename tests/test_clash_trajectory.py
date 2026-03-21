"""Tests for Metric 1: Hard Clash Trajectory Slope."""

from datetime import date
from pathlib import Path

import pytest

from coordination_metrics.clash_trajectory import (
    build_trajectory,
    compute_trajectory_slope,
    trajectory_to_score,
)
from coordination_metrics.core import ClashRoundSummary


class TestBuildTrajectory:
    """Tests for build_trajectory()."""

    def test_parses_sample_xmls(self, all_clash_xmls: list[Path]):
        summaries = build_trajectory(all_clash_xmls)
        assert len(summaries) == 3
        # Should be sorted by date
        assert summaries[0].round_date <= summaries[1].round_date <= summaries[2].round_date

    def test_counts_are_positive(self, all_clash_xmls: list[Path]):
        summaries = build_trajectory(all_clash_xmls)
        for s in summaries:
            assert s.total > 0
            assert s.new >= 0
            assert s.active >= 0
            assert s.reviewed >= 0
            assert s.resolved >= 0

    def test_total_equals_sum(self, all_clash_xmls: list[Path]):
        summaries = build_trajectory(all_clash_xmls)
        for s in summaries:
            assert s.total == s.new + s.active + s.reviewed + s.resolved

    def test_single_xml(self, clash_round1_xml: Path):
        summaries = build_trajectory([clash_round1_xml])
        assert len(summaries) == 1
        assert summaries[0].total == 20


class TestComputeTrajectorySlope:
    """Tests for compute_trajectory_slope()."""

    def test_decreasing_trajectory(self, three_round_summaries):
        result = compute_trajectory_slope(three_round_summaries)
        assert result["slope"] < 0, "Decreasing trajectory should have negative slope"
        assert result["health_level"] in ("healthy", "at_risk"), (
            "Decreasing trajectory should be healthy or at_risk"
        )
        assert result["rounds"] == 3

    def test_increasing_trajectory(self, increasing_summaries):
        result = compute_trajectory_slope(increasing_summaries)
        assert result["slope"] > 0, "Increasing trajectory should have positive slope"
        assert result["health_level"] in ("at_risk", "critical")

    def test_single_round(self):
        summaries = [
            ClashRoundSummary.from_counts(
                round_date=date(2026, 1, 15), round_label="R1",
                new=10, active=5, reviewed=2, resolved=0,
            )
        ]
        result = compute_trajectory_slope(summaries)
        assert result["slope"] == 0.0
        assert "Insufficient data" in result["interpretation"]

    def test_r_squared_range(self, three_round_summaries):
        result = compute_trajectory_slope(three_round_summaries)
        assert 0.0 <= result["r_squared"] <= 1.0

    def test_with_sample_data(self, all_clash_xmls: list[Path]):
        summaries = build_trajectory(all_clash_xmls)
        result = compute_trajectory_slope(summaries)
        assert "slope" in result
        assert "interpretation" in result
        assert result["rounds"] == 3


class TestTrajectoryToScore:
    """Tests for trajectory_to_score()."""

    def test_negative_slope_high_score(self):
        assert trajectory_to_score(-5.0) >= 95.0

    def test_positive_slope_low_score(self):
        assert trajectory_to_score(10.0) <= 5.0

    def test_zero_slope_mid_score(self):
        score = trajectory_to_score(0.0)
        assert 20.0 <= score <= 80.0

    def test_clamped_to_0_100(self):
        assert trajectory_to_score(-100.0) == 100.0
        assert trajectory_to_score(100.0) == 0.0
