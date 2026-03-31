import random

import pytest
from unittest.mock import patch, MagicMock
from backend.analysis.bench_contributions import (
    parse_schedule_response,
    RosterPlayer,
    compute_availability_rate,
    distribute_sp_starts,
    SimulationResult,
    simulate_season,
)


def _make_hitter(mlb_id: int, name: str, pos: str, team: str, pa: int = 600, rank: int = 50) -> RosterPlayer:
    return RosterPlayer(
        mlb_id=mlb_id, name=name, position=pos, player_type="hitter",
        eligible_positions=pos, team=team, proj_pa=pa, overall_rank=rank,
    )


def _make_pitcher(mlb_id: int, name: str, pos: str, team: str, ip: float = 180.0, rank: int = 50) -> RosterPlayer:
    return RosterPlayer(
        mlb_id=mlb_id, name=name, position=pos, player_type="pitcher",
        eligible_positions=pos, team=team, proj_ip=ip, overall_rank=rank,
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


class TestSimulateSeason:
    def test_starter_contributes_more_than_bench(self):
        """A starting-caliber C should have higher contribution than a bench OF."""
        roster = [
            _make_hitter(1, "C1", "C", "NYY", rank=10),
            _make_hitter(2, "1B1", "1B", "NYY", rank=11),
            _make_hitter(3, "2B1", "2B", "NYY", rank=12),
            _make_hitter(4, "3B1", "3B", "NYY", rank=13),
            _make_hitter(5, "SS1", "SS", "NYY", rank=14),
            _make_hitter(6, "OF1", "OF", "NYY", rank=15),
            _make_hitter(7, "OF2", "OF", "NYY", rank=16),
            _make_hitter(8, "OF3", "OF", "NYY", rank=17),
            _make_hitter(9, "UTIL1", "1B/DH", "NYY", rank=18),
            _make_hitter(10, "UTIL2", "OF/DH", "NYY", rank=19),
            _make_hitter(11, "BenchH1", "OF", "NYY", rank=100),
            _make_hitter(12, "BenchH2", "1B", "NYY", rank=120),
        ]
        schedule = {f"2026-04-{d:02d}": {"NYY"} for d in range(1, 11)}
        result = simulate_season(roster, schedule, team_season_games={"NYY": 162}, num_sims=50, seed=42)
        starter_rate = result.player_contribution_rates[1]
        assert starter_rate > 0.8
        bench_rate = result.player_contribution_rates[11]
        assert bench_rate < starter_rate
        assert bench_rate > 0.0

    def test_sp_only_contributes_on_start_days(self):
        """Bench SP contribution rate should reflect start frequency, not every day."""
        roster = [
            _make_pitcher(20, "SP1", "SP", "NYY", ip=180.0, rank=10),
            _make_pitcher(21, "SP2", "SP", "NYY", ip=180.0, rank=11),
            _make_pitcher(22, "SP3", "SP", "NYY", ip=180.0, rank=12),
            _make_pitcher(23, "RP1", "RP", "NYY", ip=60.0, rank=30),
            _make_pitcher(24, "RP2", "RP", "NYY", ip=60.0, rank=31),
            _make_pitcher(25, "P1", "SP", "NYY", ip=170.0, rank=20),
            _make_pitcher(26, "P2", "RP", "NYY", ip=55.0, rank=40),
            _make_pitcher(27, "BenchSP", "SP", "NYY", ip=150.0, rank=60),
            _make_hitter(1, "C1", "C", "NYY", rank=10),
            _make_hitter(2, "1B1", "1B", "NYY", rank=11),
            _make_hitter(3, "2B1", "2B", "NYY", rank=12),
            _make_hitter(4, "3B1", "3B", "NYY", rank=13),
            _make_hitter(5, "SS1", "SS", "NYY", rank=14),
            _make_hitter(6, "OF1", "OF", "NYY", rank=15),
            _make_hitter(7, "OF2", "OF", "NYY", rank=16),
            _make_hitter(8, "OF3", "OF", "NYY", rank=17),
            _make_hitter(9, "UTIL1", "DH", "NYY", rank=18),
            _make_hitter(10, "UTIL2", "DH", "NYY", rank=19),
        ]
        schedule = {f"2026-04-{d:02d}": {"NYY"} for d in range(1, 31)}
        result = simulate_season(roster, schedule, team_season_games={"NYY": 162}, num_sims=50, seed=42)
        bench_sp_rate = result.player_contribution_rates[27]
        assert 0.0 < bench_sp_rate < 0.8
