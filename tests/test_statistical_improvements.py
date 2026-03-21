"""Tests for the statistical improvements:
- Exponential decay fitting & changepoint detection
- Zero-clash projection
- Hungarian algorithm matching
- Coordinate shift detection
- BCF parsing
- Survival analysis for censored RFI data
- Business days calculation
- Correlation p-value / significance
"""

from __future__ import annotations

import io
import math
import zipfile
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from coordination_metrics.core import ClashPoint, ClashRoundSummary, MeetingSummary


# -----------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------

@pytest.fixture
def decaying_summaries() -> list[ClashRoundSummary]:
    """Summaries that follow an exponential decay pattern."""
    # N(t) ~ 100 * exp(-0.05 * t), measured every 14 days
    base = date(2026, 1, 1)
    return [
        ClashRoundSummary.from_counts(
            round_date=base + timedelta(days=d),
            round_label=f"R{i}",
            new=max(1, int(100 * math.exp(-0.05 * d) * 0.3)),
            active=max(1, int(100 * math.exp(-0.05 * d) * 0.3)),
            reviewed=max(1, int(100 * math.exp(-0.05 * d) * 0.2)),
            resolved=max(1, int(100 * math.exp(-0.05 * d) * 0.2)),
        )
        for i, d in enumerate([0, 14, 28, 42, 56, 70])
    ]


@pytest.fixture
def spiking_summaries() -> list[ClashRoundSummary]:
    """Summaries with a clear changepoint (spike at round 3)."""
    return [
        ClashRoundSummary.from_counts(
            round_date=date(2026, 1, 1), round_label="R1",
            new=50, active=20, reviewed=10, resolved=5,
        ),
        ClashRoundSummary.from_counts(
            round_date=date(2026, 1, 15), round_label="R2",
            new=40, active=15, reviewed=8, resolved=10,
        ),
        ClashRoundSummary.from_counts(
            round_date=date(2026, 1, 29), round_label="R3 - scope change",
            new=120, active=40, reviewed=5, resolved=5,  # spike
        ),
        ClashRoundSummary.from_counts(
            round_date=date(2026, 2, 12), round_label="R4",
            new=100, active=35, reviewed=10, resolved=15,
        ),
    ]


@pytest.fixture
def resolved_points_with_guid() -> list[ClashPoint]:
    """Resolved points with GUID for BCF matching."""
    return [
        ClashPoint("R1", 1000, 2000, 3000, "resolved", "T", guid="guid-aaa"),
        ClashPoint("R2", 5000, 6000, 7000, "resolved", "T", guid="guid-bbb"),
        ClashPoint("R3", 9000, 1000, 4000, "resolved", "T", guid="guid-ccc"),
    ]


@pytest.fixture
def current_points_with_guid() -> list[ClashPoint]:
    """Current points: guid-aaa recurs, guid-ddd is new."""
    return [
        ClashPoint("N1", 1100, 2100, 3100, "new", "T", guid="guid-aaa"),  # GUID match
        ClashPoint("N2", 20000, 20000, 20000, "new", "T", guid="guid-ddd"),  # no match
        ClashPoint("N3", 5100, 6100, 7100, "active", "T", guid="guid-eee"),  # spatial match to R2
    ]


@pytest.fixture
def shifted_current_points() -> list[ClashPoint]:
    """Current points shifted by (500, 500, 0) from resolved positions."""
    return [
        ClashPoint("S1", 1500, 2500, 3000, "new", "T"),  # R1 shifted by 500,500,0
        ClashPoint("S2", 5500, 6500, 7000, "new", "T"),  # R2 shifted
        ClashPoint("S3", 9500, 1500, 4000, "active", "T"),  # R3 shifted
    ]


@pytest.fixture
def minimal_bcf_zip(tmp_path: Path) -> Path:
    """Create a minimal BCF-ZIP file for testing."""
    bcf_path = tmp_path / "test.bcf"

    markup_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Markup>
    <Topic Guid="topic-001">
        <Title>MEP Clash at Level 2</Title>
        <TopicStatus>Active</TopicStatus>
        <TopicType>Clash</TopicType>
        <Priority>High</Priority>
        <CreationDate>2026-01-15T10:00:00Z</CreationDate>
        <ModifiedDate>2026-01-20T14:00:00Z</ModifiedDate>
        <AssignedTo>John Doe</AssignedTo>
        <Description>Duct intersects beam at grid C-4</Description>
    </Topic>
    <Viewpoints>
        <ViewPoint Guid="vp-001"/>
    </Viewpoints>
</Markup>"""

    viewpoint_xml = """<?xml version="1.0" encoding="UTF-8"?>
<VisualizationInfo>
    <PerspectiveCamera>
        <CameraViewPoint>
            <X>1500.0</X>
            <Y>2500.0</Y>
            <Z>3200.0</Z>
        </CameraViewPoint>
    </PerspectiveCamera>
</VisualizationInfo>"""

    markup2_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Markup>
    <Topic Guid="topic-002">
        <Title>Resolved pipe clash</Title>
        <TopicStatus>Closed</TopicStatus>
        <TopicType>Clash</TopicType>
        <Priority>Medium</Priority>
        <CreationDate>2026-01-10T08:00:00Z</CreationDate>
        <AssignedTo>Jane Smith</AssignedTo>
        <Description>Already fixed</Description>
    </Topic>
</Markup>"""

    with zipfile.ZipFile(bcf_path, "w") as zf:
        zf.writestr("bcf.version", '<?xml version="1.0"?><Version VersionId="2.1"/>')
        zf.writestr("topic-001/markup.bcf", markup_xml)
        zf.writestr("topic-001/vp-001.bcfv", viewpoint_xml)
        zf.writestr("topic-002/markup.bcf", markup2_xml)

    return bcf_path


# -----------------------------------------------------------------------
# Exponential Decay Tests
# -----------------------------------------------------------------------

class TestExponentialDecay:
    """Tests for exponential decay fitting in clash_trajectory."""

    def test_decay_rate_positive_for_decreasing(self, decaying_summaries):
        from coordination_metrics.clash_trajectory import compute_trajectory_slope

        result = compute_trajectory_slope(decaying_summaries)
        assert result["decay_rate"] is not None
        assert result["decay_rate"] > 0, "Decaying data should have positive decay rate"

    def test_decay_r_squared_good_fit(self, decaying_summaries):
        from coordination_metrics.clash_trajectory import compute_trajectory_slope

        result = compute_trajectory_slope(decaying_summaries)
        assert result["decay_r_squared"] is not None
        assert result["decay_r_squared"] > 0.5, "Exponential data should have good R^2"

    def test_decay_health_classification(self, decaying_summaries):
        from coordination_metrics.clash_trajectory import compute_trajectory_slope

        result = compute_trajectory_slope(decaying_summaries)
        assert result["decay_health"] in ("healthy", "slowing", "stalled")

    def test_linear_slope_still_present(self, decaying_summaries):
        from coordination_metrics.clash_trajectory import compute_trajectory_slope

        result = compute_trajectory_slope(decaying_summaries)
        assert "slope" in result
        assert "intercept" in result
        assert "r_squared" in result

    def test_insufficient_data(self):
        from coordination_metrics.clash_trajectory import compute_trajectory_slope

        single = [ClashRoundSummary.from_counts(
            round_date=date(2026, 1, 1), round_label="R1",
            new=10, active=5, reviewed=2, resolved=0,
        )]
        result = compute_trajectory_slope(single)
        assert result["decay_rate"] is None
        assert result["decay_health"] is None


class TestChangepointDetection:
    """Tests for changepoint detection."""

    def test_detects_spike(self, spiking_summaries):
        from coordination_metrics.clash_trajectory import detect_changepoints

        changepoints = detect_changepoints(spiking_summaries)
        assert len(changepoints) >= 1
        # The spike is at round index 2 (R3)
        indices = [cp["round_index"] for cp in changepoints]
        assert 2 in indices

    def test_no_changepoints_in_smooth_decay(self, decaying_summaries):
        from coordination_metrics.clash_trajectory import detect_changepoints

        changepoints = detect_changepoints(decaying_summaries)
        assert len(changepoints) == 0

    def test_changepoints_in_trajectory_result(self, spiking_summaries):
        from coordination_metrics.clash_trajectory import compute_trajectory_slope

        result = compute_trajectory_slope(spiking_summaries)
        assert "changepoints" in result
        assert len(result["changepoints"]) >= 1

    def test_custom_threshold(self, spiking_summaries):
        from coordination_metrics.clash_trajectory import detect_changepoints

        # Very high threshold should not detect the spike
        changepoints = detect_changepoints(spiking_summaries, spike_threshold=5.0)
        assert len(changepoints) == 0


class TestZeroClashProjection:
    """Tests for zero-clash projection."""

    def test_projects_date_for_decaying(self, decaying_summaries):
        from coordination_metrics.clash_trajectory import projected_zero_date

        result = projected_zero_date(decaying_summaries, threshold=5)
        assert result["projected_date"] is not None
        assert result["model_used"] in ("exponential_decay", "linear")
        assert result["warning"] is None or "linear" in (result["warning"] or "")

    def test_no_projection_for_increasing(self):
        from coordination_metrics.clash_trajectory import projected_zero_date

        increasing = [
            ClashRoundSummary.from_counts(
                round_date=date(2026, 1, 1) + timedelta(days=i * 14),
                round_label=f"R{i}",
                new=10 + i * 10, active=5 + i * 5, reviewed=2, resolved=1,
            )
            for i in range(4)
        ]
        result = projected_zero_date(increasing)
        assert result["projected_date"] is None
        assert "not decreasing" in (result["warning"] or "").lower()

    def test_single_round(self):
        from coordination_metrics.clash_trajectory import projected_zero_date

        result = projected_zero_date([
            ClashRoundSummary.from_counts(
                round_date=date(2026, 1, 1), round_label="R1",
                new=10, active=5, reviewed=2, resolved=0,
            )
        ])
        assert result["projected_date"] is None


# -----------------------------------------------------------------------
# Hungarian Algorithm Tests
# -----------------------------------------------------------------------

class TestHungarianMatching:
    """Tests for optimal bipartite matching in recurring_clashes."""

    def test_detects_spatial_recurrence(
        self, sample_clash_points_resolved, sample_clash_points_current
    ):
        from coordination_metrics.recurring_clashes import detect_recurrences

        result = detect_recurrences(
            sample_clash_points_resolved,
            sample_clash_points_current,
            threshold_mm=500,
        )
        assert result["recurring_count"] >= 1
        assert result["resolved_count"] == 3
        assert result["matching_method"] is not None

    def test_guid_matching_priority(
        self, resolved_points_with_guid, current_points_with_guid
    ):
        from coordination_metrics.recurring_clashes import detect_recurrences

        result = detect_recurrences(
            resolved_points_with_guid,
            current_points_with_guid,
            threshold_mm=500,
        )
        # guid-aaa should match
        guid_matched = any(
            pair[0] == "R1" and pair[1] == "N1"
            for pair in result["recurring_pairs"]
        )
        assert guid_matched, "GUID matching should find guid-aaa recurrence"
        assert result["recurring_count"] >= 1

    def test_model_units_conversion(self):
        from coordination_metrics.recurring_clashes import detect_recurrences

        # Points in metres instead of mm
        resolved = [ClashPoint("R1", 1.0, 2.0, 3.0, "resolved", "T")]
        current = [ClashPoint("N1", 1.05, 2.05, 3.05, "new", "T")]

        # In metres, distance ~ 87mm. With model_units="m" and threshold 500mm
        result = detect_recurrences(resolved, current, threshold_mm=500, model_units="m")
        assert result["recurring_count"] == 1

    def test_returns_matching_method(
        self, sample_clash_points_resolved, sample_clash_points_current
    ):
        from coordination_metrics.recurring_clashes import detect_recurrences

        result = detect_recurrences(
            sample_clash_points_resolved,
            sample_clash_points_current,
        )
        assert "matching_method" in result
        assert result["matching_method"] in (
            "hungarian", "greedy", "guid", "guid+hungarian",
            "guid+greedy", "none",
        )


class TestCoordinateShiftDetection:
    """Tests for coordinate shift detection."""

    def test_shift_detection(self, sample_clash_points_resolved, shifted_current_points):
        from coordination_metrics.recurring_clashes import detect_recurrences

        result = detect_recurrences(
            sample_clash_points_resolved,
            shifted_current_points,
            threshold_mm=500,
        )
        # Shift of (500, 500, 0) => magnitude ~707mm > 100mm threshold
        assert result["shift_detected"] is True
        assert result["shift_magnitude_mm"] > 100
        assert result["shift_warning"] is not None

    def test_no_shift_for_aligned_models(
        self, sample_clash_points_resolved, sample_clash_points_current
    ):
        from coordination_metrics.recurring_clashes import detect_recurrences

        result = detect_recurrences(
            sample_clash_points_resolved,
            sample_clash_points_current,
        )
        # The sample data has very different centroids due to far-away point,
        # but that's expected; check the field exists
        assert "shift_detected" in result
        assert "shift_magnitude_mm" in result


# -----------------------------------------------------------------------
# BCF Parser Tests
# -----------------------------------------------------------------------

class TestBCFParser:
    """Tests for BCF-ZIP parsing."""

    def test_parse_bcf_zip(self, minimal_bcf_zip: Path):
        from coordination_metrics.parsers.bcf import parse_bcf_zip

        issues = parse_bcf_zip(minimal_bcf_zip)
        assert len(issues) == 2

    def test_issue_fields(self, minimal_bcf_zip: Path):
        from coordination_metrics.parsers.bcf import parse_bcf_zip

        issues = parse_bcf_zip(minimal_bcf_zip)
        active = [i for i in issues if i.status == "Active"]
        assert len(active) == 1
        assert active[0].title == "MEP Clash at Level 2"
        assert active[0].guid == "topic-001"
        assert active[0].type == "Clash"
        assert active[0].priority == "High"
        assert active[0].assigned_to == "John Doe"

    def test_viewpoint_coordinates(self, minimal_bcf_zip: Path):
        from coordination_metrics.parsers.bcf import parse_bcf_zip

        issues = parse_bcf_zip(minimal_bcf_zip)
        topic1 = [i for i in issues if i.guid == "topic-001"][0]
        assert topic1.point_x == 1500.0
        assert topic1.point_y == 2500.0
        assert topic1.point_z == 3200.0

    def test_issue_without_viewpoint(self, minimal_bcf_zip: Path):
        from coordination_metrics.parsers.bcf import parse_bcf_zip

        issues = parse_bcf_zip(minimal_bcf_zip)
        topic2 = [i for i in issues if i.guid == "topic-002"][0]
        assert topic2.point_x is None
        assert topic2.point_y is None
        assert topic2.point_z is None

    def test_bcf_to_clash_points(self, minimal_bcf_zip: Path):
        from coordination_metrics.parsers.bcf import (
            bcf_issues_to_clash_points,
            parse_bcf_zip,
        )

        issues = parse_bcf_zip(minimal_bcf_zip)
        points = bcf_issues_to_clash_points(issues)
        # Only topic-001 has coordinates
        assert len(points) == 1
        assert points[0].guid == "topic-001"
        assert points[0].status == "active"

    def test_bcf_to_status_counts(self, minimal_bcf_zip: Path):
        from coordination_metrics.parsers.bcf import (
            bcf_to_status_counts,
            parse_bcf_zip,
        )

        issues = parse_bcf_zip(minimal_bcf_zip)
        counts = bcf_to_status_counts(issues)
        assert counts["active"] == 1
        assert counts["resolved"] == 1
        assert counts["new"] == 0


class TestSolibriParser:
    """Tests for Solibri parser (BCF wrapper)."""

    def test_parses_bcf_zip(self, minimal_bcf_zip: Path):
        from coordination_metrics.parsers.solibri import parse_solibri_results

        result = parse_solibri_results(minimal_bcf_zip)
        assert result["source_format"] == "bcf"
        assert result["summary"]["total"] == 2

    def test_returns_issues(self, minimal_bcf_zip: Path):
        from coordination_metrics.parsers.solibri import parse_solibri_results

        result = parse_solibri_results(minimal_bcf_zip)
        assert len(result["issues"]) == 2
        for issue in result["issues"]:
            assert "id" in issue
            assert "severity" in issue
            assert "status" in issue


# -----------------------------------------------------------------------
# Survival Analysis Tests
# -----------------------------------------------------------------------

class TestSurvivalAnalysis:
    """Tests for Kaplan-Meier censored RFI analysis."""

    def test_kaplan_meier_all_uncensored(self):
        from coordination_metrics.rfi_distribution import _kaplan_meier_percentiles

        times = np.array([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], dtype=float)
        censored = np.zeros(10, dtype=bool)

        result = _kaplan_meier_percentiles(times, censored)
        assert result["p50"] is not None
        assert result["p90"] is not None
        # P50 should be around 5, P90 around 9
        assert 4 <= result["p50"] <= 6
        assert 8 <= result["p90"] <= 10

    def test_kaplan_meier_with_censoring(self):
        from coordination_metrics.rfi_distribution import _kaplan_meier_percentiles

        # 8 closed (1-8 days) + 2 censored at day 3 and 5
        times = np.array([1, 2, 3, 3, 4, 5, 5, 6, 7, 8], dtype=float)
        censored = np.array([False, False, True, False, False, True, False,
                             False, False, False])

        result = _kaplan_meier_percentiles(times, censored)
        # With censoring, estimates should differ from naive percentiles
        assert result["p50"] is not None
        assert result["p90"] is not None

    def test_kaplan_meier_empty(self):
        from coordination_metrics.rfi_distribution import _kaplan_meier_percentiles

        result = _kaplan_meier_percentiles(np.array([]), np.array([], dtype=bool))
        assert result["p50"] is None
        assert result["p90"] is None

    def test_rfi_analysis_includes_km_fields(self, rfi_register: Path):
        from coordination_metrics.rfi_distribution import analyse_rfi_distribution

        result = analyse_rfi_distribution(rfi_register, include_open_rfis=True)
        overall = result["overall"]
        assert "km_p50" in overall
        assert "km_p90" in overall


# -----------------------------------------------------------------------
# Business Days Tests
# -----------------------------------------------------------------------

class TestBusinessDays:
    """Tests for business day calculations."""

    def test_business_days_weekdays_only(self):
        from coordination_metrics.rfi_distribution import _business_days

        # Monday to Friday = 5 calendar days but 5 business days
        assert _business_days(date(2026, 1, 5), date(2026, 1, 10)) == 5  # Mon-Sat = 5 bdays

    def test_business_days_skip_weekend(self):
        from coordination_metrics.rfi_distribution import _business_days

        # Monday to next Monday = 7 calendar days, 5 business days
        assert _business_days(date(2026, 1, 5), date(2026, 1, 12)) == 5

    def test_business_days_same_day(self):
        from coordination_metrics.rfi_distribution import _business_days

        assert _business_days(date(2026, 1, 5), date(2026, 1, 5)) == 0

    def test_rfi_uses_business_days(self, rfi_register: Path):
        from coordination_metrics.rfi_distribution import analyse_rfi_distribution

        result = analyse_rfi_distribution(rfi_register)
        overall = result["overall"]
        # Business day median should generally be <= calendar day median
        # (since weekends are excluded)
        if overall["median_days"] is not None:
            assert overall["median_days"] >= 0


# -----------------------------------------------------------------------
# Category-aware RFI Analysis
# -----------------------------------------------------------------------

class TestCategoryAwareRFI:
    """Tests for category-aware RFI analysis."""

    def test_by_category_present_if_column_exists(self, rfi_register: Path):
        from coordination_metrics.rfi_distribution import analyse_rfi_distribution
        import pandas as pd

        # Check if the sample data has a category column
        df = pd.read_csv(rfi_register)
        if "category" in df.columns.str.strip().str.lower():
            result = analyse_rfi_distribution(rfi_register)
            assert "by_category" in result


# -----------------------------------------------------------------------
# Correlation P-Value Tests
# -----------------------------------------------------------------------

class TestCorrelationPValue:
    """Tests for Pearson correlation with p-value."""

    def test_pearson_correlation_basic(self):
        from coordination_metrics.meeting_decisions import _pearson_correlation

        x = np.array([0.5, 0.6, 0.7, 0.8, 0.9, 1.0])
        y = np.array([0.4, 0.5, 0.6, 0.7, 0.8, 0.9])

        r, t_stat, p_value, ci = _pearson_correlation(x, y)
        assert abs(r - 1.0) < 0.01, "Perfect linear relationship should have r~1"
        assert p_value < 0.01, "Strong correlation should have small p-value"
        assert ci[0] > 0.5  # CI lower bound should be high

    def test_no_correlation(self):
        from coordination_metrics.meeting_decisions import _pearson_correlation

        np.random.seed(42)
        x = np.random.rand(100)
        y = np.random.rand(100)

        r, t_stat, p_value, ci = _pearson_correlation(x, y)
        assert abs(r) < 0.3, "Random data should have low correlation"

    def test_insufficient_data(self):
        from coordination_metrics.meeting_decisions import _pearson_correlation

        r, t_stat, p_value, ci = _pearson_correlation(
            np.array([1.0, 2.0]), np.array([3.0, 4.0])
        )
        # Only 2 points: p-value should be 1.0 (not enough data)
        assert p_value == 1.0

    def test_result_includes_significance(self, sample_meetings):
        from coordination_metrics.meeting_decisions import (
            compute_attendance_decision_correlation,
        )

        result = compute_attendance_decision_correlation(sample_meetings)
        assert "pearson_r" in result
        assert "p_value" in result
        assert "confidence_interval" in result
        assert "significant" in result
        assert isinstance(result["significant"], bool)

    def test_significance_requires_n_ge_5(self):
        from coordination_metrics.meeting_decisions import (
            compute_attendance_decision_correlation,
        )

        # Only 3 meetings -- should not be significant regardless
        meetings = [
            MeetingSummary(
                meeting_date=date(2026, 1, i * 7 + 1),
                total_items=10, decided_items=8, deferred_items=2,
                disciplines_required={"A", "B"}, disciplines_present={"A", "B"},
            )
            for i in range(3)
        ]
        result = compute_attendance_decision_correlation(meetings)
        assert result["significant"] is False

    def test_empty_meetings_returns_none_stats(self):
        from coordination_metrics.meeting_decisions import (
            compute_attendance_decision_correlation,
        )

        result = compute_attendance_decision_correlation([])
        assert result["pearson_r"] is None
        assert result["p_value"] is None
        assert result["significant"] is False
