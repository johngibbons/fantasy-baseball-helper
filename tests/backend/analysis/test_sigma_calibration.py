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


import json
from pathlib import Path

from backend.scripts.calibrate_category_sigma import (
    CAT_KEYS,
    CAT_KINDS,
    compute_team_rates_per_day,
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
        assert "records" in fixture
        assert set(fixture["computed_sigma"].keys()) == set(CAT_KEYS)
        assert len(fixture["records"]) > 100  # ~190 expected after filtering

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
