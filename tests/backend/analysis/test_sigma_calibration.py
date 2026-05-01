"""Tests for category sigma calibration math."""

from __future__ import annotations

import math
import random
import pytest

from backend.analysis.sigma_calibration import (
    compute_category_sigma,
    CountStatObservation,
)


class TestComputeCategorySigma:
    def test_recovers_known_sigma_for_count_stat(self):
        """Generate synthetic data with a known σ; verify it's recovered within tolerance."""
        rng = random.Random(42)
        true_sigma = 5.0
        team_rate_per_day = {1: {"R": 10.0}, 2: {"R": 8.0}}
        observations = []
        for team_id in (1, 2):
            for period_id in range(1, 21):
                period_days = 7
                expected = team_rate_per_day[team_id]["R"] * period_days
                observed = expected + rng.gauss(0.0, true_sigma)
                observations.append(CountStatObservation(
                    team_id=team_id, period_id=period_id, period_days=period_days,
                    cat="R", observed=observed,
                ))

        result = compute_category_sigma(
            observations=observations,
            team_rates_per_day=team_rate_per_day,
            cat_keys=["R"],
            cat_kinds={"R": "count"},
        )

        # With 40 samples and N(0, 5) noise, sample stddev should be within ~25% of 5.0
        assert math.isclose(result["R"], true_sigma, rel_tol=0.25)

    def test_rate_stat_residual_is_observed_minus_rate(self):
        """For rate stats (OBP), residual is observed_rate - season_rate (no period_days scaling)."""
        rng = random.Random(7)
        true_sigma = 0.020
        team_rate_per_day = {1: {"OBP": 0.330}, 2: {"OBP": 0.300}}
        observations = []
        for team_id in (1, 2):
            for period_id in range(1, 21):
                expected = team_rate_per_day[team_id]["OBP"]
                observed = expected + rng.gauss(0.0, true_sigma)
                observations.append(CountStatObservation(
                    team_id=team_id, period_id=period_id, period_days=7,
                    cat="OBP", observed=observed,
                ))

        result = compute_category_sigma(
            observations=observations,
            team_rates_per_day=team_rate_per_day,
            cat_keys=["OBP"],
            cat_kinds={"OBP": "rate"},
        )
        assert math.isclose(result["OBP"], true_sigma, rel_tol=0.30)

    def test_returns_zero_for_cat_with_no_observations(self):
        result = compute_category_sigma(
            observations=[],
            team_rates_per_day={},
            cat_keys=["R", "TB"],
            cat_kinds={"R": "count", "TB": "count"},
        )
        assert result == {"R": 0.0, "TB": 0.0}

    def test_handles_multiple_cats_independently(self):
        """Different cats should produce different σ values when noise differs."""
        rng = random.Random(99)
        team_rates = {1: {"R": 10.0, "TB": 30.0}}
        observations = []
        for period_id in range(1, 41):
            observations.append(CountStatObservation(
                team_id=1, period_id=period_id, period_days=7, cat="R",
                observed=10.0 * 7 + rng.gauss(0.0, 5.0),
            ))
            observations.append(CountStatObservation(
                team_id=1, period_id=period_id, period_days=7, cat="TB",
                observed=30.0 * 7 + rng.gauss(0.0, 15.0),
            ))

        result = compute_category_sigma(
            observations=observations,
            team_rates_per_day=team_rates,
            cat_keys=["R", "TB"],
            cat_kinds={"R": "count", "TB": "count"},
        )
        # σ_TB should be ~3x σ_R (15 vs 5)
        assert result["TB"] / result["R"] > 2.0
        assert result["TB"] / result["R"] < 4.0
