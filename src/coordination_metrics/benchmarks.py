"""Coordination metrics benchmark database.

Provides industry benchmarks for comparison and allows anonymous
contribution of project metrics to build the benchmark dataset.

Initial benchmarks are derived from published research:
- Navigant/CMAA (2013): ~1M RFIs across 1,362 projects
- GIRI: 70%+ of rework is design-induced
- CII: 5-15% rework cost
- Chahrour et al. (2020): 20% cost savings on infrastructure project with active clash management
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Benchmark:
    metric: str
    percentile_25: float
    median: float
    percentile_75: float
    percentile_90: float
    source: str
    sample_size: int
    year: int


# Industry benchmarks from published research
INDUSTRY_BENCHMARKS = {
    "clash_reduction_rate_per_round": Benchmark(
        metric="Clash reduction rate per round (%)",
        percentile_25=15.0,
        median=30.0,
        percentile_75=45.0,
        percentile_90=60.0,
        source="Author estimates based on Chahrour et al. (2020) and practitioner surveys",
        sample_size=12,
        year=2020,
    ),
    "recurring_clash_rate": Benchmark(
        metric="Recurring clash rate (%)",
        percentile_25=3.0,
        median=8.0,
        percentile_75=15.0,
        percentile_90=25.0,
        source="Author estimates based on practitioner interviews (not from published data)",
        sample_size=20,
        year=2024,
    ),
    "first_submission_approval_rate": Benchmark(
        metric="First-submission approval rate (%)",
        percentile_25=55.0,
        median=70.0,
        percentile_75=82.0,
        percentile_90=90.0,
        source="Author estimates based on industry surveys",
        sample_size=100,
        year=2023,
    ),
    "rfi_response_p90_days": Benchmark(
        metric="RFI 90th percentile response time (business days)",
        percentile_25=8.0,
        median=14.0,
        percentile_75=21.0,
        percentile_90=35.0,
        source="Navigant/CMAA (2013) summary statistics; percentile distribution estimated by author",
        sample_size=1362,
        year=2013,
    ),
    "rfi_no_response_rate": Benchmark(
        metric="RFI no-response rate (%)",
        percentile_25=5.0,
        median=12.0,
        percentile_75=22.0,
        percentile_90=35.0,
        source="Navigant/CMAA (2013) summary statistics; percentile distribution estimated by author",
        sample_size=1362,
        year=2013,
    ),
    "meeting_decision_rate": Benchmark(
        metric="Meeting decision resolution rate (%)",
        percentile_25=35.0,
        median=50.0,
        percentile_75=65.0,
        percentile_90=80.0,
        source="Author estimates based on Cavka et al. (2015); percentile distribution estimated",
        sample_size=27,
        year=2015,
    ),
}


def get_benchmark(metric_name: str) -> Benchmark | None:
    """Get the industry benchmark for a metric."""
    return INDUSTRY_BENCHMARKS.get(metric_name)


def compare_to_benchmark(metric_name: str, value: float) -> dict:
    """Compare a project's metric value to industry benchmarks.

    Returns:
        percentile_rank: Where this project falls (0-100)
        comparison: "above_average", "average", "below_average", "critical"
        insight: Human-readable comparison string
    """
    benchmark = INDUSTRY_BENCHMARKS.get(metric_name)
    if not benchmark:
        return {"error": f"No benchmark for {metric_name}"}

    # Estimate percentile rank using linear interpolation
    points = [
        (0, 0),
        (benchmark.percentile_25, 25),
        (benchmark.median, 50),
        (benchmark.percentile_75, 75),
        (benchmark.percentile_90, 90),
        (benchmark.percentile_90 * 1.5, 100),
    ]

    # For metrics where lower is better (recurrence rate, RFI days, no-response rate)
    lower_is_better = metric_name in (
        "recurring_clash_rate",
        "rfi_response_p90_days",
        "rfi_no_response_rate",
    )

    if lower_is_better:
        # Invert: lower value = higher percentile rank
        points = [(p[0], 100 - p[1]) for p in points]

    # Linear interpolation
    percentile = 50  # default
    for i in range(len(points) - 1):
        x1, y1 = points[i]
        x2, y2 = points[i + 1]
        if x1 <= value <= x2:
            if x2 != x1:
                percentile = y1 + (y2 - y1) * (value - x1) / (x2 - x1)
            break
    else:
        if value <= points[0][0]:
            percentile = points[0][1]
        else:
            percentile = points[-1][1]

    percentile = max(0, min(100, percentile))

    # Classification
    if percentile >= 75:
        comparison = "above_average"
    elif percentile >= 40:
        comparison = "average"
    elif percentile >= 20:
        comparison = "below_average"
    else:
        comparison = "critical"

    # Insight
    if lower_is_better:
        if comparison == "above_average":
            insight = (
                f"Your {benchmark.metric} of {value} is better than "
                f"{percentile:.0f}% of projects."
            )
        elif comparison == "critical":
            insight = (
                f"Your {benchmark.metric} of {value} is worse than "
                f"{100 - percentile:.0f}% of projects. Immediate action recommended."
            )
        else:
            insight = (
                f"Your {benchmark.metric} of {value} is at the "
                f"{percentile:.0f}th percentile."
            )
    else:
        if comparison == "above_average":
            insight = (
                f"Your {benchmark.metric} of {value} is better than "
                f"{percentile:.0f}% of projects."
            )
        elif comparison == "critical":
            insight = (
                f"Your {benchmark.metric} of {value} is in the bottom "
                f"{percentile:.0f}%. Immediate action recommended."
            )
        else:
            insight = (
                f"Your {benchmark.metric} of {value} is at the "
                f"{percentile:.0f}th percentile."
            )

    return {
        "metric": metric_name,
        "value": value,
        "percentile_rank": round(percentile, 1),
        "comparison": comparison,
        "insight": insight,
        "benchmark_median": benchmark.median,
        "benchmark_source": benchmark.source,
        "benchmark_sample_size": benchmark.sample_size,
    }


def generate_benchmark_report(metrics: dict) -> list[dict]:
    """Compare all available metrics against industry benchmarks.

    Args:
        metrics: Dict mapping metric_name to value
    """
    results = []
    for name, value in metrics.items():
        if name in INDUSTRY_BENCHMARKS:
            results.append(compare_to_benchmark(name, value))
    return results
