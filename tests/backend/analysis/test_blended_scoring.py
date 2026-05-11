import pytest
import math
from backend.analysis.blended_scoring import compute_30d_production_z


def test_z_score_above_pool_mean_is_positive():
    # 5 candidates' 30d totals
    pool = {
        1: {"r": 10, "tb": 30, "rbi": 10, "sb": 1, "obp": 0.320, "pa": 100},
        2: {"r": 8, "tb": 25, "rbi": 8, "sb": 2, "obp": 0.300, "pa": 100},
        3: {"r": 12, "tb": 35, "rbi": 12, "sb": 1, "obp": 0.340, "pa": 100},
        4: {"r": 9, "tb": 28, "rbi": 9, "sb": 1, "obp": 0.310, "pa": 100},
        5: {"r": 15, "tb": 45, "rbi": 15, "sb": 3, "obp": 0.360, "pa": 100},  # superstar
    }
    z = compute_30d_production_z(pool)
    # Player 5 should have the highest z; player 2 the lowest
    sorted_ids = sorted(z.keys(), key=lambda k: -z[k])
    assert sorted_ids[0] == 5
    assert sorted_ids[-1] == 2
    # Reasonable scale: z is between -3 and +3 in this pool
    for v in z.values():
        assert -3 < v < 3


def test_z_score_handles_single_player_pool():
    pool = {1: {"r": 10, "tb": 30, "rbi": 10, "sb": 1, "obp": 0.320, "pa": 100}}
    z = compute_30d_production_z(pool)
    assert z[1] == 0.0  # single player, no variance, z=0


def test_xwoba_signal_positive_when_above_projection():
    from backend.analysis.blended_scoring import compute_xwoba_signal
    # Player whose xwOBA (.347) is above projected wOBA (.310) -> positive
    result = compute_xwoba_signal(xwoba=0.347, projected_woba=0.310)
    assert result > 0
    assert result == pytest.approx(0.037, abs=1e-3)

def test_xwoba_signal_returns_zero_when_inputs_missing():
    from backend.analysis.blended_scoring import compute_xwoba_signal
    assert compute_xwoba_signal(xwoba=None, projected_woba=0.310) == 0.0
    assert compute_xwoba_signal(xwoba=0.347, projected_woba=None) == 0.0

def test_luck_penalty_positive_when_overperforming():
    from backend.analysis.blended_scoring import compute_luck_penalty
    # Player's actual wOBA exceeds their xwOBA -> overperforming -> positive penalty
    # We'll subtract this from blended score so higher = worse
    result = compute_luck_penalty(woba=0.380, xwoba=0.300)
    assert result > 0
    assert result == pytest.approx(0.08, abs=1e-3)

def test_luck_penalty_zero_when_underperforming():
    from backend.analysis.blended_scoring import compute_luck_penalty
    # Player's wOBA is below their xwOBA -> they're unlucky, no penalty
    assert compute_luck_penalty(woba=0.280, xwoba=0.310) == 0.0

def test_blend_scores_returns_breakdown():
    from backend.analysis.blended_scoring import blend_scores
    # Player whose projection delta is decent, production-z is hot, xwoba is
    # neutral, no luck penalty -> blended should be > projection-only
    result = blend_scores(
        projection_delta=0.5,
        production_z=1.5,
        xwoba_signal=0.0,
        luck_penalty=0.0,
    )
    # default weights: 0.5, 0.3, 0.15, 0.05
    expected = 0.5 * 0.5 + 0.3 * 1.5 + 0.15 * 0.0 - 0.05 * 0.0
    assert result["blended"] == pytest.approx(expected)
    assert result["breakdown"]["projection_contribution"] == pytest.approx(0.25)
    assert result["breakdown"]["production_contribution"] == pytest.approx(0.45)

def test_blend_scores_penalty_drags_score_down():
    from backend.analysis.blended_scoring import blend_scores
    # Same hot production-z but a player who is +0.08 wOBA over xwOBA
    no_penalty = blend_scores(0.5, 1.5, 0.0, 0.0)["blended"]
    with_penalty = blend_scores(0.5, 1.5, 0.0, 0.08)["blended"]
    assert with_penalty < no_penalty
