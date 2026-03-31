import random

import pytest
from unittest.mock import patch, MagicMock
from backend.analysis.bench_contributions import parse_schedule_response
from backend.analysis.bench_contributions import (
    RosterPlayer,
    compute_availability_rate,
    distribute_sp_starts,
)


class TestScheduleParsing:
    def test_parses_dates_and_teams(self):
        """parse_schedule_response extracts date -> set of team abbrevs."""
        fake_response = {
            "dates": [
                {
                    "date": "2026-04-01",
                    "games": [
                        {
                            "gameType": "R",
                            "status": {"abstractGameCode": "S"},
                            "teams": {
                                "home": {"team": {"id": 147}},  # NYY
                                "away": {"team": {"id": 111}},  # BOS
                            },
                        },
                    ],
                },
                {
                    "date": "2026-04-02",
                    "games": [
                        {
                            "gameType": "R",
                            "status": {"abstractGameCode": "S"},
                            "teams": {
                                "home": {"team": {"id": 119}},  # LAD
                                "away": {"team": {"id": 137}},  # SF
                            },
                        },
                    ],
                },
            ]
        }
        schedule = parse_schedule_response(fake_response)
        assert schedule["2026-04-01"] == {"NYY", "BOS"}
        assert schedule["2026-04-02"] == {"LAD", "SF"}

    def test_skips_non_regular_season_games(self):
        fake_response = {
            "dates": [
                {
                    "date": "2026-04-01",
                    "games": [
                        {
                            "gameType": "E",  # Exhibition
                            "status": {"abstractGameCode": "S"},
                            "teams": {
                                "home": {"team": {"id": 147}},
                                "away": {"team": {"id": 111}},
                            },
                        },
                    ],
                },
            ]
        }
        schedule = parse_schedule_response(fake_response)
        assert schedule.get("2026-04-01", set()) == set()

    def test_skips_finished_games(self):
        fake_response = {
            "dates": [
                {
                    "date": "2026-04-01",
                    "games": [
                        {
                            "gameType": "R",
                            "status": {"abstractGameCode": "F"},
                            "teams": {
                                "home": {"team": {"id": 147}},
                                "away": {"team": {"id": 111}},
                            },
                        },
                    ],
                },
            ]
        }
        schedule = parse_schedule_response(fake_response)
        assert schedule.get("2026-04-01", set()) == set()


class TestAvailabilityModel:
    def test_fulltime_hitter_availability(self):
        """Full-time hitter (600 PA, 162 team games) -> ~0.93 availability."""
        player = RosterPlayer(
            mlb_id=1, name="Juan Soto", position="OF", player_type="hitter",
            eligible_positions="OF/DH", team="NYY",
            proj_pa=600, proj_ip=0.0, overall_rank=5,
        )
        rate = compute_availability_rate(player, team_season_games=162)
        assert rate == pytest.approx(600 / 4.0 / 162, abs=0.01)

    def test_platoon_hitter_availability(self):
        """Platoon player (350 PA) -> ~0.54 availability."""
        player = RosterPlayer(
            mlb_id=2, name="Platoon Guy", position="OF", player_type="hitter",
            eligible_positions="OF", team="NYY",
            proj_pa=350, proj_ip=0.0, overall_rank=200,
        )
        rate = compute_availability_rate(player, team_season_games=162)
        assert rate == pytest.approx(350 / 4.0 / 162, abs=0.01)

    def test_hitter_availability_capped_at_1(self):
        """Very high PA player should be capped at 1.0."""
        player = RosterPlayer(
            mlb_id=3, name="Iron Man", position="SS", player_type="hitter",
            eligible_positions="SS", team="NYY",
            proj_pa=700, proj_ip=0.0, overall_rank=1,
        )
        rate = compute_availability_rate(player, team_season_games=162)
        assert rate == 1.0

    def test_sp_projected_starts(self):
        """SP projected starts = proj_ip / 5.5."""
        player = RosterPlayer(
            mlb_id=10, name="Corbin Burnes", position="SP", player_type="pitcher",
            eligible_positions="SP", team="BAL",
            proj_pa=0, proj_ip=180.0, overall_rank=20,
        )
        rate = compute_availability_rate(player, team_season_games=162)
        expected = round(180.0 / 5.5) / 162
        assert rate == pytest.approx(expected, abs=0.01)

    def test_rp_always_available(self):
        """RPs are always available when their team plays."""
        player = RosterPlayer(
            mlb_id=20, name="Edwin Diaz", position="RP", player_type="pitcher",
            eligible_positions="RP", team="NYM",
            proj_pa=0, proj_ip=60.0, overall_rank=80,
        )
        rate = compute_availability_rate(player, team_season_games=162)
        assert rate == 1.0


class TestSPStartDistribution:
    def test_correct_number_of_starts(self):
        """distribute_sp_starts returns exactly projected_starts dates."""
        team_game_dates = [f"2026-04-{d:02d}" for d in range(1, 31)]
        rng = random.Random(42)
        starts = distribute_sp_starts(projected_starts=6, team_game_dates=team_game_dates, rng=rng)
        assert len(starts) == 6
        for d in starts:
            assert d in team_game_dates

    def test_starts_are_unique(self):
        """No duplicate start dates."""
        team_game_dates = [f"2026-04-{d:02d}" for d in range(1, 31)]
        rng = random.Random(42)
        starts = distribute_sp_starts(projected_starts=6, team_game_dates=team_game_dates, rng=rng)
        assert len(starts) == len(set(starts))

    def test_starts_roughly_evenly_spaced(self):
        """Starts should be spread across the schedule, not clustered."""
        team_game_dates = [f"2026-04-{d:02d}" for d in range(1, 31)]
        rng = random.Random(42)
        starts = distribute_sp_starts(projected_starts=6, team_game_dates=team_game_dates, rng=rng)
        indices = sorted(team_game_dates.index(d) for d in starts)
        gaps = [indices[i + 1] - indices[i] for i in range(len(indices) - 1)]
        for gap in gaps:
            assert 1 <= gap <= 10

    def test_more_starts_than_games_caps(self):
        """If projected_starts > team_game_dates, return all dates."""
        team_game_dates = ["2026-04-01", "2026-04-02", "2026-04-03"]
        rng = random.Random(42)
        starts = distribute_sp_starts(projected_starts=10, team_game_dates=team_game_dates, rng=rng)
        assert len(starts) == 3
