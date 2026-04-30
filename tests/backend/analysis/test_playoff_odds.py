# tests/backend/analysis/test_playoff_odds.py
"""Tests for the playoff odds simulator engine."""

from __future__ import annotations

import pytest
from backend.analysis.waivers import PlayerProjection
from backend.analysis.playoff_odds import project_team_period


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
        expected_r = 5 * 90 + 2 * 90 * 0.25
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
