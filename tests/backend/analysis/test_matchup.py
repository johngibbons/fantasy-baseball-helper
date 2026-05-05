# tests/backend/analysis/test_matchup.py

import pytest
from backend.analysis.matchup import (
    PlayerProjection,
    compute_per_game_projections,
    blend_rate_stat,
    compute_win_probability,
    optimize_daily_lineup,
    compute_matchup_projections,
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

    def test_low_ip_sp_returns_zeroes(self):
        """SP with very low IP (round(ip/6) == 0) should return zeroes."""
        player = PlayerProjection(
            mlb_id=5, name="Low IP Pitcher", position="SP", player_type="pitcher",
            pa=0, r=0, tb=0, rbi=0, sb=0, obp=0.0,
            ip=2.0, k=3, qs=0, era=4.50, whip=1.50, svhd=0,
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


class TestMatchupProjectionProbableStarts:
    """Verify team K/QS aggregation uses per-date probable-pitcher data."""

    def _build_sp(self, mlb_id, name):
        # 180 IP / 6 per start = 30 projected starts, 210 K → 7 K/start
        return PlayerProjection(
            mlb_id=mlb_id, name=name, position="SP", player_type="pitcher",
            pa=0, r=0, tb=0, rbi=0, sb=0, obp=0.0,
            ip=180.0, k=210, qs=18, era=3.50, whip=1.20, svhd=0,
        )

    def _roster_entry(self, mlb_id, name, lineup_slot_id, team="NYY"):
        return {
            "mlb_id": mlb_id,
            "name": name,
            "position": "SP",
            "player_type": "pitcher",
            "lineup_slot_id": lineup_slot_id,
            "mlb_team": team,
            "injury_status": "ACTIVE",
            "eligible_positions": "SP/P",
        }

    def test_probable_starts_drive_k_projection(self, monkeypatch):
        """When probable_pitcher_ids lists 3 SP starts, K ≈ 3 × per-start K.
        Without probable_pitcher_ids, the 0.2 fallback vastly undercounts."""
        # Build 3 opponent SPs, each projected 7 K/start (210 K / 30 starts)
        sps = {i: self._build_sp(i, f"SP{i}") for i in (101, 102, 103)}

        def mock_load(ids, season):
            return {pid: sps[pid] for pid in ids if pid in sps}
        monkeypatch.setattr("backend.analysis.matchup._load_projections", mock_load)

        opp_roster = [
            self._roster_entry(101, "SP1", lineup_slot_id=14),
            self._roster_entry(102, "SP2", lineup_slot_id=14),
            self._roster_entry(103, "SP3", lineup_slot_id=13),
        ]

        actuals = {"my": {}, "opponent": {}}
        team_games_remaining = {"NYY": 3}
        remaining_season_games = {"NYY": 150}
        remaining_dates = ["2026-04-25", "2026-04-26", "2026-04-27"]
        team_schedule_by_date = {d: ["NYY"] for d in remaining_dates}

        # With probable pitcher IDs: each SP probable on exactly one date
        probable_ids = {
            "2026-04-25": [101],
            "2026-04-26": [102],
            "2026-04-27": [103],
        }
        with_probables = compute_matchup_projections(
            my_roster=[],
            opponent_roster=opp_roster,
            actuals=actuals,
            team_games_remaining=team_games_remaining,
            probable_pitcher_ids=probable_ids,
            remaining_season_games=remaining_season_games,
            days_remaining=len(remaining_dates),
            remaining_dates=remaining_dates,
            team_schedule_by_date=team_schedule_by_date,
        )

        # Without probable pitcher IDs (legacy buggy behavior): all SPs fall back to 0.2
        without_probables = compute_matchup_projections(
            my_roster=[],
            opponent_roster=opp_roster,
            actuals=actuals,
            team_games_remaining=team_games_remaining,
            probable_pitcher_ids={},
            remaining_season_games=remaining_season_games,
            days_remaining=len(remaining_dates),
            remaining_dates=remaining_dates,
            team_schedule_by_date=team_schedule_by_date,
        )

        k_with = with_probables["categories"]["K"]["opponent_projected_final"]
        k_without = without_probables["categories"]["K"]["opponent_projected_final"]

        # Expected K with probables: 3 starts × 7 K/start = 21
        assert k_with == pytest.approx(21.0, abs=1.0)
        # Expected K without: 3 SPs × 3 days × 0.2 × 7 K = 12.6 (undercount)
        assert k_without == pytest.approx(12.6, abs=1.0)
        # The fix should produce materially more K than the fallback
        assert k_with > k_without * 1.5


class TestPerDateTeamSchedule:
    """Hitter contribution should respect each team's actual game-day schedule
    (i.e., zero credit on off-days), not just whether the team has any games
    remaining in the matchup period."""

    def test_hitter_off_day_excluded_from_total(self, monkeypatch):
        # 1 hitter, 100 R over 80 RoS games = 1.25 R/game
        hitter = PlayerProjection(
            mlb_id=501, name="Test Hitter", position="OF", player_type="hitter",
            pa=600, r=100, tb=0, rbi=0, sb=0, obp=0.300,
            ip=0.0, k=0, qs=0, era=0.0, whip=0.0, svhd=0,
        )

        def mock_load(ids, season):
            return {501: hitter} if 501 in ids else {}
        monkeypatch.setattr("backend.analysis.matchup._load_projections", mock_load)

        my_roster = [{
            "mlb_id": 501,
            "name": "Test Hitter",
            "position": "OF",
            "player_type": "hitter",
            "lineup_slot_id": 5,
            "mlb_team": "NYY",
            "injury_status": "ACTIVE",
            "eligible_positions": "OF",
        }]

        actuals = {"my": {}, "opponent": {}}
        # Team plays 2 of 3 remaining dates (off-day on 04-26)
        team_games_remaining = {"NYY": 2}
        remaining_season_games = {"NYY": 80}
        remaining_dates = ["2026-04-25", "2026-04-26", "2026-04-27"]
        team_schedule_by_date = {
            "2026-04-25": ["NYY"],
            "2026-04-26": [],          # NYY off-day
            "2026-04-27": ["NYY"],
        }

        result = compute_matchup_projections(
            my_roster=my_roster,
            opponent_roster=[],
            actuals=actuals,
            team_games_remaining=team_games_remaining,
            probable_pitcher_ids={},
            remaining_season_games=remaining_season_games,
            days_remaining=len(remaining_dates),
            remaining_dates=remaining_dates,
            team_schedule_by_date=team_schedule_by_date,
        )

        # Expected: 1.25 R/game × 2 game-days = 2.5
        # Buggy (counts all 3 dates): 1.25 × 3 = 3.75
        my_r = result["categories"]["R"]["my_projected_final"]
        assert my_r == pytest.approx(2.5, abs=0.05), (
            f"Expected 2.5 R (2 game-days × 1.25/game), got {my_r}. "
            "Off-day on 2026-04-26 should not contribute."
        )
