"""Roster health: how is each of my rostered players performing vs their
ATC RoS projection? Output is a per-player z-score where:
  positive = beating their projection (asset)
  negative = underperforming projection (drop candidate)
"""
from __future__ import annotations
import statistics
from typing import Iterable

# Cats where lower is better (rate stats for pitchers)
_INVERTED_KEYS = {"era", "whip"}


def _pace_ratio(current_v: float, current_volume: float,
                projected_v: float, projected_volume: float,
                cat: str) -> float:
    """How far the current per-volume rate is from projected per-volume rate.

    For counting stats: ratio = (current / current_volume) / (projected / projected_volume).
    For rate stats (era, whip, obp): direct ratio of values.
    """
    if cat in _INVERTED_KEYS:
        # Lower is better — invert so positive = beating projection
        if not current_v or not projected_v:
            return 0.0
        return projected_v / current_v
    if cat == "obp":
        if not projected_v:
            return 0.0
        return current_v / projected_v
    # Counting stat: normalize by volume
    if current_volume <= 0 or projected_volume <= 0 or projected_v <= 0:
        return 0.0
    return (current_v / current_volume) / (projected_v / projected_volume)


_HITTER_CATS = [("r", "pa"), ("tb", "pa"), ("rbi", "pa"), ("sb", "pa"), ("obp", "pa")]
_PITCHER_CATS = [("era", "ip"), ("whip", "ip"), ("k", "ip"), ("qs", "ip"), ("svhd", "ip")]


def compute_roster_value_z(roster: Iterable[dict]) -> dict[int, float]:
    """Each rostered player's current-vs-projection composite z.

    roster: list of {mlb_id, player_type, current, projected}
    Returns: mlb_id -> composite z (sum over cats of within-pool z-of-ratio)
    """
    roster = list(roster)
    z_by_player: dict[int, float] = {p["mlb_id"]: 0.0 for p in roster}

    # Compute ratios per cat per player, then z within each subgroup (hitter vs pitcher)
    for ptype, cats in (("hitter", _HITTER_CATS), ("pitcher", _PITCHER_CATS)):
        sub = [p for p in roster if p.get("player_type") == ptype]
        if len(sub) <= 1:
            continue
        for cat, vol in cats:
            ratios = {
                p["mlb_id"]: _pace_ratio(
                    p["current"].get(cat, 0) or 0,
                    p["current"].get(vol, 0) or 0,
                    p["projected"].get(cat, 0) or 0,
                    p["projected"].get(vol, 0) or 0,
                    cat,
                )
                for p in sub
            }
            mean = statistics.fmean(ratios.values())
            stdev = statistics.pstdev(ratios.values())
            if stdev == 0:
                continue
            for pid, r in ratios.items():
                z_by_player[pid] += (r - mean) / stdev
    return z_by_player
