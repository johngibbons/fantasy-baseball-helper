"""Phase 4 value-at-pick curve analysis."""

from __future__ import annotations

from backend.analysis.history.value_curve import (
    concentration,
    fit_shapes,
    pooled_curve,
    rank_linear_prediction,
    season_correlations,
    stability,
)


def curve(*pairs: tuple[int, float]) -> list[dict]:
    return [{"round": r, "picks": 10, "mean_realized_value": v} for r, v in pairs]


class TestPooledCurve:
    def test_pools_each_round_across_seasons(self):
        curves = {
            2020: curve((1, 8.0), (2, 4.0)),
            2021: curve((1, 6.0), (2, 2.0)),
            2022: curve((1, 7.0), (2, 3.0)),
        }
        rows = pooled_curve(curves, min_seasons=3)

        assert [r["round"] for r in rows] == [1, 2]
        assert rows[0]["mean"] == 7.0
        assert rows[0]["min"] == 6.0 and rows[0]["max"] == 8.0
        assert rows[0]["range"] == 2.0

    def test_rounds_only_a_few_seasons_reached_are_dropped(self):
        """Rounds 26 and 27 exist in three seasons only.

        A two-observation mean reads like a curve point and is a coin flip.
        """
        curves = {
            2020: curve((1, 8.0), (26, 1.0)),
            2021: curve((1, 6.0)),
            2022: curve((1, 7.0)),
            2023: curve((1, 5.0)),
            2024: curve((1, 4.0)),
        }
        rows = pooled_curve(curves, min_seasons=5)
        assert [r["round"] for r in rows] == [1]


class TestStability:
    def test_agreeing_seasons_report_low_between_season_spread(self):
        curves = {s: curve((1, 8.0), (2, 4.0)) for s in range(2016, 2026)}
        result = stability(curves)
        assert result["mean_between_season_sd"] == 0.0

    def test_ratio_compares_between_season_to_within_round_noise(self):
        """A curve is usable when seasons agree more closely than picks do."""
        curves = {2016 + i: curve((1, 8.0 + i * 0.1), (2, 4.0 + i * 0.1))
                  for i in range(10)}
        result = stability(curves, within_round_sd={1: 4.0, 2: 4.0})

        assert result["between_over_within"] < 1
        assert result["mean_within_round_sd"] == 4.0


class TestSeasonCorrelations:
    def test_identical_shapes_correlate_perfectly(self):
        shape = [(r, 10.0 - r) for r in range(1, 11)]
        curves = {2020: curve(*shape), 2021: curve(*shape), 2022: curve(*shape)}
        result = season_correlations(curves)

        assert result["pairs"] == 3
        assert result["mean_spearman"] == 1.0

    def test_reversed_shapes_anticorrelate(self):
        up = [(r, float(r)) for r in range(1, 11)]
        down = [(r, 10.0 - r) for r in range(1, 11)]
        result = season_correlations({2020: curve(*up), 2021: curve(*down)})
        assert result["mean_spearman"] == -1.0


class TestRankLinear:
    def test_reads_the_player_ranked_round_times_teams(self):
        board = [float(100 - i) for i in range(300)]   # 100.0 down to -199.0
        assert rank_linear_prediction(1, board) == board[9]
        assert rank_linear_prediction(5, board) == board[49]

    def test_clamps_past_the_end_of_a_short_board(self):
        """A 250-player pool has nothing at rank 260; it must not wrap."""
        board = [float(250 - i) for i in range(250)]
        assert rank_linear_prediction(26, board) == board[-1]

    def test_empty_board(self):
        assert rank_linear_prediction(1, []) is None


class TestShapeFits:
    def test_a_perfectly_linear_curve_is_fitted_by_the_linear_model(self):
        rounds = list(range(1, 26))
        values = [10.0 - 0.4 * r for r in rounds]
        result = fit_shapes(rounds, values)

        assert result["fits"]["linear"]["rmse"] < 1e-9
        assert result["best"] == "linear"

    def test_shapes_that_all_fit_equally_are_reported_inseparable(self):
        """Three candidates within a hair of each other is not a winner.

        With 25 points there is room to overfit, and preferring a shape by
        0.05 SGP of RMSE would be fitting noise.
        """
        # A nearly flat curve: every candidate describes it about as well, so
        # no shape is identified and the winner would be arbitrary.
        rounds = list(range(1, 26))
        values = [2.0 + (0.02 if r % 2 else -0.02) for r in rounds]
        result = fit_shapes(rounds, values)
        assert result["shapes_separable"] is False

    def test_too_few_points_to_fit(self):
        assert fit_shapes([1, 2], [1.0, 2.0])["n"] == 2


class TestConcentration:
    def test_counts_players_above_replacement(self):
        values = [5.0, 3.0, 1.0, -1.0, -2.0]
        result = concentration(values, roster_spots=4)

        assert result["pool"] == 5
        assert result["above_replacement"] == 3
        assert result["rostered_spots_below_replacement"] == 1
        assert result["share_of_rostered_spots_below_replacement"] == 0.25

    def test_more_above_replacement_than_roster_spots(self):
        """A deep season cannot report negative unfilled spots."""
        result = concentration([1.0] * 10, roster_spots=4)
        assert result["rostered_spots_below_replacement"] == 0
