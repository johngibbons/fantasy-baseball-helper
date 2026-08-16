"""Tests for ex-post valuation inputs and the frozen Phase 2 artifacts."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from backend.analysis.retro.expost import (
    PlayerIdentity,
    align_pool,
    attrition_report,
    batting_actuals_to_row,
    pitching_actuals_to_row,
    season_elapsed_fraction,
)
from backend.analysis.zscores import ValuationConfig, compute_hitter_sgp

FIXTURE_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "backend" / "data" / "fixtures" / "retro_2026"
)

IDENTITY = PlayerIdentity(
    mlb_id=1, full_name="Test Hitter", primary_position="OF",
    team="TST", eligible_positions="OF",
)
PITCHER_IDENTITY = PlayerIdentity(
    mlb_id=2, full_name="Test Pitcher", primary_position="SP", team="TST",
)


class TestSeasonElapsedFraction:
    def test_zero_before_opening_day_and_one_after_the_finale(self):
        assert season_elapsed_fraction(date(2026, 3, 1)) == 0.0
        assert season_elapsed_fraction(date(2026, 3, 25)) == 0.0
        assert season_elapsed_fraction(date(2026, 12, 1)) == 1.0

    def test_midseason_is_a_proportion_of_the_days_elapsed(self):
        # 2026-08-15 is 143 days into a 186-day season.
        assert season_elapsed_fraction(date(2026, 8, 15)) == pytest.approx(143 / 186, abs=1e-4)


class TestActualsToRows:
    def test_batting_actuals_map_onto_projection_column_names(self):
        stats = {
            "plate_appearances": 550, "runs": 86, "total_bases": 249, "rbi": 73,
            "stolen_bases": 30, "obp": 0.375, "hits": 140, "walks": 45,
            "hit_by_pitch": 5, "sac_flies": 4, "at_bats": 496,
        }
        row = batting_actuals_to_row(IDENTITY, stats)
        assert row["proj_pa"] == 550
        assert row["proj_runs"] == 86
        assert row["proj_total_bases"] == 249
        assert row["proj_stolen_bases"] == 30
        assert row["proj_obp"] == 0.375
        # Components must be the realized ones — the engine derives the pool's
        # league OBP from them.
        assert row["proj_at_bats"] == 496
        assert row["proj_walks"] == 45

    def test_pitching_actuals_map_onto_projection_column_names(self):
        stats = {
            "innings_pitched": 155.2, "strikeouts": 181, "quality_starts": 17,
            "era": 2.54, "whip": 1.19, "saves": 0, "holds": 0,
            "hits_allowed": 140, "walks_allowed": 45, "earned_runs": 44,
        }
        row = pitching_actuals_to_row(PITCHER_IDENTITY, stats)
        assert row["proj_ip"] == 155.2
        assert row["proj_pitcher_strikeouts"] == 181
        assert row["proj_quality_starts"] == 17
        assert row["proj_era"] == 2.54
        assert row["proj_earned_runs"] == 44

    def test_a_player_who_never_appeared_becomes_a_zero_row(self):
        """Dropping them instead would compute replacement level over survivors."""
        row = batting_actuals_to_row(IDENTITY, None)
        assert row["mlb_id"] == 1
        assert row["full_name"] == "Test Hitter"
        assert row["proj_pa"] == 0.0
        assert row["proj_runs"] == 0.0

    def test_missing_and_malformed_stat_values_become_zero(self):
        row = batting_actuals_to_row(IDENTITY, {"runs": None, "rbi": "n/a"})
        assert row["proj_runs"] == 0.0
        assert row["proj_rbi"] == 0.0


class TestAlignPool:
    def test_result_is_exactly_the_requested_universe(self):
        rows = [batting_actuals_to_row(IDENTITY, {"plate_appearances": 500})]
        identities = {
            1: IDENTITY,
            7: PlayerIdentity(mlb_id=7, full_name="Never Played",
                              primary_position="1B"),
        }
        aligned = align_pool(rows, {1, 7}, identities, batting_actuals_to_row)
        assert {r["mlb_id"] for r in aligned} == {1, 7}
        missing = next(r for r in aligned if r["mlb_id"] == 7)
        assert missing["proj_pa"] == 0.0

    def test_players_outside_the_universe_are_dropped(self):
        rows = [
            batting_actuals_to_row(IDENTITY, {"plate_appearances": 500}),
            batting_actuals_to_row(
                PlayerIdentity(mlb_id=99, full_name="Callup",
                               primary_position="OF"),
                {"plate_appearances": 300}),
        ]
        aligned = align_pool(rows, {1}, {1: IDENTITY}, batting_actuals_to_row)
        assert {r["mlb_id"] for r in aligned} == {1}

    def test_ordering_is_deterministic(self):
        identities = {i: PlayerIdentity(mlb_id=i, full_name=f"P{i}",
                                        primary_position="OF")
                      for i in (5, 1, 3)}
        aligned = align_pool([], {5, 1, 3}, identities, batting_actuals_to_row)
        assert [r["mlb_id"] for r in aligned] == [1, 3, 5]


class TestZeroPlayingTimeValuation:
    def test_a_player_who_never_played_lands_at_exactly_minus_replacement(self):
        """The floor of the ex-post board, and a load-bearing sanity check."""
        denoms = {"R": 20.0, "TB": 50.0, "RBI": 20.0, "SB": 10.0, "OBP": 0.004}
        identities = {
            i: PlayerIdentity(mlb_id=i, full_name=f"P{i}", primary_position="OF")
            for i in range(1, 40)
        }
        rows = [
            batting_actuals_to_row(identities[i], {
                "plate_appearances": 600, "runs": 100 - i, "total_bases": 250,
                "rbi": 80, "stolen_bases": 10, "obp": 0.340,
                "hits": 150, "walks": 50, "hit_by_pitch": 3,
                "sac_flies": 4, "at_bats": 540,
            })
            for i in range(1, 39)
        ]
        rows.append(batting_actuals_to_row(identities[39], None))

        results = compute_hitter_sgp(rows, config=ValuationConfig(
            sgp_denominators=denoms, apply_playing_time_discount=False))
        never_played = next(r for r in results if r["mlb_id"] == 39)
        assert never_played["total_zscore"] == pytest.approx(
            never_played["replacement_adj"], abs=0.002)


class TestAttritionReport:
    def test_reports_shortfall_worst_first(self):
        pre = [
            {"mlb_id": 1, "full_name": "Healthy", "proj_pa": 600},
            {"mlb_id": 2, "full_name": "Injured", "proj_pa": 550},
        ]
        post = [
            {"mlb_id": 1, "proj_pa": 590},
            {"mlb_id": 2, "proj_pa": 0},
        ]
        report = attrition_report(pre, post, "proj_pa")
        assert [r["mlb_id"] for r in report] == [2, 1]
        assert report[0]["never_played"] is True
        assert report[0]["delta"] == -550
        assert report[1]["ratio"] == pytest.approx(590 / 600, abs=1e-3)

    def test_zero_projection_yields_no_ratio_rather_than_dividing_by_zero(self):
        report = attrition_report(
            [{"mlb_id": 1, "full_name": "X", "proj_pa": 0}],
            [{"mlb_id": 1, "proj_pa": 10}], "proj_pa")
        assert report[0]["ratio"] is None


class TestFrozenPhase2Artifacts:
    """Guards the committed boards (see backend/scripts/retro_expost.py)."""

    def _load(self, name):
        return json.loads((FIXTURE_DIR / name).read_text())

    def test_both_boards_cover_the_identical_player_pool(self):
        pre, exp = self._load("preseason_board.json"), self._load("expost_values.json")
        for side in ("hitters", "pitchers"):
            assert ({r["mlb_id"] for r in pre[side]}
                    == {r["mlb_id"] for r in exp[side]}), (
                f"{side} pools diverged — the two boards are not comparable"
            )

    def test_both_boards_share_pinned_denominators(self):
        pre, exp = self._load("preseason_board.json"), self._load("expost_values.json")
        assert pre["sgp_denominators"] == exp["sgp_denominators"]
        assert set(pre["sgp_denominators"]) == {
            "R", "TB", "RBI", "SB", "OBP", "K", "QS", "ERA", "WHIP", "SVHD"}

    def test_expost_board_disables_the_playing_time_discount(self):
        exp = self._load("expost_values.json")
        assert exp["config"]["apply_playing_time_discount"] is False

    def test_quality_starts_are_populated_for_starters(self):
        """Regression for MLB's season-stats endpoint omitting QS entirely,
        which zeroed a whole category and buried starters under relievers."""
        exp = self._load("expost_values.json")
        starters = [r for r in exp["pitchers"] if (r.get("proj_ip") or 0) >= 100]
        assert starters, "fixture should contain starters"
        with_qs = [r for r in starters if r.get("zscore_qs", 0) > 0]
        assert len(with_qs) / len(starters) > 0.8, (
            "most 100+ IP pitchers should have quality starts"
        )

    def test_boards_are_sorted_best_first(self):
        for name in ("preseason_board.json", "expost_values.json"):
            board = self._load(name)
            for side in ("hitters", "pitchers"):
                totals = [r["total_zscore"] for r in board[side]]
                assert totals == sorted(totals, reverse=True)
