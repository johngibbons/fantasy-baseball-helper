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

        mcw += marginal_win

    return mcw


# ── Draft score blending (from computeDraftScore + page.tsx:784-868) ──

def compute_draft_score(
    mcw: float,
    vona: float,
    urgency: float,
    roster_fit: int,
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


def compute_vona(
    player: Player,
    available_by_position: dict[str, list[tuple[int, float]]],
) -> float:
    """Compute VONA for a player. available_by_position maps position -> [(mlb_id, normalized_value)] sorted desc."""
    if player.player_type == "pitcher":
        primary_pos = player.pitcher_role()
    else:
        primary_pos = player.get_positions()[0]

    pos_players = available_by_position.get(primary_pos, [])
    my_idx = -1
    my_value = 0.0
    for i, (mid, val) in enumerate(pos_players):
        if mid == player.mlb_id:
            my_idx = i
            my_value = val
            break

    if my_idx >= 0 and my_idx < len(pos_players) - 1:
        next_value = pos_players[my_idx + 1][1]
        return my_value - next_value
    elif my_idx >= 0:
        return my_value
    return 0.0


def build_available_by_position(
    available: list[Player],
    cat_stats: dict[str, CatStats],
) -> dict[str, list[tuple[int, float]]]:
    """Build position -> [(mlb_id, normalized_value)] sorted desc by value."""
    by_pos: dict[str, list[tuple[int, float]]] = {}
    for p in available:
        nv = get_normalized_value(p, cat_stats)
        for pos in p.get_positions():
            if pos not in by_pos:
                by_pos[pos] = []
            by_pos[pos].append((p.mlb_id, nv))

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
    has_starting_need: bool,
    current_pick: int,
    picks_until_mine: int,
    total_picks_made: int,
    my_pick_count: int,
    config: SimConfig,
) -> float:
    normalized_value = get_normalized_value(player, cat_stats)
    vona = compute_vona(player, available_by_position)

    # Urgency
    urgency = 0.0
    if player.espn_adp is not None:
        adp_gap = player.espn_adp - current_pick
        urgency = max(0.0, min(15.0, picks_until_mine - adp_gap))

    roster_fit = 1 if has_starting_need else 0

    confidence = standings_confidence(total_picks_made, config)
    draft_progress = min(1.0, my_pick_count / 25)  # 25 rounds

    has_mcw = total_picks_made >= 2 * config.NUM_TEAMS  # need some data from all teams

    if has_mcw and confidence > 0:
        mcw = compute_mcw(player.zscores, my_totals, other_team_totals, strategies, config.NUM_TEAMS)
        score = compute_draft_score(mcw, vona, urgency, roster_fit, confidence, draft_progress, config)
        # Blend with BPA when confidence is low
        raw_score = normalized_value + vona * config.VONA_WEIGHT_BPA + urgency * config.URGENCY_WEIGHT_BPA
        score = score * confidence + raw_score * (1 - confidence)
    else:
        score = normalized_value + vona * config.VONA_WEIGHT_BPA + urgency * config.URGENCY_WEIGHT_BPA

    # Availability discount
    if player.espn_adp is not None:
        avail = compute_availability(player.espn_adp, current_pick, picks_until_mine, config.ADP_SIGMA)
        score *= 1 - avail * config.AVAILABILITY_DISCOUNT

    # Bench penalty
    if not has_starting_need and draft_progress > 0.15:
        score *= max(0.35, 1 - draft_progress * config.BENCH_PENALTY_RATE)

    return score
