import pytest
from backend.analysis.trades import TradePlayerInfo, compute_trade_suggestions
from backend.analysis.waivers import (
    PlayerProjection,
    build_team_totals,
    compute_expected_wins,
    HITTER_BENCH_WEIGHT,
)


class TestTradePlayerInfoWeights:
    def test_has_weight_fields(self):
        p = TradePlayerInfo(
            mlb_id=1, name="Test", position="SS",
            total_zscore=3.0, weight=1.0, incoming_weight=0.25,
        )
        assert p.weight == 1.0
        assert p.incoming_weight == 0.25

    def test_weight_fields_default_to_1(self):
        p = TradePlayerInfo(
            mlb_id=1, name="Test", position="SS", total_zscore=3.0,
        )
        assert p.weight == 1.0
        assert p.incoming_weight == 1.0


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


class TestTradeReOptimization:
    """Verify that trade simulation re-optimizes lineups rather than assuming weight 1.0."""

    def test_suggestions_include_weight_fields(self, monkeypatch):
        """Weight and incoming_weight fields should appear in serialized suggestions."""
        projs = {}
        for i in range(1, 11):
            pos = ["C", "1B", "2B", "3B", "SS", "OF", "OF", "OF", "DH", "DH"][i - 1]
            projs[i] = _proj(i, f"MyStarter{i}", pos, "hitter", pos, i * 10,
                             r=80 - i * 2, pa=500, obp=0.350)
        projs[11] = _proj(11, "MyBench", "1B", "hitter", "1B", 300,
                          r=20, pa=200, obp=0.280)
        projs[12] = _proj(12, "MySP", "SP", "pitcher", "SP", 5,
                          k=200, qs=16, ip=180, era=3.0, whip=1.1)

        for i in range(101, 111):
            idx = i - 100
            pos = ["C", "1B", "2B", "3B", "SS", "OF", "OF", "OF", "DH", "DH"][idx - 1]
            projs[i] = _proj(i, f"TheirStarter{idx}", pos, "hitter", pos, idx * 10,
                             r=80 - idx * 2, pa=500, obp=0.350)
        projs[111] = _proj(111, "TheirBench", "OF", "hitter", "OF", 290,
                           r=25, pa=250, obp=0.290)
        projs[112] = _proj(112, "TheirSP", "SP", "pitcher", "SP", 6,
                           k=190, qs=15, ip=175, era=3.2, whip=1.15)

        def mock_load(ids, season):
            return {pid: projs[pid] for pid in ids if pid in projs}
        monkeypatch.setattr("backend.analysis.trades.load_projections_for_players", mock_load)

        def mock_zscores(ids, season):
            return {pid: max(0, 10 - projs[pid].overall_rank / 30) for pid in ids if pid in projs}
        monkeypatch.setattr("backend.analysis.trades._load_zscores", mock_zscores)

        my_roster = [{"mlb_id": i, "lineup_slot_id": 0} for i in range(1, 13)]
        their_players = [{"mlb_id": i, "lineup_slot_id": 0} for i in range(101, 113)]
        all_teams = [
            {"team_id": 1, "team_name": "My Team", "players": my_roster},
            {"team_id": 2, "team_name": "Their Team", "players": their_players},
        ]

        result = compute_trade_suggestions(
            my_roster=my_roster,
            all_team_rosters=all_teams,
            my_team_index=0,
            season=2026,
            max_trade_size=1,
            fairness_threshold=2.0,
        )

        for s in result["suggestions"]:
            for p in s["my_players_out"]:
                assert "weight" in p, "my_players_out should have weight field"
                assert "incoming_weight" in p, "my_players_out should have incoming_weight field"
            for p in s["their_players_out"]:
                assert "weight" in p, "their_players_out should have weight field"
                assert "incoming_weight" in p, "their_players_out should have incoming_weight field"


class TestTradeWeightAccuracy:
    """Verify weight values reflect actual lineup optimization results."""

    def test_bench_hitter_becomes_starter_on_new_team(self, monkeypatch):
        """A bench 1B on my team (weight=0.25) should get incoming_weight=1.0
        if the receiving team has an open 1B slot."""
        projs = {}
        # My team: full lineup + 1 bench 1B
        positions = ["C", "1B", "2B", "3B", "SS", "OF", "OF", "OF", "DH", "DH"]
        for i in range(1, 11):
            projs[i] = _proj(i, f"MyStart{i}", positions[i-1], "hitter",
                             positions[i-1], i * 10,
                             r=80 - i, pa=500, obp=0.350)
        projs[11] = _proj(11, "MyBench1B", "1B", "hitter", "1B", 250,
                          r=30, pa=300, obp=0.300)
        projs[12] = _proj(12, "MySP", "SP", "pitcher", "SP", 5,
                          k=200, qs=16, ip=180, era=3.0, whip=1.1)

        # Their team: 9 starters (no 1B!) + 1 pitcher
        their_positions = ["C", "2B", "3B", "SS", "OF", "OF", "OF", "DH", "DH"]
        for i in range(101, 110):
            idx = i - 100
            projs[i] = _proj(i, f"TheirStart{idx}", their_positions[idx-1], "hitter",
                             their_positions[idx-1], idx * 10,
                             r=80 - idx, pa=500, obp=0.350)
        projs[110] = _proj(110, "TheirSP", "SP", "pitcher", "SP", 6,
                           k=190, qs=15, ip=175, era=3.2, whip=1.15)
        # Their team gets a player from me; I get one of theirs
        projs[111] = _proj(111, "TheirBenchDH", "DH", "hitter", "DH", 280,
                           r=25, pa=250, obp=0.290)

        def mock_load(ids, season):
            return {pid: projs[pid] for pid in ids if pid in projs}
        monkeypatch.setattr("backend.analysis.trades.load_projections_for_players", mock_load)

        def mock_zscores(ids, season):
            return {pid: max(0, 10 - projs[pid].overall_rank / 30) for pid in ids if pid in projs}
        monkeypatch.setattr("backend.analysis.trades._load_zscores", mock_zscores)

        my_roster = [{"mlb_id": i, "lineup_slot_id": 0} for i in range(1, 13)]
        their_roster = [{"mlb_id": i, "lineup_slot_id": 0} for i in range(101, 112)]

        all_teams = [
            {"team_id": 1, "team_name": "My Team", "players": my_roster},
            {"team_id": 2, "team_name": "Their Team", "players": their_roster},
        ]

        result = compute_trade_suggestions(
            my_roster=my_roster,
            all_team_rosters=all_teams,
            my_team_index=0,
            season=2026,
            max_trade_size=1,
            fairness_threshold=2.0,
        )

        # Find a trade where I send MyBench1B (id=11)
        bench_trades = [
            s for s in result["suggestions"]
            if any(p["mlb_id"] == 11 for p in s["my_players_out"])
        ]

        if bench_trades:
            trade = bench_trades[0]
            my_player = next(p for p in trade["my_players_out"] if p["mlb_id"] == 11)
            # On my team this player is bench
            assert my_player["weight"] == pytest.approx(HITTER_BENCH_WEIGHT), \
                "MyBench1B should have bench weight on my team"
            # On their team with an open 1B slot, should be starter
            assert my_player["incoming_weight"] == pytest.approx(1.0), \
                "MyBench1B should be starter on team that needs a 1B"
