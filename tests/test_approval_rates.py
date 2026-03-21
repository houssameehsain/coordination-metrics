"""Tests for Metric 3: First-Submission Approval Rate."""

from pathlib import Path

import pandas as pd
import pytest

from coordination_metrics.approval_rates import (
    approval_to_score,
    compute_approval_rates,
    cross_reference_with_rfis,
)


class TestComputeApprovalRates:
    """Tests for compute_approval_rates()."""

    def test_with_sample_data(self, submittal_register: Path):
        rates = compute_approval_rates(submittal_register)
        assert isinstance(rates, pd.DataFrame)
        assert len(rates) == 5  # 5 disciplines
        assert "discipline" in rates.columns
        assert "first_submission_approval_pct" in rates.columns

    def test_all_disciplines_present(self, submittal_register: Path):
        rates = compute_approval_rates(submittal_register)
        disciplines = set(rates["discipline"])
        expected = {"Structural", "Mechanical", "Electrical", "Hydraulic", "Architecture"}
        assert disciplines == expected

    def test_rates_between_0_and_100(self, submittal_register: Path):
        rates = compute_approval_rates(submittal_register)
        for _, row in rates.iterrows():
            assert 0 <= row["first_submission_approval_pct"] <= 100

    def test_structural_high_approval(self, submittal_register: Path):
        """Structural has many Approved in the sample data."""
        rates = compute_approval_rates(submittal_register)
        struct = rates[rates["discipline"] == "Structural"]
        assert struct.iloc[0]["first_submission_approval_pct"] >= 70

    def test_empty_register(self, empty_csv: Path):
        rates = compute_approval_rates(empty_csv)
        assert rates.empty

    def test_health_levels_assigned(self, submittal_register: Path):
        rates = compute_approval_rates(submittal_register)
        assert all(
            row["health_level"] in ("healthy", "at_risk", "critical")
            for _, row in rates.iterrows()
        )


class TestCrossReferenceWithRfis:
    """Tests for cross_reference_with_rfis()."""

    def test_adds_rfi_count(self, submittal_register: Path, rfi_register: Path):
        rates = compute_approval_rates(submittal_register)
        merged = cross_reference_with_rfis(rates, rfi_register)
        assert "rfi_count" in merged.columns
        assert all(merged["rfi_count"] >= 0)

    def test_adds_risk_flag(self, submittal_register: Path, rfi_register: Path):
        rates = compute_approval_rates(submittal_register)
        merged = cross_reference_with_rfis(rates, rfi_register)
        assert "risk_flag" in merged.columns
        assert merged["risk_flag"].dtype == bool


class TestApprovalToScore:
    """Tests for approval_to_score()."""

    def test_with_sample_data(self, submittal_register: Path):
        rates = compute_approval_rates(submittal_register)
        score = approval_to_score(rates)
        assert 0 <= score <= 100

    def test_empty_dataframe(self):
        empty = pd.DataFrame(columns=["first_submission_approval_pct", "first_submissions"])
        assert approval_to_score(empty) == 50.0
