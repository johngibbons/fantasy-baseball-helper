"""Full draft simulation engine."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from .config import SimConfig
from .player_pool import (
    Player, KeeperEntry, ALL_CAT_KEYS, HITTING_CAT_KEYS, PITCHING_CAT_KEYS,
    TOTAL_ROSTER_SIZE, keeper_pick_index, build_keeper_adp_list, count_kept_below_adp,
)
from .roster import RosterState
from .scoring_model import (
    analyze_category_standings,
    detect_strategy,
    compute_cat_stats,
    compute_replacement_levels,
    build_available_by_position,
    full_player_score,
    CatStats,
    CategoryStanding,
)
from .rollout import rollout_score


@dataclass
class DraftResult:
    """Result of a single draft simulation."""
    my_slot: int  # 0-indexed draft slot
    my_players: list[Player] = field(default_factory=list)
    all_team_totals: list[dict[str, float]] = field(default_factory=list)  # team_idx -> cat totals
    pick_order: list[int] = field(default_factory=list)  # mlb_ids in pick order for my team
    bench_pitcher_count: int = 0  # pitchers assigned to bench for my team
    sp_count: int = 0
    rp_count: int = 0


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


def _competitive_picks_until_next_turn(
    current_pick: int,
    my_team: int,
    num_teams: int,
    keeper_indices: set[int],
) -> int:
    """Count non-keeper picks between current_pick and my next turn."""
    count = 0
    for i in range(current_pick + 1, num_teams * 25 + 1):
        if snake_order(i, num_teams) == my_team:
            return count
        if i not in keeper_indices:
            count += 1
    return 999


def simulate_draft(
    all_players: list[Player],
    my_slot: int,
    config: SimConfig,
    rng: random.Random,
    keepers: list[KeeperEntry] | None = None,
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
    my_bench_pitcher_count = 0
    my_sp_count = 0
    my_rp_count = 0
    my_hitter_count = 0

    # ── Keeper setup ──
    keeper_indices: set[int] = set()
    keeper_adps_sorted: list[float] = []

    if keepers:
        # Compute which pick slots are pre-assigned to keepers.
        # Handle collisions: in the real league, traded picks let a team have
        # multiple picks per round, but the simulation uses pure snake. If two
        # keepers from the same team map to the same pick index, find a nearby
        # slot owned by that team.
        team_used_indices: dict[int, set[int]] = {}
        for k in keepers:
            idx = keeper_pick_index(k.team_idx, k.round_cost, num_teams)
            if idx >= total_picks:
                continue
            used = team_used_indices.setdefault(k.team_idx, set())
            if idx in keeper_indices:
                # Collision — find nearest open pick for this team
                found = False
                for offset in range(1, num_rounds):
                    for candidate_round in [k.round_cost + offset, k.round_cost - offset]:
                        if candidate_round < 1 or candidate_round > num_rounds:
                            continue
                        alt_idx = keeper_pick_index(k.team_idx, candidate_round, num_teams)
                        if alt_idx not in keeper_indices and alt_idx not in used:
                            keeper_indices.add(alt_idx)
                            used.add(alt_idx)
                            found = True
                            break
                    if found:
                        break
            else:
                keeper_indices.add(idx)
                used.add(idx)

        # Build sorted keeper ADP list for effective ADP calculation
        keeper_adps_sorted = build_keeper_adp_list(keepers, player_by_id)

        # Pre-assign keeper players to their teams
        for k in keepers:
            p = player_by_id.get(k.mlb_id)
            if p is None or p.mlb_id not in available_set:
                continue
            team_idx = k.team_idx
            available_set.discard(p.mlb_id)
            assigned_slot = rosters[team_idx].add_player(p)
            weight = 1.0
            if assigned_slot == "BE":
                weight = config.PITCHER_BENCH_CONTRIBUTION if p.player_type == "pitcher" else config.HITTER_BENCH_CONTRIBUTION
                if team_idx == my_slot and p.player_type == "pitcher":
                    my_bench_pitcher_count += 1
            for cat_key in ALL_CAT_KEYS:
                team_totals[team_idx][cat_key] += p.zscores.get(cat_key, 0.0) * weight
            team_players[team_idx].append(p)

            if team_idx == my_slot:
                my_pick_count += 1
                if p.player_type == "pitcher":
                    if p.pitcher_role() == "SP":
                        my_sp_count += 1
                    else:
                        my_rp_count += 1
                else:
                    my_hitter_count += 1

    # Precompute ADP-sorted order for opponent picks (rebuilt when pool changes significantly)
    # We'll sort once and maintain it lazily
    cat_stats: dict[str, CatStats] = {}
    replacement_levels: dict[str, float] = {}
    cat_stats_round: int = -1  # last round we computed cat_stats

    result = DraftResult(my_slot=my_slot)

    # Add my keepers to result
    if keepers:
        for k in keepers:
            if k.team_idx == my_slot:
                p = player_by_id.get(k.mlb_id)
                if p:
                    result.my_players.append(p)
                    result.pick_order.append(p.mlb_id)

    # Track competitive (non-keeper) picks made so far
    competitive_picks_so_far = 0

    for pick_idx in range(total_picks):
        # Skip keeper pick slots
        if pick_idx in keeper_indices:
            continue

        team_idx = snake_order(pick_idx, num_teams)
        current_round = pick_idx // num_teams

        if not available_set:
            break

        if team_idx == my_slot:
            # === MY PICK: use full scoring model ===

            # Recompute catStats at round boundaries
            if current_round != cat_stats_round:
                avail_players = [p for p in available_list if p.mlb_id in available_set]
                # Restrict normalization pool to draftable universe
                if config.RESTRICT_NORM_POOL:
                    draftable_limit = num_teams * num_rounds
                    norm_pool = sorted(avail_players, key=lambda p: p.overall_rank)[:draftable_limit]
                else:
                    norm_pool = avail_players
                cat_stats = compute_cat_stats(norm_pool)
                replacement_levels = compute_replacement_levels(avail_players, cat_stats, num_teams)
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

            # Compute keeper-adjusted pick counts for urgency
            if keeper_indices:
                pum = _competitive_picks_until_next_turn(pick_idx, my_slot, num_teams, keeper_indices)
            else:
                pum = picks_until_next_turn(pick_idx, my_slot, num_teams)

            best_score = float("-inf")
            best_player: Player | None = None
            scored_candidates: list[tuple[float, Player]] = []

            for p in avail_players:
                if not rosters[my_slot].can_add(p):
                    continue
                has_need = rosters[my_slot].has_starting_need(p)

                # Composition steering: once target is met, treat as bench pick
                if has_need and p.player_type == "pitcher":
                    role = p.pitcher_role()
                    if role == "SP" and config.TARGET_SP is not None and my_sp_count >= config.TARGET_SP:
                        has_need = False
                    elif role == "RP" and config.TARGET_RP is not None and my_rp_count >= config.TARGET_RP:
                        has_need = False
                if has_need and p.player_type == "hitter" and config.MAX_HITTERS is not None and my_hitter_count >= config.MAX_HITTERS:
                    has_need = False

                if config.USE_SLOT_SCARCITY and has_need:
                    roster_need = rosters[my_slot].slot_scarcity(p)
                else:
                    roster_need = 1.0 if has_need else 0.0

                # Keeper-adjusted current_pick for urgency/availability
                effective_current_pick = competitive_picks_so_far if keeper_indices else pick_idx

                score = full_player_score(
                    player=p,
                    my_totals=team_totals[my_slot],
                    other_team_totals=other_team_totals,
                    strategies=strategies,
                    cat_stats=cat_stats,
                    available_by_position=available_by_position,
                    has_starting_need=roster_need,
                    current_pick=effective_current_pick,
                    picks_until_mine=pum,
                    total_picks_made=pick_idx,
                    my_pick_count=my_pick_count,
                    config=config,
                    bench_pitcher_count=my_bench_pitcher_count,
                    replacement_levels=replacement_levels,
                    keeper_adps_sorted=keeper_adps_sorted,
                    standings=standings,
                )
                scored_candidates.append((score, p))
                if score > best_score:
                    best_score = score
                    best_player = p

            # Rollout re-ranking: simulate rest of draft for top candidates
            if config.USE_ROLLOUT and pick_idx >= config.ROLLOUT_MIN_PICK and best_player is not None:
                scored_candidates.sort(key=lambda x: x[0], reverse=True)
                top_candidates = [p for _, p in scored_candidates[:config.ROLLOUT_TOP_N]]

                # Build remaining pick schedule (team indices for all future picks)
                remaining_schedule: list[int] = []
                for future_idx in range(pick_idx + 1, total_picks):
                    if future_idx in keeper_indices:
                        continue
                    remaining_schedule.append(snake_order(future_idx, num_teams))

                # ADP-sorted player list for deterministic rollout picks
                adp_sorted = sorted(
                    [p for p in available_list if p.mlb_id in available_set],
                    key=lambda p: p.blended_adp if p.blended_adp is not None else 999.0,
                )

                # Run rollout for each top candidate
                best_rollout = float("-inf")
                best_rollout_player: Player | None = None
                for p in top_candidates:
                    projected_wins = rollout_score(
                        candidate=p,
                        my_slot=my_slot,
                        available_set=available_set,
                        adp_sorted=adp_sorted,
                        player_by_id=player_by_id,
                        rosters=rosters,
                        team_totals=team_totals,
                        pick_schedule=remaining_schedule,
                        config=config,
                    )
                    if projected_wins > best_rollout:
                        best_rollout = projected_wins
                        best_rollout_player = p

                if best_rollout_player is not None:
                    best_player = best_rollout_player

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
            # === OPPONENT PICK: ADP + noise + roster need ===
            opp_sigma = -1.0 if config.USE_VARIABLE_SIGMA else config.ADP_SIGMA
            chosen = _opponent_pick(
                available_list, available_set, player_by_id,
                rosters[team_idx], rng, opp_sigma,
                config.OPP_BENCH_ADP_PENALTY,
                team_totals=team_totals[team_idx],
                scarcity_bonus=config.OPP_SCARCITY_BONUS,
                cat_need_bonus=config.OPP_CAT_NEED_BONUS,
            )
            if chosen is None:
                continue

        # Update state
        available_set.discard(chosen.mlb_id)
        assigned_slot = rosters[team_idx].add_player(chosen)
        if assigned_slot == "BE":
            weight = config.PITCHER_BENCH_CONTRIBUTION if chosen.player_type == "pitcher" else config.HITTER_BENCH_CONTRIBUTION
            if team_idx == my_slot and chosen.player_type == "pitcher":
                my_bench_pitcher_count += 1
        else:
            weight = 1.0
        for cat_key in ALL_CAT_KEYS:
            team_totals[team_idx][cat_key] += chosen.zscores.get(cat_key, 0.0) * weight
        team_players[team_idx].append(chosen)

        # Track SP/RP/hitter counts for our team
        if team_idx == my_slot:
            if chosen.player_type == "pitcher":
                if chosen.pitcher_role() == "SP":
                    my_sp_count += 1
                else:
                    my_rp_count += 1
            else:
                my_hitter_count += 1

        competitive_picks_so_far += 1

    result.all_team_totals = team_totals
    result.bench_pitcher_count = my_bench_pitcher_count
    result.sp_count = my_sp_count
    result.rp_count = my_rp_count
    return result


def _category_need_bonus(player: Player, team_totals: dict[str, float], bonus_per_cat: float) -> float:
    """Small ADP bonus for players helping a team's weakest categories."""
    cats = PITCHING_CAT_KEYS if player.player_type == "pitcher" else HITTING_CAT_KEYS
    # Find weakest 2 categories for this player type
    cat_vals = [(k, team_totals.get(k, 0.0)) for k in cats]
    cat_vals.sort(key=lambda x: x[1])
    weak_cats = {k for k, _ in cat_vals[:2]}

    bonus = 0.0
    for cat_key in weak_cats:
        if player.zscores.get(cat_key, 0.0) > 0.5:
            bonus += bonus_per_cat
    return bonus


def _opponent_pick(
    available_list: list[Player],
    available_set: set[int],
    player_by_id: dict[int, Player],
    roster: RosterState,
    rng: random.Random,
    adp_sigma: float,
    bench_adp_penalty: float,
    team_totals: dict[str, float] | None = None,
    scarcity_bonus: float = 15.0,
    cat_need_bonus: float = 4.0,
) -> Player | None:
    """Opponent picks by ADP + noise, with positional scarcity and category need bonuses.

    - Bench-only players get a penalty added to their effective ADP.
    - Players filling scarce starting slots get a bonus (lower effective ADP).
    - Players helping a team's weakest categories get a small bonus.
    """
    candidates: list[tuple[float, int]] = []
    for p in available_list:
        if p.mlb_id not in available_set:
            continue
        adp = p.blended_adp if p.blended_adp is not None else 999.0
        effective_sigma = (10.0 + 0.1 * adp) if adp_sigma < 0 else adp_sigma
        noisy_adp = adp + rng.gauss(0, effective_sigma)

        # Bench penalty or positional scarcity bonus
        if not roster.has_starting_need(p):
            noisy_adp += bench_adp_penalty
        else:
            scarcity = roster.slot_scarcity(p)
            noisy_adp -= scarcity * scarcity_bonus

        # Category need bonus
        if team_totals and cat_need_bonus > 0:
            noisy_adp -= _category_need_bonus(p, team_totals, cat_need_bonus)

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
