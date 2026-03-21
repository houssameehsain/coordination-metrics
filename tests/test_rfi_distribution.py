"""Tests for Metric 4: RFI Response Time Distribution."""

from pathlib import Path

import pytest

from coordination_metrics.rfi_distribution import analyse_rfi_distribution, rfi_to_score


class TestAnalyseRfiDistribution:
    """Tests for analyse_rfi_distribution()."""

    def test_with_sample_data(self, rfi_register: Path):
        result = analyse_rfi_distribution(rfi_register)
        assert "overall" in result
        assert "by_discipline" in result

    def test_overall_stats(self, rfi_register: Path):
        result = analyse_rfi_distribution(rfi_register)
        overall = result["overall"]
        assert overall["total_rfis"] == 100
        assert overall["closed_rfis"] > 0
        assert overall["open_rfis"] >= 0
        assert overall["total_rfis"] == overall["closed_rfis"] + overall["open_rfis"]

    def test_median_less_than_p90(self, rfi_register: Path):
        result = analyse_rfi_distribution(rfi_register)
        overall = result["overall"]
        if overall["median_days"] is not None and overall["p90_days"] is not None:
            assert overall["median_days"] <= overall["p90_days"]

    def test_all_disciplines_present(self, rfi_register: Path):
        result = analyse_rfi_distribution(rfi_register)
        disciplines = {d["discipline"] for d in result["by_discipline"]}
        expected = {"Structural", "Mechanical", "Electrical", "Hydraulic", "Architecture"}
        assert disciplines == expected

    def test_bottleneck_detection(self, rfi_register: Path):
        result = analyse_rfi_distribution(rfi_register)
        # At least check that the flag exists
        for d in result["by_discipline"]:
            assert "is_bottleneck" in d

    def test_health_levels(self, rfi_register: Path):
        result = analyse_rfi_distribution(rfi_register)
        for d in result["by_discipline"]:
            assert d["health_level"] in ("healthy", "at_risk", "critical")

    def test_sorted_by_p90_descending(self, rfi_register: Path):
        result = analyse_rfi_distribution(rfi_register)
        by_disc = result["by_discipline"]
        p90s = [d["p90_days"] for d in by_disc if d["p90_days"] is not None]
        assert p90s == sorted(p90s, reverse=True)


class TestRfiToScore:
    """Tests for rfi_to_score()."""

    def test_fast_responses_high_score(self):
        result = {"overall": {"p90_days": 3.0}}
        assert rfi_to_score(result) >= 85.0

    def test_slow_responses_low_score(self):
        result = {"overall": {"p90_days": 28.0}}
        assert rfi_to_score(result) <= 15.0

    def test_no_data(self):
        result = {"overall": {"p90_days": None}}
        assert rfi_to_score(result) == 50.0

    def test_with_sample_data(self, rfi_register: Path):
        result = analyse_rfi_distribution(rfi_register)
        score = rfi_to_score(result)
        assert 0 <= score <= 100
