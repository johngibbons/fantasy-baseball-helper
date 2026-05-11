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
