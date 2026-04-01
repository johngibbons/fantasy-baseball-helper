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
    aggregate_by_role,
    RoleAggregation,
    compute_stat_impact,
    build_sweep_configs,
    SweepConfig,
    replacement_level_per_start_stats,
    allocate_weekly_streams,
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


class TestAggregation:
    def test_aggregate_separates_starters_from_bench(self):
        """Players with >0.75 contribution rate are starters; others are bench."""
        rates = {1: 0.93, 2: 0.91, 3: 0.15, 4: 0.88, 5: 0.20}
        players = [
            _make_hitter(1, "H1", "C", "NYY", rank=10),
            _make_hitter(2, "H2", "1B", "NYY", rank=11),
            _make_hitter(3, "BenchH", "OF", "NYY", rank=100),
            _make_pitcher(4, "SP1", "SP", "NYY", ip=180.0, rank=20),
            _make_pitcher(5, "BenchRP", "RP", "NYY", ip=60.0, rank=90),
        ]
        result = aggregate_by_role(rates, players)
        assert len(result.bench_hitters) == 1
        assert result.bench_hitters[0].mlb_id == 3
        assert result.avg_bench_hitter_rate == pytest.approx(0.15, abs=0.01)

    def test_aggregate_bench_pitcher_sp_vs_rp(self):
        """Bench pitchers are split into SP and RP categories."""
        rates = {10: 0.30, 20: 0.12}
        players = [
            _make_pitcher(10, "BenchSP", "SP", "NYY", ip=150.0, rank=60),
            _make_pitcher(20, "BenchRP", "RP", "NYY", ip=55.0, rank=90),
        ]
        result = aggregate_by_role(rates, players)
        assert result.avg_bench_sp_rate == pytest.approx(0.30, abs=0.01)
        assert result.avg_bench_rp_rate == pytest.approx(0.12, abs=0.01)


class TestStatImpact:
    def test_stat_impact_scales_by_contribution_rate(self):
        """Season stat impact = projected stats * contribution rate."""
        player = RosterPlayer(
            mlb_id=1, name="Bench Hitter", position="OF", player_type="hitter",
            eligible_positions="OF", team="NYY",
            proj_pa=400, proj_r=60, proj_tb=150, proj_rbi=55,
            proj_sb=10, proj_obp=0.320, overall_rank=100,
        )
        rates = {1: 0.20}
        impact = compute_stat_impact([player], rates)
        assert impact["R"] == pytest.approx(60 * 0.20, abs=0.1)
        assert impact["TB"] == pytest.approx(150 * 0.20, abs=0.1)
        assert impact["RBI"] == pytest.approx(55 * 0.20, abs=0.1)
        assert impact["SB"] == pytest.approx(10 * 0.20, abs=0.1)

    def test_stat_impact_sums_multiple_players(self):
        """Impact sums across all players in the group."""
        p1 = RosterPlayer(
            mlb_id=1, name="H1", position="OF", player_type="hitter",
            eligible_positions="OF", team="NYY",
            proj_pa=400, proj_r=60, proj_tb=150, proj_rbi=55,
            proj_sb=10, proj_obp=0.320, overall_rank=100,
        )
        p2 = RosterPlayer(
            mlb_id=2, name="H2", position="1B", player_type="hitter",
            eligible_positions="1B", team="NYY",
            proj_pa=300, proj_r=40, proj_tb=100, proj_rbi=35,
            proj_sb=5, proj_obp=0.310, overall_rank=120,
        )
        rates = {1: 0.20, 2: 0.15}
        impact = compute_stat_impact([p1, p2], rates)
        assert impact["R"] == pytest.approx(60 * 0.20 + 40 * 0.15, abs=0.1)

    def test_pitcher_stat_impact(self):
        """Pitching stats are included for pitcher players."""
        pitcher = RosterPlayer(
            mlb_id=10, name="SP", position="SP", player_type="pitcher",
            eligible_positions="SP", team="NYY",
            proj_ip=150.0, proj_k=140, proj_qs=15,
            proj_era=3.50, proj_whip=1.15, proj_svhd=0,
            overall_rank=60,
        )
        rates = {10: 0.30}
        impact = compute_stat_impact([pitcher], rates)
        assert impact["K"] == pytest.approx(140 * 0.30, abs=0.1)
        assert impact["QS"] == pytest.approx(15 * 0.30, abs=0.1)


class TestSweepConfigs:
    def test_baseline_config_unchanged(self):
        """First config is 'baseline' with the original roster."""
        roster = [
            _make_hitter(1, "H1", "C", "NYY", rank=10),
            _make_hitter(2, "H2", "1B", "NYY", rank=50),
            _make_pitcher(10, "SP1", "SP", "NYY", ip=180.0, rank=20),
            _make_pitcher(11, "RP1", "RP", "NYY", ip=60.0, rank=90),
        ]
        configs = build_sweep_configs(roster)
        assert configs[0].label == "baseline"
        assert len(configs[0].roster) == 4

    def test_plus_one_hitter_drops_worst_pitcher(self):
        """+1 hitter config drops the lowest-ranked pitcher."""
        roster = [
            _make_hitter(1, "H1", "C", "NYY", rank=10),
            _make_pitcher(10, "SP1", "SP", "NYY", ip=180.0, rank=20),
            _make_pitcher(11, "RP1", "RP", "NYY", ip=60.0, rank=90),
        ]
        configs = build_sweep_configs(roster)
        plus1 = next(c for c in configs if c.label == "+1 hitter")
        pitcher_ids = [p.mlb_id for p in plus1.roster if p.player_type == "pitcher"]
        assert 11 not in pitcher_ids
        hitter_ids = [p.mlb_id for p in plus1.roster if p.player_type == "hitter"]
        assert len(hitter_ids) == 2

    def test_minus_one_hitter_drops_worst_hitter(self):
        """-1 hitter config drops the lowest-ranked hitter."""
        roster = [
            _make_hitter(1, "H1", "C", "NYY", rank=10),
            _make_hitter(2, "H2", "OF", "NYY", rank=100),
            _make_pitcher(10, "SP1", "SP", "NYY", ip=180.0, rank=20),
        ]
        configs = build_sweep_configs(roster)
        minus1 = next(c for c in configs if c.label == "-1 hitter")
        hitter_ids = [p.mlb_id for p in minus1.roster if p.player_type == "hitter"]
        assert 2 not in hitter_ids


class TestStreaming:
    def test_replacement_level_per_start_stats(self):
        """Per-start stats are full-season replacement-level projections / projected starts."""
        stats = replacement_level_per_start_stats()
        # Replacement-level SP: 100 IP, 80 K, 6 QS over ~18 starts (100/5.5)
        assert stats["k"] == pytest.approx(80 / 18, abs=0.5)
        assert stats["qs"] == pytest.approx(6 / 18, abs=0.1)
        assert stats["ip"] == pytest.approx(100 / 18, abs=0.5)
        assert stats["era"] == pytest.approx(4.50, abs=0.01)
        assert stats["whip"] == pytest.approx(1.35, abs=0.01)
        assert stats["svhd"] == pytest.approx(0.0)

    def test_allocate_weekly_streams_respects_budget(self):
        """allocate_weekly_streams never exceeds max_transactions."""
        week_dates = [f"2026-04-{d:02d}" for d in range(6, 13)]
        schedule = {d: {"NYY", "BOS", "LAD"} for d in week_dates}
        sp_start_dates: dict[int, set[str]] = {}
        streaming_slot_ids = [-100, -200]

        streams = allocate_weekly_streams(
            streaming_slot_ids=streaming_slot_ids,
            sp_start_dates=sp_start_dates,
            week_dates=week_dates,
            schedule=schedule,
            max_transactions=3,
        )
        total_pickups = sum(len(v) for v in streams.values())
        assert total_pickups == 3

    def test_allocate_weekly_streams_skips_days_with_anchored_start(self):
        """Don't stream into a slot on days when its anchored SP is already pitching."""
        week_dates = [f"2026-04-{d:02d}" for d in range(6, 13)]
        schedule = {d: {"NYY"} for d in week_dates}
        sp_start_dates = {-100: {"2026-04-06", "2026-04-11"}}
        streaming_slot_ids = [-100]

        streams = allocate_weekly_streams(
            streaming_slot_ids=streaming_slot_ids,
            sp_start_dates=sp_start_dates,
            week_dates=week_dates,
            schedule=schedule,
            max_transactions=10,
        )
        assert "2026-04-06" not in streams or -100 not in [s["slot_id"] for s in streams.get("2026-04-06", [])]
        assert "2026-04-11" not in streams or -100 not in [s["slot_id"] for s in streams.get("2026-04-11", [])]
        streamed_days = sum(1 for d, v in streams.items() if len(v) > 0)
        assert streamed_days == 5

    def test_allocate_weekly_streams_zero_budget(self):
        """Zero transactions means no streaming."""
        week_dates = [f"2026-04-{d:02d}" for d in range(6, 13)]
        schedule = {d: {"NYY"} for d in week_dates}
        streams = allocate_weekly_streams(
            streaming_slot_ids=[-100],
            sp_start_dates={},
            week_dates=week_dates,
            schedule=schedule,
            max_transactions=0,
        )
        total_pickups = sum(len(v) for v in streams.values())
        assert total_pickups == 0

    def test_streaming_adds_extra_starts(self):
        """With streaming enabled, total pitcher starts should increase."""
        roster = [
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
            _make_pitcher(20, "SP1", "SP", "NYY", ip=180.0, rank=10),
            _make_pitcher(21, "SP2", "SP", "NYY", ip=180.0, rank=11),
            _make_pitcher(22, "SP3", "SP", "NYY", ip=180.0, rank=12),
            _make_pitcher(23, "RP1", "RP", "NYY", ip=60.0, rank=30),
            _make_pitcher(24, "RP2", "RP", "NYY", ip=60.0, rank=31),
            _make_pitcher(25, "StreamSP", "SP", "NYY", ip=100.0, rank=350),
        ]
        schedule_dict = {f"2026-04-{d:02d}": {"NYY"} for d in range(1, 29)}

        result_no_stream = simulate_season(
            roster, schedule_dict, team_season_games={"NYY": 162},
            num_sims=30, seed=42, streams_per_week=0,
        )
        result_streaming = simulate_season(
            roster, schedule_dict, team_season_games={"NYY": 162},
            num_sims=30, seed=42, streams_per_week=10,
        )

        assert result_streaming.streaming_starts > 0
        assert result_no_stream.streaming_starts == 0

    def test_streaming_zero_is_backward_compatible(self):
        """streams_per_week=0 produces identical results to no streaming."""
        roster = [
            _make_hitter(1, "C1", "C", "NYY", rank=10),
            _make_hitter(2, "1B1", "1B", "NYY", rank=11),
            _make_pitcher(20, "SP1", "SP", "NYY", ip=180.0, rank=10),
            _make_pitcher(21, "RP1", "RP", "NYY", ip=60.0, rank=30),
        ]
        schedule = {f"2026-04-{d:02d}": {"NYY"} for d in range(1, 8)}
        r1 = simulate_season(roster, schedule, {"NYY": 162}, num_sims=20, seed=42)
        r2 = simulate_season(roster, schedule, {"NYY": 162}, num_sims=20, seed=42, streams_per_week=0)
        assert r1.player_contribution_rates == r2.player_contribution_rates
        assert r1.streaming_starts == 0
        assert r2.streaming_starts == 0
