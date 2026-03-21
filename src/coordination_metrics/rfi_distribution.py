"""Metric 4: RFI Response Time Distribution.

Analyses how long it takes each discipline to respond to RFIs and
identifies bottleneck disciplines whose slow responses hold up
downstream work.

The key insight is not the *average* response time but the *distribution* --
specifically the P90 (90th percentile). A discipline with a healthy
median but a fat right tail has a few RFIs that sit unanswered for
weeks, silently blocking coordination.

Enhancements:
    - **Business days**: All durations use ``numpy.busday_count()`` instead
      of calendar days.
    - **Censored observations**: Open (unanswered) RFIs are included as
      right-censored data using a simple Kaplan-Meier estimator, producing
      adjusted P50/P90 that account for still-open RFIs.
    - **Category-aware analysis**: If a ``category`` column exists, separate
      distributions are computed per category.

Usage:
    >>> from coordination_metrics import analyse_rfi_distribution
    >>> result = analyse_rfi_distribution("rfi_register.csv")
    >>> for d in result["by_discipline"]:
    ...     print(f"{d['discipline']}: P90 = {d['p90_days']:.0f} days")
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Union

import numpy as np
import pandas as pd

from coordination_metrics.core import HealthLevel
from coordination_metrics.parsers.csv_register import read_register


# ---------------------------------------------------------------------------
# Business day helpers
# ---------------------------------------------------------------------------

def _business_days(start: date, end: date) -> int:
    """Compute business days between two dates using numpy.busday_count."""
    try:
        return int(np.busday_count(
            np.datetime64(start, 'D'),
            np.datetime64(end, 'D'),
        ))
    except Exception:
        # Fallback to calendar days if busday_count fails
        return (end - start).days


def _business_days_series(
    start_series: pd.Series,
    end_series: pd.Series,
) -> pd.Series:
    """Vectorised business-day calculation for two date Series."""
    result = pd.Series(np.nan, index=start_series.index)
    mask = start_series.notna() & end_series.notna()
    if mask.any():
        starts = start_series[mask].dt.date
        ends = end_series[mask].dt.date
        bdays = [
            _business_days(s, e) for s, e in zip(starts, ends)
        ]
        result.loc[mask] = bdays
    return result


# ---------------------------------------------------------------------------
# Kaplan-Meier survival estimator (simple implementation)
# ---------------------------------------------------------------------------

def _kaplan_meier_percentiles(
    times: np.ndarray,
    censored: np.ndarray,
    percentiles: tuple[float, ...] = (50.0, 90.0),
) -> dict[str, float | None]:
    """Compute adjusted percentiles using a Kaplan-Meier survival estimator.

    Args:
        times: Array of response times (or current duration for open RFIs).
        censored: Boolean array; True = right-censored (still open).
        percentiles: Which percentiles to compute.

    Returns:
        Dict mapping "p50", "p90", etc. to their estimated values.
        None if the survival function never drops below the required level.
    """
    if len(times) == 0:
        return {f"p{int(p)}": None for p in percentiles}

    # Sort by time
    order = np.argsort(times)
    sorted_times = times[order]
    sorted_censored = censored[order]

    n = len(sorted_times)
    at_risk = n
    survival = 1.0

    # Build survival function at each event time
    event_times: list[float] = []
    survival_values: list[float] = []
    event_times.append(0.0)
    survival_values.append(1.0)

    i = 0
    while i < n:
        t = sorted_times[i]
        # Count events (uncensored) and censored at this time
        events = 0
        censored_here = 0
        while i < n and sorted_times[i] == t:
            if sorted_censored[i]:
                censored_here += 1
            else:
                events += 1
            i += 1

        if events > 0 and at_risk > 0:
            survival *= (1.0 - events / at_risk)
            event_times.append(float(t))
            survival_values.append(survival)

        at_risk -= (events + censored_here)

    # Extract percentiles from survival function
    # P_x means the time at which survival drops to (1 - x/100)
    result = {}
    for p in percentiles:
        target_survival = 1.0 - (p / 100.0)
        found = None
        for t, s in zip(event_times, survival_values):
            if s <= target_survival:
                found = t
                break
        result[f"p{int(p)}"] = found

    return result


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def analyse_rfi_distribution(
    register_path: Union[str, Path],
    *,
    p90_threshold_days: float = 14.0,
    include_open_rfis: bool = True,
) -> dict:
    """Analyse RFI response time distribution by discipline.

    Args:
        register_path: Path to the RFI register (CSV or Excel).
        p90_threshold_days: P90 threshold (business days) above which a
            discipline is flagged as a bottleneck.
        include_open_rfis: If True, include open RFIs as right-censored
            observations in survival analysis (default True).

    Returns:
        Dictionary with:
            overall: {total_rfis, open_rfis, closed_rfis, median_days,
                      p90_days, mean_days, health_level, interpretation,
                      km_p50, km_p90}
            by_discipline: list of per-discipline dicts
            by_category: list of per-category dicts (if category column exists)
    """
    df = read_register(register_path)
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")

    required = {"date_submitted", "discipline"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"RFI register missing columns: {missing}")

    # Parse dates
    df["date_submitted"] = pd.to_datetime(df["date_submitted"], errors="coerce")

    has_response = "date_responded" in df.columns
    if has_response:
        df["date_responded"] = pd.to_datetime(df["date_responded"], errors="coerce")
        df["response_days"] = _business_days_series(
            df["date_submitted"], df["date_responded"]
        )
    else:
        df["date_responded"] = pd.NaT
        df["response_days"] = np.nan

    df["discipline"] = df["discipline"].str.strip()

    today = pd.Timestamp.now().normalize()

    # Overall stats
    closed = df.dropna(subset=["response_days"])
    overall = _compute_stats(
        df, closed, "Overall", p90_threshold_days,
        include_open_rfis=include_open_rfis,
        today=today,
    )

    # Per-discipline
    by_discipline = []
    for discipline, group in df.groupby("discipline"):
        grp_closed = group.dropna(subset=["response_days"])
        stats = _compute_stats(
            group, grp_closed, str(discipline), p90_threshold_days,
            include_open_rfis=include_open_rfis,
            today=today,
        )
        by_discipline.append(stats)

    # Sort by P90 descending to highlight worst performers
    by_discipline.sort(key=lambda d: d.get("p90_days") or 0, reverse=True)

    result = {
        "overall": overall,
        "by_discipline": by_discipline,
    }

    # Category-aware analysis
    has_category = "category" in df.columns
    if has_category:
        df["category"] = df["category"].fillna("Uncategorised").str.strip()
        by_category = []
        for category, group in df.groupby("category"):
            grp_closed = group.dropna(subset=["response_days"])
            stats = _compute_stats(
                group, grp_closed, str(category), p90_threshold_days,
                include_open_rfis=include_open_rfis,
                today=today,
                label_key="category",
            )
            by_category.append(stats)
        by_category.sort(key=lambda d: d.get("p90_days") or 0, reverse=True)
        result["by_category"] = by_category

    return result


def _compute_stats(
    all_rfis: pd.DataFrame,
    closed_rfis: pd.DataFrame,
    label: str,
    p90_threshold: float,
    *,
    include_open_rfis: bool = True,
    today: pd.Timestamp | None = None,
    label_key: str = "discipline",
) -> dict:
    """Compute response-time statistics for a subset of RFIs."""
    total = len(all_rfis)
    closed_count = len(closed_rfis)
    open_count = total - closed_count

    if closed_count == 0:
        return {
            label_key: label,
            "total_rfis": total,
            "open_rfis": open_count,
            "closed_rfis": 0,
            "median_days": None,
            "mean_days": None,
            "p90_days": None,
            "km_p50": None,
            "km_p90": None,
            "is_bottleneck": open_count > 0,
            "health_level": HealthLevel.AT_RISK.value if total > 0 else HealthLevel.HEALTHY.value,
            "interpretation": f"{label}: all {total} RFIs still open." if total > 0 else f"{label}: no RFIs.",
        }

    days = closed_rfis["response_days"].values.astype(float)
    median_days = float(np.median(days))
    mean_days = float(np.mean(days))
    p90_days = float(np.percentile(days, 90))

    # Kaplan-Meier with censored observations
    km_p50: float | None = None
    km_p90: float | None = None

    if include_open_rfis and open_count > 0 and today is not None:
        open_rfis = all_rfis[all_rfis["response_days"].isna()].copy()
        if not open_rfis.empty and "date_submitted" in open_rfis.columns:
            open_durations = _business_days_series(
                open_rfis["date_submitted"],
                pd.Series(today, index=open_rfis.index),
            ).values.astype(float)

            all_times = np.concatenate([days, open_durations[~np.isnan(open_durations)]])
            censored_flags = np.concatenate([
                np.zeros(len(days), dtype=bool),
                np.ones(int((~np.isnan(open_durations)).sum()), dtype=bool),
            ])

            km_result = _kaplan_meier_percentiles(all_times, censored_flags)
            km_p50 = km_result.get("p50")
            km_p90 = km_result.get("p90")
    else:
        # No censoring needed -- KM matches empirical
        km_p50 = median_days
        km_p90 = p90_days

    is_bottleneck = p90_days > p90_threshold

    if p90_days <= 7:
        health = HealthLevel.HEALTHY
    elif p90_days <= p90_threshold:
        health = HealthLevel.AT_RISK
    else:
        health = HealthLevel.CRITICAL

    pct_open = (open_count / total * 100) if total > 0 else 0
    interpretation = (
        f"{label}: median {median_days:.0f}d, P90 {p90_days:.0f}d, "
        f"{pct_open:.0f}% still open."
    )
    if is_bottleneck:
        interpretation += " BOTTLENECK -- P90 exceeds threshold."
    if km_p90 is not None and km_p90 > p90_days:
        interpretation += (
            f" Censored P90 ({km_p90:.0f}d) higher than closed-only P90 -- "
            f"open RFIs may be skewing the distribution."
        )

    return {
        label_key: label,
        "total_rfis": total,
        "open_rfis": open_count,
        "closed_rfis": closed_count,
        "median_days": round(median_days, 1),
        "mean_days": round(mean_days, 1),
        "p90_days": round(p90_days, 1),
        "km_p50": round(km_p50, 1) if km_p50 is not None else None,
        "km_p90": round(km_p90, 1) if km_p90 is not None else None,
        "is_bottleneck": is_bottleneck,
        "health_level": health.value,
        "interpretation": interpretation,
    }


def rfi_to_score(result: dict) -> float:
    """Convert RFI distribution result to a 0-100 health score.

    Uses the overall P90 response time: 0 days = 100, >=30 days = 0.

    Args:
        result: Output from analyse_rfi_distribution().

    Returns:
        Score where 100 = fast responses, 0 = very slow.
    """
    p90 = result["overall"].get("p90_days")
    if p90 is None:
        return 50.0  # no data
    # Linear scale: 0 days -> 100, 30 days -> 0
    score = 100.0 - (p90 / 30.0) * 100.0
    return max(0.0, min(100.0, score))
