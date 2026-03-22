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

from backend.database import get_connection
from backend.simulation.scoring_model import compute_rank, win_prob_from_rank

logger = logging.getLogger(__name__)

# The 10 H2H categories
HITTING_CATS = ["R", "TB", "RBI", "SB", "OBP"]
PITCHING_CATS = ["K", "QS", "ERA", "WHIP", "SVHD"]
ALL_CATS = HITTING_CATS + PITCHING_CATS

# Categories where lower is better
INVERTED_CATS = {"ERA", "WHIP"}

# ESPN lineup slot IDs that count as active starters
# 0=C, 1=1B, 2=2B, 3=3B, 4=SS, 5=OF, 12=UTIL,
# 13=P, 14=SP, 15=RP
ACTIVE_SLOT_IDS = set(range(16))  # 0-15 inclusive
# 16=Bench, 17=IL

# Bench contribution weights (match draft-categories.ts / roster-optimizer.ts)
HITTER_BENCH_WEIGHT = 0.20
SP_BENCH_WEIGHT = 0.45
RP_BENCH_WEIGHT = 0.15
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

    When duplicate names exist (e.g. two "Juan Soto" players), prefers
    the one with an entry in the rankings table (i.e. the relevant player).

    Args:
        espn_players: List of dicts with at least 'name' key.
        season: Season to check rankings for disambiguation.

    Returns:
        Dict of normalized_name -> mlb_id for successfully matched players.
    """
    conn = get_connection()
    all_db_players = conn.execute("SELECT mlb_id, full_name FROM players").fetchall()

    # Get ranked player IDs for disambiguation
    ranked_ids = set()
    ranked_rows = conn.execute(
        "SELECT mlb_id FROM rankings WHERE season = ?", (season,)
    ).fetchall()
    for row in ranked_rows:
        ranked_ids.add(row["mlb_id"])
    conn.close()

    # Build lookup tables — for duplicates, prefer the ranked player
    name_to_id: dict[str, int] = {}
    stripped_to_id: dict[str, int] = {}
    for p in all_db_players:
        key = p["full_name"].lower()
        stripped_key = _strip_accents(p["full_name"])
        mid = p["mlb_id"]

        # Prefer ranked players over unranked ones for name collisions
        if key not in name_to_id or (mid in ranked_ids and name_to_id[key] not in ranked_ids):
            name_to_id[key] = mid
        if stripped_key not in stripped_to_id or (mid in ranked_ids and stripped_to_id[stripped_key] not in ranked_ids):
            stripped_to_id[stripped_key] = mid

    resolved: dict[str, int] = {}
    unmatched = 0
    for ep in espn_players:
        name = ep.get("name", "").strip()
        if not name:
            continue
        mlb_id = name_to_id.get(name.lower())
        if not mlb_id:
            mlb_id = stripped_to_id.get(_strip_accents(name))
        if mlb_id:
            resolved[name] = mlb_id
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
                   r.proj_ip, r.proj_k, r.proj_qs, r.proj_era, r.proj_whip, r.proj_svhd
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


# ── Bench weighting ──────────────────────────────────────────────────────────


def _player_weight(lineup_slot_id: int, proj: PlayerProjection) -> float:
    """Return the contribution weight for a player based on lineup slot.

    Starters contribute 100%. Bench/IL players contribute a fraction
    matching the draft simulator's benchContribution logic.
    """
    if lineup_slot_id in ACTIVE_SLOT_IDS:
        return 1.0
    # IL players (slot 17+) contribute nothing
    if lineup_slot_id >= 17:
        return IL_WEIGHT
    # Bench (slot 16)
    if proj.player_type == "pitcher":
        # SP vs RP: SP has QS projections, RP has SVHD but no QS
        if proj.qs > 0:
            return SP_BENCH_WEIGHT
        return RP_BENCH_WEIGHT
    return HITTER_BENCH_WEIGHT


# ── Core recommendation engine ────────────────────────────────────────────────


def compute_waiver_recommendations(
    my_roster_ids: list[int],
    my_roster_slots: list[dict],  # [{"mlb_id": int, "lineup_slot_id": int}]
    all_team_roster_slots: list[list[dict]],  # Other teams: [{"mlb_id": int, "lineup_slot_id": int}]
    free_agent_ids: list[int],
    season: int,
    remaining_faab: float = 100.0,
) -> dict:
    """Compute waiver wire recommendations.

    Returns ranked list of add/drop pairs with expected wins improvement.
    """
    # Collect all player IDs we need projections for
    other_team_ids = [s["mlb_id"] for team in all_team_roster_slots for s in team]
    all_ids = list(set(my_roster_ids + other_team_ids + free_agent_ids))

    projections = load_projections_for_players(all_ids, season)

    # Build my team totals with bench weighting
    my_totals = TeamTotals()
    my_weights: dict[int, float] = {}  # mlb_id -> weight (for swap calculations)
    for slot in my_roster_slots:
        pid = slot["mlb_id"]
        proj = projections.get(pid)
        if proj:
            w = _player_weight(slot.get("lineup_slot_id", 0), proj)
            my_totals.add_player(proj, w)
            my_weights[pid] = w

    # Build other teams' totals with bench weighting
    other_team_totals: list[TeamTotals] = []
    for team_slots in all_team_roster_slots:
        tt = TeamTotals()
        for slot in team_slots:
            pid = slot["mlb_id"]
            proj = projections.get(pid)
            if proj:
                w = _player_weight(slot.get("lineup_slot_id", 0), proj)
                tt.add_player(proj, w)
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
    other_team_player_counts = [
        sum(1 for s in team_slots if s["mlb_id"] in projections)
        for team_slots in all_team_roster_slots
    ]
    logger.info(f"Other teams proj counts: {other_team_player_counts}")
    logger.info(f"Other teams R values: {[t.get('R', 0) for t in other_cat_values]}")
    baseline_wins, baseline_cat_probs = compute_expected_wins(my_cat_values, other_cat_values)

    # Identify droppable players on my roster (IL/bench deprioritized)
    droppable: list[tuple[int, bool, float]] = []  # (mlb_id, is_bench_or_IL, weight)
    for slot in my_roster_slots:
        pid = slot["mlb_id"]
        slot_id = slot.get("lineup_slot_id", 0)
        is_non_active = slot_id not in ACTIVE_SLOT_IDS
        w = my_weights.get(pid, 1.0)
        droppable.append((pid, is_non_active, w))

    # Sort: non-IL/bench first, then bench/IL
    droppable.sort(key=lambda x: x[1])

    # Evaluate each free agent
    recommendations: list[WaiverRecommendation] = []

    for fa_id in free_agent_ids:
        fa_proj = projections.get(fa_id)
        if not fa_proj:
            continue

        best_delta = -999.0
        best_drop_id: Optional[int] = None
        best_cat_impact: dict[str, float] = {}

        for drop_id, _is_non_active, drop_weight in droppable:
            drop_proj = projections.get(drop_id)
            if not drop_proj:
                continue

            # Swap: remove drop (at its current weight), add FA as starter (weight 1.0)
            trial = my_totals.copy()
            trial.remove_player(drop_proj, drop_weight)
            trial.add_player(fa_proj, 1.0)

            trial_cat_values = trial.category_values()
            trial_wins, trial_cat_probs = compute_expected_wins(trial_cat_values, other_cat_values)
            delta = trial_wins - baseline_wins

            if delta > best_delta:
                best_delta = delta
                best_drop_id = drop_id
                best_cat_impact = {
                    cat: round(trial_cat_probs[cat] - baseline_cat_probs[cat], 4)
                    for cat in ALL_CATS
                }

        if best_delta > -10 and best_drop_id is not None:
            drop_proj = projections.get(best_drop_id)
            recommendations.append(WaiverRecommendation(
                add_player_id=fa_id,
                add_player_name=fa_proj.name,
                add_player_position=fa_proj.position,
                drop_player_id=best_drop_id,
                drop_player_name=drop_proj.name if drop_proj else "Unknown",
                drop_player_position=drop_proj.position if drop_proj else "",
                delta_expected_wins=round(best_delta, 4),
                suggested_faab_bid=0,  # Computed below
                category_impact=best_cat_impact,
            ))

    # Sort by delta expected wins descending
    recommendations.sort(key=lambda r: r.delta_expected_wins, reverse=True)

    # Compute FAAB bids
    _assign_faab_bids(recommendations, remaining_faab)

    return {
        "baseline_expected_wins": round(baseline_wins, 3),
        "baseline_category_probs": {cat: round(v, 4) for cat, v in baseline_cat_probs.items()},
        "my_team_totals": {k: round(v, 3) for k, v in my_cat_values.items()},
        "projection_coverage": {
            "my_roster": f"{my_roster_with_proj}/{len(my_roster_ids)}",
            "missing_ids": my_roster_without_proj[:10],
            "other_teams_player_counts": other_team_player_counts,
        },
        "other_teams_R": [round(t.get("R", 0), 1) for t in other_cat_values],
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
