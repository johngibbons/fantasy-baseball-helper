"""Waiver wire recommendation engine.

Computes expected-wins improvement for each free agent relative to the
user's current roster, using the same rankings/projections data as the
draft simulator and the existing MCW scoring infrastructure.
"""

from __future__ import annotations

import logging
import unicodedata
from dataclasses import dataclass
from typing import Optional

from backend.analysis.lineup_optimizer import optimize_hitter_lineup
from backend.database import get_connection
from backend.simulation.scoring_model import compute_rank, win_prob_from_rank

logger = logging.getLogger(__name__)

# The 10 H2H categories
HITTING_CATS = ["R", "TB", "RBI", "SB", "OBP"]
PITCHING_CATS = ["K", "QS", "ERA", "WHIP", "SVHD"]
ALL_CATS = HITTING_CATS + PITCHING_CATS

# Categories where lower is better
INVERTED_CATS = {"ERA", "WHIP"}

# Bench contribution weights (match draft-categories.ts / roster-optimizer.ts)
HITTER_BENCH_WEIGHT = 0.20
IL_WEIGHT = 0.0


# ── Data structures ──────────────────────────────────────────────────────────


@dataclass
class PlayerProjection:
    """Projection data matching the rankings table fields used by the draft."""
    mlb_id: int
    name: str
    position: str
    player_type: str
    # Count stats
    pa: int = 0
    r: int = 0
    tb: int = 0
    rbi: int = 0
    sb: int = 0
    ip: float = 0.0
    k: int = 0
    qs: int = 0
    svhd: int = 0
    # Rate stats (pre-computed, weighted by PA/IP when aggregating)
    obp: float = 0.0
    era: float = 0.0
    whip: float = 0.0
    # Lineup optimizer fields
    eligible_positions: str = ""
    overall_rank: int = 9999


@dataclass
class TeamTotals:
    """Aggregated team stats matching draft-categories.ts computeTeamCategories.

    Rate stats (OBP, ERA, WHIP) are PA/IP-weighted averages, not raw sums.
    """
    # Hitting count stats
    r: float = 0.0
    tb: float = 0.0
    rbi: float = 0.0
    sb: float = 0.0
    # Pitching count stats
    k: float = 0.0
    qs: float = 0.0
    svhd: float = 0.0
    # Rate stat accumulators (weighted sums for final division)
    total_pa: float = 0.0
    weighted_obp: float = 0.0  # sum of obp * pa * weight
    total_ip: float = 0.0
    weighted_era: float = 0.0  # sum of era * ip * weight
    weighted_whip: float = 0.0  # sum of whip * ip * weight

    def category_values(self) -> dict[str, float]:
        """Compute the 10 category values (matches draft page logic)."""
        obp = self.weighted_obp / self.total_pa if self.total_pa > 0 else 0.0
        era = self.weighted_era / self.total_ip if self.total_ip > 0 else 9.99
        whip = self.weighted_whip / self.total_ip if self.total_ip > 0 else 2.50
        return {
            "R": self.r, "TB": self.tb, "RBI": self.rbi, "SB": self.sb,
            "OBP": obp,
            "K": self.k, "QS": self.qs,
            "ERA": era, "WHIP": whip,
            "SVHD": self.svhd,
        }

    def add_player(self, p: PlayerProjection, weight: float = 1.0) -> None:
        if p.player_type == "hitter" or p.pa > 0:
            self.r += p.r * weight
            self.tb += p.tb * weight
            self.rbi += p.rbi * weight
            self.sb += p.sb * weight
            self.total_pa += p.pa * weight
            self.weighted_obp += p.obp * p.pa * weight
        if p.player_type == "pitcher" or p.ip > 0:
            self.k += p.k * weight
            self.qs += p.qs * weight
            self.svhd += p.svhd * weight
            self.total_ip += p.ip * weight
            self.weighted_era += p.era * p.ip * weight
            self.weighted_whip += p.whip * p.ip * weight

    def remove_player(self, p: PlayerProjection, weight: float = 1.0) -> None:
        if p.player_type == "hitter" or p.pa > 0:
            self.r -= p.r * weight
            self.tb -= p.tb * weight
            self.rbi -= p.rbi * weight
            self.sb -= p.sb * weight
            self.total_pa -= p.pa * weight
            self.weighted_obp -= p.obp * p.pa * weight
        if p.player_type == "pitcher" or p.ip > 0:
            self.k -= p.k * weight
            self.qs -= p.qs * weight
            self.svhd -= p.svhd * weight
            self.total_ip -= p.ip * weight
            self.weighted_era -= p.era * p.ip * weight
            self.weighted_whip -= p.whip * p.ip * weight

    def copy(self) -> TeamTotals:
        return TeamTotals(
            r=self.r, tb=self.tb, rbi=self.rbi, sb=self.sb,
            k=self.k, qs=self.qs, svhd=self.svhd,
            total_pa=self.total_pa, weighted_obp=self.weighted_obp,
            total_ip=self.total_ip, weighted_era=self.weighted_era,
            weighted_whip=self.weighted_whip,
        )


@dataclass
class WaiverRecommendation:
    add_player_id: int
    add_player_name: str
    add_player_position: str
    drop_player_id: Optional[int]
    drop_player_name: Optional[str]
    drop_player_position: Optional[str]
    delta_expected_wins: float
    suggested_faab_bid: int
    category_impact: dict[str, float]
    category_stat_delta: dict[str, float]


# ── Player ID resolution ─────────────────────────────────────────────────────


def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    ).lower()


def resolve_espn_names_to_mlbid(
    espn_players: list[dict],
    season: int = 2026,
) -> dict[str, int]:
    """Map ESPN player names to mlb_id using name-based matching.

    When duplicate names exist (e.g. two "Edwin Diaz" or "Juan Soto" players),
    uses ESPN's player_type hint and rankings presence for disambiguation.

    Args:
        espn_players: List of dicts with 'name' and optional 'player_type' keys.
        season: Season to check rankings for disambiguation.

    Returns:
        Dict of normalized_name -> mlb_id for successfully matched players.
    """
    conn = get_connection()
    all_db_players = conn.execute(
        "SELECT mlb_id, full_name, player_type FROM players"
    ).fetchall()

    # Get ranked player IDs for disambiguation
    ranked_ids = set()
    ranked_rows = conn.execute(
        "SELECT mlb_id FROM rankings WHERE season = ?", (season,)
    ).fetchall()
    for row in ranked_rows:
        ranked_ids.add(row["mlb_id"])
    conn.close()

    # Build lookup: name -> list of (mlb_id, player_type, is_ranked) for disambiguation
    from collections import defaultdict
    name_candidates: dict[str, list[tuple[int, str, bool]]] = defaultdict(list)
    stripped_candidates: dict[str, list[tuple[int, str, bool]]] = defaultdict(list)
    for p in all_db_players:
        key = p["full_name"].lower()
        stripped_key = _strip_accents(p["full_name"])
        mid = p["mlb_id"]
        ptype = p["player_type"] or ""
        is_ranked = mid in ranked_ids
        name_candidates[key].append((mid, ptype, is_ranked))
        stripped_candidates[stripped_key].append((mid, ptype, is_ranked))

    def _pick_best(candidates: list[tuple[int, str, bool]], hint_type: str | None) -> int:
        """Pick the best candidate from duplicates using type hint and ranking."""
        if len(candidates) == 1:
            return candidates[0][0]
        # If we have a type hint from ESPN, prefer matching type
        if hint_type:
            type_matches = [c for c in candidates if c[1] == hint_type]
            if len(type_matches) == 1:
                return type_matches[0][0]
            if type_matches:
                # Among type matches, prefer ranked
                ranked_type = [c for c in type_matches if c[2]]
                if ranked_type:
                    return ranked_type[0][0]
                return type_matches[0][0]
        # No type hint or no type match — prefer ranked
        ranked = [c for c in candidates if c[2]]
        if ranked:
            return ranked[0][0]
        return candidates[0][0]

    # Build a per-ESPN-player type hint map (first occurrence wins for each name)
    name_type_hints: dict[str, str | None] = {}
    for ep in espn_players:
        name = ep.get("name", "").strip()
        if name and name not in name_type_hints:
            name_type_hints[name] = ep.get("player_type")

    resolved: dict[str, int] = {}
    unmatched = 0
    for name, hint_type in name_type_hints.items():
        key = name.lower()
        candidates = name_candidates.get(key)
        if not candidates:
            candidates = stripped_candidates.get(_strip_accents(name))
        if candidates:
            resolved[name] = _pick_best(candidates, hint_type)
        else:
            unmatched += 1

    if unmatched > 0:
        logger.info(f"Player name resolution: {len(resolved)} matched, {unmatched} unmatched")
    return resolved


# ── Projection loading ────────────────────────────────────────────────────────


def load_projections_for_players(
    mlb_ids: list[int],
    season: int,
) -> dict[int, PlayerProjection]:
    """Load projections from the rankings table (same data the draft uses)."""
    conn = get_connection()
    placeholders = ",".join(["?"] * len(mlb_ids))
    rows = conn.execute(
        f"""SELECT r.mlb_id, pl.full_name, pl.primary_position, r.player_type,
                   r.proj_pa, r.proj_r, r.proj_tb, r.proj_rbi, r.proj_sb, r.proj_obp,
                   r.proj_ip, r.proj_k, r.proj_qs, r.proj_era, r.proj_whip, r.proj_svhd,
                   pl.eligible_positions, r.overall_rank
            FROM rankings r
            JOIN players pl ON r.mlb_id = pl.mlb_id
            WHERE r.mlb_id IN ({placeholders})
              AND r.season = ?""",
        (*mlb_ids, season),
    ).fetchall()

    projections: dict[int, PlayerProjection] = {}
    for row in rows:
        projections[row["mlb_id"]] = PlayerProjection(
            mlb_id=row["mlb_id"],
            name=row["full_name"],
            position=row["primary_position"] or "",
            player_type=row["player_type"] or "hitter",
            pa=row["proj_pa"] or 0,
            r=row["proj_r"] or 0,
            tb=row["proj_tb"] or 0,
            rbi=row["proj_rbi"] or 0,
            sb=row["proj_sb"] or 0,
            obp=row["proj_obp"] or 0.0,
            ip=row["proj_ip"] or 0.0,
            k=row["proj_k"] or 0,
            qs=row["proj_qs"] or 0,
            era=row["proj_era"] or 0.0,
            whip=row["proj_whip"] or 0.0,
            svhd=row["proj_svhd"] or 0,
            eligible_positions=row["eligible_positions"] or "",
            overall_rank=row["overall_rank"] or 9999,
        )

    conn.close()
    logger.info(f"Loaded projections for {len(projections)}/{len(mlb_ids)} players from rankings")
    return projections


# ── Expected wins computation ─────────────────────────────────────────────────


def compute_expected_wins(
    my_cat_values: dict[str, float],
    other_teams_cat_values: list[dict[str, float]],
) -> tuple[float, dict[str, float]]:
    """Compute expected weekly wins from category values.

    Handles ERA/WHIP inversion (lower is better).

    Returns:
        (total_expected_wins, per_category_win_probs)
    """
    num_teams = len(other_teams_cat_values) + 1
    cat_win_probs: dict[str, float] = {}

    for cat in ALL_CATS:
        my_val = my_cat_values.get(cat, 0.0)
        other_vals = [t.get(cat, 0.0) for t in other_teams_cat_values]

        if cat in INVERTED_CATS:
            # Lower is better — negate so compute_rank's "higher is better" works
            my_val = -my_val
            other_vals = [-v for v in other_vals]

        rank = compute_rank(my_val, other_vals)
        cat_win_probs[cat] = win_prob_from_rank(rank, num_teams)

    return sum(cat_win_probs.values()), cat_win_probs


# ── Lineup-optimized team building ───────────────────────────────────────────

IL_SLOT_THRESHOLD = 17  # ESPN lineup_slot_id >= 17 means IL


def build_team_totals(
    roster_slots: list[dict],
    projections: dict[int, PlayerProjection],
) -> tuple[TeamTotals, dict[int, float]]:
    """Build team totals using lineup-optimized weights.

    Pitchers: all non-IL at 1.0 (daily league rotation).
    Hitters: run greedy optimizer to assign active (1.0) or bench (0.20).
    IL: 0.0.

    Returns:
        (TeamTotals, {mlb_id: weight})
    """
    totals = TeamTotals()
    weights: dict[int, float] = {}

    il_ids: set[int] = set()
    pitcher_ids: list[int] = []
    hitter_dicts: list[dict] = []

    for slot in roster_slots:
        pid = slot["mlb_id"]
        proj = projections.get(pid)
        if not proj:
            continue

        if slot.get("lineup_slot_id", 0) >= IL_SLOT_THRESHOLD:
            il_ids.add(pid)
            weights[pid] = IL_WEIGHT
            continue

        if proj.player_type == "pitcher":
            pitcher_ids.append(pid)
        else:
            hitter_dicts.append({
                "mlb_id": pid,
                "eligible_positions": proj.eligible_positions,
                "overall_rank": proj.overall_rank,
                "player_type": proj.player_type,
            })

    # Pitchers: all non-IL at 1.0
    for pid in pitcher_ids:
        w = 1.0
        weights[pid] = w
        totals.add_player(projections[pid], w)

    # Hitters: optimize lineup
    assignments = optimize_hitter_lineup(hitter_dicts)
    for a in assignments:
        proj = projections.get(a.mlb_id)
        if not proj:
            continue
        w = 1.0 if a.is_starter else HITTER_BENCH_WEIGHT
        weights[a.mlb_id] = w
        totals.add_player(proj, w)

    return totals, weights


# ── Core recommendation engine ────────────────────────────────────────────────


def compute_waiver_recommendations(
    my_roster_ids: list[int],
    my_roster_slots: list[dict],
    all_team_roster_slots: list[list[dict]],
    free_agent_ids: list[int],
    season: int,
    remaining_faab: float = 100.0,
    open_roster_slots: int = 0,
) -> dict:
    """Compute waiver wire recommendations.

    For each (FA, drop) pair, builds the trial roster and re-optimizes the
    lineup to determine proper starter/bench assignments.
    """
    other_team_ids = [s["mlb_id"] for team in all_team_roster_slots for s in team]
    all_ids = list(set(my_roster_ids + other_team_ids + free_agent_ids))

    projections = load_projections_for_players(all_ids, season)

    # Build my baseline using lineup optimization
    my_totals, my_weights = build_team_totals(my_roster_slots, projections)

    # Build other teams' totals
    other_team_totals: list[TeamTotals] = []
    for team_slots in all_team_roster_slots:
        tt, _ = build_team_totals(team_slots, projections)
        other_team_totals.append(tt)

    # Compute baseline expected wins
    my_roster_with_proj = sum(1 for pid in my_roster_ids if pid in projections)
    my_roster_without_proj = [pid for pid in my_roster_ids if pid not in projections]
    logger.info(
        f"My roster projections: {my_roster_with_proj}/{len(my_roster_ids)} have projections, "
        f"missing: {my_roster_without_proj[:10]}"
    )
    my_cat_values = my_totals.category_values()
    other_cat_values = [t.category_values() for t in other_team_totals]
    logger.info(f"My team category values: {my_cat_values}")
    baseline_wins, baseline_cat_probs = compute_expected_wins(my_cat_values, other_cat_values)

    # Identify droppable players (exclude IL)
    droppable_ids: list[int] = []
    for slot in my_roster_slots:
        pid = slot["mlb_id"]
        if slot.get("lineup_slot_id", 0) >= IL_SLOT_THRESHOLD:
            continue
        droppable_ids.append(pid)

    # Evaluate each free agent
    recommendations: list[WaiverRecommendation] = []

    for fa_id in free_agent_ids:
        fa_proj = projections.get(fa_id)
        if not fa_proj:
            continue

        best_delta = -999.0
        best_drop_id: Optional[int] = None
        best_cat_impact: dict[str, float] = {}
        best_stat_delta: dict[str, float] = {}
        is_no_drop = False

        # Try "add without drop" if open roster slots available
        if open_roster_slots > 0:
            trial_slots = list(my_roster_slots) + [{"mlb_id": fa_id, "lineup_slot_id": 0}]
            trial_totals, _ = build_team_totals(trial_slots, projections)
            trial_cat_values = trial_totals.category_values()
            trial_wins, trial_cat_probs = compute_expected_wins(trial_cat_values, other_cat_values)
            delta = trial_wins - baseline_wins
            if delta > best_delta:
                best_delta = delta
                best_drop_id = None
                is_no_drop = True
                best_cat_impact = {
                    cat: round(trial_cat_probs[cat] - baseline_cat_probs[cat], 4)
                    for cat in ALL_CATS
                }
                best_stat_delta = {
                    cat: round(trial_cat_values[cat] - my_cat_values[cat], 3)
                    for cat in ALL_CATS
                }

        # Try each drop option
        for drop_id in droppable_ids:
            drop_proj = projections.get(drop_id)
            if not drop_proj:
                continue

            trial_slots = [s for s in my_roster_slots if s["mlb_id"] != drop_id]
            trial_slots.append({"mlb_id": fa_id, "lineup_slot_id": 0})

            trial_totals, _ = build_team_totals(trial_slots, projections)
            trial_cat_values = trial_totals.category_values()
            trial_wins, trial_cat_probs = compute_expected_wins(trial_cat_values, other_cat_values)
            delta = trial_wins - baseline_wins

            # Prefer dropping worse-ranked player when deltas are tied
            drop_rank = drop_proj.overall_rank
            best_drop_rank = projections[best_drop_id].overall_rank if best_drop_id and best_drop_id in projections else -1
            is_better = delta > best_delta or (delta == best_delta and drop_rank > best_drop_rank)

            if is_better:
                best_delta = delta
                best_drop_id = drop_id
                is_no_drop = False
                best_cat_impact = {
                    cat: round(trial_cat_probs[cat] - baseline_cat_probs[cat], 4)
                    for cat in ALL_CATS
                }
                best_stat_delta = {
                    cat: round(trial_cat_values[cat] - my_cat_values[cat], 3)
                    for cat in ALL_CATS
                }

        if best_delta > -10 and (best_drop_id is not None or is_no_drop):
            drop_proj = projections.get(best_drop_id) if best_drop_id else None
            recommendations.append(WaiverRecommendation(
                add_player_id=fa_id,
                add_player_name=fa_proj.name,
                add_player_position=fa_proj.position,
                drop_player_id=best_drop_id,
                drop_player_name=drop_proj.name if drop_proj else None,
                drop_player_position=drop_proj.position if drop_proj else None,
                delta_expected_wins=round(best_delta, 4),
                suggested_faab_bid=0,
                category_impact=best_cat_impact,
                category_stat_delta=best_stat_delta,
            ))

    recommendations.sort(key=lambda r: r.delta_expected_wins, reverse=True)
    _assign_faab_bids(recommendations, remaining_faab)

    return {
        "baseline_expected_wins": round(baseline_wins, 3),
        "baseline_category_probs": {cat: round(v, 4) for cat, v in baseline_cat_probs.items()},
        "my_team_totals": {k: round(v, 3) for k, v in my_cat_values.items()},
        "projection_coverage": {
            "my_roster": f"{my_roster_with_proj}/{len(my_roster_ids)}",
            "missing_ids": my_roster_without_proj[:10],
        },
        "recommendations": [
            {
                "rank": i + 1,
                "add_player": {
                    "id": r.add_player_id,
                    "name": r.add_player_name,
                    "position": r.add_player_position,
                },
                "drop_player": {
                    "id": r.drop_player_id,
                    "name": r.drop_player_name,
                    "position": r.drop_player_position,
                } if r.drop_player_id else None,
                "delta_expected_wins": r.delta_expected_wins,
                "suggested_faab_bid": r.suggested_faab_bid,
                "category_impact": r.category_impact,
                "category_stat_delta": r.category_stat_delta,
            }
            for i, r in enumerate(recommendations)
        ],
    }


# ── FAAB bid recommender ─────────────────────────────────────────────────────


def _assign_faab_bids(
    recommendations: list[WaiverRecommendation],
    remaining_faab: float,
) -> None:
    """Assign FAAB bid suggestions proportional to expected wins improvement."""
    if not recommendations:
        return

    positive = [r for r in recommendations if r.delta_expected_wins > 0.01]
    if not positive:
        return

    max_delta = positive[0].delta_expected_wins
    if max_delta <= 0:
        return

    max_bid = remaining_faab * 0.4  # Cap any single bid at 40% of remaining budget

    for r in positive:
        fraction = r.delta_expected_wins / max_delta
        # Square root scaling: top players get more, but diminishing
        bid = max_bid * (fraction ** 0.5)
        r.suggested_faab_bid = max(0, round(bid))

    # Everyone else stays at $0
