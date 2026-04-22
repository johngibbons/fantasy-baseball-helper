import pytest
from backend.analysis.waivers import (
    PlayerProjection,
    TeamTotals,
    compute_expected_wins,
    build_team_totals,
    HITTER_BENCH_WEIGHT,
    IL_WEIGHT,
)
from backend.analysis.waivers import identify_stream_slot


def _proj(mlb_id, name, position, player_type,
          eligible_positions="", overall_rank=9999, **kwargs):
    defaults = dict(pa=0, r=0, tb=0, rbi=0, sb=0, obp=0.0,
                    ip=0.0, k=0, qs=0, era=0.0, whip=0.0, svhd=0)
    defaults.update(kwargs)
    return PlayerProjection(
        mlb_id=mlb_id, name=name, position=position, player_type=player_type,
        eligible_positions=eligible_positions, overall_rank=overall_rank,
        **defaults,
    )


class TestPlayerProjectionFields:
    def test_has_eligible_positions_field(self):
        p = PlayerProjection(
            mlb_id=1, name="Test", position="SS", player_type="hitter",
            eligible_positions="SS/2B", overall_rank=50,
        )
        assert p.eligible_positions == "SS/2B"
        assert p.overall_rank == 50

    def test_defaults_for_new_fields(self):
        p = PlayerProjection(
            mlb_id=1, name="Test", position="SS", player_type="hitter",
        )
        assert p.eligible_positions == ""
        assert p.overall_rank == 9999


class TestBuildTeamTotals:
    def test_bench_hitter_gets_reduced_weight(self):
        """With 11 hitters and 10 active slots, the worst-ranked hitter benches."""
        projections = {
            1: _proj(1, "C", "C", "hitter", "C", 10, r=80),
            2: _proj(2, "1B", "1B", "hitter", "1B", 20, r=70),
            3: _proj(3, "2B", "2B", "hitter", "2B", 30, r=60),
            4: _proj(4, "3B", "3B", "hitter", "3B", 40, r=50),
            5: _proj(5, "SS", "SS", "hitter", "SS", 50, r=40),
            6: _proj(6, "OF1", "OF", "hitter", "OF", 60, r=30),
            7: _proj(7, "OF2", "OF", "hitter", "OF", 70, r=20),
            8: _proj(8, "OF3", "OF", "hitter", "OF", 80, r=10),
            9: _proj(9, "UTIL1", "DH", "hitter", "DH", 90, r=5),
            10: _proj(10, "UTIL2", "DH", "hitter", "DH", 100, r=3),
            11: _proj(11, "Bench", "1B", "hitter", "1B", 300, r=100),
        }
        roster_slots = [{"mlb_id": i, "lineup_slot_id": 0} for i in range(1, 12)]
        totals, weights = build_team_totals(roster_slots, projections)
        assert weights[11] == pytest.approx(HITTER_BENCH_WEIGHT)
        for pid in range(1, 11):
            assert weights[pid] == pytest.approx(1.0), f"Player {pid} should be starter"

    def test_pitcher_always_weight_1(self):
        projections = {
            1: _proj(1, "SP1", "SP", "pitcher", "SP", 10, k=200, qs=16, ip=180, era=3.0, whip=1.1),
            2: _proj(2, "SP2", "SP", "pitcher", "SP", 20, k=150, qs=12, ip=160, era=3.5, whip=1.2),
        }
        roster_slots = [
            {"mlb_id": 1, "lineup_slot_id": 14},
            {"mlb_id": 2, "lineup_slot_id": 16},  # bench in ESPN
        ]
        totals, weights = build_team_totals(roster_slots, projections)
        assert weights[1] == 1.0
        assert weights[2] == 1.0

    def test_il_pitcher_weight_0(self):
        projections = {
            1: _proj(1, "SP1", "SP", "pitcher", "SP", 10, k=200, qs=16, ip=180, era=3.0, whip=1.1),
        }
        roster_slots = [{"mlb_id": 1, "lineup_slot_id": 17}]
        totals, weights = build_team_totals(roster_slots, projections)
        assert weights[1] == 0.0

    def test_swap_fa_displaces_weak_starter(self):
        base_projs = {
            1: _proj(1, "C", "C", "hitter", "C", 10, r=80),
            2: _proj(2, "1B_weak", "1B", "hitter", "1B", 200, r=20),
            3: _proj(3, "2B", "2B", "hitter", "2B", 30, r=60),
            4: _proj(4, "3B", "3B", "hitter", "3B", 40, r=50),
            5: _proj(5, "SS", "SS", "hitter", "SS", 50, r=40),
            6: _proj(6, "OF1", "OF", "hitter", "OF", 60, r=30),
            7: _proj(7, "OF2", "OF", "hitter", "OF", 70, r=25),
            8: _proj(8, "OF3", "OF", "hitter", "OF", 80, r=20),
            9: _proj(9, "UTIL1", "DH", "hitter", "DH", 90, r=15),
            10: _proj(10, "UTIL2", "DH", "hitter", "DH", 100, r=10),
            11: _proj(11, "Bench", "1B", "hitter", "1B", 300, r=5),
        }
        base_slots = [{"mlb_id": i, "lineup_slot_id": 0} for i in range(1, 12)]

        _, base_weights = build_team_totals(base_slots, base_projs)
        assert base_weights[11] == pytest.approx(HITTER_BENCH_WEIGHT)
        assert base_weights[2] == pytest.approx(1.0)

        fa = _proj(99, "FA_1B", "1B", "hitter", "1B", 15, r=75)
        trial_projs = {k: v for k, v in base_projs.items() if k != 11}
        trial_projs[99] = fa
        trial_slots = [s for s in base_slots if s["mlb_id"] != 11]
        trial_slots.append({"mlb_id": 99, "lineup_slot_id": 0})

        _, trial_weights = build_team_totals(trial_slots, trial_projs)
        assert trial_weights[99] == pytest.approx(1.0)
        assert trial_weights[2] == pytest.approx(HITTER_BENCH_WEIGHT)

    def test_stream_slot_zero_weighted(self):
        """Stream-slot pitcher is weight 0 — his projections don't enter totals."""
        projections = {
            1: _proj(1, "Ace",      "SP", "pitcher", overall_rank=30,
                     ip=180, k=220, qs=18, era=3.20, whip=1.10),
            2: _proj(2, "Streamer", "SP", "pitcher", overall_rank=400,
                     ip=80,  k=60,  qs=4,  era=5.80, whip=1.55),
        }
        slots = [
            {"mlb_id": 1, "lineup_slot_id": 14},
            {"mlb_id": 2, "lineup_slot_id": 14},
        ]
        totals_with, weights_with = build_team_totals(
            slots, projections, stream_slot_id=2,
        )
        # Compare against totals built from the ace alone
        ace_only_slots = [{"mlb_id": 1, "lineup_slot_id": 14}]
        totals_ace, _ = build_team_totals(ace_only_slots, projections)

        assert weights_with[2] == 0.0
        assert weights_with[1] == 1.0
        # Zero-weighting is equivalent to absence for all count & rate-weighted sums
        assert totals_with.k == pytest.approx(totals_ace.k)
        assert totals_with.qs == pytest.approx(totals_ace.qs)
        assert totals_with.total_ip == pytest.approx(totals_ace.total_ip)
        assert totals_with.weighted_era == pytest.approx(totals_ace.weighted_era)
        assert totals_with.weighted_whip == pytest.approx(totals_ace.weighted_whip)


class TestIdentifyStreamSlot:
    def test_picks_highest_rank_pitcher(self):
        """Highest overall_rank = worst projection = stream slot."""
        projections = {
            1: _proj(1, "Ace",    "SP", "pitcher", overall_rank=20,  ip=180),
            2: _proj(2, "Mid",    "SP", "pitcher", overall_rank=120, ip=150),
            3: _proj(3, "Streamer", "SP", "pitcher", overall_rank=400, ip=80),
        }
        slots = [{"mlb_id": i, "lineup_slot_id": 14} for i in (1, 2, 3)]
        assert identify_stream_slot(slots, projections) == 3

    def test_tie_breaks_by_lowest_ip(self):
        """Equal overall_rank → fewer IP wins (more churn-like)."""
        projections = {
            1: _proj(1, "A", "SP", "pitcher", overall_rank=300, ip=140),
            2: _proj(2, "B", "SP", "pitcher", overall_rank=300, ip=90),
        }
        slots = [{"mlb_id": i, "lineup_slot_id": 14} for i in (1, 2)]
        assert identify_stream_slot(slots, projections) == 2

    def test_ignores_il_pitchers(self):
        """IL pitchers are not candidates."""
        projections = {
            1: _proj(1, "Active",   "SP", "pitcher", overall_rank=50, ip=180),
            2: _proj(2, "InjuredWorst", "SP", "pitcher", overall_rank=500, ip=40),
        }
        slots = [
            {"mlb_id": 1, "lineup_slot_id": 14},
            {"mlb_id": 2, "lineup_slot_id": 17},  # IL
        ]
        assert identify_stream_slot(slots, projections) == 1

    def test_ignores_hitters(self):
        """Only pitchers are stream-slot candidates."""
        projections = {
            1: _proj(1, "SP", "SP", "pitcher", overall_rank=60, ip=180),
            2: _proj(2, "WorstBatter", "2B", "hitter", overall_rank=999, r=5),
        }
        slots = [
            {"mlb_id": 1, "lineup_slot_id": 14},
            {"mlb_id": 2, "lineup_slot_id": 2},
        ]
        assert identify_stream_slot(slots, projections) == 1

    def test_returns_none_when_no_active_pitchers(self):
        projections = {
            1: _proj(1, "H", "SS", "hitter", overall_rank=10, r=80),
        }
        slots = [{"mlb_id": 1, "lineup_slot_id": 4}]
        assert identify_stream_slot(slots, projections) is None

    def test_skips_players_without_projections(self):
        """Players missing from the projections dict are skipped without error."""
        projections = {
            1: _proj(1, "A", "SP", "pitcher", overall_rank=50, ip=180),
        }
        slots = [
            {"mlb_id": 1, "lineup_slot_id": 14},
            {"mlb_id": 99, "lineup_slot_id": 14},  # no projection
        ]
        assert identify_stream_slot(slots, projections) == 1
