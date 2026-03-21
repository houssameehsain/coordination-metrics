"""Tests for benchmark comparison module."""

import pytest

from coordination_metrics.benchmarks import (
    INDUSTRY_BENCHMARKS,
    Benchmark,
    compare_to_benchmark,
    generate_benchmark_report,
    get_benchmark,
)


class TestGetBenchmark:
    """Tests for get_benchmark()."""

    def test_returns_benchmark_for_known_metric(self):
        b = get_benchmark("recurring_clash_rate")
        assert isinstance(b, Benchmark)
        assert b.median == 8.0

    def test_returns_none_for_unknown_metric(self):
        assert get_benchmark("nonexistent_metric") is None

    def test_all_benchmarks_have_required_fields(self):
        for name, b in INDUSTRY_BENCHMARKS.items():
            assert b.percentile_25 <= b.median <= b.percentile_75 <= b.percentile_90
            assert b.sample_size > 0
            assert b.year > 2000
            assert len(b.source) > 0


class TestCompareToBenchmark:
    """Tests for compare_to_benchmark()."""

    def test_unknown_metric_returns_error(self):
        result = compare_to_benchmark("fake_metric", 50.0)
        assert "error" in result

    def test_high_approval_rate_is_above_average(self):
        result = compare_to_benchmark("first_submission_approval_rate", 85.0)
        assert result["comparison"] in ("above_average",)
        assert result["percentile_rank"] > 75

    def test_low_approval_rate_is_critical(self):
        result = compare_to_benchmark("first_submission_approval_rate", 20.0)
        assert result["comparison"] in ("critical", "below_average")
        assert result["percentile_rank"] < 25

    def test_median_value_is_average(self):
        result = compare_to_benchmark("meeting_decision_rate", 50.0)
        assert result["percentile_rank"] == pytest.approx(50.0, abs=5)
        assert result["comparison"] == "average"

    def test_lower_is_better_metrics(self):
        # Low recurring clash rate should score well
        result = compare_to_benchmark("recurring_clash_rate", 2.0)
        assert result["percentile_rank"] > 75
        assert result["comparison"] == "above_average"

    def test_lower_is_better_high_value(self):
        # High recurring clash rate should score poorly
        result = compare_to_benchmark("recurring_clash_rate", 30.0)
        assert result["percentile_rank"] < 25

    def test_rfi_response_p90_good(self):
        result = compare_to_benchmark("rfi_response_p90_days", 5.0)
        assert result["comparison"] == "above_average"

    def test_rfi_response_p90_bad(self):
        result = compare_to_benchmark("rfi_response_p90_days", 40.0)
        assert result["percentile_rank"] < 20

    def test_result_contains_all_keys(self):
        result = compare_to_benchmark("meeting_decision_rate", 60.0)
        assert "metric" in result
        assert "value" in result
        assert "percentile_rank" in result
        assert "comparison" in result
        assert "insight" in result
        assert "benchmark_median" in result
        assert "benchmark_source" in result
        assert "benchmark_sample_size" in result

    def test_percentile_clamped_0_100(self):
        # Extreme values
        result = compare_to_benchmark("first_submission_approval_rate", 0.0)
        assert 0 <= result["percentile_rank"] <= 100

        result = compare_to_benchmark("first_submission_approval_rate", 1000.0)
        assert 0 <= result["percentile_rank"] <= 100


class TestGenerateBenchmarkReport:
    """Tests for generate_benchmark_report()."""

    def test_returns_list_of_dicts(self):
        metrics = {
            "recurring_clash_rate": 10.0,
            "meeting_decision_rate": 55.0,
        }
        results = generate_benchmark_report(metrics)
        assert isinstance(results, list)
        assert len(results) == 2

    def test_skips_unknown_metrics(self):
        metrics = {
            "recurring_clash_rate": 10.0,
            "made_up_metric": 42.0,
        }
        results = generate_benchmark_report(metrics)
        assert len(results) == 1

    def test_empty_metrics(self):
        results = generate_benchmark_report({})
        assert results == []

    def test_all_metrics_at_once(self):
        metrics = {
            "clash_reduction_rate_per_round": 35.0,
            "recurring_clash_rate": 5.0,
            "first_submission_approval_rate": 75.0,
            "rfi_response_p90_days": 10.0,
            "rfi_no_response_rate": 8.0,
            "meeting_decision_rate": 60.0,
        }
        results = generate_benchmark_report(metrics)
        assert len(results) == 6
