# tests/backend/analysis/test_playoff_odds.py
"""Tests for the playoff odds simulator engine."""

from __future__ import annotations

import pytest
import numpy as np
from backend.analysis.waivers import HITTER_BENCH_WEIGHT, PlayerProjection
from backend.analysis.playoff_odds import project_team_period, simulate_head_to_head


def _hitter(mlb_id: int, name: str, **stats) -> PlayerProjection:
    base = dict(pa=600, r=90, tb=270, rbi=80, sb=10, obp=0.340)
    base.update(stats)
    return PlayerProjection(
        mlb_id=mlb_id, name=name, position="OF", player_type="hitter",
        eligible_positions="OF/UTIL", **base,
    )


def _sp(mlb_id: int, name: str, **stats) -> PlayerProjection:
    base = dict(ip=180.0, k=200, qs=18, era=3.50, whip=1.15)
    base.update(stats)
    return PlayerProjection(
        mlb_id=mlb_id, name=name, position="SP", player_type="pitcher",
        eligible_positions="SP/P", **base,
    )


class TestProjectTeamPeriod:
    def test_period_weight_scales_count_stats_linearly(self):
        roster = [_hitter(1, "A"), _hitter(2, "B"), _hitter(3, "C")]
        full = project_team_period(roster, period_weight=1.0)
        half = project_team_period(roster, period_weight=0.5)
        # Count stats must scale by period_weight
        assert half["R"] == pytest.approx(full["R"] / 2, rel=1e-6)
        assert half["TB"] == pytest.approx(full["TB"] / 2, rel=1e-6)
        # Rate stats stay constant
        assert half["OBP"] == pytest.approx(full["OBP"], rel=1e-6)

    def test_starters_and_bench_weighted_correctly(self):
        # 7 OF-eligible hitters. With 3 OF + 2 UTIL = 5 hitter slots that
        # they can fill, 5 will start and 2 will be bench (0.25 weight).
        # All hitters identical with r=90 → expected R = 5*90 + 2*90*0.25
        roster = [_hitter(i, f"H{i}") for i in range(1, 8)]  # 7 hitters
        result = project_team_period(roster, period_weight=1.0)
        expected_r = 5 * 90 + 2 * 90 * HITTER_BENCH_WEIGHT
        assert result["R"] == pytest.approx(expected_r, rel=1e-6)

    def test_pitcher_rate_stats_use_ip_weighted_average(self):
        roster = [
            _sp(1, "Ace", ip=200.0, era=2.50, whip=1.00, k=240, qs=22),
            _sp(2, "Mid", ip=160.0, era=4.00, whip=1.30, k=140, qs=12),
        ]
        result = project_team_period(roster, period_weight=1.0)
        # Both start (3 SP + 2 P = 5 slots, 2 SPs)
        weighted_era = (2.50 * 200 + 4.00 * 160) / (200 + 160)
        assert result["ERA"] == pytest.approx(weighted_era, rel=1e-3)

    def test_il_player_zero_weight(self):
        # Hitter with mlb_id=99 marked IL contributes nothing
        result = project_team_period(
            roster=[_hitter(1, "A"), _hitter(99, "Injured")],
            period_weight=1.0,
            il_mlb_ids={99: True},
        )
        # Only player 1 contributes; r=90
        assert result["R"] == pytest.approx(90, rel=1e-6)


class TestSimulateHeadToHead:
    def test_dominant_team_wins_most_cats(self):
        # Team A is much better at every cat
        a = {"R": 100, "TB": 300, "RBI": 100, "SB": 20, "OBP": 0.380,
             "K": 100, "QS": 8, "ERA": 3.00, "WHIP": 1.05, "SVHD": 10}
        b = {"R": 50, "TB": 150, "RBI": 50, "SB": 5, "OBP": 0.300,
             "K": 50, "QS": 3, "ERA": 5.00, "WHIP": 1.40, "SVHD": 4}
        rng = np.random.default_rng(seed=42)
        a_w, a_l, a_t = simulate_head_to_head(a, b, rng)
        # A should win nearly all 10
        assert a_w >= 9
        assert a_w + a_l + a_t == 10

    def test_tie_means_zero_margin(self):
        same = {"R": 80, "TB": 240, "RBI": 80, "SB": 10, "OBP": 0.330,
                "K": 80, "QS": 6, "ERA": 3.50, "WHIP": 1.20, "SVHD": 6}
        rng = np.random.default_rng(seed=42)
        # Run many trials; with sigma > 0, ties from noise should be near 0
        ties = 0
        for _ in range(100):
            _, _, t = simulate_head_to_head(same, same.copy(), rng)
            ties += t
        # With continuous gaussian noise, exact equality is essentially never;
        # pure ties (~0%) are rare. Win/loss should split ~50/50 across runs.
        assert ties == 0  # gaussians never tie

    def test_inverted_cats_lower_wins(self):
        # Team A has lower ERA — should win ERA/WHIP categories more often
        a = {"R": 80, "TB": 240, "RBI": 80, "SB": 10, "OBP": 0.330,
             "K": 80, "QS": 6, "ERA": 2.50, "WHIP": 1.00, "SVHD": 6}
        b = {"R": 80, "TB": 240, "RBI": 80, "SB": 10, "OBP": 0.330,
             "K": 80, "QS": 6, "ERA": 5.00, "WHIP": 1.50, "SVHD": 6}
        rng = np.random.default_rng(seed=42)
        wins = 0
        for _ in range(200):
            a_w, _, _ = simulate_head_to_head(a, b, rng)
            wins += a_w
        # A wins ERA + WHIP almost always (~2 cats), splits the 8 equal cats
        # ~50/50. Average around 2 + 4 = 6.
        avg = wins / 200
        assert 5.0 <= avg <= 7.0
