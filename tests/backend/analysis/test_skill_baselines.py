"""Tests for skill-baseline delta math and composites."""

import pytest

from backend.analysis.skill_baselines import (
    compute_metric_deltas,
    compute_skill_change_zscore,
    compute_sustainability_score,
    LEAGUE_AVG_BARREL_PCT,
    LEAGUE_AVG_HARD_HIT_PCT,
    LEAGUE_AVG_WHIFF_PCT,
)


class TestComputeMetricDeltas:
    def test_hitter_deltas_use_prior_season_when_available(self):
        current = {"xwoba": 0.380, "barrel_pct": 12.0,
                   "hard_hit_pct": 45.0, "sprint_speed": 28.0}
        prior = {"xwoba": 0.330, "barrel_pct": 8.0,
                 "hard_hit_pct": 40.0, "sprint_speed": 27.5}
        result = compute_metric_deltas(current, prior, player_type="hitter")
        assert result["delta_xwoba"] == pytest.approx(0.050)
        assert result["delta_barrel_pct"] == pytest.approx(4.0)
        assert result["delta_hard_hit_pct"] == pytest.approx(5.0)
        assert result["delta_sprint_speed"] == pytest.approx(0.5)
        assert result["baseline_source"] == "prior_season"

    def test_hitter_falls_back_to_league_avg_when_no_prior(self):
        current = {"xwoba": 0.350, "barrel_pct": 10.0,
                   "hard_hit_pct": 38.0, "sprint_speed": 27.0}
        result = compute_metric_deltas(current, prior=None, player_type="hitter")
        # delta = current - league_avg
        assert result["delta_barrel_pct"] == pytest.approx(10.0 - LEAGUE_AVG_BARREL_PCT)
        assert result["delta_hard_hit_pct"] == pytest.approx(38.0 - LEAGUE_AVG_HARD_HIT_PCT)
        assert result["baseline_source"] == "league_avg"

    def test_pitcher_deltas_use_prior_season_when_available(self):
        current = {"xera": 3.20, "whiff_pct": 30.0, "k_pct": 28.0,
                   "bb_pct": 7.0, "chase_rate": 32.0}
        prior = {"xera": 4.10, "whiff_pct": 25.0, "k_pct": 22.0,
                 "bb_pct": 8.5, "chase_rate": 30.0}
        result = compute_metric_deltas(current, prior, player_type="pitcher")
        # xERA delta is current - prior; lower is better, but we store the raw delta
        assert result["delta_xera"] == pytest.approx(-0.90)
        assert result["delta_whiff_pct"] == pytest.approx(5.0)
        assert result["delta_k_pct"] == pytest.approx(6.0)
        assert result["delta_bb_pct"] == pytest.approx(-1.5)
        assert result["delta_chase_rate"] == pytest.approx(2.0)


class TestComputeSkillChangeZscore:
    def test_hitter_zscore_aggregates_weighted_metrics(self):
        deltas = {
            "delta_xwoba": 0.050,    # weight 3
            "delta_barrel_pct": 5.0, # weight 2
            "delta_hard_hit_pct": 3.0,  # weight 1.5
            "delta_sprint_speed": 0.5,  # weight 1
        }
        pop_stats = {
            "delta_xwoba": (0.0, 0.025),       # z = 2.0
            "delta_barrel_pct": (0.0, 2.5),     # z = 2.0
            "delta_hard_hit_pct": (0.0, 3.0),   # z = 1.0
            "delta_sprint_speed": (0.0, 0.5),   # z = 1.0
        }
        z = compute_skill_change_zscore(deltas, pop_stats, player_type="hitter")
        # Weighted avg: (3*2.0 + 2*2.0 + 1.5*1.0 + 1.0*1.0) / 7.5 = 12.5 / 7.5
        assert z == pytest.approx(12.5 / 7.5, rel=1e-3)

    def test_pitcher_zscore_inverts_xera(self):
        deltas = {
            "delta_xera": -0.50,
            "delta_whiff_pct": 4.0,
            "delta_k_pct": 2.0,
            "delta_bb_pct": -0.8,
            "delta_chase_rate": 1.0,
        }
        pop_stats = {
            "delta_xera": (0.0, 0.50),
            "delta_whiff_pct": (0.0, 2.0),
            "delta_k_pct": (0.0, 2.0),
            "delta_bb_pct": (0.0, 0.8),
            "delta_chase_rate": (0.0, 1.0),
        }
        z = compute_skill_change_zscore(deltas, pop_stats, player_type="pitcher")
        # Inverted xERA z: -(-0.50/0.50) = 1.0; weight 3
        # whiff: 4.0/2.0 = 2.0; weight 2
        # K%-BB% combined: avg of (2.0/2.0=1.0) and -(-0.8/0.8)=1.0 → 1.0; weight 2
        # chase_rate: 1.0/1.0 = 1.0; weight 1
        # weighted avg = (3*1.0 + 2*2.0 + 2*1.0 + 1*1.0) / 8 = 10/8 = 1.25
        assert z == pytest.approx(1.25, rel=1e-3)

    def test_zscore_returns_none_when_no_metrics_available(self):
        z = compute_skill_change_zscore({}, {}, player_type="hitter")
        assert z is None


class TestComputeSustainabilityScore:
    def test_hitter_score_high_when_metrics_strong(self):
        current = {
            "xwoba": 0.385, "woba": 0.380,
            "barrel_pct": 12.0,
            "hard_hit_pct": 45.0,
        }
        score = compute_sustainability_score(current, player_type="hitter")
        assert score >= 70

    def test_hitter_score_low_when_overperforming(self):
        current = {
            "xwoba": 0.300, "woba": 0.380,
            "barrel_pct": 5.0,
            "hard_hit_pct": 30.0,
        }
        score = compute_sustainability_score(current, player_type="hitter")
        assert score <= 40

    def test_pitcher_score_high_when_xera_below_era(self):
        current = {
            "xera": 2.80, "era": 3.50,
            "whiff_pct": 32.0,
            "csw_pct": 32.0,
            "bb_pct": 6.0,
        }
        score = compute_sustainability_score(current, player_type="pitcher")
        assert score >= 70

    def test_returns_zero_when_metrics_missing(self):
        score = compute_sustainability_score({}, player_type="hitter")
        assert score == 0
