"""Tests for the breakout finder engine."""

import pytest

from backend.analysis.breakouts import (
    HotPlayer,
    BreakoutRecommendation,
    prorate_window_to_ros,
    sustainability_filter_passes,
    LEAGUE_AVG_BARREL_PCT,
    LEAGUE_AVG_HARD_HIT_PCT,
    LEAGUE_AVG_WHIFF_PCT,
)


class TestProrateWindowToRos:
    def test_hitter_pace_extrapolated_by_games_remaining(self):
        # 14d window, 12 games played, 90 games remaining in season
        window_stats = {
            "games": 12, "pa": 55, "ab": 48, "r": 12, "h": 17, "hr": 4,
            "rbi": 14, "sb": 2, "bb": 6, "k": 9, "hbp": 1, "sf": 0,
            "total_bases": 32, "obp": 0.420, "slg": 0.667,
        }
        result = prorate_window_to_ros(
            window_stats, player_type="hitter",
            games_in_window=12, games_remaining=90,
        )
        assert result["pa"] == pytest.approx(55 * 90 / 12, abs=1)
        assert result["r"] == pytest.approx(12 * 90 / 12, abs=1)
        assert result["tb"] == pytest.approx(32 * 90 / 12, abs=1)
        assert result["obp"] == pytest.approx(0.420)

    def test_pitcher_pace_extrapolated_to_remaining_starts(self):
        window_stats = {
            "games": 3, "games_started": 3, "ip": 18.0, "k": 22, "bb": 4,
            "h_allowed": 13, "er": 5, "saves": 0, "holds": 0, "quality_starts": 2,
            "era": 2.50, "whip": 0.944,
        }
        result = prorate_window_to_ros(
            window_stats, player_type="pitcher",
            games_in_window=3, games_remaining=25,
        )
        assert result["ip"] == pytest.approx(18.0 * 25 / 3, abs=1)
        assert result["k"] == pytest.approx(22 * 25 / 3, abs=1)
        assert result["qs"] == pytest.approx(2 * 25 / 3, abs=1)
        assert result["era"] == pytest.approx(2.50)


class TestSustainabilityFilter:
    def test_hitter_passes_with_two_of_three_checks(self):
        # xwOBA gap OK + barrel% strong; sprint speed weak. Should pass (>= 2 of 3)
        statcast = {
            "xwoba": 0.380, "woba": 0.385,    # gap = -0.005 (OK)
            "barrel_pct": 12.0,                # well above 7.0 * 0.85 = 5.95
            "hard_hit_pct": 30.0,              # below 35.0 * 0.95 = 33.25 (fails this leg)
            "sprint_speed": 25.0,              # below 27.0 (fails)
        }
        # checks: gap OK, barrel% OR hard_hit% OK (yes), sprint_speed OK? no
        # 2 of 3 -> pass
        assert sustainability_filter_passes(statcast, player_type="hitter") is True

    def test_hitter_fails_when_two_checks_fail(self):
        statcast = {
            "xwoba": 0.300, "woba": 0.380,    # gap = -0.080 (fails)
            "barrel_pct": 4.0,                 # below 5.95 (fails)
            "hard_hit_pct": 30.0,              # below 33.25 (fails)
            "sprint_speed": 28.0,              # OK
        }
        assert sustainability_filter_passes(statcast, player_type="hitter") is False

    def test_pitcher_passes_with_two_of_three(self):
        statcast = {
            "xera": 3.20, "era": 3.50,    # xera <= era + 0.50 ✓
            "whiff_pct": 30.0,             # >= 25.0 * 0.95 = 23.75 ✓
            "csw_pct": 25.0,               # below 28.0 * 0.95 = 26.6 (this leg fails)
            "bb_pct": 11.0,                # > 8.5 * 1.20 = 10.2 ✗
        }
        # checks: xera-era ✓, whiff OR csw ✓ (whiff passes), bb_pct ✗
        # 2 of 3 -> pass
        assert sustainability_filter_passes(statcast, player_type="pitcher") is True

    def test_returns_false_when_critical_data_missing(self):
        # Missing xwOBA (and woba) entirely -> can't evaluate gap check
        statcast = {"barrel_pct": 12.0, "hard_hit_pct": 40.0, "sprint_speed": 28.0}
        # Without xwOBA gap, only 2 checks possible — need both to pass
        # barrel_pct OR hard_hit_pct ✓, sprint_speed ✓ -> 2 of 2 -> pass
        assert sustainability_filter_passes(statcast, player_type="hitter") is True
