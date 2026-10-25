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


class TestComputeBetweenTeamSigma:
    def test_count_stat_uses_per_typical_period_units(self):
        # Three teams with per-day R rates of 9, 10, 11.
        # In typical 7-day periods: 63, 70, 77.
        # Sample stddev of (63, 70, 77) — Python sample variance = 49 → σ = 7.0
        team_rates = {
            1: {"R": 9.0},
            2: {"R": 10.0},
            3: {"R": 11.0},
        }
        from backend.analysis.sigma_calibration import compute_between_team_sigma
        result = compute_between_team_sigma(
            team_rates_per_day=team_rates,
            cat_keys=["R"],
            cat_kinds={"R": "count"},
        )
        assert result["R"] == pytest.approx(7.0, rel=1e-6)

    def test_rate_stat_uses_season_rate_directly(self):
        team_rates = {
            1: {"OBP": 0.300},
            2: {"OBP": 0.330},
            3: {"OBP": 0.360},
        }
        from backend.analysis.sigma_calibration import compute_between_team_sigma
        result = compute_between_team_sigma(
            team_rates_per_day=team_rates,
            cat_keys=["OBP"],
            cat_kinds={"OBP": "rate"},
        )
        # Sample stddev of (0.300, 0.330, 0.360) = 0.030
        assert result["OBP"] == pytest.approx(0.030, rel=1e-6)

    def test_single_team_returns_zero(self):
        from backend.analysis.sigma_calibration import compute_between_team_sigma
        result = compute_between_team_sigma(
            team_rates_per_day={1: {"R": 10.0}},
            cat_keys=["R"],
            cat_kinds={"R": "count"},
        )
        assert result["R"] == 0.0

    def test_handles_multiple_cats(self):
        team_rates = {
            1: {"R": 9.0, "OBP": 0.300},
            2: {"R": 11.0, "OBP": 0.360},
        }
        from backend.analysis.sigma_calibration import compute_between_team_sigma
        result = compute_between_team_sigma(
            team_rates_per_day=team_rates,
            cat_keys=["R", "OBP"],
            cat_kinds={"R": "count", "OBP": "rate"},
        )
        # R: 63, 77 → sample stddev of (63, 77): mean=70, var = (49+49)/(2-1) = 98, σ = sqrt(98) ≈ 9.899
        assert result["R"] == pytest.approx(math.sqrt(98.0), rel=1e-6)
        # OBP: sample stddev of (0.300, 0.360) = sqrt((0.0009+0.0009)/1) = sqrt(0.0018) ≈ 0.04243
        assert result["OBP"] == pytest.approx(math.sqrt(0.0018), rel=1e-6)


class TestPoolVariance:
    def test_equal_sizes_average_the_variances(self):
        from backend.analysis.sigma_calibration import pool_variance
        result = pool_variance([({"R": 9.0}, 10), ({"R": 16.0}, 10)])
        assert result["R"] == pytest.approx(12.5, rel=1e-9)

    def test_weights_by_degrees_of_freedom(self):
        from backend.analysis.sigma_calibration import pool_variance
        result = pool_variance([({"R": 9.0}, 3), ({"R": 36.0}, 5)])
        # (2 * 9 + 4 * 36) / 6 = 27
        assert result["R"] == pytest.approx(27.0, rel=1e-9)

    def test_matches_variance_of_seasons_centred_on_themselves(self):
        """Pooling equals the variance of the raw samples, each season de-meaned."""
        from backend.analysis.sigma_calibration import pool_variance
        rng = random.Random(3)
        seasons = [[rng.gauss(mu, 2.0) for _ in range(10)] for mu in (50.0, 58.0)]

        def var(xs):
            m = sum(xs) / len(xs)
            return sum((x - m) ** 2 for x in xs) / (len(xs) - 1)

        pooled = pool_variance([({"R": var(xs)}, len(xs)) for xs in seasons])
        squares = sum((x - sum(xs) / len(xs)) ** 2 for xs in seasons for x in xs)
        dof = sum(len(xs) - 1 for xs in seasons)
        assert pooled["R"] == pytest.approx(squares / dof, rel=1e-9)

    def test_negative_estimates_pool_before_truncation(self):
        from backend.analysis.sigma_calibration import pool_variance
        result = pool_variance([({"ERA": -0.03}, 10), ({"ERA": 0.02}, 10)])
        assert result["ERA"] == pytest.approx(-0.005, rel=1e-9)


def _season(rng, n_teams, n_periods, true_sd, noise_sd, mean=50.0):
    """Synthetic league: each team's true weekly mean plus independent weekly noise."""
    truth = {t: rng.gauss(mean, true_sd) for t in range(n_teams)}
    periods = {t: [(pid, 7, truth[t] + rng.gauss(0.0, noise_sd))
                   for pid in range(1, n_periods + 1)] for t in truth}
    return periods


class TestTrueBetweenTeamVariance:
    def test_subtracts_mean_noise_of_a_season_average(self):
        from backend.analysis.sigma_calibration import true_between_team_variance
        result = true_between_team_variance(
            between_sigma={"R": 3.0}, within_sigma={"R": 6.0},
            periods_per_team=[18, 18, 9],
        )
        # noise = mean(36/18, 36/18, 36/9) = 8/3; 9 - 8/3
        assert result["R"] == pytest.approx(9.0 - 8.0 / 3.0, rel=1e-9)

    def test_goes_negative_when_spread_is_all_noise(self):
        from backend.analysis.sigma_calibration import true_between_team_variance
        result = true_between_team_variance(
            between_sigma={"ERA": 0.2}, within_sigma={"ERA": 1.2},
            periods_per_team=[19] * 10,
        )
        assert result["ERA"] < 0

    def test_recovers_true_spread_that_observed_spread_overstates(self):
        from backend.analysis.sigma_calibration import (
            compute_between_team_sigma, compute_category_sigma, true_between_team_variance,
        )
        rng = random.Random(11)
        periods = _season(rng, n_teams=400, n_periods=19, true_sd=2.0, noise_sd=6.0)
        rates = {t: {"R": sum(v for _, _, v in ps) / (7 * len(ps))} for t, ps in periods.items()}
        observations = [CountStatObservation(team_id=t, period_id=pid, period_days=d,
                                             cat="R", observed=v)
                        for t, ps in periods.items() for pid, d, v in ps]
        between = compute_between_team_sigma(rates, ["R"], {"R": "count"})
        within = compute_category_sigma(observations, rates, ["R"], {"R": "count"})
        corrected = true_between_team_variance(between, within, [19] * 400)
        # Observed variance is about 4 + 36/19 = 5.9; the truth is 4.
        assert between["R"] ** 2 == pytest.approx(4.0 + 36.0 / 19.0, rel=0.15)
        assert corrected["R"] == pytest.approx(4.0, rel=0.15)


class TestSplitHalfBetweenVariance:
    def test_covariance_of_odd_and_even_averages(self):
        from backend.analysis.sigma_calibration import split_half_between_variance
        periods = {
            1: [(1, 7, 7.0), (2, 7, 21.0)],   # odd 7, even 21
            2: [(1, 7, 21.0), (2, 7, 35.0)],  # odd 21, even 35
        }
        # cov((7, 21), (21, 35)) = 98
        assert split_half_between_variance(periods, "count") == pytest.approx(98.0)

    def test_rate_stats_average_without_period_scaling(self):
        from backend.analysis.sigma_calibration import split_half_between_variance
        periods = {
            1: [(1, 5, 3.0), (2, 9, 5.0)],
            2: [(1, 5, 4.0), (2, 9, 7.0)],
        }
        # odd (3, 4), even (5, 7): cov = (−0.5)(−1) + (0.5)(1) = 1.0
        assert split_half_between_variance(periods, "rate") == pytest.approx(1.0)

    def test_pure_noise_has_no_persistent_spread(self):
        from backend.analysis.sigma_calibration import split_half_between_variance
        rng = random.Random(5)
        periods = _season(rng, n_teams=400, n_periods=19, true_sd=0.0, noise_sd=6.0)
        # Observed variance of a season average would be ~36/19 = 1.9
        assert abs(split_half_between_variance(periods, "rate")) < 0.4

    def test_recovers_true_spread(self):
        from backend.analysis.sigma_calibration import split_half_between_variance
        rng = random.Random(8)
        periods = _season(rng, n_teams=400, n_periods=19, true_sd=2.0, noise_sd=6.0)
        assert split_half_between_variance(periods, "rate") == pytest.approx(4.0, rel=0.2)


import json
from pathlib import Path

from backend.scripts.calibrate_category_sigma import (
    CAT_KEYS,
    CAT_KINDS,
    FIXTURES_DIR,
    compute_team_rates_per_day,
    load_fixture,
    pooled_between_sigma,
    pooled_between_variance,
    pooled_split_half_variance,
    records_to_observations,
)
from backend.data.espn_history import MatchupRecord


FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "backend" / "data" / "fixtures" / "sigma_calibration_2025.json"
)


class TestCalibrationFixtureRegression:
    """Pin the 2025 σ calibration to the committed fixture data."""

    def _load_fixture(self) -> dict:
        with FIXTURE_PATH.open() as f:
            return json.load(f)

    def test_fixture_exists_and_has_expected_shape(self):
        fixture = self._load_fixture()
        assert "computed_sigma" in fixture
        assert "computed_between_sigma" in fixture
        assert "records" in fixture
        assert set(fixture["computed_sigma"].keys()) == set(CAT_KEYS)
        assert set(fixture["computed_between_sigma"].keys()) == set(CAT_KEYS)
        assert len(fixture["records"]) > 100

    def test_recomputing_sigma_from_fixture_records_matches_stored_sigma(self):
        """Math regression: reconstructing σ from fixture records should reproduce the stored values."""
        fixture = self._load_fixture()
        records = [
            MatchupRecord(
                team_id=r["team_id"],
                matchup_period_id=r["matchup_period_id"],
                period_days=r["period_days"],
                cats=r["cats"],
            )
            for r in fixture["records"]
        ]
        rates = compute_team_rates_per_day(records)
        observations = records_to_observations(records)

        from backend.analysis.sigma_calibration import compute_category_sigma
        recomputed = compute_category_sigma(
            observations=observations,
            team_rates_per_day=rates,
            cat_keys=CAT_KEYS,
            cat_kinds=CAT_KINDS,
        )

        for cat in CAT_KEYS:
            stored = fixture["computed_sigma"][cat]
            assert recomputed[cat] == pytest.approx(stored, rel=1e-6), (
                f"Drift in σ_{cat}: stored={stored}, recomputed={recomputed[cat]}"
            )

    def test_matchup_constants_match_fixture(self):
        """The CATEGORY_SIGMA constants in matchup.py should match the fixture."""
        from backend.analysis.matchup import CATEGORY_SIGMA
        fixture = self._load_fixture()
        for cat in CAT_KEYS:
            assert CATEGORY_SIGMA[cat] == pytest.approx(
                fixture["computed_sigma"][cat], rel=1e-3
            ), (
                f"matchup.py CATEGORY_SIGMA['{cat}'] = {CATEGORY_SIGMA[cat]} "
                f"but fixture has {fixture['computed_sigma'][cat]}. "
                f"Re-run backend/scripts/calibrate_category_sigma.py and update."
            )

    def test_recomputing_between_sigma_from_fixture_records_matches_stored(self):
        fixture = self._load_fixture()
        records = [
            MatchupRecord(
                team_id=r["team_id"],
                matchup_period_id=r["matchup_period_id"],
                period_days=r["period_days"],
                cats=r["cats"],
            )
            for r in fixture["records"]
        ]
        rates = compute_team_rates_per_day(records)
        from backend.analysis.sigma_calibration import compute_between_team_sigma
        recomputed = compute_between_team_sigma(
            team_rates_per_day=rates,
            cat_keys=CAT_KEYS,
            cat_kinds=CAT_KINDS,
        )
        for cat in CAT_KEYS:
            stored = fixture["computed_between_sigma"][cat]
            assert recomputed[cat] == pytest.approx(stored, rel=1e-6), (
                f"Drift in σ_between_{cat}: stored={stored}, recomputed={recomputed[cat]}"
            )



POOLED_SEASONS = [2025, 2026]


@pytest.mark.parametrize("season", POOLED_SEASONS)
def test_between_sigma_recomputes_from_each_pooled_fixture(season):
    """Every season that feeds the pooled constants reproduces from its records."""
    with (FIXTURES_DIR / f"sigma_calibration_{season}.json").open() as f:
        fixture = json.load(f)
    records = [
        MatchupRecord(
            team_id=r["team_id"],
            matchup_period_id=r["matchup_period_id"],
            period_days=r["period_days"],
            cats=r["cats"],
        )
        for r in fixture["records"]
    ]
    from backend.analysis.sigma_calibration import compute_between_team_sigma
    recomputed = compute_between_team_sigma(
        team_rates_per_day=compute_team_rates_per_day(records),
        cat_keys=CAT_KEYS,
        cat_kinds=CAT_KINDS,
    )
    for cat in CAT_KEYS:
        assert recomputed[cat] == pytest.approx(
            fixture["computed_between_sigma"][cat], rel=1e-6)


def test_matchup_between_sigma_constants_are_the_pooled_seasons():
    from backend.analysis.matchup import CATEGORY_BETWEEN_SIGMA
    pooled = pooled_between_sigma(POOLED_SEASONS)
    for cat in CAT_KEYS:
        assert CATEGORY_BETWEEN_SIGMA[cat] == pytest.approx(pooled[cat], rel=1e-4), (
            f"matchup.py CATEGORY_BETWEEN_SIGMA['{cat}'] = {CATEGORY_BETWEEN_SIGMA[cat]} "
            f"but pooling {POOLED_SEASONS} gives {pooled[cat]}. Re-run "
            f"calibrate_category_sigma --pool-seasons and update."
        )


def test_noise_correction_agrees_with_the_odd_even_split():
    """The two estimates of true spread, one from a noise model and one without,
    agree on the committed seasons; in ERA and WHIP both find little or none."""
    corrected = pooled_between_variance(POOLED_SEASONS)
    split_half = pooled_split_half_variance(POOLED_SEASONS)
    observed = {
        cat: sum(load_fixture(season)["computed_between_sigma"][cat] ** 2
                 for season in POOLED_SEASONS) / len(POOLED_SEASONS)
        for cat in CAT_KEYS
    }
    for cat in CAT_KEYS:
        if cat in ("ERA", "WHIP"):
            assert corrected[cat] < 0, cat
            # Under a fifth of the observed variance persists from odd weeks to even.
            assert split_half[cat] < 0.2 * observed[cat], cat
            continue
        assert math.sqrt(corrected[cat]) == pytest.approx(
            math.sqrt(split_half[cat]), rel=0.10), cat
