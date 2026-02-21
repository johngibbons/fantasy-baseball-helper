"""Full draft simulation engine."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from .config import SimConfig
from .player_pool import Player, ALL_CAT_KEYS, TOTAL_ROSTER_SIZE, BENCH_CONTRIBUTION
from .roster import RosterState
from .scoring_model import (
    analyze_category_standings,
    detect_strategy,
    compute_cat_stats,
    build_available_by_position,
    full_player_score,
    CatStats,
)


@dataclass
class DraftResult:
    """Result of a single draft simulation."""
    my_slot: int  # 0-indexed draft slot
    my_players: list[Player] = field(default_factory=list)
    all_team_totals: list[dict[str, float]] = field(default_factory=list)  # team_idx -> cat totals
    pick_order: list[int] = field(default_factory=list)  # mlb_ids in pick order for my team


def snake_order(pick_index: int, num_teams: int) -> int:
    """Return team index (0-based) for a given overall pick index in snake draft."""
    rnd = pick_index // num_teams
    pos = pick_index % num_teams
    if rnd % 2 == 0:
        return pos
    return num_teams - 1 - pos


def picks_until_next_turn(current_pick: int, my_team: int, num_teams: int) -> int:
    """How many picks until my_team picks again after current_pick."""
    for i in range(current_pick + 1, num_teams * 25 + 1):
        if snake_order(i, num_teams) == my_team:
            return i - current_pick
    return 999


def simulate_draft(
    all_players: list[Player],
    my_slot: int,
    config: SimConfig,
    rng: random.Random,
) -> DraftResult:
    """Run a single draft simulation. my_slot is 0-indexed."""
    num_teams = config.NUM_TEAMS
    num_rounds = config.NUM_ROUNDS
    total_picks = num_teams * num_rounds

    # Build player lookup
    player_by_id: dict[int, Player] = {p.mlb_id: p for p in all_players}
    available_set: set[int] = {p.mlb_id for p in all_players}
    available_list: list[Player] = list(all_players)  # maintained for quick iteration

    # Per-team state
    rosters = [RosterState() for _ in range(num_teams)]
    team_totals: list[dict[str, float]] = [
        {k: 0.0 for k in ALL_CAT_KEYS} for _ in range(num_teams)
    ]
    team_players: list[list[Player]] = [[] for _ in range(num_teams)]
    my_pick_count = 0

    # Precompute ADP-sorted order for opponent picks (rebuilt when pool changes significantly)
    # We'll sort once and maintain it lazily
    cat_stats: dict[str, CatStats] = {}
    cat_stats_round: int = -1  # last round we computed cat_stats

    result = DraftResult(my_slot=my_slot)

    for pick_idx in range(total_picks):
        team_idx = snake_order(pick_idx, num_teams)
        current_round = pick_idx // num_teams

        if not available_set:
            break

        if team_idx == my_slot:
            # === MY PICK: use full scoring model ===

            # Recompute catStats at round boundaries
            if current_round != cat_stats_round:
                avail_players = [p for p in available_list if p.mlb_id in available_set]
                cat_stats = compute_cat_stats(avail_players)
                cat_stats_round = current_round

            avail_players = [p for p in available_list if p.mlb_id in available_set]
            available_by_position = build_available_by_position(avail_players, cat_stats)

            # Build other team totals (sorted desc per category)
            other_team_totals: dict[str, list[float]] = {}
            for cat_key in ALL_CAT_KEYS:
                vals = [
                    team_totals[t][cat_key]
                    for t in range(num_teams)
                    if t != my_slot
                ]
                vals.sort(reverse=True)
                other_team_totals[cat_key] = vals

            # Build strategy map
            standings = analyze_category_standings(
                team_totals[my_slot], other_team_totals, num_teams
            )
            standings = detect_strategy(standings, my_pick_count, num_teams, config.PLAYOFF_SPOTS)
            strategies = {s.cat_key: s.strategy for s in standings}

            pum = picks_until_next_turn(pick_idx, my_slot, num_teams)

            best_score = float("-inf")
            best_player: Player | None = None

            for p in avail_players:
                if not rosters[my_slot].can_add(p):
                    continue
                has_need = rosters[my_slot].has_starting_need(p)
                score = full_player_score(
                    player=p,
                    my_totals=team_totals[my_slot],
                    other_team_totals=other_team_totals,
                    strategies=strategies,
                    cat_stats=cat_stats,
                    available_by_position=available_by_position,
                    has_starting_need=has_need,
                    current_pick=pick_idx,
                    picks_until_mine=pum,
                    total_picks_made=pick_idx,
                    my_pick_count=my_pick_count,
                    config=config,
                )
                if score > best_score:
                    best_score = score
                    best_player = p

            if best_player is None:
                # Fallback: just pick best available that fits
                for p in avail_players:
                    if rosters[my_slot].can_add(p):
                        best_player = p
                        break

            if best_player is None:
                continue

            chosen = best_player
            my_pick_count += 1
            result.my_players.append(chosen)
            result.pick_order.append(chosen.mlb_id)

        else:
            # === OPPONENT PICK: ADP + noise ===
            chosen = _opponent_pick(
                available_list, available_set, player_by_id,
                rosters[team_idx], rng, config.ADP_SIGMA,
            )
            if chosen is None:
                continue

        # Update state
        available_set.discard(chosen.mlb_id)
        assigned_slot = rosters[team_idx].add_player(chosen)
        weight = BENCH_CONTRIBUTION if assigned_slot == "BE" else 1.0
        for cat_key in ALL_CAT_KEYS:
            team_totals[team_idx][cat_key] += chosen.zscores.get(cat_key, 0.0) * weight
        team_players[team_idx].append(chosen)

    result.all_team_totals = team_totals
    return result


def _opponent_pick(
    available_list: list[Player],
    available_set: set[int],
    player_by_id: dict[int, Player],
    roster: RosterState,
    rng: random.Random,
    adp_sigma: float,
) -> Player | None:
    """Opponent picks by ADP + gaussian noise, first that fits roster."""
    candidates: list[tuple[float, int]] = []
    for p in available_list:
        if p.mlb_id not in available_set:
            continue
        adp = p.espn_adp if p.espn_adp is not None else 999.0
        noisy_adp = adp + rng.gauss(0, adp_sigma)
        candidates.append((noisy_adp, p.mlb_id))

    candidates.sort(key=lambda x: x[0])

    for _, mlb_id in candidates:
        p = player_by_id[mlb_id]
        if roster.can_add(p):
            return p

    # Fallback: take anyone
    for _, mlb_id in candidates:
        return player_by_id[mlb_id]

    return None
