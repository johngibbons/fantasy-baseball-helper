"""Tests for empirical Bayes shrinkage math."""

from __future__ import annotations

import math
import pytest

from backend.analysis.shrinkage import compute_shrinkage_weight


class TestComputeShrinkageWeight:
    def test_zero_periods_gives_zero_weight(self):
        assert compute_shrinkage_weight(W=0, sigma_within=10.0, sigma_between=5.0) == 0.0

    def test_zero_between_sigma_gives_zero_weight(self):
        assert compute_shrinkage_weight(W=10, sigma_within=10.0, sigma_between=0.0) == 0.0

    def test_negative_periods_treated_as_zero(self):
        assert compute_shrinkage_weight(W=-1, sigma_within=10.0, sigma_between=5.0) == 0.0

    def test_known_midrange_value(self):
        # σ_w=10, σ_b=5, W=4 → (25 * 4) / (25 * 4 + 100) = 100/200 = 0.5
        assert compute_shrinkage_weight(W=4, sigma_within=10.0, sigma_between=5.0) == pytest.approx(0.5)

    def test_large_W_approaches_one(self):
        w = compute_shrinkage_weight(W=10_000, sigma_within=10.0, sigma_between=5.0)
        assert w > 0.99

    def test_small_between_relative_to_within_gives_small_weight(self):
        # σ_b much smaller than σ_w → prior dominates even with many periods
        w = compute_shrinkage_weight(W=5, sigma_within=10.0, sigma_between=0.5)
        # (0.25 * 5) / (0.25 * 5 + 100) = 1.25 / 101.25 ≈ 0.0123
        assert w == pytest.approx(1.25 / 101.25, rel=1e-6)


from backend.analysis.shrinkage import (
    ObservedPeriod,
    compute_observed_typical_period_count,
    compute_observed_period_rate,
)


def _obs(period_id: int, days: int, **cats) -> ObservedPeriod:
    return ObservedPeriod(matchup_period_id=period_id, period_days=days, cats=dict(cats))


class TestComputeObservedTypicalPeriodCount:
    def test_seven_day_periods_average_normalizes_to_typical_period(self):
        observations = [
            _obs(1, 7, R=70.0),
            _obs(2, 7, R=84.0),
        ]
        # total=154 over 14 days → 11/day → 77 per typical 7-day period
        mean, n = compute_observed_typical_period_count(observations, "R")
        assert mean == pytest.approx(77.0)
        assert n == 2

    def test_mixed_period_lengths_are_normalized(self):
        # 7-day period: 56 R = 8/day; 14-day period: 154 R = 11/day
        # combined per-day: (56+154)/(7+14) = 210/21 = 10/day → 70 per typical week
        observations = [
            _obs(1, 7, R=56.0),
            _obs(2, 14, R=154.0),
        ]
        mean, n = compute_observed_typical_period_count(observations, "R")
        assert mean == pytest.approx(70.0)
        assert n == 2

    def test_missing_cat_in_some_periods_reduces_n(self):
        # Period 1 has R, period 2 doesn't
        observations = [
            _obs(1, 7, R=70.0),
            _obs(2, 7, TB=200.0),  # no R
        ]
        mean, n = compute_observed_typical_period_count(observations, "R")
        assert mean == pytest.approx(70.0)  # only period 1 counted
        assert n == 1

    def test_no_observations_returns_zero(self):
        mean, n = compute_observed_typical_period_count([], "R")
        assert mean == 0.0
        assert n == 0


class TestComputeObservedPeriodRate:
    def test_unweighted_mean_across_periods(self):
        # ERA values: 3.00, 4.00, 5.00 → avg 4.00
        observations = [
            _obs(1, 7, ERA=3.00),
            _obs(2, 7, ERA=4.00),
            _obs(3, 7, ERA=5.00),
        ]
        mean, n = compute_observed_period_rate(observations, "ERA")
        assert mean == pytest.approx(4.00)
        assert n == 3

    def test_period_length_does_not_affect_rate_mean(self):
        # Rates are not scaled by days
        observations = [
            _obs(1, 7, OBP=0.300),
            _obs(2, 14, OBP=0.400),
        ]
        mean, n = compute_observed_period_rate(observations, "OBP")
        assert mean == pytest.approx(0.350)
        assert n == 2

    def test_no_observations_returns_zero(self):
        mean, n = compute_observed_period_rate([], "OBP")
        assert mean == 0.0
        assert n == 0
