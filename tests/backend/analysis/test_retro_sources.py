"""Tests for projection-source scoring."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.analysis.retro.sources import (
    blend_values,
    common_player_ids,
    coverage_report,
    rate_accuracy,
    volume_accuracy,
)

FIXTURE = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "backend" / "data" / "fixtures" / "retro_2026"
    / "projection_source_accuracy.json"
)


class TestCommonPlayers:
    def test_intersection_across_sources(self):
        rows = {
            "a": [{"mlb_id": 1}, {"mlb_id": 2}, {"mlb_id": 3}],
            "b": [{"mlb_id": 2}, {"mlb_id": 3}, {"mlb_id": 4}],
            "c": [{"mlb_id": 3}, {"mlb_id": 2}],
        }
        assert common_player_ids(rows) == {2, 3}

    def test_no_sources_gives_nothing(self):
        assert common_player_ids({}) == set()

    def test_coverage_separates_breadth_from_the_scored_set(self):
        """A source covering few players can look accurate by ducking the hard
        cases, so breadth is reported alongside accuracy rather than folded in."""
        rows = {"wide": [{"mlb_id": i} for i in range(100)],
                "narrow": [{"mlb_id": i} for i in range(10)]}
        report = {c["source"]: c for c in coverage_report(rows, {1, 2, 3})}
        assert report["wide"]["projected_players"] == 100
        assert report["narrow"]["projected_players"] == 10
        assert report["narrow"]["in_common_set"] == 3


class TestVolumeAccuracy:
    def test_perfect_playing_time_forecast(self):
        projections = [{"mlb_id": i, "proj_pa": i * 100} for i in range(1, 6)]
        actuals = [{"mlb_id": i, "proj_pa": i * 100} for i in range(1, 6)]
        result = volume_accuracy(projections, actuals, "proj_pa")
        assert result["correlation"] == pytest.approx(1.0)
        assert result["mean_error"] == pytest.approx(0.0)

    def test_systematic_over_projection_shows_negative_mean_error(self):
        projections = [{"mlb_id": i, "proj_pa": 600} for i in range(5)]
        actuals = [{"mlb_id": i, "proj_pa": 400} for i in range(5)]
        result = volume_accuracy(projections, actuals, "proj_pa")
        assert result["mean_error"] == pytest.approx(-200.0)
        assert result["mean_abs_error"] == pytest.approx(200.0)

    def test_players_without_actuals_are_skipped(self):
        assert volume_accuracy([{"mlb_id": 9, "proj_pa": 500}], [], "proj_pa") == {"n": 0}


class TestRateAccuracy:
    def test_ignores_players_below_the_volume_floor(self):
        """A realized rate over 12 plate appearances is noise, not skill."""
        projections = [{"mlb_id": 1, "proj_obp": 0.350},
                       {"mlb_id": 2, "proj_obp": 0.330}]
        actuals = [{"mlb_id": 1, "proj_obp": 0.360, "proj_pa": 600},
                   {"mlb_id": 2, "proj_obp": 0.900, "proj_pa": 12}]
        result = rate_accuracy(projections, actuals, "proj_obp", "proj_pa",
                               min_volume=200)
        assert result["n"] == 1

    def test_zero_rates_are_excluded(self):
        projections = [{"mlb_id": 1, "proj_era": 0.0}]
        actuals = [{"mlb_id": 1, "proj_era": 3.0, "proj_ip": 100}]
        assert rate_accuracy(projections, actuals, "proj_era", "proj_ip", 40)["n"] == 0


class TestBlendValues:
    def test_equal_weight_average(self):
        blended = blend_values({"a": {1: 4.0, 2: 2.0}, "b": {1: 6.0, 2: 4.0}})
        assert blended == {1: 5.0, 2: 3.0}

    def test_only_players_every_source_covers(self):
        blended = blend_values({"a": {1: 1.0, 2: 1.0}, "b": {2: 3.0, 3: 3.0}})
        assert set(blended) == {2}

    def test_weights_are_respected(self):
        blended = blend_values({"a": {1: 0.0}, "b": {1: 10.0}},
                               weights={"a": 3.0, "b": 1.0})
        assert blended[1] == pytest.approx(2.5)

    def test_no_sources_returns_nothing(self):
        assert blend_values({}) == {}


class TestFrozenLayerDArtifact:
    @staticmethod
    def _load():
        return json.loads(FIXTURE.read_text())

    def test_every_source_is_scored_over_the_same_players(self):
        payload = self._load()
        for pool in ("hitters", "pitchers"):
            counts = {
                source: value["value_accuracy"]["n"]
                for source, value in payload[pool]["sources"].items()
            }
            assert len(set(counts.values())) == 1, counts

    def test_commercial_projections_beat_the_apps_own_models(self):
        """trend and statcast_adjusted are computed in-house; the finding is
        that they are clearly worse than the FanGraphs systems."""
        payload = self._load()
        for pool in ("hitters", "pitchers"):
            sources = payload[pool]["sources"]
            best_commercial = max(
                sources[s]["value_accuracy"]["spearman"]
                for s in ("thebatx", "steamer"))
            best_inhouse = max(
                sources[s]["value_accuracy"]["spearman"]
                for s in ("trend", "statcast_adjusted"))
            assert best_commercial > best_inhouse

    def test_blending_does_not_beat_the_best_single_source(self):
        payload = self._load()
        for pool in ("hitters", "pitchers"):
            best = max(value["value_accuracy"]["spearman"]
                       for value in payload[pool]["sources"].values())
            for blend in payload[pool]["blends"].values():
                assert blend["spearman"] <= best + 1e-9

    def test_close_sources_are_reported_as_indistinguishable(self):
        """Guards against reading a 0.006 gap as a real difference."""
        payload = self._load()
        significance = payload["hitters"]["significance_vs_best"]
        assert significance["steamer"]["distinguishable"] is False
        assert significance["zips"]["distinguishable"] is True
