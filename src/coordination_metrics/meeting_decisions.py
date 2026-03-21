"""Metric 5: Meeting Decision Resolution Rate.

Measures how productive coordination meetings are by tracking:
1. What fraction of agenda items reach a decision (vs. deferred).
2. Whether attendance of required disciplines correlates with
   higher decision rates.

A meeting where 80 % of items are deferred is a meeting that wasted
everyone's time. Worse, it signals that the right people are not
in the room or the team cannot agree -- both coordination red flags.

Enhancements:
    - **Pearson correlation with p-value**: Formal statistical test for
      attendance-decision correlation using t-distribution.
    - **Confidence interval**: 95% CI for the correlation coefficient.
    - **Significance flag**: ``p < 0.05`` and ``n >= 5``.

Usage:
    >>> from coordination_metrics import parse_meeting_csv, compute_attendance_decision_correlation
    >>> meetings = parse_meeting_csv("meeting_minutes.csv")
    >>> result = compute_attendance_decision_correlation(meetings)
    >>> print(f"Avg decision rate: {result['avg_decision_rate_pct']:.0f}%")
"""

from __future__ import annotations

import math
import statistics
from datetime import date, datetime
from pathlib import Path
from typing import Sequence, Union

import numpy as np

from coordination_metrics.core import HealthLevel, MeetingSummary
from coordination_metrics.parsers.csv_register import read_register


def parse_meeting_csv(path: Union[str, Path]) -> list[MeetingSummary]:
    """Parse a meeting-minutes CSV into MeetingSummary objects.

    Expected columns:
        meeting_date, item_number, item_description, status,
        disciplines_required, disciplines_present

    Items are grouped by meeting_date. Status values:
        DECIDED / RESOLVED / CLOSED -> decided
        DEFERRED / OPEN / PENDING   -> deferred
        Anything else               -> counted in total but neither decided nor deferred

    Args:
        path: Path to the meeting minutes CSV or Excel file.

    Returns:
        List of MeetingSummary objects, one per meeting date.
    """
    df = read_register(path)
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")

    required = {"meeting_date", "status"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Meeting register missing columns: {missing}")

    df["meeting_date"] = df["meeting_date"].astype(str).str.strip()
    df["status"] = df["status"].str.strip().str.upper()

    decided_statuses = {"DECIDED", "RESOLVED", "CLOSED"}
    deferred_statuses = {"DEFERRED", "OPEN", "PENDING"}

    summaries: list[MeetingSummary] = []

    for meeting_date_str, group in df.groupby("meeting_date"):
        try:
            meeting_date = datetime.strptime(str(meeting_date_str), "%Y-%m-%d").date()
        except ValueError:
            try:
                meeting_date = datetime.strptime(str(meeting_date_str), "%d/%m/%Y").date()
            except ValueError:
                continue  # skip unparseable dates

        total_items = len(group)
        decided = int((group["status"].isin(decided_statuses)).sum())
        deferred = int((group["status"].isin(deferred_statuses)).sum())

        # Collect disciplines from all rows in this meeting
        all_required: set[str] = set()
        all_present: set[str] = set()

        if "disciplines_required" in group.columns:
            for val in group["disciplines_required"].dropna():
                all_required.update(d.strip() for d in str(val).split(",") if d.strip())
        if "disciplines_present" in group.columns:
            for val in group["disciplines_present"].dropna():
                all_present.update(d.strip() for d in str(val).split(",") if d.strip())

        summaries.append(
            MeetingSummary(
                meeting_date=meeting_date,
                total_items=total_items,
                decided_items=decided,
                deferred_items=deferred,
                disciplines_required=all_required,
                disciplines_present=all_present,
            )
        )

    summaries.sort(key=lambda s: s.meeting_date)
    return summaries


# ---------------------------------------------------------------------------
# Statistical helpers
# ---------------------------------------------------------------------------

def _pearson_correlation(x: np.ndarray, y: np.ndarray) -> tuple[float, float, float, tuple[float, float]]:
    """Compute Pearson r, t-statistic, p-value, and 95% CI.

    Uses the formula:
        t = r * sqrt(n-2) / sqrt(1 - r^2)
        p = 2 * (1 - CDF_t(|t|, df=n-2))

    For the 95% CI, we use Fisher's z-transformation:
        z = 0.5 * ln((1+r)/(1-r))
        SE = 1 / sqrt(n-3)
        CI = tanh(z +/- 1.96 * SE)

    Returns:
        (r, t_stat, p_value, (ci_lower, ci_upper))
    """
    n = len(x)
    if n < 3:
        return 0.0, 0.0, 1.0, (-1.0, 1.0)

    # Correlation
    x_mean = np.mean(x)
    y_mean = np.mean(y)
    numerator = np.sum((x - x_mean) * (y - y_mean))
    denom = np.sqrt(np.sum((x - x_mean) ** 2) * np.sum((y - y_mean) ** 2))

    if denom == 0:
        return 0.0, 0.0, 1.0, (-1.0, 1.0)

    r = float(numerator / denom)

    # T-statistic
    df = n - 2
    if abs(r) >= 1.0:
        t_stat = float("inf") if r > 0 else float("-inf")
        p_value = 0.0
    else:
        t_stat = r * math.sqrt(df) / math.sqrt(1.0 - r * r)
        # Approximate p-value from t-distribution using regularized
        # incomplete beta function.
        p_value = _t_distribution_p_value(abs(t_stat), df)

    # 95% CI via Fisher z-transform
    r_clamped = max(-0.9999, min(0.9999, r))
    z = 0.5 * math.log((1 + r_clamped) / (1 - r_clamped))
    se = 1.0 / math.sqrt(max(n - 3, 1))
    z_lo = z - 1.96 * se
    z_hi = z + 1.96 * se
    ci_lower = math.tanh(z_lo)
    ci_upper = math.tanh(z_hi)

    return r, t_stat, p_value, (ci_lower, ci_upper)


def _t_distribution_p_value(t_abs: float, df: int) -> float:
    """Approximate two-tailed p-value for Student's t-distribution.

    Uses the regularized incomplete beta function approximation:
        p = I_x(df/2, 1/2) where x = df / (df + t^2)

    For our purposes, an approximation via the normal distribution is
    acceptable when df > 30. For smaller df, we use a continued-fraction
    expansion of the beta function.
    """
    if df <= 0:
        return 1.0
    if t_abs == 0:
        return 1.0

    x = df / (df + t_abs * t_abs)

    # Use regularized incomplete beta function
    p = _regularized_incomplete_beta(df / 2.0, 0.5, x)
    return min(1.0, max(0.0, p))


def _regularized_incomplete_beta(a: float, b: float, x: float) -> float:
    """Compute the regularized incomplete beta function I_x(a, b).

    Uses a simple continued fraction expansion (Lentz's method).
    Sufficient accuracy for p-value computation.
    """
    if x < 0 or x > 1:
        return 0.0
    if x == 0:
        return 0.0
    if x == 1:
        return 1.0

    # For numerical stability, use the identity I_x(a,b) = 1 - I_{1-x}(b,a)
    # when x > (a+1)/(a+b+2)
    if x > (a + 1.0) / (a + b + 2.0):
        return 1.0 - _regularized_incomplete_beta(b, a, 1.0 - x)

    # Log of the prefactor: x^a * (1-x)^b / (a * B(a,b))
    lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front = math.exp(
        a * math.log(x) + b * math.log(1.0 - x) - lbeta - math.log(a)
    )

    # Continued fraction (Lentz's method)
    f = 1.0
    c = 1.0
    d = 1.0 - (a + b) * x / (a + 1.0)
    if abs(d) < 1e-30:
        d = 1e-30
    d = 1.0 / d
    f = d

    for m in range(1, 201):
        # Even step
        numerator = m * (b - m) * x / ((a + 2 * m - 1) * (a + 2 * m))
        d = 1.0 + numerator * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + numerator / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        f *= d * c

        # Odd step
        numerator = -(a + m) * (a + b + m) * x / ((a + 2 * m) * (a + 2 * m + 1))
        d = 1.0 + numerator * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + numerator / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delta = d * c
        f *= delta

        if abs(delta - 1.0) < 1e-8:
            break

    return front * f


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def compute_attendance_decision_correlation(
    summaries: Sequence[MeetingSummary],
) -> dict:
    """Compute attendance-decision correlation across meetings.

    Args:
        summaries: List of MeetingSummary objects.

    Returns:
        Dictionary with:
            avg_decision_rate_pct: Average decision rate across meetings.
            avg_attendance_rate_pct: Average attendance rate.
            meetings_with_full_attendance: Count of meetings where all required attended.
            decision_rate_full_attendance: Decision rate when attendance is 100%.
            decision_rate_partial_attendance: Decision rate when attendance < 100%.
            pearson_r: Pearson correlation coefficient.
            p_value: Two-tailed p-value.
            confidence_interval: (lower, upper) 95% CI for correlation.
            significant: True if p < 0.05 and n >= 5.
            correlation_strength: "strong", "moderate", "weak", or "insufficient_data".
            per_meeting: List of per-meeting dicts.
            health_level: Traffic-light classification.
            interpretation: Human-readable assessment.
    """
    if not summaries:
        return {
            "avg_decision_rate_pct": 0.0,
            "avg_attendance_rate_pct": 0.0,
            "meetings_with_full_attendance": 0,
            "decision_rate_full_attendance": 0.0,
            "decision_rate_partial_attendance": 0.0,
            "pearson_r": None,
            "p_value": None,
            "confidence_interval": None,
            "significant": False,
            "correlation_strength": "insufficient_data",
            "per_meeting": [],
            "health_level": HealthLevel.AT_RISK.value,
            "interpretation": "No meeting data available.",
        }

    decision_rates = [m.decision_rate for m in summaries]
    attendance_rates = [m.attendance_rate for m in summaries]

    avg_decision = statistics.mean(decision_rates) * 100
    avg_attendance = statistics.mean(attendance_rates) * 100

    # Split by full vs partial attendance
    full_attendance = [m for m in summaries if m.attendance_rate >= 1.0]
    partial_attendance = [m for m in summaries if m.attendance_rate < 1.0]

    rate_full = (
        statistics.mean(m.decision_rate for m in full_attendance) * 100
        if full_attendance
        else 0.0
    )
    rate_partial = (
        statistics.mean(m.decision_rate for m in partial_attendance) * 100
        if partial_attendance
        else 0.0
    )

    # ---- Pearson correlation with p-value ----
    n = len(summaries)
    x = np.array(attendance_rates)
    y = np.array(decision_rates)
    pearson_r, t_stat, p_value, ci = _pearson_correlation(x, y)

    significant = p_value < 0.05 and n >= 5

    # Assess correlation
    if n < 5:
        correlation = "insufficient_data"
    elif significant:
        if abs(pearson_r) > 0.6:
            correlation = "strong"
        elif abs(pearson_r) > 0.3:
            correlation = "moderate"
        else:
            correlation = "weak"
    else:
        # Not significant -- check the old heuristic for backward compat
        if len(full_attendance) >= 2 and len(partial_attendance) >= 2:
            diff = rate_full - rate_partial
            if diff > 20:
                correlation = "strong"
            elif diff > 10:
                correlation = "moderate"
            else:
                correlation = "weak"
        else:
            correlation = "insufficient_data"

    # Health
    if avg_decision >= 70:
        health = HealthLevel.HEALTHY
        interpretation = (
            f"Avg decision rate {avg_decision:.0f}% -- "
            f"meetings are productive."
        )
    elif avg_decision >= 45:
        health = HealthLevel.AT_RISK
        interpretation = (
            f"Avg decision rate {avg_decision:.0f}% -- "
            f"too many items deferred; check attendance and preparation."
        )
    else:
        health = HealthLevel.CRITICAL
        interpretation = (
            f"Avg decision rate {avg_decision:.0f}% -- "
            f"meetings are not resolving issues; redesign the process."
        )

    if significant and correlation == "strong":
        interpretation += (
            f" Strong attendance-decision correlation: r={pearson_r:.2f}, "
            f"p={p_value:.4f}. {rate_full:.0f}% with full attendance "
            f"vs {rate_partial:.0f}% without."
        )
    elif not significant and n >= 5:
        interpretation += (
            f" Attendance-decision correlation not statistically significant "
            f"(r={pearson_r:.2f}, p={p_value:.3f}) -- insufficient evidence."
        )

    per_meeting = [
        {
            "meeting_date": m.meeting_date.isoformat(),
            "total_items": m.total_items,
            "decided_items": m.decided_items,
            "deferred_items": m.deferred_items,
            "decision_rate_pct": round(m.decision_rate * 100, 1),
            "attendance_rate_pct": round(m.attendance_rate * 100, 1),
        }
        for m in summaries
    ]

    return {
        "avg_decision_rate_pct": round(avg_decision, 1),
        "avg_attendance_rate_pct": round(avg_attendance, 1),
        "meetings_with_full_attendance": len(full_attendance),
        "decision_rate_full_attendance": round(rate_full, 1),
        "decision_rate_partial_attendance": round(rate_partial, 1),
        "pearson_r": round(pearson_r, 4),
        "p_value": round(p_value, 4),
        "confidence_interval": (round(ci[0], 4), round(ci[1], 4)),
        "significant": significant,
        "correlation_strength": correlation,
        "per_meeting": per_meeting,
        "health_level": health.value,
        "interpretation": interpretation,
    }


def meeting_to_score(result: dict) -> float:
    """Convert meeting decision result to a 0-100 health score.

    Args:
        result: Output from compute_attendance_decision_correlation().

    Returns:
        Score where 100 = all items decided, 0 = nothing decided.
    """
    return max(0.0, min(100.0, result.get("avg_decision_rate_pct", 50.0)))
