import pytest
from backend.analysis.lineup_optimizer import (
    optimize_hitter_lineup,
    HitterSlotAssignment,
    HITTER_ACTIVE_SLOTS,
    POSITION_TO_ACTIVE_SLOTS,
)


def _hitter(mlb_id: int, positions: str, overall_rank: int) -> dict:
    return {
        "mlb_id": mlb_id,
        "eligible_positions": positions,
        "overall_rank": overall_rank,
        "player_type": "hitter",
    }


class TestOptimizeHitterLineup:
    def test_all_starters_when_roster_fits(self):
        hitters = [
            _hitter(1, "C", 10),
            _hitter(2, "1B", 20),
            _hitter(3, "2B", 30),
            _hitter(4, "3B", 40),
            _hitter(5, "SS", 50),
            _hitter(6, "OF", 60),
            _hitter(7, "OF", 70),
            _hitter(8, "OF", 80),
            _hitter(9, "DH", 90),
        ]
        result = optimize_hitter_lineup(hitters)
        assert all(a.is_starter for a in result)
        assert len(result) == 9

    def test_bench_overflow(self):
        hitters = [
            _hitter(1, "C", 10),
            _hitter(2, "1B", 20),
            _hitter(3, "2B", 30),
            _hitter(4, "3B", 40),
            _hitter(5, "SS", 50),
            _hitter(6, "OF", 60),
            _hitter(7, "CF", 70),
            _hitter(8, "RF", 80),
            _hitter(9, "1B/DH", 90),
            _hitter(10, "OF/DH", 100),
            _hitter(11, "1B/DH", 200),
            _hitter(12, "OF", 250),
        ]
        result = optimize_hitter_lineup(hitters)
        starters = [a for a in result if a.is_starter]
        bench = [a for a in result if not a.is_starter]
        # 10 active slots (C+1B+2B+3B+SS+OF×3+UTIL×2), 12 hitters → 2 bench
        assert len(starters) == 10
        assert len(bench) == 2
        bench_ids = {a.mlb_id for a in bench}
        assert 11 in bench_ids
        assert 12 in bench_ids

    def test_constrained_position_gets_priority(self):
        hitters = [
            _hitter(1, "C/1B", 5),
            _hitter(2, "C", 50),
            _hitter(3, "1B", 10),
            _hitter(4, "2B", 15),
            _hitter(5, "3B", 20),
            _hitter(6, "SS", 25),
            _hitter(7, "OF", 30),
            _hitter(8, "OF", 35),
            _hitter(9, "OF", 40),
            _hitter(10, "DH", 45),
            _hitter(11, "DH", 55),
        ]
        result = optimize_hitter_lineup(hitters)
        p2 = next(a for a in result if a.mlb_id == 2)
        assert p2.is_starter
        assert p2.slot == "C"
        p1 = next(a for a in result if a.mlb_id == 1)
        assert p1.is_starter

    def test_multi_position_player_fills_best_slot(self):
        hitters = [
            _hitter(1, "C", 10),
            _hitter(2, "1B", 20),
            _hitter(3, "SS/2B", 30),
            _hitter(4, "3B", 40),
            _hitter(5, "SS", 50),
            _hitter(6, "OF", 60),
            _hitter(7, "OF", 70),
            _hitter(8, "OF", 80),
            _hitter(9, "DH", 90),
        ]
        result = optimize_hitter_lineup(hitters)
        starters = {a.mlb_id for a in result if a.is_starter}
        assert len(starters) == 9

    def test_empty_roster(self):
        result = optimize_hitter_lineup([])
        assert result == []

    def test_swap_changes_assignment(self):
        base = [
            _hitter(1, "C", 10),
            _hitter(2, "1B", 20),
            _hitter(3, "2B", 30),
            _hitter(4, "3B", 40),
            _hitter(5, "SS", 50),
            _hitter(6, "OF", 60),
            _hitter(7, "OF", 70),
            _hitter(8, "OF", 80),
            _hitter(9, "DH", 90),
            _hitter(10, "DH", 95),
            _hitter(11, "1B", 200),
        ]
        baseline = optimize_hitter_lineup(base)
        p11 = next(a for a in baseline if a.mlb_id == 11)
        assert not p11.is_starter

        trial = [h for h in base if h["mlb_id"] != 11]
        trial.append(_hitter(99, "1B", 15))
        trial_result = optimize_hitter_lineup(trial)
        p99 = next(a for a in trial_result if a.mlb_id == 99)
        assert p99.is_starter


class TestPositionEligibility:
    def test_of_aliases(self):
        for pos in ["LF", "CF", "RF"]:
            slots = POSITION_TO_ACTIVE_SLOTS.get(pos, POSITION_TO_ACTIVE_SLOTS.get("OF"))
            assert "OF" in slots

    def test_dh_only_util(self):
        assert POSITION_TO_ACTIVE_SLOTS["DH"] == ["UTIL"]

    def test_pitcher_positions_not_in_hitter_slots(self):
        assert "SP" not in POSITION_TO_ACTIVE_SLOTS
        assert "RP" not in POSITION_TO_ACTIVE_SLOTS
