"""Golden regression for the SGP valuation engine.

The fixture holds frozen projection rows (2026 preseason THE BAT X) alongside
the SGP values the engine produced for them. Recomputing must reproduce those
values exactly — this is the net beneath every constant the season
retrospective proposes changing.

If this test fails, the valuation model changed. That is only ever intentional:
confirm the change is wanted, then regenerate the fixture and say so in the
commit message.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.analysis.zscores import (
    ValuationConfig,
    compute_hitter_sgp,
    compute_pitcher_sgp,
)

FIXTURE = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "backend" / "data" / "fixtures" / "zscores_golden_2026.json"
)


@pytest.fixture(scope="module")
def golden() -> dict:
    return json.loads(FIXTURE.read_text())


@pytest.fixture(scope="module")
def config(golden) -> ValuationConfig:
    # Denominators come from the fixture so the test never depends on whatever
    # seasons happen to be loaded in league_season_totals.
    return ValuationConfig(sgp_denominators=golden["sgp_denominators"])


class TestGoldenFixture:
    def test_fixture_covers_both_pools_and_the_discount_path(self, golden):
        hitters = golden["hitter_rows"]
        pitchers = golden["pitcher_rows"]
        assert len(hitters) >= 100
        assert len(pitchers) >= 100
        # Part-time hitters exercise the playing-time discount.
        assert sum(1 for r in hitters if (r["proj_pa"] or 0) < 500) >= 20
        # Relievers exercise the RP pool, SVHD, and RP replacement level.
        assert sum(1 for r in pitchers
                   if (r["proj_saves"] or 0) + (r["proj_holds"] or 0) > 5) >= 20

    def test_hitter_valuations_match_the_golden_output(self, golden, config):
        actual = compute_hitter_sgp(golden["hitter_rows"], config=config)
        expected = {e["mlb_id"]: e for e in golden["expected_hitters"]}
        assert len(actual) == len(expected)
        for player in actual:
            want = expected[player["mlb_id"]]
            assert player["total_zscore"] == want["total_zscore"], (
                f"{player['full_name']} total_zscore drifted"
            )
            assert player["replacement_adj"] == want["replacement_adj"], (
                f"{player['full_name']} replacement_adj drifted"
            )

    def test_pitcher_valuations_match_the_golden_output(self, golden, config):
        actual = compute_pitcher_sgp(golden["pitcher_rows"], config=config)
        expected = {e["mlb_id"]: e for e in golden["expected_pitchers"]}
        assert len(actual) == len(expected)
        for player in actual:
            want = expected[player["mlb_id"]]
            assert player["total_zscore"] == want["total_zscore"], (
                f"{player['full_name']} total_zscore drifted"
            )
            assert player["replacement_adj"] == want["replacement_adj"], (
                f"{player['full_name']} replacement_adj drifted"
            )

    def test_results_are_returned_best_first(self, golden, config):
        for results in (compute_hitter_sgp(golden["hitter_rows"], config=config),
                        compute_pitcher_sgp(golden["pitcher_rows"], config=config)):
            totals = [p["total_zscore"] for p in results]
            assert totals == sorted(totals, reverse=True)

    def test_valuation_is_deterministic(self, golden, config):
        a = compute_hitter_sgp(golden["hitter_rows"], config=config)
        b = compute_hitter_sgp(golden["hitter_rows"], config=config)
        assert [p["total_zscore"] for p in a] == [p["total_zscore"] for p in b]


class TestGoldenConfigSensitivity:
    """The knobs must actually move the golden numbers, or the ablations in the
    retrospective would silently measure nothing."""

    def test_disabling_each_knob_changes_the_result(self, golden, config):
        denoms = golden["sgp_denominators"]
        baseline = compute_hitter_sgp(golden["hitter_rows"], config=config)
        base_total = sum(p["total_zscore"] for p in baseline)

        variants = {
            "no_playing_time_discount": ValuationConfig(
                sgp_denominators=denoms, apply_playing_time_discount=False),
            "no_replacement": ValuationConfig(
                sgp_denominators=denoms, apply_replacement=False),
            "flat_category_weights": ValuationConfig(
                sgp_denominators=denoms,
                category_weights={c: 1.0 for c in denoms}),
        }
        for label, variant in variants.items():
            total = sum(p["total_zscore"]
                        for p in compute_hitter_sgp(golden["hitter_rows"], config=variant))
            assert total != base_total, f"{label} had no effect on hitter valuations"

    def test_streaming_bonus_redistributes_rather_than_adds_value(self, golden):
        """The bonus is not a pure addition to qualifying starters.

        It is applied before replacement level is computed, so lifting the
        qualifying SPs also lifts the SP replacement baseline that is then
        subtracted from every pitcher. The league-wide sum therefore *falls*;
        what the bonus actually buys is a wider gap between rosterable-all-season
        starters and the streaming tier. Layer A's ablation has to measure that
        gap, not the level.
        """
        denoms = golden["sgp_denominators"]
        rows = golden["pitcher_rows"]

        def by_id(streaming_bonus):
            cfg = ValuationConfig(sgp_denominators=denoms,
                                  streaming_bonus=streaming_bonus)
            return {p["mlb_id"]: p for p in compute_pitcher_sgp(rows, config=cfg)}

        with_bonus, without = by_id(0.70), by_id(0.0)

        qualifies = [
            mlb_id for mlb_id, p in with_bonus.items()
            if p["proj_qs"] > 0 and p["proj_era"] <= 4.00 and p["proj_whip"] <= 1.25
        ]
        others = [mlb_id for mlb_id in with_bonus if mlb_id not in qualifies]
        assert qualifies and others, "fixture must contain both groups"

        def gap(board):
            mean_q = sum(board[i]["total_zscore"] for i in qualifies) / len(qualifies)
            mean_o = sum(board[i]["total_zscore"] for i in others) / len(others)
            return mean_q - mean_o

        assert gap(with_bonus) > gap(without)

    def test_streaming_bonus_raises_the_replacement_baseline(self, golden):
        """Pins the side effect described above so it cannot change unnoticed."""
        denoms = golden["sgp_denominators"]
        rows = golden["pitcher_rows"]

        def replacement_adj(streaming_bonus):
            cfg = ValuationConfig(sgp_denominators=denoms,
                                  streaming_bonus=streaming_bonus)
            results = compute_pitcher_sgp(rows, config=cfg)
            starters = [p for p in results if p["proj_qs"] > 0]
            # replacement_adj is stored negated, so a lower value = higher baseline.
            return starters[0]["replacement_adj"]

        assert replacement_adj(0.70) < replacement_adj(0.0)
