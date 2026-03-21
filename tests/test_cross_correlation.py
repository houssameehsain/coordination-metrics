"""Tests for cross-metric correlation engine."""

import pytest

from coordination_metrics.cross_correlation import (
    CrossCorrelation,
    discover_cross_correlations,
)


class TestCrossCorrelationDataclass:
    """Tests for CrossCorrelation dataclass."""

    def test_basic_creation(self):
        cc = CrossCorrelation(
            metric_a="rfi_no_response_rate",
            metric_b="coordination_health",
            correlation=-0.8,
            p_value=0.01,
            direction="negative",
            insight="Test insight",
            actionable=True,
        )
        assert cc.metric_a == "rfi_no_response_rate"
        assert cc.actionable is True
        assert cc.correlation == -0.8


class TestDiscoverCrossCorrelations:
    """Tests for discover_cross_correlations()."""

    def test_rfi_no_response_triggers_insight(self):
        """High RFI no-response rate should produce an insight."""
        results = discover_cross_correlations(
            clash_trajectory_data={},
            recurrence_data={},
            approval_data={},
            rfi_data={"no_response_pct": 25},
            meeting_data={},
        )
        assert len(results) >= 1
        rfi_insight = [c for c in results if c.metric_a == "rfi_no_response_rate"]
        assert len(rfi_insight) == 1
        assert rfi_insight[0].actionable is True
        assert "25%" in rfi_insight[0].insight

    def test_low_rfi_no_response_no_insight(self):
        """Low RFI no-response rate should not trigger."""
        results = discover_cross_correlations(
            clash_trajectory_data={},
            recurrence_data={},
            approval_data={},
            rfi_data={"no_response_pct": 5},
            meeting_data={},
        )
        rfi_insight = [c for c in results if c.metric_a == "rfi_no_response_rate"]
        assert len(rfi_insight) == 0

    def test_low_decision_rate_with_poor_clash_health(self):
        """Low meeting decisions + poor clash trajectory should correlate."""
        results = discover_cross_correlations(
            clash_trajectory_data={"health": "stalled"},
            recurrence_data={},
            approval_data={},
            rfi_data={},
            meeting_data={"avg_decision_rate_pct": 35},
        )
        decision_insights = [
            c for c in results if c.metric_a == "meeting_decision_rate"
        ]
        assert len(decision_insights) == 1
        assert decision_insights[0].direction == "negative"

    def test_high_decision_rate_no_trigger(self):
        """Good decision rates should not trigger clash correlation."""
        results = discover_cross_correlations(
            clash_trajectory_data={"health": "stalled"},
            recurrence_data={},
            approval_data={},
            rfi_data={},
            meeting_data={"avg_decision_rate_pct": 75},
        )
        decision_insights = [
            c for c in results if c.metric_a == "meeting_decision_rate"
        ]
        assert len(decision_insights) == 0

    def test_critical_absence_with_recurrence(self):
        """Absent discipline + high recurrence should produce insight."""
        results = discover_cross_correlations(
            clash_trajectory_data={},
            recurrence_data={"recurrence_rate_pct": 18.0},
            approval_data={},
            rfi_data={},
            meeting_data={"critical_absence": "Mechanical"},
        )
        absence_insights = [
            c for c in results if c.metric_a == "critical_absence_discipline"
        ]
        assert len(absence_insights) == 1
        assert "Mechanical" in absence_insights[0].insight

    def test_no_critical_absence_no_trigger(self):
        """No absent discipline should not trigger."""
        results = discover_cross_correlations(
            clash_trajectory_data={},
            recurrence_data={"recurrence_rate_pct": 18.0},
            approval_data={},
            rfi_data={},
            meeting_data={},
        )
        absence_insights = [
            c for c in results if c.metric_a == "critical_absence_discipline"
        ]
        assert len(absence_insights) == 0

    def test_empty_data_returns_empty(self):
        """All empty inputs should return no correlations."""
        results = discover_cross_correlations(
            clash_trajectory_data={},
            recurrence_data={},
            approval_data={},
            rfi_data={},
            meeting_data={},
        )
        assert results == []

    def test_none_data_returns_empty(self):
        """None inputs should return no correlations without crashing."""
        results = discover_cross_correlations(
            clash_trajectory_data=None,
            recurrence_data=None,
            approval_data=None,
            rfi_data=None,
            meeting_data=None,
        )
        assert results == []

    def test_multiple_insights_at_once(self):
        """Multiple conditions met should produce multiple insights."""
        results = discover_cross_correlations(
            clash_trajectory_data={"health": "slowing"},
            recurrence_data={"recurrence_rate_pct": 20.0},
            approval_data={},
            rfi_data={"no_response_pct": 30},
            meeting_data={
                "avg_decision_rate_pct": 40,
                "critical_absence": "Electrical",
            },
        )
        # Should have at least: decision rate, critical absence, RFI no-response
        assert len(results) >= 3
        metric_a_set = {c.metric_a for c in results}
        assert "rfi_no_response_rate" in metric_a_set
        assert "meeting_decision_rate" in metric_a_set
        assert "critical_absence_discipline" in metric_a_set

    def test_all_correlations_have_direction(self):
        """Every correlation should have a valid direction."""
        results = discover_cross_correlations(
            clash_trajectory_data={"health": "stalled"},
            recurrence_data={"recurrence_rate_pct": 15.0},
            approval_data={},
            rfi_data={"no_response_pct": 20},
            meeting_data={"avg_decision_rate_pct": 30, "critical_absence": "Structural"},
        )
        for c in results:
            assert c.direction in ("positive", "negative")
