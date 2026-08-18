"""Phase 3 keeper backtest statistics."""

from __future__ import annotations

from backend.analysis.history.keeper_backtest import (
    aggregate_accuracy,
    bootstrap_mean_ci,
    bootstrap_proportion_ci,
    by_baseline_thickness,
    by_seasons_kept,
    pick_index_for_round,
    surplus_vs_round_cost,
)
from backend.analysis.retro.keeper_eval import value_at_pick_curve


def outcome(surplus: float, cost: int = 10, seasons: int | None = 1,
            prior: float | None = None, baseline: int | None = 10) -> dict:
    return {
        "realized_surplus": surplus,
        "round_cost": cost,
        "seasons_kept": seasons,
        "prior_surplus": prior,
        "baseline_picks": baseline,
    }


class TestPickIndex:
    def test_round_survives_the_round_trip_through_the_curve(self):
        """The synthetic index must bucket back into the sheet's own round.

        Rounds are not reliably ten picks wide once traded and supplemental
        picks exist, so a running pick count would smear round boundaries.
        """
        picks = [
            {"pick_index": pick_index_for_round(r), "board_value": 0.0,
             "realized_value": float(r)}
            for r in (1, 1, 2, 25)
        ]
        curve = value_at_pick_curve(picks)

        assert [c["round"] for c in curve] == [1, 2, 25]
        assert [c["picks"] for c in curve] == [2, 1, 1]

    def test_missing_round_yields_no_index(self):
        assert pick_index_for_round(None) is None
        assert pick_index_for_round(0) is None


class TestBootstraps:
    def test_mean_ci_brackets_the_mean(self):
        values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
        lo, hi = bootstrap_mean_ci(values)
        assert lo is not None and lo < 4.5 < hi

    def test_ci_is_none_for_a_sample_too_small_to_support_one(self):
        assert bootstrap_mean_ci([1.0, 2.0]) == (None, None)
        assert bootstrap_proportion_ci(1, 3) == (None, None)

    def test_proportion_ci_narrows_as_n_grows(self):
        small_lo, small_hi = bootstrap_proportion_ci(28, 40)     # the 2026 n
        large_lo, large_hi = bootstrap_proportion_ci(256, 357)   # every season
        assert (large_hi - large_lo) < (small_hi - small_lo)


class TestSurplusVsRoundCost:
    def test_flat_relationship_is_reported_flat(self):
        outcomes = [outcome(1.0 if i % 2 else -1.0, cost=(i % 25) + 1)
                    for i in range(200)]
        result = surplus_vs_round_cost(outcomes)

        assert result["flat"] is True
        assert result["slope_ci"][0] <= 0 <= result["slope_ci"][1]

    def test_real_slope_is_not_reported_flat(self):
        outcomes = [outcome(0.5 * ((i % 25) + 1), cost=(i % 25) + 1)
                    for i in range(200)]
        result = surplus_vs_round_cost(outcomes)

        assert result["flat"] is False
        assert result["slope"] > 0.4

    def test_too_few_decisions_to_fit(self):
        assert surplus_vs_round_cost([outcome(1.0)])["n"] == 1


class TestGrouping:
    def test_by_seasons_kept_splits_and_counts(self):
        outcomes = ([outcome(2.0, cost=20, seasons=1)] * 10
                    + [outcome(-1.0, cost=15, seasons=2)] * 6)
        rows = by_seasons_kept(outcomes)

        assert [r["seasons_kept"] for r in rows] == [1, 2]
        assert rows[0]["n"] == 10 and rows[0]["beat_rate"] == 1.0
        assert rows[1]["n"] == 6 and rows[1]["beat_rate"] == 0.0
        assert rows[1]["mean_round_cost"] == 15.0

    def test_outcome_without_seasons_kept_is_skipped(self):
        """2015 and 2016 have no Seasons Kept column at all."""
        rows = by_seasons_kept([outcome(1.0, seasons=None)] * 5)
        assert rows == []

    def test_baseline_thickness_split(self):
        outcomes = ([outcome(1.0, baseline=2)] * 8
                    + [outcome(-1.0, baseline=10)] * 8)
        rows = {r["baseline"]: r for r in by_baseline_thickness(outcomes)}

        assert rows["<5 picks"]["n"] == 8
        assert rows["<5 picks"]["beat_rate"] == 1.0
        assert rows[">=5 picks"]["beat_rate"] == 0.0


class TestAggregate:
    def test_counts_beats_and_reports_a_ci(self):
        outcomes = [outcome(1.0)] * 7 + [outcome(-1.0)] * 3
        result = aggregate_accuracy(outcomes)

        assert result["n"] == 10
        assert result["beat_their_round"] == 7
        assert result["beat_rate"] == 0.7
        assert result["mean_realized_surplus"] == 0.4
        lo, hi = result["beat_rate_ci"]
        assert lo < 0.7 < hi

    def test_sign_agreement_uses_only_decisions_with_a_baseline(self):
        """Seasons whose predecessor was never backfilled carry no baseline.

        Counting those as disagreements would drag the rate toward zero and
        look like a finding about the baseline rather than about coverage.
        """
        outcomes = ([outcome(1.0, prior=2.0)] * 6      # agree
                    + [outcome(1.0, prior=-2.0)] * 2   # disagree
                    + [outcome(1.0, prior=None)] * 5)  # no baseline
        result = aggregate_accuracy(outcomes)

        assert result["n"] == 13
        assert result["prior_baseline_n"] == 8
        assert result["prior_sign_agreement"] == 0.75

    def test_empty_input(self):
        assert aggregate_accuracy([]) == {"n": 0}
