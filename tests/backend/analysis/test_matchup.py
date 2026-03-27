# tests/backend/analysis/test_matchup.py

import pytest
from backend.analysis.matchup import (
    PlayerProjection,
    compute_per_game_projections,
    blend_rate_stat,
    compute_win_probability,
    compute_projected_finals,
    optimize_daily_lineup,
)


class TestPerGameProjections:
    def test_hitter_pro_rates_by_team_games(self):
        player = PlayerProjection(
            mlb_id=1, name="Juan Soto", position="OF", player_type="hitter",
            pa=600, r=100, tb=300, rbi=100, sb=10, obp=0.400,
            ip=0.0, k=0, qs=0, era=0.0, whip=0.0, svhd=0,
        )
        # 80 remaining season games, 4 remaining this week
        result = compute_per_game_projections(player, remaining_season_games=80)
        assert result["r"] == pytest.approx(100 / 80, abs=0.01)
        assert result["tb"] == pytest.approx(300 / 80, abs=0.01)
        assert result["pa"] == pytest.approx(600 / 80, abs=0.01)
        assert result["obp"] == pytest.approx(0.400, abs=0.001)

    def test_sp_pro_rates_by_projected_starts(self):
        player = PlayerProjection(
            mlb_id=2, name="Corbin Burnes", position="SP", player_type="pitcher",
            pa=0, r=0, tb=0, rbi=0, sb=0, obp=0.0,
            ip=180.0, k=200, qs=18, era=3.00, whip=1.10, svhd=0,
        )
        # 180 IP / 6 IP per start = 30 projected starts
        result = compute_per_game_projections(player, remaining_season_games=80)
        assert result["k"] == pytest.approx(200 / 30, abs=0.1)
        assert result["qs"] == pytest.approx(18 / 30, abs=0.01)
        assert result["ip"] == pytest.approx(180 / 30, abs=0.1)
        assert result["era"] == pytest.approx(3.00, abs=0.01)

    def test_rp_pro_rates_by_team_games(self):
        player = PlayerProjection(
            mlb_id=3, name="Edwin Diaz", position="RP", player_type="pitcher",
            pa=0, r=0, tb=0, rbi=0, sb=0, obp=0.0,
            ip=60.0, k=80, qs=0, era=2.50, whip=1.00, svhd=30,
        )
        result = compute_per_game_projections(player, remaining_season_games=80)
        assert result["k"] == pytest.approx(80 / 80, abs=0.01)
        assert result["svhd"] == pytest.approx(30 / 80, abs=0.01)
        assert result["ip"] == pytest.approx(60 / 80, abs=0.01)

    def test_zero_ip_sp_returns_zeroes(self):
        player = PlayerProjection(
            mlb_id=4, name="Injured Pitcher", position="SP", player_type="pitcher",
            pa=0, r=0, tb=0, rbi=0, sb=0, obp=0.0,
            ip=0.0, k=0, qs=0, era=0.0, whip=0.0, svhd=0,
        )
        result = compute_per_game_projections(player, remaining_season_games=80)
        assert result["k"] == 0.0
        assert result["ip"] == 0.0


class TestBlendRateStat:
    def test_blend_obp(self):
        # actual OBP .300 over 20 PA, projected .350 over 10 PA
        result = blend_rate_stat(
            actual_value=0.300, actual_weight=20,
            projected_value=0.350, projected_weight=10,
        )
        # (0.300 * 20 + 0.350 * 10) / 30 = 9.5 / 30 = 0.3167
        assert result == pytest.approx(0.3167, abs=0.001)

    def test_blend_with_zero_actual(self):
        result = blend_rate_stat(
            actual_value=0.0, actual_weight=0,
            projected_value=3.50, projected_weight=12.0,
        )
        assert result == pytest.approx(3.50, abs=0.01)

    def test_blend_with_zero_projected(self):
        result = blend_rate_stat(
            actual_value=3.00, actual_weight=18.0,
            projected_value=0.0, projected_weight=0.0,
        )
        assert result == pytest.approx(3.00, abs=0.01)


class TestWinProbability:
    def test_large_lead_high_confidence(self):
        # R: my 30 vs their 15, sigma=5 → big lead
        prob = compute_win_probability(30.0, 15.0, sigma=5.0, inverted=False)
        assert prob > 0.9

    def test_tied_is_fifty_fifty(self):
        prob = compute_win_probability(25.0, 25.0, sigma=5.0, inverted=False)
        assert prob == pytest.approx(0.5, abs=0.01)

    def test_losing_low_confidence(self):
        prob = compute_win_probability(15.0, 30.0, sigma=5.0, inverted=False)
        assert prob < 0.1

    def test_inverted_category_era(self):
        # ERA: lower is better. my 3.00 vs their 4.00 → I'm winning
        prob = compute_win_probability(3.00, 4.00, sigma=1.0, inverted=True)
        assert prob > 0.7

    def test_inverted_category_losing(self):
        # ERA: my 5.00 vs their 3.00 → I'm losing
        prob = compute_win_probability(5.00, 3.00, sigma=1.0, inverted=True)
        assert prob < 0.3


class TestDailyLineupOptimizer:
    def test_hitters_assigned_to_best_slots(self):
        """Players should fill starting slots before bench."""
        players = [
            {"mlb_id": 1, "position": "SS", "player_type": "hitter", "eligible_positions": "SS"},
            {"mlb_id": 2, "position": "SS", "player_type": "hitter", "eligible_positions": "SS"},
            {"mlb_id": 3, "position": "OF", "player_type": "hitter", "eligible_positions": "OF"},
        ]
        result = optimize_daily_lineup(players)
        starting_ids = {p["mlb_id"] for p in result["starters"]}
        # All 3 should start: SS slot, UTIL slot, OF slot
        assert len(result["starters"]) == 3
        assert len(result["bench"]) == 0

    def test_overflow_goes_to_bench(self):
        """When too many players for available slots, extras are benched."""
        # 4 SS-only players: 1 fills SS, 2 fill UTIL (×2), 1 benched
        players = [
            {"mlb_id": i, "position": "SS", "player_type": "hitter", "eligible_positions": "SS"}
            for i in range(4)
        ]
        result = optimize_daily_lineup(players)
        assert len(result["starters"]) == 3  # SS + 2 UTIL
        assert len(result["bench"]) == 1

    def test_pitchers_fill_pitcher_slots(self):
        players = [
            {"mlb_id": 10, "position": "SP", "player_type": "pitcher", "eligible_positions": "SP"},
            {"mlb_id": 11, "position": "RP", "player_type": "pitcher", "eligible_positions": "RP"},
        ]
        result = optimize_daily_lineup(players)
        assert len(result["starters"]) == 2
        assert len(result["bench"]) == 0
