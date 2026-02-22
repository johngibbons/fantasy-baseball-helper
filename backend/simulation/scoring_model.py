"""Python port of the TypeScript scoring model from draft-optimizer.ts and page.tsx."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .config import SimConfig
from .player_pool import (
    Player,
    ALL_CAT_KEYS,
    HITTING_CAT_KEYS,
    PITCHING_CAT_KEYS,
    CAT_LABELS,
)


# ── Position demand slots (starting roster, excluding flex) ──
POSITION_DEMAND_SLOTS: dict[str, int] = {
    "C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "SP": 3, "RP": 2,
}

_OF_ALIASES: dict[str, str] = {"LF": "OF", "CF": "OF", "RF": "OF"}


def _normalize_position(pos: str) -> str:
    """Normalize OF sub-positions (LF/CF/RF) to OF."""
    return _OF_ALIASES.get(pos, pos)


# ── Normal CDF (from pick-predictor.ts) ──

def _normal_cdf(x: float) -> float:
    if x < -8:
        return 0.0
    if x > 8:
        return 1.0
    a1 = 0.254829592
    a2 = -0.284496736
    a3 = 1.421413741
    a4 = -1.453152027
    a5 = 1.061405429
    p = 0.3275911
    sign = -1.0 if x < 0 else 1.0
    abs_x = abs(x)
    t = 1.0 / (1.0 + p * abs_x)
    y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(-abs_x * abs_x / 2)
    return 0.5 * (1.0 + sign * y)


def variable_adp_sigma(adp: float) -> float:
    """Compute ADP-dependent sigma: tighter for consensus picks, wider for late rounds."""
    return 10.0 + 0.1 * adp


def compute_availability(espn_adp: float, current_pick: int, picks_until_mine: int, sigma: float = 18.0) -> float:
    target_pick = current_pick + picks_until_mine
    z = (target_pick - espn_adp) / sigma
    return max(0.0, min(1.0, 1.0 - _normal_cdf(z)))


# ── Core ranking functions (from draft-optimizer.ts) ──

def win_prob_from_rank(rank: float, num_teams: int) -> float:
    if num_teams <= 1:
        return 0.5
    return (num_teams - rank) / (num_teams - 1)


def compute_rank(my_value: float, other_totals: list[float]) -> float:
    teams_above = 0
    tied_teams = 0
    for t in other_totals:
        if t > my_value:
            teams_above += 1
        elif t == my_value:
            tied_teams += 1
    return teams_above + 1 + tied_teams / 2


def standings_confidence(total_picks_made: int, config: SimConfig) -> float:
    span = config.CONFIDENCE_END - config.CONFIDENCE_START
    if span <= 0:
        return 1.0
    return max(0.0, min(1.0, (total_picks_made - config.CONFIDENCE_START) / span))


# ── Category standings analysis ──

@dataclass
class CategoryStanding:
    cat_key: str
    my_total: float
    my_rank: float
    win_prob: float
    gap_above: float
    gap_below: float
    strategy: str  # 'target' | 'neutral' | 'punt' | 'lock'


def analyze_category_standings(
    my_totals: dict[str, float],
    other_team_totals: dict[str, list[float]],
    num_teams: int,
) -> list[CategoryStanding]:
    standings: list[CategoryStanding] = []
    for cat_key in ALL_CAT_KEYS:
        my_val = my_totals.get(cat_key, 0.0)
        other_vals = other_team_totals.get(cat_key, [])

        rank = compute_rank(my_val, other_vals)
        win_prob = win_prob_from_rank(rank, num_teams)

        gap_above = 0.0
        teams_above = [v for v in other_vals if v > my_val]
        if teams_above:
            gap_above = min(teams_above, key=lambda v: v - my_val) - my_val

        gap_below = 0.0
        teams_below = [v for v in other_vals if v < my_val]
        if teams_below:
            gap_below = my_val - max(teams_below)

        standings.append(CategoryStanding(
            cat_key=cat_key,
            my_total=my_val,
            my_rank=rank,
            win_prob=win_prob,
            gap_above=gap_above,
            gap_below=gap_below,
            strategy="neutral",
        ))
    return standings


def detect_strategy(
    standings: list[CategoryStanding],
    my_pick_count: int,
    num_teams: int,
    playoff_spots: int = 6,
) -> list[CategoryStanding]:
    if my_pick_count < 6:
        return standings

    playoff_ratio = playoff_spots / num_teams
    punt_gap = 3.0 + (playoff_ratio - 0.4) * 7.5
    punt_rank_floor = num_teams if playoff_ratio >= 0.55 else num_teams - 1
    target_low = 3 if playoff_ratio >= 0.55 else 4
    target_high = 8 if playoff_ratio >= 0.55 else 7

    for s in standings:
        if s.my_rank <= 2 and s.gap_below >= 1.0:
            s.strategy = "lock"
        elif s.my_rank >= punt_rank_floor and s.gap_above >= punt_gap:
            s.strategy = "punt"
        elif target_low <= s.my_rank <= target_high:
            s.strategy = "target"
        else:
            s.strategy = "neutral"

    # Enforce max 2 punts
    punt_cats = [s for s in standings if s.strategy == "punt"]
    punt_cats.sort(key=lambda s: s.my_rank, reverse=True)
    if len(punt_cats) > 2:
        keep = {s.cat_key for s in punt_cats[:2]}
        for s in standings:
            if s.strategy == "punt" and s.cat_key not in keep:
                s.strategy = "neutral"

    return standings


# ── MCW computation ──

def compute_mcw(
    player_zscores: dict[str, float],
    my_totals: dict[str, float],
    other_team_totals: dict[str, list[float]],
    strategies: dict[str, str],
    num_teams: int,
    config: SimConfig | None = None,
) -> float:
    mcw = 0.0
    for cat_key in ALL_CAT_KEYS:
        strategy = strategies.get(cat_key, "neutral")
        if strategy == "punt":
            continue

        my_val = my_totals.get(cat_key, 0.0)
        player_val = player_zscores.get(cat_key, 0.0)

        if player_val == 0:
            continue

        new_val = my_val + player_val
        other_vals = other_team_totals.get(cat_key, [])

        rank_before = compute_rank(my_val, other_vals)
        rank_after = compute_rank(new_val, other_vals)

        win_before = win_prob_from_rank(rank_before, num_teams)
        win_after = win_prob_from_rank(rank_after, num_teams)

        marginal_win = win_after - win_before

        # Fractional credit for closing gaps
        if marginal_win == 0 and player_val > 0:
            teams_above_before = [v for v in other_vals if v > my_val]
            teams_above_after = [v for v in other_vals if v > new_val]
            if teams_above_before and len(teams_above_after) == len(teams_above_before):
                closest_above = min(teams_above_before, key=lambda v: v - my_val)
                gap_before = closest_above - my_val
                gap_after = closest_above - new_val
                if gap_before > 0:
                    gap_closed = (gap_before - gap_after) / gap_before
                    marginal_win = (gap_closed ** 1.5) * 0.55 / (num_teams - 1)

        # Apply strategy multiplier: lock categories get reduced credit,
        # target categories get boosted credit
        if config is not None:
            if strategy == "lock":
                marginal_win *= config.LOCK_MCW_WEIGHT
            elif strategy == "target":
                marginal_win *= config.TARGET_MCW_WEIGHT

        mcw += marginal_win

    return mcw


# ── Draft score blending (from computeDraftScore + page.tsx:784-868) ──

def compute_draft_score(
    mcw: float,
    vona: float,
    urgency: float,
    roster_fit: float,
    confidence: float,
    draft_progress: float,
    config: SimConfig,
) -> float:
    return (
        mcw * config.MCW_WEIGHT * confidence
        + vona * config.VONA_WEIGHT_MCW
        + urgency * config.URGENCY_WEIGHT_MCW
        + roster_fit * draft_progress
    )


# ── catStats / normalized value / VONA (from page.tsx:698-761) ──

@dataclass
class CatStats:
    mean: float
    stdev: float


def compute_cat_stats(
    available_players: list[Player],
) -> dict[str, CatStats]:
    stats: dict[str, CatStats] = {}
    for cat_key in ALL_CAT_KEYS:
        is_hitter_cat = cat_key in HITTING_CAT_KEYS
        relevant = [
            p for p in available_players
            if (p.player_type == "hitter") == is_hitter_cat
        ]
        values = [p.zscores.get(cat_key, 0.0) for p in relevant]
        n = len(values) or 1
        mean = sum(values) / n
        variance = sum((v - mean) ** 2 for v in values) / n
        stdev = math.sqrt(variance) if variance > 0 else 1.0
        stats[cat_key] = CatStats(mean=mean, stdev=stdev)
    return stats


def get_normalized_value(player: Player, cat_stats: dict[str, CatStats]) -> float:
    cats = PITCHING_CAT_KEYS if player.player_type == "pitcher" else HITTING_CAT_KEYS
    total = 0.0
    for cat_key in cats:
        raw = player.zscores.get(cat_key, 0.0)
        cs = cat_stats[cat_key]
        total += (raw - cs.mean) / cs.stdev
    return total


def compute_replacement_levels(
    available_players: list[Player],
    cat_stats: dict[str, CatStats],
    num_teams: int,
) -> dict[str, float]:
    """Compute replacement-level NV for each position.

    Replacement level = NV of the player at rank (slots × num_teams) in the
    available pool at that position. This is the standard VORP baseline.
    """
    by_pos: dict[str, list[float]] = {}
    for p in available_players:
        nv = get_normalized_value(p, cat_stats)
        if p.player_type == "pitcher":
            pos = p.pitcher_role()
        else:
            for raw_pos in p.get_positions():
                pos = _normalize_position(raw_pos)
                if pos in POSITION_DEMAND_SLOTS:
                    if pos not in by_pos:
                        by_pos[pos] = []
                    by_pos[pos].append(nv)
            continue
        if pos in POSITION_DEMAND_SLOTS:
            if pos not in by_pos:
                by_pos[pos] = []
            by_pos[pos].append(nv)

    replacement_levels: dict[str, float] = {}
    for pos, slots in POSITION_DEMAND_SLOTS.items():
        nvs = by_pos.get(pos, [])
        nvs.sort(reverse=True)
        depth = slots * num_teams
        idx = min(depth - 1, len(nvs) - 1)
        replacement_levels[pos] = nvs[idx] if idx >= 0 else 0.0
    return replacement_levels


def compute_surplus_value(
    player: Player,
    normalized_value: float,
    replacement_levels: dict[str, float],
) -> float:
    """Compute surplus value (VORP): max(NV - replacement) across eligible positions."""
    if player.player_type == "pitcher":
        positions = [player.pitcher_role()]
    else:
        positions = [_normalize_position(p) for p in player.get_positions()]
    # Deduplicate (e.g., LF + CF + RF all map to OF)
    seen: set[str] = set()
    best = None
    for pos in positions:
        if pos in seen:
            continue
        seen.add(pos)
        repl = replacement_levels.get(pos)
        if repl is not None:
            surplus = normalized_value - repl
            if best is None or surplus > best:
                best = surplus
    return best if best is not None else normalized_value


def _vona_at_position(
    mlb_id: int,
    pos: str,
    available_by_position: dict[str, list[tuple[int, float, float]]],
) -> float:
    """Compute VONA at a single position."""
    pos_players = available_by_position.get(pos, [])
    my_idx = -1
    my_value = 0.0
    for i, (mid, val, _adp) in enumerate(pos_players):
        if mid == mlb_id:
            my_idx = i
            my_value = val
            break

    if my_idx >= 0 and my_idx < len(pos_players) - 1:
        next_value = pos_players[my_idx + 1][1]
        return my_value - next_value
    elif my_idx >= 0:
        return my_value
    return 0.0


def compute_vona(
    player: Player,
    available_by_position: dict[str, list[tuple[int, float, float]]],
) -> float:
    """Compute VONA for a player. Returns the max VONA across all eligible positions."""
    positions = [player.pitcher_role()] if player.player_type == "pitcher" else player.get_positions()
    return max((_vona_at_position(player.mlb_id, pos, available_by_position) for pos in positions), default=0.0)


def _window_vona_at_position(
    mlb_id: int,
    pos: str,
    available_by_position: dict[str, list[tuple[int, float, float]]],
    current_pick: int,
    picks_until_mine: int,
    adp_sigma: float,
) -> float:
    """Compute window VONA at a single position."""
    pos_players = available_by_position.get(pos, [])

    # Find this player's value
    my_value = 0.0
    found = False
    for mid, val, _adp in pos_players:
        if mid == mlb_id:
            my_value = val
            found = True
            break
    if not found:
        return 0.0

    # Collect alternatives with their availability at our next pick
    # pos_players is sorted desc by value
    alternatives: list[tuple[float, float]] = []  # (value, P(available at next pick))
    for mid, val, adp in pos_players:
        if mid == mlb_id:
            continue
        sigma = variable_adp_sigma(adp) if adp_sigma < 0 else adp_sigma
        p_avail = compute_availability(adp, current_pick, picks_until_mine, sigma)
        alternatives.append((val, p_avail))

    if not alternatives:
        return my_value  # only player at position

    # Expected value of best replacement if we wait:
    # For each alternative (sorted desc by value), compute the probability
    # that it's the best available option. P(player_i is best available) =
    # P(available_i) * product(P(gone_j) for all j better than i).
    # Expected replacement = sum(value_i * P(i is best available)).
    #
    # Also account for the scenario where ALL alternatives are gone:
    # in that case replacement value = 0 (no one left at position).
    expected_replacement = 0.0
    p_all_gone_so_far = 1.0  # probability that all better alternatives are gone

    for val, p_avail in alternatives:
        # P(this is the best available) = P(all better ones gone) * P(this one available)
        p_is_best = p_all_gone_so_far * p_avail
        expected_replacement += val * p_is_best
        # Update: for the next (worse) player, this one also needs to be gone
        p_all_gone_so_far *= (1.0 - p_avail)

    # p_all_gone_so_far is now P(every alternative is gone) — replacement = 0 in that case
    # (already handled since we only add value when someone is available)

    return my_value - expected_replacement


def compute_window_vona(
    player: Player,
    available_by_position: dict[str, list[tuple[int, float, float]]],
    current_pick: int,
    picks_until_mine: int,
    adp_sigma: float,
) -> float:
    """Compute window VONA: max across all eligible positions.

    For each position, computes the value gap vs expected best replacement at
    next pick, accounting for the probability each alternative gets taken.
    Returns the max across all positions — the player's scarcity value is
    determined by their most constrained position.
    """
    positions = [player.pitcher_role()] if player.player_type == "pitcher" else player.get_positions()
    return max(
        (_window_vona_at_position(player.mlb_id, pos, available_by_position, current_pick, picks_until_mine, adp_sigma) for pos in positions),
        default=0.0,
    )


def build_available_by_position(
    available: list[Player],
    cat_stats: dict[str, CatStats],
) -> dict[str, list[tuple[int, float, float]]]:
    """Build position -> [(mlb_id, normalized_value, adp)] sorted desc by value."""
    by_pos: dict[str, list[tuple[int, float, float]]] = {}
    for p in available:
        nv = get_normalized_value(p, cat_stats)
        adp = p.espn_adp if p.espn_adp is not None else 999.0
        for pos in p.get_positions():
            if pos not in by_pos:
                by_pos[pos] = []
            by_pos[pos].append((p.mlb_id, nv, adp))

    for pos in by_pos:
        by_pos[pos].sort(key=lambda x: x[1], reverse=True)

    return by_pos


# ── Full player scoring pipeline (from page.tsx:784-868) ──

def full_player_score(
    player: Player,
    my_totals: dict[str, float],
    other_team_totals: dict[str, list[float]],
    strategies: dict[str, str],
    cat_stats: dict[str, CatStats],
    available_by_position: dict[str, list[tuple[int, float]]],
    has_starting_need: float,
    current_pick: int,
    picks_until_mine: int,
    total_picks_made: int,
    my_pick_count: int,
    config: SimConfig,
    bench_pitcher_count: int = 0,
    replacement_levels: dict[str, float] | None = None,
) -> float:
    normalized_value = get_normalized_value(player, cat_stats)

    if config.USE_SURPLUS_VALUE and replacement_levels is not None:
        bpa_value = compute_surplus_value(player, normalized_value, replacement_levels)
    else:
        bpa_value = normalized_value

    effective_sigma = -1.0 if config.USE_VARIABLE_SIGMA else config.ADP_SIGMA

    if config.USE_WINDOW_VONA:
        vona = compute_window_vona(
            player, available_by_position, current_pick, picks_until_mine, effective_sigma,
        )
    else:
        vona = compute_vona(player, available_by_position)

    # Urgency
    urgency = 0.0
    if player.espn_adp is not None:
        adp_gap = player.espn_adp - current_pick
        urgency = max(0.0, min(15.0, picks_until_mine - adp_gap))

    roster_fit = has_starting_need  # float: 0.0 (bench), 1.0 (binary), or scarcity gradient

    confidence = standings_confidence(total_picks_made, config)
    draft_progress = min(1.0, my_pick_count / 25)  # 25 rounds

    has_mcw = total_picks_made >= 2 * config.NUM_TEAMS  # need some data from all teams

    bpa_urgency_weight = config.URGENCY_WEIGHT_BPA * (draft_progress if config.SCALE_BPA_URGENCY else 1.0)

    if has_mcw and confidence > 0:
        mcw = compute_mcw(player.zscores, my_totals, other_team_totals, strategies, config.NUM_TEAMS, config)
        score = compute_draft_score(mcw, vona, urgency, roster_fit, confidence, draft_progress, config)
        # Blend with BPA when confidence is low
        raw_score = bpa_value + vona * config.VONA_WEIGHT_BPA + urgency * bpa_urgency_weight
        score = score * confidence + raw_score * (1 - confidence)
    else:
        score = bpa_value + vona * config.VONA_WEIGHT_BPA + urgency * bpa_urgency_weight

    # Availability discount — skip when window VONA is active (scarcity already baked in)
    if not config.USE_WINDOW_VONA and player.espn_adp is not None:
        avail_sigma = variable_adp_sigma(player.espn_adp) if config.USE_VARIABLE_SIGMA else config.ADP_SIGMA
        avail = compute_availability(player.espn_adp, current_pick, picks_until_mine, avail_sigma)
        score *= 1 - avail * config.AVAILABILITY_DISCOUNT

    # Bench penalty — pitcher-aware: softer penalty for first few bench pitchers
    # (daily league streaming/swap value), then saturates to full penalty
    if has_starting_need == 0 and draft_progress > 0.15:
        if player.player_type == "pitcher":
            saturation = min(1.0, bench_pitcher_count / 3)
            floor = 0.65 - saturation * 0.30
            scale = 0.35 + saturation * 0.28
            score *= max(floor, 1 - draft_progress * scale)
        else:
            score *= max(0.35, 1 - draft_progress * config.BENCH_PENALTY_RATE)

    return score
