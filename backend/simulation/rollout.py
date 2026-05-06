"""Rollout-based player scoring: simulate the rest of the draft to evaluate each candidate.

Instead of myopic MCW ("how much does this one pick help NOW?"), rollout scoring asks
"how much does picking this player change my projected end-of-draft outcome?"

For each candidate:
1. Tentatively add them to my team
2. Simulate the remaining draft picks deterministically (ADP + positional need)
3. Evaluate my final team's expected weekly wins
4. Score = projected expected wins

This naturally captures trajectory value: if picking an SP now leads to a team that's
competitive in QS/K by end of draft, the rollout score will be high — even if the
single-pick MCW would be tiny.
"""

from __future__ import annotations

from .config import SimConfig
from .player_pool import Player, ALL_CAT_KEYS, HITTING_CAT_KEYS, PITCHING_CAT_KEYS
from .roster import RosterState
from .scoring_model import compute_rank, win_prob_from_rank


def _category_need_bonus(player: Player, team_totals: dict[str, float], bonus_per_cat: float) -> float:
    """Small ADP bonus for players helping a team's weakest categories."""
    cats = PITCHING_CAT_KEYS if player.player_type == "pitcher" else HITTING_CAT_KEYS
    cat_vals = [(k, team_totals.get(k, 0.0)) for k in cats]
    cat_vals.sort(key=lambda x: x[1])
    weak_cats = {k for k, _ in cat_vals[:2]}

    bonus = 0.0
    for cat_key in weak_cats:
        if player.zscores.get(cat_key, 0.0) > 0.5:
            bonus += bonus_per_cat
    return bonus


def _deterministic_pick(
    available_set: set[int],
    adp_sorted: list[Player],
    player_by_id: dict[int, Player],
    roster: RosterState,
    team_totals: dict[str, float],
    config: SimConfig,
) -> Player | None:
    """Pick deterministically by ADP + positional scarcity + category need (no noise).

    Since adp_sorted is in ADP order and bonuses are bounded, we can early-exit
    once raw ADP exceeds our best score by more than the max possible bonus.
    """
    max_bonus = config.OPP_SCARCITY_BONUS + config.OPP_CAT_NEED_BONUS * 2
    best_score = float("inf")
    best_player: Player | None = None

    for p in adp_sorted:
        if p.mlb_id not in available_set:
            continue

        raw_adp = p.blended_adp if p.blended_adp is not None else 999.0

        # Early exit: if raw ADP is already worse than best even with max bonus, stop
        if raw_adp - max_bonus > best_score:
            break

        effective_adp = raw_adp
        if not roster.has_starting_need(p):
            effective_adp += config.OPP_BENCH_ADP_PENALTY
        else:
            scarcity = roster.slot_scarcity(p)
            effective_adp -= scarcity * config.OPP_SCARCITY_BONUS
            effective_adp -= _category_need_bonus(p, team_totals, config.OPP_CAT_NEED_BONUS)

        if effective_adp < best_score:
            best_score = effective_adp
            best_player = p

    if best_player is not None and roster.can_add(best_player):
        return best_player

    # Fallback: first available that fits
    for p in adp_sorted:
        if p.mlb_id in available_set and roster.can_add(p):
            return p

    return None


def _evaluate_team(
    my_totals: dict[str, float],
    all_team_totals: list[dict[str, float]],
    my_slot: int,
    num_teams: int,
) -> float:
    """Compute expected weekly wins for my team against final standings."""
    total_win_prob = 0.0
    for cat_key in ALL_CAT_KEYS:
        other_vals = sorted(
            [all_team_totals[t][cat_key] for t in range(num_teams) if t != my_slot],
            reverse=True,
        )
        rank = compute_rank(my_totals[cat_key], other_vals)
        total_win_prob += win_prob_from_rank(rank, num_teams)
    return total_win_prob


def rollout_score(
    candidate: Player,
    my_slot: int,
    available_set: set[int],
    adp_sorted: list[Player],
    player_by_id: dict[int, Player],
    rosters: list[RosterState],
    team_totals: list[dict[str, float]],
    pick_schedule: list[int],
    config: SimConfig,
) -> float:
    """Score a candidate by simulating the rest of the draft after picking them.

    Args:
        candidate: Player to evaluate
        my_slot: My team index (0-based)
        available_set: Set of available player mlb_ids (will NOT be modified)
        adp_sorted: All players sorted by ADP (for efficient opponent picks)
        player_by_id: Player lookup by mlb_id
        rosters: Current roster states per team (will NOT be modified)
        team_totals: Current z-score totals per team (will NOT be modified)
        pick_schedule: Team index for each remaining pick after this one
        config: Simulation config

    Returns:
        Projected expected weekly wins for my team
    """
    num_teams = config.NUM_TEAMS

    # Copy mutable state
    sim_rosters = [r.copy() for r in rosters]
    sim_totals = [{**t} for t in team_totals]
    sim_available = set(available_set)

    # Add candidate to my team
    sim_available.discard(candidate.mlb_id)
    assigned_slot = sim_rosters[my_slot].add_player(candidate)
    weight = 1.0
    if assigned_slot == "BE":
        if candidate.player_type == "pitcher":
            weight = config.RP_BENCH_CONTRIBUTION if candidate.pitcher_role() == "RP" else config.PITCHER_BENCH_CONTRIBUTION
        else:
            weight = config.HITTER_BENCH_CONTRIBUTION
    for cat_key in ALL_CAT_KEYS:
        sim_totals[my_slot][cat_key] += candidate.zscores.get(cat_key, 0.0) * weight

    # Simulate remaining picks deterministically
    for team_idx in pick_schedule:
        chosen = _deterministic_pick(
            sim_available, adp_sorted, player_by_id,
            sim_rosters[team_idx], sim_totals[team_idx], config,
        )
        if chosen is None:
            continue

        sim_available.discard(chosen.mlb_id)
        slot = sim_rosters[team_idx].add_player(chosen)
        w = 1.0
        if slot == "BE":
            if chosen.player_type == "pitcher":
                w = config.RP_BENCH_CONTRIBUTION if chosen.pitcher_role() == "RP" else config.PITCHER_BENCH_CONTRIBUTION
            else:
                w = config.HITTER_BENCH_CONTRIBUTION
        for cat_key in ALL_CAT_KEYS:
            sim_totals[team_idx][cat_key] += chosen.zscores.get(cat_key, 0.0) * w

    return _evaluate_team(sim_totals[my_slot], sim_totals, my_slot, num_teams)
