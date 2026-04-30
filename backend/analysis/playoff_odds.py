# backend/analysis/playoff_odds.py
"""Playoff odds Monte Carlo simulator.

Given each team's roster, current cumulative W/L/T, and the remaining matchup
schedule, runs N trials of the rest of the season and reports each team's
probability of finishing in the top K (playoff slots).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np

from backend.analysis.matchup import (
    CATEGORY_SIGMA,
    optimize_daily_lineup,
)
from backend.analysis.waivers import (
    ALL_CATS,
    HITTER_BENCH_WEIGHT,
    INVERTED_CATS,
    PlayerProjection,
    TeamTotals,
)

logger = logging.getLogger(__name__)

IL_LINEUP_SLOT_MIN = 17  # ESPN lineupSlotId 17+ are IL slots
BENCH_LINEUP_SLOT = 16
PITCHER_BENCH_WEIGHT_SP = 0.95
PITCHER_BENCH_WEIGHT_RP = 0.95


def _bench_weight(player: PlayerProjection) -> float:
    """Bench contribution weight matching roster-optimizer.ts."""
    if player.player_type == "hitter":
        return HITTER_BENCH_WEIGHT
    # SP and RP both use ~0.95 per memory and roster-optimizer.ts
    return PITCHER_BENCH_WEIGHT_SP if player.qs > 0 else PITCHER_BENCH_WEIGHT_RP


def project_team_period(
    roster: list[PlayerProjection],
    period_weight: float,
    il_mlb_ids: Optional[dict[int, bool]] = None,
) -> dict[str, float]:
    """Project a team's category totals for one matchup period.

    Args:
        roster: All non-IL players on the team for this period.
        period_weight: Fraction of full RoS this period represents (e.g. 7/91).
        il_mlb_ids: Mapping of mlb_id → True for IL players. IL players
            contribute 0. Pass None or empty dict for no IL.

    Returns:
        Dict with the 10 H2H category keys (R, TB, RBI, SB, OBP, K, QS,
        ERA, WHIP, SVHD).
    """
    il = il_mlb_ids or {}
    active = [p for p in roster if not il.get(p.mlb_id, False)]

    # Run greedy lineup optimizer on the active roster to identify starters.
    # `optimize_daily_lineup` accepts a list of dicts; convert.
    as_dicts = [
        {
            "mlb_id": p.mlb_id,
            "position": p.position,
            "player_type": p.player_type,
            "eligible_positions": p.eligible_positions or p.position,
        }
        for p in active
    ]
    lineup = optimize_daily_lineup(as_dicts)
    starter_ids = {d["mlb_id"] for d in lineup["starters"]}

    # Build a TeamTotals scaled by period_weight
    totals = TeamTotals()
    for p in active:
        weight = period_weight if p.mlb_id in starter_ids else period_weight * _bench_weight(p)
        totals.add_player(p, weight=weight)

    return totals.category_values()
