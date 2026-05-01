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


from backend.analysis.shrinkage import apply_shrinkage_to_period


SIGMA_WITHIN = {"R": 5.0, "TB": 15.0, "ERA": 1.0, "OBP": 0.025}
SIGMA_BETWEEN = {"R": 5.0, "TB": 15.0, "ERA": 1.0, "OBP": 0.025}
CAT_KINDS = {"R": "count", "TB": "count", "ERA": "rate", "OBP": "rate"}


class TestApplyShrinkageToPeriod:
    def test_zero_history_returns_projection_unchanged(self):
        projected = {"R": 70.0, "TB": 200.0, "ERA": 3.50, "OBP": 0.330}
        out, weights = apply_shrinkage_to_period(
            projected_period_cats=projected,
            observations=[],
            current_period_days=7,
            sigma_within=SIGMA_WITHIN,
            sigma_between=SIGMA_BETWEEN,
            cat_kinds=CAT_KINDS,
        )
        assert out == projected
        for cat in projected:
            assert weights[cat] == 0.0

    def test_count_stat_shrinks_toward_observed(self):
        # σ_w = σ_b = 5, W = 1 → w = 25 / (25 + 25) = 0.5
        # observed mean per typical period = 100 (well above projected 70)
        observations = [
            _obs(1, 7, R=100.0),
        ]
        out, weights = apply_shrinkage_to_period(
            projected_period_cats={"R": 70.0},
            observations=observations,
            current_period_days=7,
            sigma_within={"R": 5.0},
            sigma_between={"R": 5.0},
            cat_kinds={"R": "count"},
        )
        # shrunk_typical = 0.5 * 100 + 0.5 * 70 = 85; period_days=7 so output = 85
        assert out["R"] == pytest.approx(85.0)
        assert weights["R"] == pytest.approx(0.5)

    def test_count_stat_period_days_rescaling_for_long_periods(self):
        # 14-day period: projected = 140, observed = 100/typical. With w=0.5:
        # shrunk_typical = 0.5*100 + 0.5*(140 / 14 * 7) = 0.5*100 + 0.5*70 = 85
        # back to 14-day period: 85 / 7 * 14 = 170
        observations = [_obs(1, 7, R=100.0)]
        out, _ = apply_shrinkage_to_period(
            projected_period_cats={"R": 140.0},
            observations=observations,
            current_period_days=14,
            sigma_within={"R": 5.0},
            sigma_between={"R": 5.0},
            cat_kinds={"R": "count"},
        )
        assert out["R"] == pytest.approx(170.0)

    def test_rate_stat_shrinks_directly(self):
        # σ_w = σ_b = 1.0, W=1 → w = 0.5; obs ERA = 4.50, projected = 3.50 → shrunk = 4.00
        observations = [_obs(1, 7, ERA=4.50)]
        out, weights = apply_shrinkage_to_period(
            projected_period_cats={"ERA": 3.50},
            observations=observations,
            current_period_days=7,
            sigma_within={"ERA": 1.0},
            sigma_between={"ERA": 1.0},
            cat_kinds={"ERA": "rate"},
        )
        assert out["ERA"] == pytest.approx(4.00)
        assert weights["ERA"] == pytest.approx(0.5)

    def test_missing_cat_in_history_falls_back_to_projection(self):
        # Two periods of TB but no R — R shrinkage uses W=0
        observations = [_obs(1, 7, TB=200.0), _obs(2, 7, TB=210.0)]
        out, weights = apply_shrinkage_to_period(
            projected_period_cats={"R": 70.0, "TB": 250.0},
            observations=observations,
            current_period_days=7,
            sigma_within={"R": 5.0, "TB": 15.0},
            sigma_between={"R": 5.0, "TB": 15.0},
            cat_kinds={"R": "count", "TB": "count"},
        )
        # R: no observations → projection unchanged
        assert out["R"] == pytest.approx(70.0)
        assert weights["R"] == 0.0
        # TB: 2 obs, w = (225*2)/(225*2 + 225) = 450/675 = 2/3
        # observed_typical = 410/14*7 = 205; shrunk = 2/3*205 + 1/3*250 = 220
        assert out["TB"] == pytest.approx(220.0)
        assert weights["TB"] == pytest.approx(2.0/3.0)

    def test_zero_between_sigma_for_one_cat_skips_shrinkage(self):
        observations = [_obs(1, 7, R=100.0)]
        out, weights = apply_shrinkage_to_period(
            projected_period_cats={"R": 70.0},
            observations=observations,
            current_period_days=7,
            sigma_within={"R": 5.0},
            sigma_between={"R": 0.0},  # calibration empty
            cat_kinds={"R": "count"},
        )
        assert out["R"] == pytest.approx(70.0)
        assert weights["R"] == 0.0
