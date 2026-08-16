"""Tests for ADP residual calibration and keeper outcome evaluation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.analysis.retro.adp_model import (
    FILLER_ADP_THRESHOLD,
    compare_sigma_models,
    compute_residuals,
    count_kept_below,
    effective_adp,
    fit_linear_sigma,
    manager_bias,
    sigma_by_bucket,
    sigma_summary,
)
from backend.analysis.retro.keeper_eval import (
    compare_curve_to_assumption,
    evaluate_keepers,
    expected_value_at_round_assumed,
    keeper_accuracy,
    keeper_cost,
    value_at_pick_curve,
)

FIXTURE_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "backend" / "data" / "fixtures" / "retro_2026"
)


def pick(index, mlb_id, team_id=1, name=None, board=0.0, realized=0.0):
    return {"pick_index": index, "mlb_id": mlb_id, "team_id": team_id,
            "name": name or f"P{mlb_id}", "board_value": board,
            "realized_value": realized}


class TestKeeperAdjustment:
    def test_counts_keepers_at_or_above_a_players_adp(self):
        keepers = [5.0, 12.0, 30.0]
        assert count_kept_below(4.0, keepers) == 0
        assert count_kept_below(12.0, keepers) == 2
        assert count_kept_below(100.0, keepers) == 3

    def test_effective_adp_moves_players_earlier(self):
        """Keepers are off the board, so everyone below them gets picked sooner."""
        assert effective_adp(50.0, [5.0, 10.0, 20.0]) == 47.0

    def test_no_keepers_leaves_adp_untouched(self):
        assert effective_adp(50.0, []) == 50.0


class TestResiduals:
    def test_residual_is_pick_number_minus_effective_adp(self):
        residuals = compute_residuals(
            [pick(9, 100)], {100: 20.0}, keeper_adps=[5.0])
        [residual] = residuals
        assert residual.pick_number == 10
        assert residual.effective_adp == 19.0
        assert residual.residual == pytest.approx(-9.0)
        assert residual.raw_residual == pytest.approx(-10.0)

    def test_players_without_adp_are_skipped(self):
        assert compute_residuals([pick(0, 100)], {}, []) == []

    def test_espn_filler_adp_is_excluded(self):
        """ESPN pads its export with 259.9/260.0 for undrafted players; those
        are placeholders and would be pure noise in the calibration."""
        residuals = compute_residuals(
            [pick(0, 1), pick(1, 2)],
            {1: 30.0, 2: FILLER_ADP_THRESHOLD + 1}, [])
        assert [r.mlb_id for r in residuals] == [1]

    def test_filler_keepers_do_not_shift_the_adjustment(self):
        residuals = compute_residuals(
            [pick(9, 100)], {100: 20.0}, keeper_adps=[5.0, 260.0])
        assert residuals[0].effective_adp == 19.0


class TestSigmaSummary:
    def test_reports_both_raw_and_adjusted_spread(self):
        residuals = compute_residuals(
            [pick(i, i) for i in range(20)],
            {i: float(i + 1) for i in range(20)}, [])
        summary = sigma_summary(residuals)
        assert summary["n"] == 20
        # Every pick landed exactly at its ADP.
        assert summary["raw"]["mean"] == pytest.approx(0.0)
        assert summary["raw"]["sigma"] == pytest.approx(0.0)


class TestSigmaByBucket:
    def test_groups_by_adp_band(self):
        residuals = compute_residuals(
            [pick(i, i) for i in range(6)],
            {0: 10.0, 1: 20.0, 2: 60.0, 3: 70.0, 4: 120.0, 5: 130.0}, [])
        buckets = {b["adp_bucket"]: b for b in sigma_by_bucket(residuals)}
        assert buckets["0-50"]["n"] == 2
        assert buckets["50-100"]["n"] == 2
        assert buckets["100-150"]["n"] == 2

    def test_buckets_come_back_in_ascending_adp_order(self):
        residuals = compute_residuals(
            [pick(i, i) for i in range(4)],
            {0: 220.0, 1: 10.0, 2: 120.0, 3: 60.0}, [])
        labels = [b["adp_bucket"] for b in sigma_by_bucket(residuals)]
        assert labels == ["0-50", "50-100", "100-150", "200+"]


class TestSigmaModelComparison:
    def test_picks_the_model_closest_to_the_measured_spread(self):
        # Spread grows steeply with ADP: the variable models should win.
        buckets = [
            {"adp_bucket": "0-50", "n": 20, "mean_adp": 25.0, "sigma": 12.5},
            {"adp_bucket": "200+", "n": 20, "mean_adp": 240.0, "sigma": 34.0},
        ]
        result = compare_sigma_models(buckets)
        assert result["best"] == "variable_py"
        assert set(result["mean_abs_error"]) == {
            "flat_18", "variable_ts", "variable_py"}

    def test_flat_wins_when_spread_really_is_constant(self):
        buckets = [
            {"adp_bucket": "0-50", "n": 20, "mean_adp": 25.0, "sigma": 18.0},
            {"adp_bucket": "200+", "n": 20, "mean_adp": 240.0, "sigma": 18.0},
        ]
        assert compare_sigma_models(buckets)["best"] == "flat_18"

    def test_linear_fit_recovers_a_known_slope(self):
        buckets = [
            {"mean_adp": 0.0, "sigma": 10.0, "n": 10},
            {"mean_adp": 100.0, "sigma": 20.0, "n": 10},
            {"mean_adp": 200.0, "sigma": 30.0, "n": 10},
        ]
        fit = fit_linear_sigma(buckets)
        assert fit["slope"] == pytest.approx(0.1)
        assert fit["intercept"] == pytest.approx(10.0)

    def test_thin_buckets_are_ignored_in_the_fit(self):
        assert fit_linear_sigma([{"mean_adp": 0.0, "sigma": 1.0, "n": 1}]) is None


class TestManagerBias:
    def test_negative_mean_marks_a_reacher(self):
        residuals = compute_residuals(
            [pick(0, 1, team_id=7), pick(1, 2, team_id=7)],
            {1: 30.0, 2: 40.0}, [])
        [row] = manager_bias(residuals, {7: "Reacher"})
        assert row["manager"] == "Reacher"
        assert row["mean_residual"] < 0


class TestKeeperCost:
    def test_first_season_costs_the_draft_round(self):
        assert keeper_cost(8, keeper_season=1) == 8

    def test_each_extra_season_costs_five_rounds(self):
        assert keeper_cost(20, keeper_season=2) == 15
        assert keeper_cost(20, keeper_season=3) == 10

    def test_cost_never_goes_below_round_one(self):
        assert keeper_cost(3, keeper_season=3) == 1

    def test_undrafted_players_default_to_the_last_round(self):
        assert keeper_cost(None, keeper_season=1, max_rounds=25) == 25


class TestValueAtPickCurve:
    def test_groups_picks_into_rounds(self):
        picks = [pick(i, i, board=1.0, realized=0.5) for i in range(20)]
        curve = value_at_pick_curve(picks)
        assert [c["round"] for c in curve] == [1, 2]
        assert curve[0]["picks"] == 10
        assert curve[0]["mean_board_value"] == pytest.approx(1.0)

    def test_assumed_value_reads_the_board_at_rank_round_times_ten(self):
        board = [{"total_zscore": float(100 - i)} for i in range(100)]
        # Round 1 -> rank 10 -> index 9 -> 91.
        assert expected_value_at_round_assumed(1, board) == pytest.approx(91.0)

    def test_assumption_comparison_reports_the_gap(self):
        picks = [pick(i, i, board=2.0, realized=0.5) for i in range(10)]
        board = [{"total_zscore": 5.0} for _ in range(50)]
        [row] = compare_curve_to_assumption(value_at_pick_curve(picks), board)
        assert row["assumption_error_vs_board"] == pytest.approx(3.0)
        assert row["assumption_error_vs_realized"] == pytest.approx(4.5)


class TestKeeperEvaluation:
    def _curve(self):
        return [{"round": 1, "picks": 10, "mean_board_value": 4.0,
                 "mean_realized_value": 1.0}]

    def test_a_keeper_who_beat_the_round_shows_positive_surplus(self):
        outcomes = evaluate_keepers(
            [{"mlb_id": 1, "teamId": 3, "roundCost": 1, "playerName": "Star"}],
            board_value={1: 6.0}, realized_value={1: 5.0}, curve=self._curve())
        [outcome] = outcomes
        assert outcome["board_surplus"] == pytest.approx(2.0)
        assert outcome["realized_surplus"] == pytest.approx(4.0)
        assert outcome["verdict"] == "correct"

    def test_a_keeper_who_missed_is_flagged(self):
        outcomes = evaluate_keepers(
            [{"mlb_id": 1, "teamId": 3, "roundCost": 1, "playerName": "Bust"}],
            board_value={1: 6.0}, realized_value={1: -2.0}, curve=self._curve())
        assert outcomes[0]["verdict"] == "should have passed"

    def test_round_costs_beyond_the_curve_fall_back_to_the_last_round(self):
        outcomes = evaluate_keepers(
            [{"mlb_id": 1, "teamId": 3, "roundCost": 24, "playerName": "Late"}],
            board_value={1: 0.0}, realized_value={1: 0.0}, curve=self._curve())
        assert len(outcomes) == 1

    def test_accuracy_measures_sign_agreement(self):
        outcomes = [
            {"board_surplus": 1.0, "realized_surplus": 1.0},
            {"board_surplus": 1.0, "realized_surplus": -1.0},
        ]
        accuracy = keeper_accuracy(outcomes)
        assert accuracy["sign_agreement"] == pytest.approx(0.5)
        assert accuracy["kept_and_worth_it"] == 1


class TestFrozenLayerCArtifacts:
    def _load(self, name):
        return json.loads((FIXTURE_DIR / name).read_text())

    def test_keeper_adjustment_removes_most_of_the_adp_bias(self):
        """40 keepers off the board pull every other player earlier; the
        adjustment should absorb most of that shift."""
        summary = self._load("adp_calibration.json")["summary"]
        assert summary["raw"]["mean"] < -20
        assert abs(summary["keeper_adjusted"]["mean"]) < abs(summary["raw"]["mean"]) / 2

    def test_adp_uncertainty_grows_with_adp(self):
        """The finding that settles flat vs variable sigma."""
        buckets = self._load("adp_calibration.json")["by_adp_bucket"]
        early = next(b for b in buckets if b["adp_bucket"] == "0-50")
        late = next(b for b in buckets if b["adp_bucket"] == "150-200")
        assert late["sigma"] > 3 * early["sigma"]

    def test_the_boards_sigma_model_is_the_worst_of_the_three(self):
        comparison = self._load("adp_calibration.json")["sigma_model_comparison"]
        errors = comparison["mean_abs_error"]
        assert errors["variable_ts"] == max(errors.values())
        assert comparison["best"] == "variable_py"

    def test_every_keeper_is_evaluated(self):
        analysis = self._load("keeper_analysis.json")
        assert analysis["accuracy"]["n"] == 40
