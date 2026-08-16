"""Tests for measured H2H category weights.

Follows the sigma-calibration precedent: the fixture stores the raw team-week
observations alongside the computed output, and the test recomputes from raw
and asserts they still agree.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.analysis.category_weights import (
    INVERTED_CATEGORIES,
    calibrate_category_weights,
    correlation,
    correlation_matrix,
    independence_scores,
    orient,
    weights_from_independence,
)

FIXTURE = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "backend" / "data" / "fixtures" / "category_weights_2025.json"
)


class TestCorrelation:
    def test_perfect_relationships(self):
        assert correlation([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)
        assert correlation([1, 2, 3], [6, 4, 2]) == pytest.approx(-1.0)

    def test_constant_series_has_no_correlation(self):
        assert correlation([1, 1, 1], [1, 2, 3]) is None

    def test_mismatched_or_tiny_input(self):
        assert correlation([1, 2], [1]) is None
        assert correlation([1], [1]) is None


class TestOrientation:
    def test_inverted_categories_are_flipped(self):
        [flipped] = orient([{"R": 10.0, "ERA": 3.5, "WHIP": 1.1}])
        assert flipped["R"] == 10.0
        assert flipped["ERA"] == -3.5
        assert flipped["WHIP"] == -1.1

    def test_orientation_turns_a_good_pitching_week_into_positive_correlation(self):
        """QS up and ERA down is one good week, not two opposing signals."""
        raw = [
            {"QS": 5.0, "ERA": 2.5},
            {"QS": 4.0, "ERA": 3.0},
            {"QS": 1.0, "ERA": 5.0},
            {"QS": 0.0, "ERA": 6.5},
        ]
        cats = ["QS", "ERA"]
        raw_r = correlation_matrix(raw, cats)["QS"]["ERA"]
        oriented_r = correlation_matrix(orient(raw), cats)["QS"]["ERA"]
        assert raw_r < 0
        assert oriented_r > 0
        assert oriented_r == pytest.approx(-raw_r)

    def test_era_and_whip_are_the_inverted_pair(self):
        assert INVERTED_CATEGORIES == frozenset({"ERA", "WHIP"})


class TestIndependenceAndWeights:
    def test_an_uncorrelated_category_scores_as_fully_independent(self):
        matrix = {"A": {"A": 1.0, "B": 0.0}, "B": {"A": 0.0, "B": 1.0}}
        assert independence_scores(matrix, ["A", "B"]) == {"A": 1.0, "B": 1.0}

    def test_a_redundant_category_scores_lower(self):
        matrix = {
            "A": {"A": 1.0, "B": 0.9, "C": 0.0},
            "B": {"A": 0.9, "B": 1.0, "C": 0.0},
            "C": {"A": 0.0, "B": 0.0, "C": 1.0},
        }
        scores = independence_scores(matrix, ["A", "B", "C"])
        assert scores["C"] > scores["A"]

    def test_sign_of_correlation_does_not_change_independence(self):
        """A strong negative correlation is just as redundant as a positive one."""
        positive = {"A": {"A": 1.0, "B": 0.8}, "B": {"A": 0.8, "B": 1.0}}
        negative = {"A": {"A": 1.0, "B": -0.8}, "B": {"A": -0.8, "B": 1.0}}
        assert (independence_scores(positive, ["A", "B"])
                == independence_scores(negative, ["A", "B"]))

    def test_weights_average_to_one(self):
        scores = {"A": 0.8, "B": 0.9, "C": 1.0}
        weights = weights_from_independence(scores, ["A", "B", "C"], dampening=1.0)
        assert sum(weights.values()) / 3 == pytest.approx(1.0, abs=1e-6)

    def test_dampening_pulls_weights_toward_equal(self):
        scores = {"A": 0.5, "B": 1.5}
        undamped = weights_from_independence(scores, ["A", "B"], dampening=1.0)
        damped = weights_from_independence(scores, ["A", "B"], dampening=0.6)
        flat = weights_from_independence(scores, ["A", "B"], dampening=0.0)
        assert flat == {"A": 1.0, "B": 1.0}
        assert abs(damped["A"] - 1.0) < abs(undamped["A"] - 1.0)

    def test_more_independent_categories_get_larger_weights(self):
        observations = [
            {"R": r, "TB": r * 2 + 1, "SB": (r * 7) % 5}
            for r in range(1, 30)
        ]
        result = calibrate_category_weights(observations, ["R", "TB", "SB"])
        # R and TB are collinear by construction; SB is not.
        assert result["weights"]["SB"] > result["weights"]["R"]
        assert result["weights"]["SB"] > result["weights"]["TB"]


@pytest.fixture(scope="module")
def fixture():
    return json.loads(FIXTURE.read_text())


class TestFrozen2025Calibration:

    def test_fixture_shape(self, fixture):
        assert fixture["season"] == 2025
        assert fixture["n_observations"] > 100
        assert set(fixture["weights"]) == set(fixture["cat_keys"])

    def test_recomputing_from_raw_observations_reproduces_the_weights(self, fixture):
        recomputed = calibrate_category_weights(
            fixture["observations"], fixture["cat_keys"], fixture["dampening"])
        assert recomputed["weights"] == fixture["weights"]
        assert recomputed["independence_scores"] == fixture["independence_scores"]

    def test_measured_weights_stay_close_to_the_shipped_ones(self, fixture):
        """Large correlation errors wash out: the dampened, normalized weights
        barely move, which is why the category-weight ablation shows almost no
        effect on ranking accuracy."""
        for cat, measured in fixture["weights"].items():
            shipped = fixture["shipped_weights"][cat]
            assert abs(measured - shipped) < 0.10, (
                f"{cat}: measured {measured} vs shipped {shipped}"
            )

    def test_stolen_bases_and_saves_remain_the_most_independent(self, fixture):
        scores = fixture["independence_scores"]
        ranked = sorted(scores, key=lambda cat: -scores[cat])
        assert set(ranked[:2]) == {"SB", "SVHD"}
