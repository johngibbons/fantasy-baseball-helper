"""Waiver wire recommendation engine.

Computes expected-wins improvement for each free agent relative to the
user's current roster, using ATC DC (RoS) projections and the existing
MCW scoring infrastructure.
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


# ── Data structures ──────────────────────────────────────────────────────────


@dataclass
class PlayerProjection:
    mlb_id: int
    name: str
    position: str
    player_type: str
    # Hitting raw components
    pa: int = 0
    ab: int = 0
    hits: int = 0
    bb: int = 0
    hbp: int = 0
    sf: int = 0
    r: int = 0
    tb: int = 0
    rbi: int = 0
    sb: int = 0
    # Pitching raw components
    ip: float = 0.0
    k: int = 0
    qs: int = 0
    era: float = 0.0
    whip: float = 0.0
    svhd: int = 0
    earned_runs: int = 0
    hits_allowed: int = 0
    bb_allowed: int = 0


@dataclass
class TeamTotals:
    """Raw summed stats for a fantasy team, used to compute category values."""
    # Hitting components
    pa: int = 0
    ab: int = 0
    hits: int = 0
    bb: int = 0
    hbp: int = 0
    sf: int = 0
    r: int = 0
    tb: int = 0
    rbi: int = 0
    sb: int = 0
    # Pitching components
    ip: float = 0.0
    k: int = 0
    qs: int = 0
    earned_runs: int = 0
    hits_allowed: int = 0
    bb_allowed: int = 0
    svhd: int = 0

    def category_values(self) -> dict[str, float]:
        """Compute the 10 category values from raw components."""
        obp = (
            (self.hits + self.bb + self.hbp) / (self.ab + self.bb + self.hbp + self.sf)
            if (self.ab + self.bb + self.hbp + self.sf) > 0
            else 0.0
        )
        era = (self.earned_runs * 9) / self.ip if self.ip > 0 else 9.99
        whip = (self.hits_allowed + self.bb_allowed) / self.ip if self.ip > 0 else 2.50
        return {
            "R": float(self.r),
            "TB": float(self.tb),
            "RBI": float(self.rbi),
            "SB": float(self.sb),
            "OBP": obp,
            "K": float(self.k),
            "QS": float(self.qs),
            "ERA": era,
            "WHIP": whip,
            "SVHD": float(self.svhd),
        }

    def add_player(self, p: PlayerProjection) -> None:
        if p.player_type == "hitter" or p.pa > 0:
            self.pa += p.pa
            self.ab += p.ab
            self.hits += p.hits
            self.bb += p.bb
            self.hbp += p.hbp
            self.sf += p.sf
            self.r += p.r
            self.tb += p.tb
            self.rbi += p.rbi
            self.sb += p.sb
        if p.player_type == "pitcher" or p.ip > 0:
            self.ip += p.ip
            self.k += p.k
            self.qs += p.qs
            self.earned_runs += p.earned_runs
            self.hits_allowed += p.hits_allowed
            self.bb_allowed += p.bb_allowed
            self.svhd += p.svhd

    def remove_player(self, p: PlayerProjection) -> None:
        if p.player_type == "hitter" or p.pa > 0:
            self.pa -= p.pa
            self.ab -= p.ab
            self.hits -= p.hits
            self.bb -= p.bb
            self.hbp -= p.hbp
            self.sf -= p.sf
            self.r -= p.r
            self.tb -= p.tb
            self.rbi -= p.rbi
            self.sb -= p.sb
        if p.player_type == "pitcher" or p.ip > 0:
            self.ip -= p.ip
            self.k -= p.k
            self.qs -= p.qs
            self.earned_runs -= p.earned_runs
            self.hits_allowed -= p.hits_allowed
            self.bb_allowed -= p.bb_allowed
            self.svhd -= p.svhd

    def copy(self) -> TeamTotals:
        return TeamTotals(
            pa=self.pa, ab=self.ab, hits=self.hits, bb=self.bb,
            hbp=self.hbp, sf=self.sf, r=self.r, tb=self.tb,
            rbi=self.rbi, sb=self.sb, ip=self.ip, k=self.k,
            qs=self.qs, earned_runs=self.earned_runs,
            hits_allowed=self.hits_allowed, bb_allowed=self.bb_allowed,
            svhd=self.svhd,
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
) -> dict[str, int]:
    """Map ESPN player names to mlb_id using name-based matching.

    Args:
        espn_players: List of dicts with at least 'name' key.

    Returns:
        Dict of normalized_name -> mlb_id for successfully matched players.
    """
    conn = get_connection()
    all_db_players = conn.execute("SELECT mlb_id, full_name FROM players").fetchall()
    conn.close()

    # Build lookup tables
    name_to_id: dict[str, int] = {}
    stripped_to_id: dict[str, int] = {}
    for p in all_db_players:
        name_to_id[p["full_name"].lower()] = p["mlb_id"]
        stripped_to_id[_strip_accents(p["full_name"])] = p["mlb_id"]

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
    source: str = "atc",
) -> dict[int, PlayerProjection]:
    """Load projections from the DB for a set of players.

    Falls back to 'atc' source if 'atcdc' has no data.
    """
    conn = get_connection()
    projections: dict[int, PlayerProjection] = {}

    # Try requested source first, then fall back through expert sources.
    # ATC is a pre-blended consensus system; the individual systems
    # (steamer, thebatx, zips) are used when ATC isn't available.
    _FALLBACK_SOURCES = ["atc", "steamer", "thebatx", "zips"]
    sources_to_try = [source] if source in _FALLBACK_SOURCES else [source]
    for fb in _FALLBACK_SOURCES:
        if fb not in sources_to_try:
            sources_to_try.append(fb)

    for src in sources_to_try:
        placeholders = ",".join(["?"] * len(mlb_ids))
        rows = conn.execute(
            f"""SELECT p.mlb_id, pl.full_name, pl.primary_position, p.player_type,
                       p.proj_pa, p.proj_at_bats, p.proj_hits, p.proj_walks,
                       p.proj_hbp, p.proj_sac_flies,
                       p.proj_runs, p.proj_total_bases, p.proj_rbi, p.proj_stolen_bases,
                       p.proj_ip, p.proj_pitcher_strikeouts, p.proj_quality_starts,
                       p.proj_era, p.proj_whip,
                       p.proj_saves, p.proj_holds,
                       p.proj_earned_runs, p.proj_hits_allowed, p.proj_walks_allowed
                FROM projections p
                JOIN players pl ON p.mlb_id = pl.mlb_id
                WHERE p.mlb_id IN ({placeholders})
                  AND p.season = ? AND p.source = ?""",
            (*mlb_ids, season, src),
        ).fetchall()

        for row in rows:
            mid = row["mlb_id"]
            if mid in projections:
                continue  # Already loaded from higher-priority source

            proj = PlayerProjection(
                mlb_id=mid,
                name=row["full_name"],
                position=row["primary_position"] or "",
                player_type=row["player_type"] or "hitter",
                pa=row["proj_pa"] or 0,
                ab=row["proj_at_bats"] or 0,
                hits=row["proj_hits"] or 0,
                bb=row["proj_walks"] or 0,
                hbp=row["proj_hbp"] or 0,
                sf=row["proj_sac_flies"] or 0,
                r=row["proj_runs"] or 0,
                tb=row["proj_total_bases"] or 0,
                rbi=row["proj_rbi"] or 0,
                sb=row["proj_stolen_bases"] or 0,
                ip=row["proj_ip"] or 0.0,
                k=row["proj_pitcher_strikeouts"] or 0,
                qs=row["proj_quality_starts"] or 0,
                era=row["proj_era"] or 0.0,
                whip=row["proj_whip"] or 0.0,
                svhd=(row["proj_saves"] or 0) + (row["proj_holds"] or 0),
                earned_runs=row["proj_earned_runs"] or 0,
                hits_allowed=row["proj_hits_allowed"] or 0,
                bb_allowed=row["proj_walks_allowed"] or 0,
            )
            projections[mid] = proj

        if projections:
            break  # Got data from this source, no need to try fallback

    conn.close()
    used_source = next((s for s in sources_to_try if projections), sources_to_try[0])
    logger.info(f"Loaded projections for {len(projections)}/{len(mlb_ids)} players (tried={sources_to_try}, used={used_source})")
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


# ── Core recommendation engine ────────────────────────────────────────────────


def compute_waiver_recommendations(
    my_roster_ids: list[int],
    my_roster_slots: list[dict],  # [{"mlb_id": int, "lineup_slot_id": int}]
    all_team_roster_ids: list[list[int]],  # Other teams' rosters
    free_agent_ids: list[int],
    season: int,
    remaining_faab: float = 100.0,
    source: str = "atc",
) -> dict:
    """Compute waiver wire recommendations.

    Returns ranked list of add/drop pairs with expected wins improvement.
    """
    # Collect all player IDs we need projections for
    all_ids = list(set(
        my_roster_ids
        + [pid for team in all_team_roster_ids for pid in team]
        + free_agent_ids
    ))

    projections = load_projections_for_players(all_ids, season, source)

    # Build team totals for each team
    my_totals = TeamTotals()
    for pid in my_roster_ids:
        proj = projections.get(pid)
        if proj:
            my_totals.add_player(proj)

    other_team_totals: list[TeamTotals] = []
    for team_ids in all_team_roster_ids:
        tt = TeamTotals()
        for pid in team_ids:
            proj = projections.get(pid)
            if proj:
                tt.add_player(proj)
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
        sum(1 for pid in team_ids if pid in projections)
        for team_ids in all_team_roster_ids
    ]
    logger.info(f"Other teams proj counts: {other_team_player_counts}")
    logger.info(f"Other teams R values: {[t.get('R', 0) for t in other_cat_values]}")
    baseline_wins, baseline_cat_probs = compute_expected_wins(my_cat_values, other_cat_values)

    # Identify droppable players on my roster (IL slots deprioritized)
    IL_SLOT_ID = 13
    droppable: list[tuple[int, bool]] = []  # (mlb_id, is_IL)
    for slot in my_roster_slots:
        pid = slot["mlb_id"]
        is_il = slot.get("lineup_slot_id") == IL_SLOT_ID
        droppable.append((pid, is_il))

    # Sort: non-IL first, then IL
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

        for drop_id, _is_il in droppable:
            drop_proj = projections.get(drop_id)
            if not drop_proj:
                continue

            # Swap: remove drop, add free agent
            trial = my_totals.copy()
            trial.remove_player(drop_proj)
            trial.add_player(fa_proj)

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
