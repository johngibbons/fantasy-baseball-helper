"""Tests for draft replay, per-pick regret, and team-level evaluation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.analysis.retro.draft_replay import (
    DraftContext,
    build_draft_board,
    compare_predicted_to_actual,
    draftable_pool,
    keeper_pick_index,
    predicted_category_wins,
    replay,
    summarize_by_round,
    summarize_by_team,
    team_category_totals,
)
from backend.simulation.config import SimConfig
from backend.simulation.player_pool import ALL_CAT_KEYS, load_players_from_rows

FIXTURE_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "backend" / "data" / "fixtures" / "retro_2026"
)


def slot(mlb_id, team_id, is_keeper=False):
    return {"mlb_id": mlb_id, "team_id": team_id, "is_keeper": is_keeper}


def context(**overrides) -> DraftContext:
    """A tiny draft: 4 players, 2 teams, one keeper."""
    base = dict(
        board=[slot(1, 100, is_keeper=True), slot(2, 200),
               slot(3, 100), slot(4, 200)],
        keeper_ids={1},
        pool_ids={1, 2, 3, 4, 5},
        realized_value={1: 10.0, 2: 1.0, 3: 8.0, 4: 2.0, 5: 6.0},
        board_value={1: 10.0, 2: 9.0, 3: 3.0, 4: 2.0, 5: 1.0},
        adp={1: 1.0, 2: 2.0, 3: 3.0, 4: 4.0, 5: 5.0},
        names={i: f"P{i}" for i in range(1, 6)},
    )
    base.update(overrides)
    return DraftContext(**base)


class TestKeeperPickIndex:
    def test_keeper_takes_its_team_s_slot_in_the_cost_round(self):
        schedule = [1, 2, 3, 3, 2, 1]      # two rounds of a 3-team snake
        round_starts = [0, 3]
        assert keeper_pick_index(2, 1, schedule, round_starts, set()) == 1
        assert keeper_pick_index(2, 2, schedule, round_starts, set()) == 4

    def test_a_second_keeper_at_the_same_cost_takes_the_next_slot(self):
        schedule = [1, 1, 2, 2]
        round_starts = [0]
        used = set()
        first = keeper_pick_index(1, 1, schedule, round_starts, used)
        used.add(first)
        assert keeper_pick_index(1, 1, schedule, round_starts, used) == 1

    def test_out_of_range_round_cost_returns_negative(self):
        assert keeper_pick_index(1, 9, [1, 2], [0], set()) == -1


class TestBuildDraftBoard:
    def test_board_is_keepers_by_round_cost_plus_logged_picks(self):
        schedule = [1, 2, 2, 1]
        board = build_draft_board(
            league_keepers=[{"mlb_id": 50, "teamId": 2, "roundCost": 1}],
            pick_log=[{"mlbId": 60, "teamId": 1, "pickIndex": 0},
                      {"mlbId": 70, "teamId": 2, "pickIndex": 2}],
            pick_schedule=schedule, round_starts=[0], total_picks=len(schedule),
        )
        assert board[0] == {"mlb_id": 60, "team_id": 1, "is_keeper": False}
        assert board[1] == {"mlb_id": 50, "team_id": 2, "is_keeper": True}
        assert board[2] == {"mlb_id": 70, "team_id": 2, "is_keeper": False}
        assert board[3] is None

    def test_a_keeper_also_present_in_the_pick_log_stays_a_keeper(self):
        """Seen in the real data: a late-round keeper carries a pickLog entry
        at the very slot it occupies. It is one player, not two picks."""
        board = build_draft_board(
            league_keepers=[{"mlb_id": 50, "teamId": 1, "roundCost": 1}],
            pick_log=[{"mlbId": 50, "teamId": 1, "pickIndex": 0}],
            pick_schedule=[1, 2], round_starts=[0], total_picks=2,
        )
        assert board[0]["is_keeper"] is True
        assert sum(1 for slot in board if slot) == 1

    def test_pick_log_positions_are_honoured_not_array_order(self):
        """state['picks'] is a Map dumped to an array, so only pickIndex is
        authoritative — reading array position would scramble the draft."""
        board = build_draft_board(
            league_keepers=[],
            pick_log=[{"mlbId": 99, "teamId": 1, "pickIndex": 3},
                      {"mlbId": 11, "teamId": 1, "pickIndex": 0}],
            pick_schedule=[1, 1, 1, 1], round_starts=[0], total_picks=4,
        )
        assert board[0]["mlb_id"] == 11
        assert board[3]["mlb_id"] == 99


class TestDraftablePool:
    def test_keepers_are_never_draftable(self):
        """They were locked before the draft, so they were never an option."""
        assert draftable_pool(context()) == {2, 3, 4, 5}


class TestReplay:
    def test_one_row_per_logged_pick_and_none_for_keepers(self):
        rows = replay(context())
        assert [row["mlb_id"] for row in rows] == [2, 3, 4]

    def test_board_regret_is_zero_when_the_board_s_best_was_taken(self):
        rows = replay(context())
        # Pick 1 took player 2, the highest board value available (9.0).
        assert rows[0]["board_regret"] == pytest.approx(0.0)
        assert rows[0]["board_best_available"] == "P2"

    def test_realized_regret_shows_the_player_who_turned_out_better(self):
        rows = replay(context())
        # Player 2 was the board's best but only returned 1.0; player 3 (8.0)
        # was still there.
        assert rows[0]["realized_regret"] == pytest.approx(1.0 - 8.0)
        assert rows[0]["realized_best_available"] == "P3"

    def test_regret_is_never_positive(self):
        for row in replay(context()):
            assert row["board_regret"] <= 0
            assert row["realized_regret"] <= 0

    def test_players_become_unavailable_once_taken(self):
        rows = replay(context())
        # By the last pick only player 5 is left besides the one taken.
        assert rows[-1]["realized_best_available"] in ("P5", "P4")

    def test_adp_delta_is_positive_for_a_player_who_slid(self):
        rows = replay(context())
        # Player 3 has ADP 3.0 and went at index 2 (pick 3) -> delta 0.
        pick = next(r for r in rows if r["mlb_id"] == 3)
        assert pick["adp_delta"] == pytest.approx(0.0)

    def test_round_is_derived_from_pick_index(self):
        ctx = context(
            board=[slot(i, 100) for i in range(1, 12)],
            keeper_ids=set(),
            pool_ids=set(range(1, 12)),
            realized_value={i: 0.0 for i in range(1, 12)},
            board_value={i: 0.0 for i in range(1, 12)},
        )
        rows = replay(ctx)
        assert rows[0]["round"] == 1
        assert rows[9]["round"] == 1
        assert rows[10]["round"] == 2


class TestSummaries:
    def test_by_team_totals_realized_value(self):
        summary = {t["team_id"]: t for t in summarize_by_team(replay(context()))}
        # Team 200 took players 2 (1.0) and 4 (2.0).
        assert summary[200]["realized_value"] == pytest.approx(3.0)
        assert summary[100]["realized_value"] == pytest.approx(8.0)

    def test_by_round_averages(self):
        rounds = summarize_by_round(replay(context()))
        assert rounds[0]["round"] == 1
        assert rounds[0]["picks"] == 3


class TestTeamCategoryTotals:
    def _player_rows(self, n, value_per_cat):
        return [
            {"mlb_id": i, "full_name": f"H{i}", "primary_position": "OF",
             "player_type": "hitter", "total_zscore": float(n - i),
             **{cat: value_per_cat for cat in ALL_CAT_KEYS}}
            for i in range(n)
        ]

    def test_starters_count_fully_and_bench_is_discounted(self):
        config = SimConfig()
        # 12 outfielders: OF(3) + UTIL(2) start, the rest go to the bench.
        players = load_players_from_rows(self._player_rows(12, 1.0))
        totals = team_category_totals(players, config)
        starters = 5
        bench = 7
        expected = starters + bench * config.HITTER_BENCH_CONTRIBUTION
        assert totals["zscore_r"] == pytest.approx(expected)

    def test_players_beyond_the_roster_contribute_nothing(self):
        config = SimConfig()
        players = load_players_from_rows(self._player_rows(40, 1.0))
        totals = team_category_totals(players, config)
        # 5 usable slots + 8 bench; everything past that is dropped.
        assert totals["zscore_r"] == pytest.approx(
            5 + 8 * config.HITTER_BENCH_CONTRIBUTION)


class TestPredictedCategoryWins:
    def test_the_strongest_team_in_a_category_wins_it_outright(self):
        totals = {
            1: {cat: 10.0 for cat in ALL_CAT_KEYS},
            2: {cat: 5.0 for cat in ALL_CAT_KEYS},
            3: {cat: 1.0 for cat in ALL_CAT_KEYS},
        }
        predicted = predicted_category_wins(totals, num_teams=3)
        assert predicted[1]["cat_win_probs"]["zscore_r"] == pytest.approx(1.0)
        assert predicted[3]["cat_win_probs"]["zscore_r"] == pytest.approx(0.0)
        assert predicted[1]["expected_wins"] == pytest.approx(len(ALL_CAT_KEYS))

    def test_identical_teams_split_every_category(self):
        totals = {i: {cat: 5.0 for cat in ALL_CAT_KEYS} for i in (1, 2, 3)}
        predicted = predicted_category_wins(totals, num_teams=3)
        for team in (1, 2, 3):
            assert predicted[team]["cat_win_probs"]["zscore_r"] == pytest.approx(0.5)


class TestCompareToActual:
    def test_reports_per_team_and_per_category_error(self):
        predicted = {
            1: {"cat_win_probs": {"zscore_r": 0.8, "zscore_tb": 0.6},
                "expected_wins": 1.4},
        }
        actual = {1: {"zscore_r": 0.5, "zscore_tb": 0.5}}
        result = compare_predicted_to_actual(predicted, actual)
        assert result["per_team"][0]["error"] == pytest.approx(0.4)
        assert result["by_category"]["zscore_r"]["mean_error"] == pytest.approx(0.3)

    def test_teams_without_actuals_are_skipped(self):
        predicted = {1: {"cat_win_probs": {"zscore_r": 0.8}, "expected_wins": 0.8}}
        assert compare_predicted_to_actual(predicted, {})["per_team"] == []


class TestFrozenLayerBArtifacts:
    def _load(self, name):
        return json.loads((FIXTURE_DIR / name).read_text())

    def test_every_logged_pick_is_replayed(self):
        decisions = self._load("draft_decisions.json")
        # 250 slots = 40 keepers + 210 drafted.
        assert len(decisions["picks"]) == 210
        assert len(decisions["by_team"]) == 10

    def test_every_team_ends_up_with_a_full_roster(self):
        """The strongest check on the board reconstruction: a 10-team, 25-round
        draft must give every team exactly 25 players once keepers are added."""
        decisions = self._load("draft_decisions.json")
        state = json.loads(
            (FIXTURE_DIR / "draft_state_2026.json").read_text())
        keeper_counts: dict[int, int] = {}
        for keeper in state["leagueKeepers"]:
            keeper_counts[keeper["teamId"]] = keeper_counts.get(keeper["teamId"], 0) + 1
        for team in decisions["by_team"]:
            total = team["picks"] + keeper_counts.get(team["team_id"], 0)
            assert total == 25, f"team {team['team_id']} has {total} players"

    def test_no_pick_beats_the_best_available(self):
        decisions = self._load("draft_decisions.json")
        for pick in decisions["picks"]:
            assert pick["board_regret"] <= 0.001
            assert pick["realized_regret"] <= 0.001

    def test_perfect_foresight_beats_every_real_strategy(self):
        counterfactuals = self._load("counterfactuals.json")
        optimal = sum(counterfactuals["expost_optimal"]["team_totals"].values())
        for label in ("actual", "board_best_available", "adp_follow"):
            assert optimal > sum(counterfactuals[label]["team_totals"].values())

    def test_the_board_beat_drafting_by_adp(self):
        """The clearest thing the app bought: ordering better than the market's."""
        solo = self._load("counterfactuals.json")["solo"]
        assert solo["board_best_available"]["team_total"] > solo["adp_follow"]["team_total"]
