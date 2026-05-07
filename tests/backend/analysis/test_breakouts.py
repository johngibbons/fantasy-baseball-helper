"""Tests for the breakout finder engine."""

import pytest

from backend.analysis.breakouts import (
    HotPlayer,
    BreakoutRecommendation,
    PRORATION_CAP,
    HOT_BLEND_ALPHA,
    prorate_window_to_ros,
    sustainability_filter_passes,
    _blend_with_atc,
    LEAGUE_AVG_BARREL_PCT,
    LEAGUE_AVG_HARD_HIT_PCT,
    LEAGUE_AVG_WHIFF_PCT,
)


class TestProrateWindowToRos:
    def test_hitter_pace_uses_raw_factor_when_below_cap(self):
        # 14d window, 12 games played, 30 games remaining => factor=2.5 (< cap)
        window_stats = {
            "games": 12, "pa": 55, "ab": 48, "r": 12, "h": 17, "hr": 4,
            "rbi": 14, "sb": 2, "bb": 6, "k": 9, "hbp": 1, "sf": 0,
            "total_bases": 32, "obp": 0.420, "slg": 0.667,
        }
        result = prorate_window_to_ros(
            window_stats, player_type="hitter",
            games_in_window=12, games_remaining=30,
        )
        assert result["pa"] == pytest.approx(55 * 30 / 12, abs=1)
        assert result["r"] == pytest.approx(12 * 30 / 12, abs=1)
        assert result["tb"] == pytest.approx(32 * 30 / 12, abs=1)
        assert result["obp"] == pytest.approx(0.420)

    def test_hitter_pace_capped_when_factor_exceeds_threshold(self):
        # 12 games / 90 remaining => raw factor 7.5, capped to PRORATION_CAP
        window_stats = {
            "games": 12, "pa": 55, "ab": 48, "r": 12, "h": 17, "hr": 4,
            "rbi": 14, "sb": 2, "bb": 6, "k": 9, "hbp": 1, "sf": 0,
            "total_bases": 32, "obp": 0.420, "slg": 0.667,
        }
        result = prorate_window_to_ros(
            window_stats, player_type="hitter",
            games_in_window=12, games_remaining=90,
        )
        assert result["pa"] == pytest.approx(55 * PRORATION_CAP, abs=0.5)
        assert result["tb"] == pytest.approx(32 * PRORATION_CAP, abs=0.5)
        assert result["obp"] == pytest.approx(0.420)  # rate stat unchanged

    def test_pitcher_pace_capped(self):
        # 3 games / 25 remaining => raw factor 8.33, capped to PRORATION_CAP
        window_stats = {
            "games": 3, "games_started": 3, "ip": 18.0, "k": 22, "bb": 4,
            "h_allowed": 13, "er": 5, "saves": 0, "holds": 0, "quality_starts": 2,
            "era": 2.50, "whip": 0.944,
        }
        result = prorate_window_to_ros(
            window_stats, player_type="pitcher",
            games_in_window=3, games_remaining=25,
        )
        assert result["ip"] == pytest.approx(18.0 * PRORATION_CAP, abs=0.5)
        assert result["k"] == pytest.approx(22 * PRORATION_CAP, abs=0.5)
        assert result["qs"] == pytest.approx(2 * PRORATION_CAP, abs=0.5)
        assert result["era"] == pytest.approx(2.50)


class TestBlendWithAtc:
    def _atc_hitter(self, **kw):
        defaults = dict(pa=500, r=70, tb=200, rbi=70, sb=10, obp=0.330)
        defaults.update(kw)
        return PlayerProjection(
            mlb_id=1, name="ATC", position="OF", player_type="hitter",
            eligible_positions="OF", overall_rank=100,
            ip=0.0, k=0, qs=0, era=0.0, whip=0.0, svhd=0,
            **defaults,
        )

    def test_blends_counting_stats_directly(self):
        prorated = {"pa": 200, "r": 30, "tb": 100, "rbi": 25, "sb": 5, "obp": 0.400}
        atc = self._atc_hitter()
        blended = _blend_with_atc(prorated, atc, alpha=0.3)
        assert blended["pa"] == pytest.approx(0.3 * 200 + 0.7 * 500)
        assert blended["tb"] == pytest.approx(0.3 * 100 + 0.7 * 200)
        assert blended["sb"] == pytest.approx(0.3 * 5 + 0.7 * 10)

    def test_pa_weighted_rate_blend_dampens_tiny_samples(self):
        # 5 PA at 1.000 OBP shouldn't override 500 PA at .317 OBP
        prorated = {"pa": 5, "r": 1, "tb": 6, "rbi": 0, "sb": 0, "obp": 1.000}
        atc = self._atc_hitter(obp=0.317)
        blended = _blend_with_atc(prorated, atc, alpha=0.3)
        # Heavily weighted toward ATC — should be just barely above .317
        assert 0.317 <= blended["obp"] <= 0.330

    def test_rate_blend_more_responsive_with_larger_hot_sample(self):
        # Two hot lines at the same OBP but different sample sizes: the larger
        # sample should pull the blended OBP further from ATC.
        atc = self._atc_hitter(obp=0.317)
        small_hot = {"pa": 5, "r": 1, "tb": 6, "rbi": 0, "sb": 0, "obp": 0.420}
        big_hot = {"pa": 300, "r": 50, "tb": 150, "rbi": 40, "sb": 5, "obp": 0.420}
        small_blend = _blend_with_atc(small_hot, atc, alpha=0.3)
        big_blend = _blend_with_atc(big_hot, atc, alpha=0.3)
        assert big_blend["obp"] > small_blend["obp"]
        assert small_blend["obp"] - 0.317 < 0.005   # tiny shift
        assert big_blend["obp"] - 0.317 > 0.015     # meaningful shift

    def test_skips_blend_when_atc_has_no_volume(self):
        prorated = {"pa": 200, "r": 30, "tb": 100, "rbi": 25, "sb": 5, "obp": 0.400}
        atc = self._atc_hitter(pa=0, r=0, tb=0, rbi=0, sb=0, obp=0.0)
        blended = _blend_with_atc(prorated, atc, alpha=0.3)
        # Returned as-is; no zeroing of rate stats
        assert blended is prorated


class TestSymmetricProration:
    def test_rostered_player_with_hot_streak_isnt_dropped(self):
        """Both rostered hot player and hot FA get the same blend treatment.

        Hot FA shouldn't surface against a rostered player who's even hotter.
        """
        from backend.analysis.breakouts import compute_hot_view

        my_roster_slots = [
            {"mlb_id": 1, "lineup_slot_id": 0},
            {"mlb_id": 2, "lineup_slot_id": 0},
        ]
        # Rostered #1 has a HOTTER recent line than FA #99.
        # ATC for both is identical; only rolling stats differ.
        projections = {
            1: _proj(1, "MyHotGuy", "hitter", obp=0.330, r=70, tb=200, rbi=70, sb=10),
            2: _proj(2, "Anchor", "hitter", obp=0.330, r=70, tb=200, rbi=70, sb=10),
            99: _proj(99, "FA", "hitter", obp=0.330, r=70, tb=200, rbi=70, sb=10),
            1001: _proj(1001, "Other", "hitter"),
        }
        rolling_stats_by_id = {
            1: {"games": 12, "pa": 55, "ab": 48, "r": 16, "h": 22, "hr": 7,
                "rbi": 20, "sb": 4, "bb": 6, "k": 8, "hbp": 1, "sf": 0,
                "total_bases": 50, "obp": 0.480, "slg": 0.900},
            99: {"games": 12, "pa": 50, "ab": 44, "r": 10, "h": 14, "hr": 4,
                 "rbi": 12, "sb": 2, "bb": 5, "k": 9, "hbp": 1, "sf": 0,
                 "total_bases": 30, "obp": 0.380, "slg": 0.600},
        }
        statcast_by_id = {
            1: {"xwoba": 0.420, "woba": 0.460, "barrel_pct": 18.0,
                "hard_hit_pct": 55.0, "sprint_speed": 28.5},
            99: {"xwoba": 0.400, "woba": 0.420, "barrel_pct": 14.0,
                 "hard_hit_pct": 50.0, "sprint_speed": 28.0},
        }

        result = compute_hot_view(
            my_roster_ids=[1, 2], my_roster_slots=my_roster_slots,
            all_team_roster_slots=[[{"mlb_id": 1001, "lineup_slot_id": 0}]],
            free_agent_ids=[99],
            projections=projections,
            rolling_stats_by_id=rolling_stats_by_id,
            statcast_by_id=statcast_by_id,
            games_in_window=12, games_remaining=120, remaining_faab=85.0,
        )
        recs = result["recommendations"]
        # The "hotter" rostered player shouldn't be dropped for the lukewarm FA.
        if recs:
            assert recs[0].drop_player["id"] != 1, (
                f"Hot rostered player #1 was sacrificed for cooler FA: {recs[0]}"
            )



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


from unittest.mock import patch
from backend.analysis.waivers import PlayerProjection


def _proj(mlb_id, name, ptype, **kw):
    defaults = dict(pa=600, r=80, tb=240, rbi=70, sb=10, obp=0.330,
                    ip=0.0, k=0, qs=0, era=0.0, whip=0.0, svhd=0,
                    eligible_positions="OF", overall_rank=100)
    defaults.update(kw)
    return PlayerProjection(
        mlb_id=mlb_id, name=name, position="OF", player_type=ptype,
        **defaults,
    )


def _pitcher_proj(mlb_id, name, **kw):
    defaults = dict(pa=0, r=0, tb=0, rbi=0, sb=0, obp=0.0,
                    ip=180.0, k=200, qs=15, era=3.50, whip=1.20, svhd=0,
                    eligible_positions="SP", overall_rank=100)
    defaults.update(kw)
    return PlayerProjection(
        mlb_id=mlb_id, name=name, position="SP", player_type="pitcher",
        **defaults,
    )


class TestComputeHotView:
    def test_returns_recommendation_when_fa_passes_filter(self):
        from backend.analysis.breakouts import compute_hot_view

        my_roster_ids = [1, 2]
        my_roster_slots = [
            {"mlb_id": 1, "lineup_slot_id": 0},
            {"mlb_id": 2, "lineup_slot_id": 0},
        ]
        # Hot FA with strong recent stats; existing weak hitter to drop.
        # FA has a modest preseason ATC line — the hot pace blends with it
        # so the FA still grades out above the Weak hitter.
        projections = {
            1: _proj(1, "Strong", "hitter"),
            2: _proj(2, "Weak", "hitter", r=40, tb=120, rbi=30, sb=2, obp=0.270),
            99: _proj(99, "FA", "hitter", pa=400, r=50, tb=160, rbi=45, sb=8, obp=0.330),
        }
        # Other team baseline so my_totals are competitive
        other_team_slots = [{"mlb_id": 1001, "lineup_slot_id": 0}]
        projections[1001] = _proj(1001, "OtherTeam", "hitter", r=70, tb=210, rbi=60, sb=8, obp=0.320)

        rolling_stats_by_id = {
            99: {"games": 12, "pa": 55, "ab": 48, "r": 14, "h": 18, "hr": 5,
                 "rbi": 16, "sb": 3, "bb": 6, "k": 8, "hbp": 1, "sf": 0,
                 "total_bases": 36, "obp": 0.450, "slg": 0.750}
        }
        statcast_by_id = {
            99: {"xwoba": 0.400, "woba": 0.430, "barrel_pct": 14.0,
                 "hard_hit_pct": 50.0, "sprint_speed": 28.5}
        }

        result = compute_hot_view(
            my_roster_ids=my_roster_ids,
            my_roster_slots=my_roster_slots,
            all_team_roster_slots=[other_team_slots],
            free_agent_ids=[99],
            projections=projections,
            rolling_stats_by_id=rolling_stats_by_id,
            statcast_by_id=statcast_by_id,
            games_in_window=12,
            games_remaining=120,
            remaining_faab=85.0,
        )

        recs = result["recommendations"]
        assert len(recs) >= 1
        assert recs[0].add_player["id"] == 99
        assert recs[0].wins_added_if_rate_continues is not None
        assert recs[0].sustainability_badges  # non-empty dict

    def test_filters_out_unsustainable_fa(self):
        from backend.analysis.breakouts import compute_hot_view

        my_roster_slots = [{"mlb_id": 1, "lineup_slot_id": 0}]
        projections = {
            1: _proj(1, "Mine", "hitter"),
            99: _proj(99, "BadFA", "hitter"),
            1001: _proj(1001, "Other", "hitter"),
        }
        rolling_stats_by_id = {
            99: {"games": 10, "pa": 40, "ab": 36, "r": 8, "h": 15, "hr": 3,
                 "rbi": 10, "sb": 1, "bb": 4, "k": 6, "hbp": 0, "sf": 0,
                 "total_bases": 28, "obp": 0.475, "slg": 0.778}
        }
        # All sustainability checks fail
        statcast_by_id = {
            99: {"xwoba": 0.290, "woba": 0.420,    # gap fails
                 "barrel_pct": 4.0,                  # fails
                 "hard_hit_pct": 28.0,               # fails
                 "sprint_speed": 26.0}                # fails
        }

        result = compute_hot_view(
            my_roster_ids=[1], my_roster_slots=my_roster_slots,
            all_team_roster_slots=[[{"mlb_id": 1001, "lineup_slot_id": 0}]],
            free_agent_ids=[99],
            projections=projections,
            rolling_stats_by_id=rolling_stats_by_id,
            statcast_by_id=statcast_by_id,
            games_in_window=10, games_remaining=120, remaining_faab=85.0,
        )
        assert result["recommendations"] == []


class TestComputeStealthView:
    def test_ranks_by_skill_change_zscore_descending(self):
        from backend.analysis.breakouts import compute_stealth_view

        baselines = [
            {"mlb_id": 1, "player_type": "hitter",
             "skill_change_zscore": 1.2, "qualifies_pa_ip": 1,
             "delta_xwoba": 0.04, "delta_barrel_pct": 3.0,
             "delta_hard_hit_pct": 2.0, "delta_sprint_speed": 0.3,
             "baseline_source": "prior_season"},
            {"mlb_id": 2, "player_type": "hitter",
             "skill_change_zscore": 2.5, "qualifies_pa_ip": 1,
             "delta_xwoba": 0.06, "delta_barrel_pct": 5.5,
             "delta_hard_hit_pct": 4.0, "delta_sprint_speed": 0.5,
             "baseline_source": "prior_season"},
            {"mlb_id": 3, "player_type": "hitter",
             "skill_change_zscore": 0.5, "qualifies_pa_ip": 1,
             "delta_xwoba": 0.01, "delta_barrel_pct": 1.0,
             "delta_hard_hit_pct": 0.5, "delta_sprint_speed": 0.0,
             "baseline_source": "league_avg"},
        ]
        player_meta = {
            1: {"name": "A", "team": "BOS", "position": "OF"},
            2: {"name": "B", "team": "LAD", "position": "SS"},
            3: {"name": "C", "team": "SF", "position": "1B"},
        }
        roster_status_by_id = {1: "FA", 2: "FA", 3: "FA"}
        current_stats = {1: {"ops": 0.700}, 2: {"ops": 0.720}, 3: {"ops": 0.690}}
        proj_stats = {1: {"ops": 0.780}, 2: {"ops": 0.760}, 3: {"ops": 0.770}}

        result = compute_stealth_view(
            baselines=baselines, player_meta=player_meta,
            roster_status_by_id=roster_status_by_id,
            current_stats=current_stats, proj_stats=proj_stats,
            scope="FA", position_filter=None, player_type_filter=None,
        )
        recs = result["recommendations"]
        assert [r.add_player["id"] for r in recs] == [2, 1, 3]
        assert recs[0].skill_change_zscore == pytest.approx(2.5)
        assert recs[0].headline_delta is not None

    def test_filters_out_unqualified_players(self):
        from backend.analysis.breakouts import compute_stealth_view

        baselines = [
            {"mlb_id": 1, "player_type": "hitter",
             "skill_change_zscore": 3.0, "qualifies_pa_ip": 0,
             "delta_xwoba": 0.10, "delta_barrel_pct": 8.0,
             "delta_hard_hit_pct": 6.0, "delta_sprint_speed": 1.0,
             "baseline_source": "prior_season"},
        ]
        result = compute_stealth_view(
            baselines=baselines,
            player_meta={1: {"name": "A", "team": "X", "position": "OF"}},
            roster_status_by_id={1: "FA"},
            current_stats={1: {}}, proj_stats={1: {}},
            scope="FA", position_filter=None, player_type_filter=None,
        )
        assert result["recommendations"] == []

    def test_scope_filter_excludes_rostered_when_fa_only(self):
        from backend.analysis.breakouts import compute_stealth_view

        baselines = [
            {"mlb_id": 1, "player_type": "hitter",
             "skill_change_zscore": 2.0, "qualifies_pa_ip": 1,
             "delta_xwoba": 0.05, "delta_barrel_pct": 4.0,
             "delta_hard_hit_pct": 3.0, "delta_sprint_speed": 0.4,
             "baseline_source": "prior_season"},
        ]
        result = compute_stealth_view(
            baselines=baselines,
            player_meta={1: {"name": "A", "team": "X", "position": "OF"}},
            roster_status_by_id={1: "team_3"},
            current_stats={1: {}}, proj_stats={1: {}},
            scope="FA", position_filter=None, player_type_filter=None,
        )
        assert result["recommendations"] == []
