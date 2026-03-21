"""Tests for Earned Coordination Value (ECV)."""

from datetime import date, timedelta

import pytest

from coordination_metrics.ecv import ECVConfig, ECVSnapshot, compute_ecv, compute_ecv_trend


@pytest.fixture
def standard_config() -> ECVConfig:
    """A standard ECV config for a 6-month coordination period."""
    return ECVConfig(
        project_start=date(2026, 1, 1),
        coordination_deadline=date(2026, 7, 1),
        total_expected_clashes=200,
        total_expected_rfis=100,
        total_expected_submittals=80,
        total_expected_meetings=24,
    )


class TestECVSnapshot:
    """Tests for ECVSnapshot dataclass."""

    def test_variance_positive_when_ahead(self):
        snap = ECVSnapshot(
            date=date(2026, 4, 1),
            planned_value=50.0,
            earned_value=60.0,
            cpi=1.2,
            spi=1.2,
        )
        assert snap.variance == 10.0

    def test_variance_negative_when_behind(self):
        snap = ECVSnapshot(
            date=date(2026, 4, 1),
            planned_value=50.0,
            earned_value=30.0,
            cpi=0.6,
            spi=0.6,
        )
        assert snap.variance == -20.0

    def test_status_ahead(self):
        snap = ECVSnapshot(date=date(2026, 4, 1), planned_value=50.0, earned_value=60.0, cpi=1.1, spi=1.1)
        assert snap.status == "ahead"

    def test_status_on_track(self):
        snap = ECVSnapshot(date=date(2026, 4, 1), planned_value=50.0, earned_value=50.0, cpi=1.0, spi=1.0)
        assert snap.status == "on_track"

    def test_status_at_risk(self):
        snap = ECVSnapshot(date=date(2026, 4, 1), planned_value=50.0, earned_value=40.0, cpi=0.85, spi=0.85)
        assert snap.status == "at_risk"

    def test_status_behind(self):
        snap = ECVSnapshot(date=date(2026, 4, 1), planned_value=50.0, earned_value=20.0, cpi=0.5, spi=0.5)
        assert snap.status == "behind"


class TestComputeECV:
    """Tests for compute_ecv()."""

    def test_basic_computation(self, standard_config):
        result = compute_ecv(
            config=standard_config,
            measurement_date=date(2026, 4, 1),
            clashes_resolved=100,
            rfis_answered=50,
            submittals_approved=40,
            decisions_made=60,
        )
        assert isinstance(result, ECVSnapshot)
        assert result.date == date(2026, 4, 1)
        assert 0 <= result.planned_value <= 100
        assert 0 <= result.earned_value <= 100
        assert result.cpi > 0

    def test_all_resolved_gives_high_ev(self, standard_config):
        result = compute_ecv(
            config=standard_config,
            measurement_date=date(2026, 4, 1),
            clashes_resolved=200,
            rfis_answered=100,
            submittals_approved=80,
            decisions_made=120,
        )
        assert result.earned_value >= 95.0

    def test_nothing_resolved_gives_zero_ev(self, standard_config):
        result = compute_ecv(
            config=standard_config,
            measurement_date=date(2026, 4, 1),
            clashes_resolved=0,
            rfis_answered=0,
            submittals_approved=0,
            decisions_made=0,
        )
        assert result.earned_value == 0.0

    def test_cpi_above_one_when_ahead(self, standard_config):
        # Measure early with lots resolved => CPI should be > 1
        result = compute_ecv(
            config=standard_config,
            measurement_date=date(2026, 2, 1),  # early in project
            clashes_resolved=150,
            rfis_answered=80,
            submittals_approved=60,
            decisions_made=80,
        )
        assert result.cpi > 1.0

    def test_cpi_below_one_when_behind(self, standard_config):
        # Measure late with very little resolved => CPI should be < 1
        # Use very small numbers relative to expectations
        result = compute_ecv(
            config=standard_config,
            measurement_date=date(2026, 6, 15),  # very late in project
            clashes_resolved=5,
            rfis_answered=2,
            submittals_approved=1,
            decisions_made=1,
        )
        assert result.cpi < 1.0

    def test_eac_date_projected(self, standard_config):
        # Use small resolution numbers so EV < 100, triggering EAC projection
        result = compute_ecv(
            config=standard_config,
            measurement_date=date(2026, 4, 1),
            clashes_resolved=10,
            rfis_answered=5,
            submittals_approved=4,
            decisions_made=3,
        )
        assert result.eac_date is not None
        assert result.eac_date > date(2026, 4, 1)

    def test_zero_totals_handle_gracefully(self):
        config = ECVConfig(
            project_start=date(2026, 1, 1),
            coordination_deadline=date(2026, 7, 1),
            total_expected_clashes=0,
            total_expected_rfis=0,
            total_expected_submittals=0,
            total_expected_meetings=0,
        )
        result = compute_ecv(
            config=config,
            measurement_date=date(2026, 4, 1),
            clashes_resolved=10,
            rfis_answered=5,
            submittals_approved=3,
            decisions_made=2,
        )
        assert result.earned_value == 0.0
        # When EV=0 and PV>0, CPI = 0/PV = 0
        assert result.cpi == 0.0

    def test_same_day_start_and_deadline(self):
        config = ECVConfig(
            project_start=date(2026, 4, 1),
            coordination_deadline=date(2026, 4, 1),
            total_expected_clashes=10,
        )
        result = compute_ecv(
            config=config,
            measurement_date=date(2026, 4, 1),
            clashes_resolved=5,
            rfis_answered=0,
            submittals_approved=0,
            decisions_made=0,
        )
        # Should not crash
        assert isinstance(result, ECVSnapshot)


class TestComputeECVTrend:
    """Tests for compute_ecv_trend()."""

    def test_trend_returns_list(self, standard_config):
        snapshots = [
            {"date": date(2026, 2, 1), "clashes_resolved": 30, "rfis_answered": 10, "submittals_approved": 8, "decisions_made": 10},
            {"date": date(2026, 3, 1), "clashes_resolved": 70, "rfis_answered": 30, "submittals_approved": 25, "decisions_made": 30},
            {"date": date(2026, 4, 1), "clashes_resolved": 120, "rfis_answered": 55, "submittals_approved": 45, "decisions_made": 55},
        ]
        results = compute_ecv_trend(standard_config, snapshots)
        assert len(results) == 3
        assert all(isinstance(r, ECVSnapshot) for r in results)

    def test_trend_ev_increases(self, standard_config):
        snapshots = [
            {"date": date(2026, 2, 1), "clashes_resolved": 30, "rfis_answered": 10},
            {"date": date(2026, 3, 1), "clashes_resolved": 70, "rfis_answered": 30},
            {"date": date(2026, 4, 1), "clashes_resolved": 120, "rfis_answered": 55},
        ]
        results = compute_ecv_trend(standard_config, snapshots)
        assert results[0].earned_value <= results[1].earned_value <= results[2].earned_value

    def test_empty_snapshots(self, standard_config):
        results = compute_ecv_trend(standard_config, [])
        assert results == []
