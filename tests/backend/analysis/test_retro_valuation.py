"""Tests for the Layer A accuracy metrics and error attribution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.analysis.retro.attribution import (
    HITTER_CATEGORIES,
    attribute,
    run_ablations,
    streaming_bonus_check,
)
from backend.analysis.retro.valuation import (
    bootstrap_delta_spearman_ci,
    decile_table,
    kendall_tau,
    ols,
    paired_series,
    pearson,
    ranked_ids,
    segment_bias,
    spearman,
    top_n_precision,
)

FIXTURE_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "backend" / "data" / "fixtures" / "retro_2026"
)


def board(values: dict[int, float], **extra) -> list[dict]:
    return [
        {"mlb_id": mlb_id, "full_name": f"P{mlb_id}", "total_zscore": value,
         "replacement_adj": 0.0, **extra}
        for mlb_id, value in values.items()
    ]


class TestCorrelations:
    def test_perfect_agreement_is_one(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert spearman(x, x) == pytest.approx(1.0)
        assert kendall_tau(x, x) == pytest.approx(1.0)

    def test_perfect_disagreement_is_minus_one(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert spearman(x, list(reversed(x))) == pytest.approx(-1.0)
        assert kendall_tau(x, list(reversed(x))) == pytest.approx(-1.0)

    def test_spearman_only_cares_about_order(self):
        x = [1.0, 2.0, 3.0, 4.0]
        stretched = [1.0, 10.0, 100.0, 1000.0]
        assert spearman(x, stretched) == pytest.approx(1.0)
        # Pearson, by contrast, is sensitive to the spacing.
        assert pearson(x, stretched) < 0.9

    def test_ties_are_handled_without_blowing_up(self):
        assert spearman([1.0, 1.0, 2.0], [1.0, 2.0, 3.0]) is not None
        assert kendall_tau([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) is None

    def test_degenerate_input_returns_none(self):
        assert spearman([1.0], [1.0]) is None
        assert pearson([1.0, 1.0], [1.0, 2.0]) is None


class TestTopNPrecision:
    def test_counts_overlap_in_the_top_slice(self):
        projected = [1, 2, 3, 4, 5]
        realized = [3, 2, 9, 8, 7]
        assert top_n_precision(projected, realized, 2) == pytest.approx(0.5)

    def test_none_when_the_boards_are_too_short(self):
        assert top_n_precision([1, 2], [1, 2], 5) is None


class TestOls:
    def test_recovers_a_known_slope(self):
        x = [1.0, 2.0, 3.0, 4.0]
        y = [2.5, 4.0, 5.5, 7.0]  # 1.5x + 1
        result = ols(x, y)
        assert result.slope == pytest.approx(1.5)
        assert result.intercept == pytest.approx(1.0)
        assert result.r_squared == pytest.approx(1.0)

    def test_slope_below_one_signals_over_dispersion(self):
        """Projections spread wider than reality — the shrinkage signal."""
        projected = [-3.0, -1.0, 1.0, 3.0]
        realized = [-1.5, -0.5, 0.5, 1.5]
        assert ols(projected, realized).slope == pytest.approx(0.5)


class TestDecileTable:
    def test_buckets_are_ordered_best_projected_first(self):
        projected = [float(i) for i in range(20)]
        realized = [float(i) for i in range(20)]
        table = decile_table(projected, realized, buckets=4)
        assert len(table) == 4
        means = [row["mean_projected"] for row in table]
        assert means == sorted(means, reverse=True)

    def test_returns_nothing_when_there_is_less_data_than_buckets(self):
        assert decile_table([1.0, 2.0], [1.0, 2.0], buckets=10) == []


class TestBootstrapDeltaCi:
    def test_identical_boards_give_an_interval_containing_zero(self):
        values = [float(i) for i in range(60)]
        lo, hi = bootstrap_delta_spearman_ci(values, values, values)
        assert lo == pytest.approx(0.0)
        assert hi == pytest.approx(0.0)

    def test_a_clearly_better_board_excludes_zero(self):
        realized = [float(i) for i in range(60)]
        good = list(realized)
        bad = list(reversed(realized))
        lo, hi = bootstrap_delta_spearman_ci(good, bad, realized)
        assert lo > 0

    def test_too_little_data_returns_no_interval(self):
        assert bootstrap_delta_spearman_ci([1.0], [1.0], [1.0]) == (None, None)


class TestPairing:
    def test_pairs_on_mlb_id_regardless_of_board_order(self):
        a = board({1: 5.0, 2: 3.0})
        b = board({2: 1.0, 1: 9.0})
        ids, projected, realized = paired_series(a, b)
        assert ids == [1, 2]
        assert projected == [5.0, 3.0]
        assert realized == [9.0, 1.0]

    def test_players_missing_from_either_board_are_excluded(self):
        ids, _, _ = paired_series(board({1: 1.0, 2: 2.0}), board({2: 2.0, 3: 3.0}))
        assert ids == [2]

    def test_ranked_ids_breaks_ties_deterministically(self):
        assert ranked_ids(board({7: 1.0, 3: 1.0, 5: 2.0})) == [5, 3, 7]


class TestAttribution:
    def test_category_deltas_sum_to_the_total_delta(self):
        projected = [{"mlb_id": 1, "full_name": "P", "total_zscore": 5.0,
                      "replacement_adj": -1.0, "zscore_r": 2.0, "zscore_tb": 2.0,
                      "zscore_rbi": 1.0, "zscore_sb": 0.5, "zscore_obp": 0.5}]
        realized = [{"mlb_id": 1, "full_name": "P", "total_zscore": 3.0,
                     "replacement_adj": -1.0, "zscore_r": 1.0, "zscore_tb": 1.5,
                     "zscore_rbi": 0.5, "zscore_sb": 0.5, "zscore_obp": 0.5}]
        result = attribute(projected, realized, HITTER_CATEGORIES)
        row = result["biggest_misses"][0]
        assert row["delta_total"] == pytest.approx(-2.0)
        assert sum(row["delta_by_category"].values()) == pytest.approx(-2.0)
        assert row["unexplained"] == pytest.approx(0.0)

    def test_adjustments_outside_the_categories_show_up_as_unexplained(self):
        """The streaming bonus moves total_zscore without touching a category."""
        projected = [{"mlb_id": 1, "full_name": "P", "total_zscore": 5.0,
                      "replacement_adj": 0.0, "zscore_r": 5.0}]
        realized = [{"mlb_id": 1, "full_name": "P", "total_zscore": 5.7,
                     "replacement_adj": 0.0, "zscore_r": 5.0}]
        result = attribute(projected, realized, ("zscore_r",))
        assert result["biggest_misses"][0]["unexplained"] == pytest.approx(0.7)

    def test_biggest_misses_and_beats_are_sorted_opposite_ways(self):
        projected = board({1: 5.0, 2: 5.0}, zscore_r=5.0)
        realized = board({1: 1.0, 2: 9.0}, zscore_r=1.0)
        result = attribute(projected, realized, ("zscore_r",))
        assert result["biggest_misses"][0]["mlb_id"] == 1
        assert result["biggest_beats"][0]["mlb_id"] == 2


class TestAblations:
    def test_a_variant_identical_to_the_baseline_is_flagged_as_noise(self):
        realized = board({i: float(i) for i in range(40)})
        baseline = board({i: float(i) for i in range(40)})
        results = run_ablations(baseline, realized, {"same": list(baseline)})
        variant = next(r for r in results if r["label"] == "same")
        assert variant["delta_spearman"] == pytest.approx(0.0)
        assert variant["inside_noise"] is True

    def test_a_clearly_worse_variant_is_not_flagged_as_noise(self):
        realized = board({i: float(i) for i in range(40)})
        baseline = board({i: float(i) for i in range(40)})
        shuffled = board({i: float((i * 17) % 40) for i in range(40)})
        results = run_ablations(baseline, realized, {"worse": shuffled})
        variant = next(r for r in results if r["label"] == "worse")
        assert variant["delta_spearman"] < 0
        assert variant["inside_noise"] is False

    def test_baseline_row_is_always_present_and_zeroed(self):
        realized = board({i: float(i) for i in range(40)})
        results = run_ablations(realized, realized, {})
        assert results[0]["label"] == "baseline"
        assert results[0]["delta_spearman"] == 0.0


class TestStreamingBonusCheck:
    def test_measures_the_realized_gap_between_qualifying_and_other_starters(self):
        projected = [
            {"mlb_id": 1, "total_zscore": 3.0, "proj_ip": 180, "proj_era": 3.2,
             "proj_whip": 1.10},
            {"mlb_id": 2, "total_zscore": 3.0, "proj_ip": 180, "proj_era": 4.5,
             "proj_whip": 1.35},
        ]
        realized = board({1: 5.0, 2: 1.0})
        result = streaming_bonus_check(projected, realized)
        assert result["qualifying"]["n"] == 1
        assert result["others"]["n"] == 1
        assert result["realized_edge"] == pytest.approx(4.0)


class TestSegmentBias:
    def test_reports_mean_error_per_segment(self):
        projected = board({1: 5.0, 2: 4.0}, primary_position="C")
        projected += board({3: 5.0}, primary_position="OF")
        realized = board({1: 3.0, 2: 2.0, 3: 5.0})
        segments = {s["segment"]: s for s in segment_bias(
            projected, realized, lambda r: r.get("primary_position"))}
        assert segments["C"]["mean_error"] == pytest.approx(-2.0)
        assert segments["OF"]["mean_error"] == pytest.approx(0.0)


class TestFrozenLayerAArtifacts:
    def _load(self, name):
        return json.loads((FIXTURE_DIR / name).read_text())

    def test_accuracy_artifact_reports_both_pools(self):
        accuracy = self._load("valuation_accuracy.json")
        for pool in ("hitters", "pitchers"):
            assert accuracy[pool]["n"] > 500
            assert -1.0 <= accuracy[pool]["spearman"] <= 1.0

    def test_calibration_is_computed_on_the_pace_adjusted_board(self):
        """Mid-season levels are only comparable after pace adjustment."""
        accuracy = self._load("valuation_accuracy.json")
        assert accuracy["expost_board"] == "pace_adjusted"
        # The uncorrected slope is kept for audit and must be the lower one.
        for pool in ("hitters", "pitchers"):
            uncorrected = accuracy["partial_season_uncorrected"][pool]["ols_slope"]
            assert uncorrected < accuracy[pool]["ols_slope"]

    def test_every_ablation_reports_a_paired_interval(self):
        ablations = self._load("ablations.json")
        for pool in ("hitters", "pitchers", "combined"):
            for result in ablations[pool]["results"]:
                if result["label"] == "baseline":
                    continue
                assert "delta_spearman_ci" in result
                assert result["inside_noise"] in (True, False)
