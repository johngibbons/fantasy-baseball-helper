"""Trade suggestion engine.

Computes mutually beneficial trade suggestions between teams using
MCW (expected wins delta) analysis and z-score fairness filtering.
Reuses shared infrastructure from the waiver wire engine.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from itertools import combinations
from typing import Optional

from backend.analysis.waivers import (
    ALL_CATS,
    PlayerProjection,
    TeamTotals,
    build_team_totals,
    compute_expected_wins,
    load_projections_for_players,
    resolve_espn_names_to_mlbid,
)
from backend.database import get_connection

logger = logging.getLogger(__name__)


# ── Data structures ──────────────────────────────────────────────────────────


@dataclass
class TradePlayerInfo:
    mlb_id: int
    name: str
    position: str
    total_zscore: float
    weight: float = 1.0           # current weight on source team
    incoming_weight: float = 1.0  # projected weight on destination team


@dataclass
class DraftPickAdjustment:
    round: int
    giving_team: str  # "me" or "them"
    zscore_value: float


@dataclass
class TradeSuggestion:
    partner_team_id: int
    partner_team_name: str
    my_players_out: list[TradePlayerInfo]
    their_players_out: list[TradePlayerInfo]
    draft_pick_adjustment: Optional[DraftPickAdjustment]
    my_delta_wins: float
    their_delta_wins: float
    fairness_score: float  # -1 to +1, 0 = perfectly fair
    acceptance_probability: float  # 0 to 1
    my_category_impact: dict[str, float]
    their_category_impact: dict[str, float]
    trade_type: str  # "1-for-1", "2-for-1", "2-for-2"


# ── Draft pick z-score values ────────────────────────────────────────────────

DRAFT_PICK_VALUES = {
    1: 8.0, 2: 6.0, 3: 4.5, 4: 3.0, 5: 2.5,
    6: 2.0, 7: 1.5, 8: 1.0, 9: 0.5, 10: 0.3,
}


def _pick_zscore(round_num: int) -> float:
    return DRAFT_PICK_VALUES.get(round_num, 0.0)


# ── Z-score loading ──────────────────────────────────────────────────────────


def _load_zscores(mlb_ids: list[int], season: int) -> dict[int, float]:
    """Load total_zscore from rankings table for a set of players."""
    if not mlb_ids:
        return {}
    conn = get_connection()
    placeholders = ",".join(["?"] * len(mlb_ids))
    rows = conn.execute(
        f"SELECT mlb_id, total_zscore FROM rankings WHERE mlb_id IN ({placeholders}) AND season = ?",
        (*mlb_ids, season),
    ).fetchall()
    conn.close()
    return {row["mlb_id"]: row["total_zscore"] or 0.0 for row in rows}


# ── Fairness scoring ─────────────────────────────────────────────────────────


def _compute_fairness(my_zscore_out: float, their_zscore_out: float) -> float:
    """Fairness score: positive means I'm getting more value."""
    avg = (abs(my_zscore_out) + abs(their_zscore_out)) / 2
    if avg < 0.1:
        return 0.0
    return (their_zscore_out - my_zscore_out) / max(avg, 1.0)


def _acceptance_probability(fairness_score: float) -> float:
    """Sigmoid-based acceptance probability. Fair trades ~0.7, lopsided ~0.1."""
    # Negative fairness = they're getting less value, less likely to accept
    return 1.0 / (1.0 + math.exp(2.0 * fairness_score))


# ── Core engine ──────────────────────────────────────────────────────────────


def compute_trade_suggestions(
    my_roster: list[dict],
    all_team_rosters: list[dict],
    my_team_index: int,
    season: int,
    max_trade_size: int = 2,
    fairness_threshold: float = 0.5,
    include_draft_picks: bool = False,
    max_tradeable_per_team: int = 15,
) -> dict:
    """Compute trade suggestions across all opponent teams.

    Args:
        my_roster: [{mlb_id, lineup_slot_id}] for my team
        all_team_rosters: [{team_id, team_name, players: [{mlb_id, lineup_slot_id}]}]
        my_team_index: index of my team in all_team_rosters
        season: season year
        max_trade_size: max players per side (1 or 2)
        fairness_threshold: max abs(fairness_score) to include
        include_draft_picks: whether to suggest draft pick compensation
        max_tradeable_per_team: cap tradeable players per team

    Returns:
        Dict with baseline_expected_wins, suggestions list, computation_stats.
    """
    # Collect all player IDs
    all_ids = set()
    for slot in my_roster:
        all_ids.add(slot["mlb_id"])
    for team in all_team_rosters:
        for slot in team["players"]:
            all_ids.add(slot["mlb_id"])

    all_ids_list = list(all_ids)
    projections = load_projections_for_players(all_ids_list, season)
    zscores = _load_zscores(all_ids_list, season)

    # Build my team totals using lineup optimization
    my_totals, my_weights = build_team_totals(my_roster, projections)

    # Build all other teams' totals
    other_team_totals_list: list[TeamTotals] = []
    other_team_weights: list[dict[int, float]] = []
    for i, team in enumerate(all_team_rosters):
        if i == my_team_index:
            other_team_totals_list.append(TeamTotals())  # placeholder
            other_team_weights.append({})
            continue
        tt, tw = build_team_totals(team["players"], projections)
        other_team_totals_list.append(tt)
        other_team_weights.append(tw)

    # Build league context: other teams' category values (excluding my team)
    league_cat_values = []
    for i, tt in enumerate(other_team_totals_list):
        if i == my_team_index:
            continue
        league_cat_values.append(tt.category_values())

    # Baseline expected wins for my team
    my_cat_values = my_totals.category_values()
    baseline_wins, baseline_cat_probs = compute_expected_wins(my_cat_values, league_cat_values)

    # Identify my tradeable players (exclude IL)
    my_tradeable = _get_tradeable_players(
        my_roster, projections, zscores, max_tradeable_per_team
    )

    suggestions: list[TradeSuggestion] = []
    trades_evaluated = 0
    trades_pruned = 0

    for i, team in enumerate(all_team_rosters):
        if i == my_team_index:
            continue

        their_totals = other_team_totals_list[i]
        their_weights = other_team_weights[i]

        # Their baseline expected wins (league context excludes them)
        their_league_cat_values = []
        for j, tt in enumerate(other_team_totals_list):
            if j == my_team_index or j == i:
                continue
            their_league_cat_values.append(tt.category_values())
        their_league_cat_values.append(my_cat_values)  # my team is part of their opponents

        their_cat_values = their_totals.category_values()
        their_baseline_wins, their_baseline_cat_probs = compute_expected_wins(
            their_cat_values, their_league_cat_values
        )

        # Their tradeable players
        their_tradeable = _get_tradeable_players(
            [{"mlb_id": s["mlb_id"], "lineup_slot_id": s.get("lineup_slot_id", 0)}
             for s in team["players"]],
            projections, zscores, max_tradeable_per_team
        )

        if not my_tradeable or not their_tradeable:
            continue

        # Generate candidate trades
        candidates = _generate_candidates(my_tradeable, their_tradeable, max_trade_size)

        for my_out_ids, their_out_ids in candidates:
            trades_evaluated += 1

            # Z-score pre-filter
            my_z_sum = sum(zscores.get(pid, 0.0) for pid in my_out_ids)
            their_z_sum = sum(zscores.get(pid, 0.0) for pid in their_out_ids)
            fairness = _compute_fairness(my_z_sum, their_z_sum)

            if abs(fairness) > fairness_threshold * 2:
                trades_pruned += 1
                continue

            # Simulate trade: swap players
            trial_my = my_totals.copy()
            trial_their = their_totals.copy()

            for pid in my_out_ids:
                proj = projections.get(pid)
                if proj:
                    trial_my.remove_player(proj, my_weights.get(pid, 1.0))
                    trial_their.add_player(proj, 1.0)  # assume starter weight on new team

            for pid in their_out_ids:
                proj = projections.get(pid)
                if proj:
                    trial_their.remove_player(proj, their_weights.get(pid, 1.0))
                    trial_my.add_player(proj, 1.0)  # assume starter weight on my team

            # Recompute expected wins for my team
            trial_my_cat = trial_my.category_values()

            # Rebuild league context post-trade (their team changed too)
            post_trade_league_cat = []
            for j, tt in enumerate(other_team_totals_list):
                if j == my_team_index:
                    continue
                if j == i:
                    post_trade_league_cat.append(trial_their.category_values())
                else:
                    post_trade_league_cat.append(tt.category_values())

            my_new_wins, my_new_cat_probs = compute_expected_wins(trial_my_cat, post_trade_league_cat)
            my_delta = my_new_wins - baseline_wins

            # Early exit: skip if I don't improve
            if my_delta <= 0:
                continue

            # Recompute expected wins for their team
            trial_their_cat = trial_their.category_values()
            post_trade_their_league = []
            for j, tt in enumerate(other_team_totals_list):
                if j == my_team_index or j == i:
                    continue
                post_trade_their_league.append(tt.category_values())
            post_trade_their_league.append(trial_my_cat)  # my post-trade totals

            their_new_wins, their_new_cat_probs = compute_expected_wins(
                trial_their_cat, post_trade_their_league
            )
            their_delta = their_new_wins - their_baseline_wins

            # Both sides must improve
            if their_delta <= 0:
                continue

            # Fairness check
            if abs(fairness) > fairness_threshold:
                # If draft picks enabled, try to find a balancing pick
                if include_draft_picks:
                    pick_adj = _find_balancing_pick(fairness, my_z_sum, their_z_sum)
                    if pick_adj and abs(_compute_fairness(
                        my_z_sum + (pick_adj.zscore_value if pick_adj.giving_team == "me" else 0),
                        their_z_sum + (pick_adj.zscore_value if pick_adj.giving_team == "them" else 0),
                    )) <= fairness_threshold:
                        pass  # pick balances it out
                    else:
                        continue
                else:
                    continue
            else:
                pick_adj = None

            # Determine trade type
            n_my = len(my_out_ids)
            n_their = len(their_out_ids)
            if n_my == 1 and n_their == 1:
                trade_type = "1-for-1"
            elif (n_my == 2 and n_their == 1) or (n_my == 1 and n_their == 2):
                trade_type = "2-for-1"
            else:
                trade_type = "2-for-2"

            # Category impact
            my_cat_impact = {
                cat: round(my_new_cat_probs[cat] - baseline_cat_probs[cat], 4)
                for cat in ALL_CATS
            }
            their_cat_impact = {
                cat: round(their_new_cat_probs[cat] - their_baseline_cat_probs[cat], 4)
                for cat in ALL_CATS
            }

            suggestions.append(TradeSuggestion(
                partner_team_id=team.get("team_id", i),
                partner_team_name=team.get("team_name", f"Team {i}"),
                my_players_out=[
                    TradePlayerInfo(
                        mlb_id=pid,
                        name=projections[pid].name if pid in projections else f"Player {pid}",
                        position=projections[pid].position if pid in projections else "",
                        total_zscore=zscores.get(pid, 0.0),
                    )
                    for pid in my_out_ids
                ],
                their_players_out=[
                    TradePlayerInfo(
                        mlb_id=pid,
                        name=projections[pid].name if pid in projections else f"Player {pid}",
                        position=projections[pid].position if pid in projections else "",
                        total_zscore=zscores.get(pid, 0.0),
                    )
                    for pid in their_out_ids
                ],
                draft_pick_adjustment=pick_adj,
                my_delta_wins=round(my_delta, 4),
                their_delta_wins=round(their_delta, 4),
                fairness_score=round(fairness, 4),
                acceptance_probability=round(_acceptance_probability(fairness), 4),
                my_category_impact=my_cat_impact,
                their_category_impact=their_cat_impact,
                trade_type=trade_type,
            ))

    # Sort by my delta wins descending
    suggestions.sort(key=lambda s: s.my_delta_wins, reverse=True)

    return {
        "baseline_expected_wins": round(baseline_wins, 3),
        "baseline_category_probs": {cat: round(v, 4) for cat, v in baseline_cat_probs.items()},
        "suggestions": [_suggestion_to_dict(s) for s in suggestions],
        "computation_stats": {
            "trades_evaluated": trades_evaluated,
            "trades_pruned": trades_pruned,
            "suggestions_found": len(suggestions),
            "opponent_teams": len(all_team_rosters) - 1,
        },
    }


# ── Helpers ──────────────────────────────────────────────────────────────────


def _get_tradeable_players(
    roster_slots: list[dict],
    projections: dict[int, PlayerProjection],
    zscores: dict[int, float],
    max_players: int,
) -> list[int]:
    """Get tradeable player IDs sorted by z-score desc, excluding IL."""
    candidates = []
    for slot in roster_slots:
        pid = slot["mlb_id"]
        slot_id = slot.get("lineup_slot_id", 0)
        if slot_id >= 17:  # IL
            continue
        if pid not in projections:
            continue
        candidates.append((pid, zscores.get(pid, 0.0)))

    candidates.sort(key=lambda x: x[1], reverse=True)
    return [pid for pid, _ in candidates[:max_players]]


def _generate_candidates(
    my_players: list[int],
    their_players: list[int],
    max_size: int,
) -> list[tuple[list[int], list[int]]]:
    """Generate all trade candidate pairs up to max_size per side."""
    candidates = []

    # 1-for-1
    for my_id in my_players:
        for their_id in their_players:
            candidates.append(([my_id], [their_id]))

    if max_size >= 2:
        # 2-for-1
        for my_pair in combinations(my_players, 2):
            for their_id in their_players:
                candidates.append((list(my_pair), [their_id]))

        # 1-for-2
        for my_id in my_players:
            for their_pair in combinations(their_players, 2):
                candidates.append(([my_id], list(their_pair)))

        # 2-for-2
        for my_pair in combinations(my_players, 2):
            for their_pair in combinations(their_players, 2):
                candidates.append((list(my_pair), list(their_pair)))

    return candidates


def _find_balancing_pick(
    fairness: float,
    my_zscore_out: float,
    their_zscore_out: float,
) -> Optional[DraftPickAdjustment]:
    """Find a draft pick that would balance a lopsided trade."""
    gap = abs(their_zscore_out - my_zscore_out)
    giving_team = "me" if fairness > 0 else "them"

    for rnd in range(1, 11):
        pick_val = _pick_zscore(rnd)
        if pick_val <= gap * 1.5 and pick_val >= gap * 0.5:
            return DraftPickAdjustment(round=rnd, giving_team=giving_team, zscore_value=pick_val)

    return None


def _suggestion_to_dict(s: TradeSuggestion) -> dict:
    return {
        "partner_team_id": s.partner_team_id,
        "partner_team_name": s.partner_team_name,
        "my_players_out": [
            {"mlb_id": p.mlb_id, "name": p.name, "position": p.position,
             "total_zscore": p.total_zscore, "weight": p.weight,
             "incoming_weight": p.incoming_weight}
            for p in s.my_players_out
        ],
        "their_players_out": [
            {"mlb_id": p.mlb_id, "name": p.name, "position": p.position,
             "total_zscore": p.total_zscore, "weight": p.weight,
             "incoming_weight": p.incoming_weight}
            for p in s.their_players_out
        ],
        "draft_pick_adjustment": {
            "round": s.draft_pick_adjustment.round,
            "giving_team": s.draft_pick_adjustment.giving_team,
            "zscore_value": s.draft_pick_adjustment.zscore_value,
        } if s.draft_pick_adjustment else None,
        "my_delta_wins": s.my_delta_wins,
        "their_delta_wins": s.their_delta_wins,
        "fairness_score": s.fairness_score,
        "acceptance_probability": s.acceptance_probability,
        "my_category_impact": s.my_category_impact,
        "their_category_impact": s.their_category_impact,
        "trade_type": s.trade_type,
    }
