"""Metric 3: First-Submission Approval Rate.

Tracks the percentage of submittals approved on the first submission
(revision 0) per discipline. A low first-time approval rate is a proxy
for poor coordination upstream — the discipline is submitting work that
hasn't been properly coordinated before review.

CII research shows that rework costs 5-15 % of total project value.
Catching poor approval rates early gives the project team time to
intervene before rejected submittals cascade into RFIs and site rework.

Usage:
    >>> from coordination_metrics import compute_approval_rates
    >>> rates = compute_approval_rates("submittal_register.csv")
    >>> print(rates[["discipline", "first_submission_approval_pct"]])
"""

from __future__ import annotations

from pathlib import Path
from typing import Union

import pandas as pd

from coordination_metrics.core import HealthLevel
from coordination_metrics.parsers.csv_register import read_register


def compute_approval_rates(
    register_path: Union[str, Path],
    *,
    approved_statuses: tuple[str, ...] = ("Approved", "Approved as Noted", "No Exception Taken"),
) -> pd.DataFrame:
    """Compute first-submission approval rate by discipline.

    Args:
        register_path: Path to a submittal register (CSV or Excel).
        approved_statuses: Status values that count as "approved".

    Returns:
        DataFrame with columns:
            discipline, total_submittals, first_submissions,
            first_submission_approved, first_submission_approval_pct,
            health_level
    """
    df = read_register(register_path)

    # Normalise column names
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")

    required = {"discipline", "revision", "status"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"Register is missing required columns: {missing}. "
            f"Found: {list(df.columns)}"
        )

    df["revision"] = pd.to_numeric(df["revision"], errors="coerce").fillna(0).astype(int)
    df["status"] = df["status"].str.strip()
    df["discipline"] = df["discipline"].str.strip()

    # First submissions only
    first_subs = df[df["revision"] == 0].copy()
    first_subs["is_approved"] = first_subs["status"].isin(approved_statuses)

    results = []
    for discipline, group in first_subs.groupby("discipline"):
        total = len(df[df["discipline"] == discipline])
        first_count = len(group)
        approved_count = int(group["is_approved"].sum())
        pct = (approved_count / first_count * 100) if first_count > 0 else 0.0

        if pct >= 75:
            health = HealthLevel.HEALTHY
        elif pct >= 50:
            health = HealthLevel.AT_RISK
        else:
            health = HealthLevel.CRITICAL

        results.append(
            {
                "discipline": discipline,
                "total_submittals": total,
                "first_submissions": first_count,
                "first_submission_approved": approved_count,
                "first_submission_approval_pct": round(pct, 1),
                "health_level": health.value,
            }
        )

    return pd.DataFrame(results)


def cross_reference_with_rfis(
    approval_rates: pd.DataFrame,
    rfi_path: Union[str, Path],
) -> pd.DataFrame:
    """Cross-reference approval rates with RFI counts per discipline.

    Disciplines with low approval rates AND high RFI counts are the
    highest-risk contributors to coordination failure.

    Args:
        approval_rates: Output from compute_approval_rates().
        rfi_path: Path to the RFI register (CSV or Excel).

    Returns:
        The approval_rates DataFrame enriched with rfi_count and risk_flag columns.
    """
    rfi_df = read_register(rfi_path)
    rfi_df.columns = rfi_df.columns.str.strip().str.lower().str.replace(" ", "_")

    if "discipline" not in rfi_df.columns:
        raise ValueError("RFI register must have a 'discipline' column.")

    rfi_df["discipline"] = rfi_df["discipline"].str.strip()
    rfi_counts = rfi_df.groupby("discipline").size().reset_index(name="rfi_count")

    merged = approval_rates.merge(rfi_counts, on="discipline", how="left")
    merged["rfi_count"] = merged["rfi_count"].fillna(0).astype(int)

    # Flag high-risk disciplines: low approval + high RFI
    median_rfis = merged["rfi_count"].median() if len(merged) > 0 else 0
    merged["risk_flag"] = (
        (merged["first_submission_approval_pct"] < 60) & (merged["rfi_count"] > median_rfis)
    )

    return merged


def approval_to_score(rates_df: pd.DataFrame) -> float:
    """Convert approval rates to a 0-100 health score.

    Uses the weighted average of first-submission approval rates across
    all disciplines (weighted by number of submittals).

    Args:
        rates_df: Output from compute_approval_rates().

    Returns:
        Score where 100 = all disciplines have 100% first-time approval.
    """
    if rates_df.empty:
        return 50.0
    total_first = rates_df["first_submissions"].sum()
    if total_first == 0:
        return 50.0
    weighted = (
        rates_df["first_submission_approval_pct"] * rates_df["first_submissions"]
    ).sum() / total_first
    return max(0.0, min(100.0, weighted))
