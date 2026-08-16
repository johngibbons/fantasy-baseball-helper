"""Python half of the cross-language draft-scoring parity check.

The draft scoring model is implemented twice — src/lib/draft-optimizer.ts drives
the live board, backend/simulation/scoring_model.py drives the simulator, the
Optuna tuner, and the season retrospective. Historically the constants were
hand-copied between them, so they could drift silently and leave every offline
experiment measuring a different model than the one that actually drafts.

Both languages assert against the same fixture. See
src/__tests__/lib/draft-scoring-parity.test.ts for the other half.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.simulation.config import SimConfig
from backend.simulation.scoring_model import (
    analyze_category_standings,
    compute_desperation_bonus,
    compute_draft_score,
    compute_mcw,
    compute_rank,
    detect_strategy,
    standings_confidence,
    win_prob_from_rank,
)

FIXTURE = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "backend" / "data" / "fixtures" / "draft_scoring_parity.json"
)
TOLERANCE = 1e-9


@pytest.fixture(scope="module")
def parity() -> dict:
    return json.loads(FIXTURE.read_text())


@pytest.fixture(scope="module")
def config(parity) -> SimConfig:
    return SimConfig(**parity["config"])


class TestFixtureIntegrity:
    def test_fixture_config_matches_shipped_defaults(self, parity):
        """The fixture must describe the model that is actually in production."""
        assert parity["config"]["MCW_WEIGHT"] == SimConfig().MCW_WEIGHT
        assert parity["config"]["CONFIDENCE_START"] == SimConfig().CONFIDENCE_START
        assert parity["config"]["CONFIDENCE_END"] == SimConfig().CONFIDENCE_END

    def test_fixture_covers_every_strategy_branch(self, parity):
        seen = {
            entry["strategy"]
            for case in parity["cases"]["detect_strategy"]
            for entry in case["expected"]
        }
        assert {"lock", "target", "punt", "neutral"} <= seen


class TestScoringParity:
    def test_standings_confidence(self, parity, config):
        for case in parity["cases"]["standings_confidence"]:
            actual = standings_confidence(case["total_picks_made"], config)
            assert actual == pytest.approx(case["expected"], abs=TOLERANCE)

    def test_compute_draft_score(self, parity, config):
        for case in parity["cases"]["compute_draft_score"]:
            actual = compute_draft_score(
                case["mcw"], case["vona"], case["urgency"], case["roster_fit"],
                case["confidence"], case["draft_progress"], config,
            )
            assert actual == pytest.approx(case["expected"], abs=TOLERANCE)

    def test_compute_rank(self, parity):
        for case in parity["cases"]["compute_rank"]:
            actual = compute_rank(case["my_value"], case["other_totals"])
            assert actual == pytest.approx(case["expected"], abs=TOLERANCE)

    def test_win_prob_from_rank(self, parity):
        for case in parity["cases"]["win_prob_from_rank"]:
            actual = win_prob_from_rank(case["rank"], case["num_teams"])
            assert actual == pytest.approx(case["expected"], abs=TOLERANCE)

    def test_detect_strategy(self, parity, config):
        for case in parity["cases"]["detect_strategy"]:
            standings = analyze_category_standings(
                case["my_totals"], case["other_team_totals"], case["num_teams"])
            standings = detect_strategy(
                standings, case["my_pick_count"], case["num_teams"],
                case["playoff_spots"])
            actual = {s.cat_key: s for s in standings}
            for want in case["expected"]:
                got = actual[want["cat_key"]]
                assert got.my_rank == pytest.approx(want["my_rank"], abs=TOLERANCE)
                assert got.win_prob == pytest.approx(want["win_prob"], abs=TOLERANCE)
                assert got.gap_above == pytest.approx(want["gap_above"], abs=TOLERANCE)
                assert got.gap_below == pytest.approx(want["gap_below"], abs=TOLERANCE)
                assert got.strategy == want["strategy"], (
                    f"{want['cat_key']} strategy drifted at pick "
                    f"{case['my_pick_count']}"
                )

    def test_compute_mcw(self, parity, config):
        for case in parity["cases"]["compute_mcw"]:
            actual = compute_mcw(
                case["player_zscores"], case["my_totals"], case["other_team_totals"],
                case["strategies"], case["num_teams"], config,
            )
            assert actual == pytest.approx(case["expected"], abs=TOLERANCE), case["label"]

    def test_compute_desperation_bonus(self, parity, config):
        from backend.simulation.scoring_model import CategoryStanding

        for case in parity["cases"]["compute_desperation_bonus"]:
            standings = [
                CategoryStanding(
                    cat_key=s["cat_key"], my_total=0.0, my_rank=0.0,
                    win_prob=s["win_prob"], gap_above=0.0, gap_below=0.0,
                    strategy=s["strategy"],
                )
                for s in case["standings"]
            ]
            actual = compute_desperation_bonus(
                case["player_zscores"], standings, config)
            assert actual == pytest.approx(case["expected"], abs=TOLERANCE), case["label"]
