"""Blended scoring for waiver recommendations.

Combines four signals: ATC RoS projection delta, 30-day production z-score,
xwOBA-vs-projection delta, and a luck-gap penalty. Pure functions only —
SQL stays in routes.py / waivers.py.
"""
from __future__ import annotations
import math
import statistics
from typing import Optional

# Categorical weights (sum doesn't have to equal 1, but should be balanced)
_CAT_WEIGHTS_HITTER = {
    "r":   1.0,
    "tb":  1.0,
    "rbi": 1.0,
    "sb":  1.0,
    "obp": 2.0,  # OBP is rate-stat, double-weighted to count vs counting stats
}


def _per_pa(stats: dict, key: str) -> float:
    pa = stats.get("pa", 0) or 0
    if pa <= 0:
        return 0.0
    if key == "obp":
        return stats.get("obp", 0.0) or 0.0  # already a rate
    return (stats.get(key, 0) or 0) / pa


def compute_30d_production_z(pool: dict[int, dict]) -> dict[int, float]:
    """Each candidate's 30d output normalized within the pool.

    pool: mlb_id -> {"r", "tb", "rbi", "sb", "obp", "pa"}
    Returns: mlb_id -> z-score (composite across cats, weighted).

    Per-cat z is computed within the pool (PA-normalized for counting stats).
    Composite z is the weighted average. Single-player pool returns z=0.
    """
    if len(pool) <= 1:
        return {pid: 0.0 for pid in pool}

    z_by_player: dict[int, float] = {pid: 0.0 for pid in pool}
    total_weight = sum(_CAT_WEIGHTS_HITTER.values())

    for cat, weight in _CAT_WEIGHTS_HITTER.items():
        per_pa_values = {pid: _per_pa(s, cat) for pid, s in pool.items()}
        mean = statistics.fmean(per_pa_values.values())
        stdev = statistics.pstdev(per_pa_values.values())
        if stdev == 0:
            continue  # no variance, no signal
        for pid, v in per_pa_values.items():
            z_by_player[pid] += weight * ((v - mean) / stdev)

    return {pid: z / total_weight for pid, z in z_by_player.items()}


def compute_xwoba_signal(xwoba: Optional[float],
                         projected_woba: Optional[float]) -> float:
    """Underlying-skill signal: xwOBA minus projected wOBA.

    Positive means the player's Statcast-implied skill is above ATC's expectation.
    Returns 0.0 when either input is missing — better to drop the signal than
    inject zeros that drag the blended score.
    """
    if xwoba is None or projected_woba is None:
        return 0.0
    return xwoba - projected_woba


def compute_luck_penalty(woba: Optional[float], xwoba: Optional[float]) -> float:
    """Luck penalty: positive when actual wOBA exceeds xwOBA (overperforming).

    Applied as a subtraction in the blended score, so a high penalty drags
    the score down. Returns 0 when underperforming (the production-z signal
    already captures the slump; no need to double-credit).
    """
    if woba is None or xwoba is None:
        return 0.0
    gap = woba - xwoba
    return max(gap, 0.0)
