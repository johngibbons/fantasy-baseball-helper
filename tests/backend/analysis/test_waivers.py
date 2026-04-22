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


from unittest.mock import patch
from backend.analysis.waivers import compute_waiver_recommendations


def _build_test_projections():
    """Minimal roster + opponents + FAs sufficient to exercise the engine."""
    projs = {}
    # My roster: 10 hitters + 1 ace + 1 streamer
    hitter_defs = [
        (101, "C_Me",   "C",   10, 85, 280, 95, 5, 0.360),
        (102, "1B_Me",  "1B",  20, 90, 300, 100, 2, 0.370),
        (103, "2B_Me",  "2B",  30, 80, 240, 70, 20, 0.340),
        (104, "3B_Me",  "3B",  40, 75, 260, 85, 5, 0.355),
        (105, "SS_Me",  "SS",  50, 85, 250, 75, 25, 0.345),
        (106, "OF1_Me", "OF",  60, 95, 310, 100, 8, 0.370),
        (107, "OF2_Me", "OF",  70, 75, 230, 80, 12, 0.335),
        (108, "OF3_Me", "OF",  80, 70, 210, 65, 18, 0.325),
        (109, "DH_Me",  "DH",  90, 100, 330, 120, 0, 0.390),
        (110, "BenchH", "1B", 300, 40, 120, 40, 3, 0.310),  # bench-worthy
    ]
    for pid, name, pos, rk, r, tb, rbi, sb, obp in hitter_defs:
        projs[pid] = _proj(pid, name, pos, "hitter",
                           eligible_positions=pos, overall_rank=rk,
                           pa=600, r=r, tb=tb, rbi=rbi, sb=sb, obp=obp)

    projs[201] = _proj(201, "Ace_Me",      "SP", "pitcher",
                       overall_rank=25, ip=200, k=240, qs=20,
                       era=3.10, whip=1.05, svhd=0)
    projs[202] = _proj(202, "Streamer_Me", "SP", "pitcher",
                       overall_rank=450, ip=60,  k=40,  qs=2,
                       era=5.80, whip=1.55, svhd=0)

    # Opponents: 9 copies of a "median" team
    for i in range(301, 310):
        projs[i] = _proj(i, f"Opp{i}", "SS", "hitter",
                         eligible_positions="SS", overall_rank=100,
                         pa=600, r=75, tb=250, rbi=80, sb=10, obp=0.340)
    for i in range(401, 410):
        projs[i] = _proj(i, f"OppSP{i}", "SP", "pitcher",
                         overall_rank=150, ip=180, k=180, qs=14,
                         era=3.80, whip=1.25, svhd=0)

    # Free agents
    projs[501] = _proj(501, "FA_Hitter", "2B", "hitter",
                       eligible_positions="2B", overall_rank=70,
                       pa=600, r=90, tb=290, rbi=95, sb=8, obp=0.365)
    projs[502] = _proj(502, "FA_Pitcher", "SP", "pitcher",
                       overall_rank=80,  ip=190, k=210, qs=18,
                       era=3.30, whip=1.10, svhd=0)
    return projs


def _call_engine(**kwargs):
    """Call compute_waiver_recommendations with _build_test_projections patched in."""
    projs = _build_test_projections()
    my_roster_ids = list(range(101, 111)) + [201, 202]
    my_roster_slots = (
        [{"mlb_id": i, "lineup_slot_id": 0} for i in range(101, 111)]
        + [{"mlb_id": 201, "lineup_slot_id": 14},
           {"mlb_id": 202, "lineup_slot_id": 14}]
    )
    # 9 opponent teams, each a median hitter + median pitcher
    opp_team_slots = [
        [{"mlb_id": 301 + i, "lineup_slot_id": 0},
         {"mlb_id": 401 + i, "lineup_slot_id": 14}]
        for i in range(9)
    ]
    fa_ids = [501, 502]

    defaults = dict(
        my_roster_ids=my_roster_ids,
        my_roster_slots=my_roster_slots,
        all_team_roster_slots=opp_team_slots,
        free_agent_ids=fa_ids,
        season=2026,
        remaining_faab=100.0,
        open_roster_slots=0,
    )
    defaults.update(kwargs)

    with patch(
        "backend.analysis.waivers.load_projections_for_players",
        return_value=projs,
    ):
        return compute_waiver_recommendations(**defaults)


class TestComputeWaiverRecommendationsStreamSlot:
    def test_stream_slot_never_appears_as_drop_when_excluded(self):
        result = _call_engine(exclude_stream_slot=True, same_type_only=False)
        drop_ids = [
            r["drop_player"]["id"]
            for r in result["recommendations"]
            if r["drop_player"] is not None
        ]
        assert 202 not in drop_ids, f"Stream slot 202 appeared as drop: {drop_ids}"

    def test_stream_slot_included_when_flag_off(self):
        """Disabling the flag returns to the pre-change behavior."""
        result = _call_engine(exclude_stream_slot=False, same_type_only=False)
        drop_ids = [
            r["drop_player"]["id"]
            for r in result["recommendations"]
            if r["drop_player"] is not None
        ]
        # Streamer becomes a drop candidate again (for hitter adds)
        assert 202 in drop_ids

    def test_response_includes_stream_slot_player(self):
        result = _call_engine(exclude_stream_slot=True)
        assert result["stream_slot_player"] is not None
        assert result["stream_slot_player"]["id"] == 202
        assert result["stream_slot_player"]["name"] == "Streamer_Me"

    def test_response_stream_slot_null_when_flag_off(self):
        result = _call_engine(exclude_stream_slot=False)
        assert result["stream_slot_player"] is None


class TestComputeWaiverRecommendationsSameType:
    def test_same_type_only_no_cross_type_drops(self):
        result = _call_engine(exclude_stream_slot=True, same_type_only=True)
        for r in result["recommendations"]:
            if r["drop_player"] is None:
                continue
            add_pos = r["add_player"]["position"]
            drop_pos = r["drop_player"]["position"]
            add_is_pitcher = add_pos in ("SP", "RP", "P")
            drop_is_pitcher = drop_pos in ("SP", "RP", "P")
            assert add_is_pitcher == drop_is_pitcher, (
                f"Cross-type rec: add={add_pos} drop={drop_pos}"
            )

    def test_same_type_default_off_allows_cross_type(self):
        """When disabled, the engine can return cross-type recommendations."""
        result = _call_engine(exclude_stream_slot=False, same_type_only=False)
        # FA_Hitter (501, hitter) may have a pitcher drop in this mode
        crosses = [
            r for r in result["recommendations"]
            if r["drop_player"] is not None
            and r["add_player"]["id"] == 501
            and r["drop_player"]["position"] in ("SP", "RP", "P")
        ]
        assert len(crosses) >= 1
