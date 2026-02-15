"""SGP (Standings Gain Points) valuation engine for fantasy baseball.

Uses historical league standings to compute SGP denominators — the average
gap between adjacent teams in each category — then values each player's
projected stats by how many standings points they contribute.

Falls back to estimated denominators if no league standings data is loaded.

League categories:
  Hitting: R, TB, RBI, SB, OBP
  Pitching (SP pool): K, QS, ERA, WHIP
  Pitching (RP pool): K, SVHD, ERA, WHIP
"""

import logging
from collections import defaultdict
import numpy as np
from backend.database import get_connection

logger = logging.getLogger(__name__)

# Minimum thresholds to be included in the player pool
MIN_PA = 200   # plate appearances for hitters
MIN_IP_SP = 30  # innings pitched for starters
MIN_IP_RP = 15  # innings pitched for relievers

# Playing time confidence thresholds — players below these get a linear discount
# to account for the risk that projected playing time doesn't materialize
FULL_CREDIT_PA = 500   # hitters at or above this PA get no discount
FULL_CREDIT_IP_SP = 140  # SP at or above this IP get no discount
FULL_CREDIT_IP_RP = 50   # RP at or above this IP get no discount

# Pitcher role classification
SP_POSITIONS = {"SP"}
RP_POSITIONS = {"RP", "CP"}

# League configuration — determines replacement-level depth
NUM_TEAMS = 10
HITTER_SLOTS = {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "UTIL": 2}
PITCHER_SLOTS = {"SP": 3, "RP": 2, "P": 2}  # P slots can be filled by SP or RP

# Map player positions → roster slot they compete for
POSITION_TO_SLOT = {
    "C": "C", "1B": "1B", "2B": "2B", "3B": "3B", "SS": "SS",
    "OF": "OF", "LF": "OF", "CF": "OF", "RF": "OF",
    "DH": "UTIL",
}


def _classify_pitcher(position: str, proj_ip: float, proj_qs: float) -> str:
    """Classify a pitcher as SP or RP based on position and stats."""
    if position in SP_POSITIONS:
        return "SP"
    if position in RP_POSITIONS:
        return "RP"
    # Ambiguous positions (P, TWP): use stats to decide
    if proj_qs > 0 or proj_ip >= 80:
        return "SP"
    return "RP"


def _zscore(values: np.ndarray) -> np.ndarray:
    """Calculate z-scores for an array. Returns 0 for constant arrays."""
    std = np.std(values)
    if std == 0:
        return np.zeros_like(values)
    return (values - np.mean(values)) / std


# Categories where lower is better (inverted for SGP)
_INVERTED_CATEGORIES = {"ERA", "WHIP"}

# Column name mapping: category name → league_season_totals column
_CATEGORY_TO_COLUMN = {
    "R": "team_r", "TB": "team_tb", "RBI": "team_rbi", "SB": "team_sb",
    "OBP": "team_obp", "K": "team_k", "QS": "team_qs",
    "ERA": "team_era", "WHIP": "team_whip", "SVHD": "team_svhd",
}


def _eligible_slots(eligible_positions: str, primary_position: str) -> list[str]:
    """Convert ESPN eligible positions string to roster slots.

    Args:
        eligible_positions: Slash-separated positions like "2B/3B/SS/OF" or None.
        primary_position: Fallback primary position.

    Returns:
        List of unique roster slots (e.g. ["2B", "3B", "SS", "OF", "UTIL"]).
    """
    if eligible_positions:
        positions = [p.strip() for p in eligible_positions.split("/")]
    else:
        positions = [primary_position]

    slots = set()
    for pos in positions:
        slot = POSITION_TO_SLOT.get(pos)
        if slot:
            slots.add(slot)
    # Every hitter can fill UTIL
    slots.add("UTIL")
    return list(slots)


def _best_slot(eligible_positions: str, primary_position: str,
               replacement_levels: dict[str, float]) -> str:
    """Find the roster slot with the lowest replacement level from eligible positions.

    Lower replacement level = scarcer position = more value above replacement.

    Args:
        eligible_positions: Slash-separated positions like "C/1B/DH" or None.
        primary_position: Fallback primary position.
        replacement_levels: {slot: replacement_value} mapping.

    Returns:
        The best slot string.
    """
    slots = _eligible_slots(eligible_positions, primary_position)
    if not slots:
        return POSITION_TO_SLOT.get(primary_position, "UTIL")

    return min(slots, key=lambda s: replacement_levels.get(s, 0.0))


def _compute_sgp_denominators(categories: list[str]) -> dict[str, float]:
    """Compute SGP denominators from historical league standings data.

    For each category and season, sorts team values and computes the average
    gap between adjacent teams: (best - worst) / (num_teams - 1).
    Averages across seasons if multiple years are available.

    Falls back to hardcoded estimates if no historical data exists.

    Args:
        categories: List of category names (e.g. ["R", "TB", "RBI", "SB", "OBP"])

    Returns:
        {category: sgp_denominator} mapping.
    """
    conn = get_connection()
    rows = conn.execute("SELECT * FROM league_season_totals").fetchall()
    conn.close()

    if not rows:
        # Fallback denominators estimated from typical 10-team H2H league
        fallback = {
            "R": 19.0, "TB": 55.0, "RBI": 20.0, "SB": 8.0, "OBP": 0.0036,
            "K": 84.0, "QS": 7.0, "ERA": 0.061, "WHIP": 0.012, "SVHD": 7.0,
        }
        result = {cat: fallback.get(cat, 1.0) for cat in categories}
        logger.warning(f"No league standings data — using fallback SGP denominators: {result}")
        return result

    # Group by season
    by_season: dict[int, list] = defaultdict(list)
    for row in rows:
        by_season[row["season"]].append(row)

    # Compute per-season denominators, then average across seasons
    season_denoms: dict[str, list[float]] = defaultdict(list)
    for season, team_rows in sorted(by_season.items()):
        n_teams = len(team_rows)
        if n_teams < 2:
            continue
        for cat in categories:
            col = _CATEGORY_TO_COLUMN.get(cat)
            if not col:
                continue
            values = sorted([row[col] or 0 for row in team_rows])
            # For inverted categories, the "best" is lowest, but the gap
            # calculation is the same: range / (n-1)
            denom = (values[-1] - values[0]) / (n_teams - 1)
            if denom > 0:
                season_denoms[cat].append(denom)

    result = {}
    fallback = {
        "R": 19.0, "TB": 55.0, "RBI": 20.0, "SB": 8.0, "OBP": 0.0036,
        "K": 84.0, "QS": 7.0, "ERA": 0.061, "WHIP": 0.012, "SVHD": 7.0,
    }
    for cat in categories:
        if season_denoms.get(cat):
            result[cat] = sum(season_denoms[cat]) / len(season_denoms[cat])
        else:
            result[cat] = fallback.get(cat, 1.0)

    logger.info(f"SGP denominators: {', '.join(f'{k}={v:.4f}' for k, v in result.items())}")
    return result


def _blend_projection_rows(
    rows, numeric_fields: list[str]
) -> tuple[list[dict], int, float]:
    """Blend multiple projection sources into one row per player.

    Groups rows by mlb_id, averages numeric_fields across sources.
    If a player has a 'statcast_adjusted' row, excludes 'trend' for that player
    (since statcast_adjusted already incorporates trend data).

    Returns:
        (blended_rows, player_count, avg_sources_per_player)
    """
    by_player = defaultdict(list)
    for row in rows:
        by_player[row["mlb_id"]].append(row)

    blended = []
    total_source_count = 0
    for mlb_id, player_rows in by_player.items():
        # If player has statcast_adjusted, exclude trend
        sources = {r["source"] for r in player_rows}
        if "statcast_adjusted" in sources:
            player_rows = [r for r in player_rows if r["source"] != "trend"]

        total_source_count += len(player_rows)
        first = player_rows[0]
        result = {
            "mlb_id": first["mlb_id"],
            "full_name": first["full_name"],
            "primary_position": first["primary_position"],
            "team": first["team"],
            "eligible_positions": first["eligible_positions"] if "eligible_positions" in first.keys() else None,
        }
        for field in numeric_fields:
            values = [r[field] or 0 for r in player_rows]
            result[field] = sum(values) / len(values)
        blended.append(result)

    avg_sources = total_source_count / len(blended) if blended else 0
    return blended, len(by_player), avg_sources


def _compute_hitter_replacement_levels(results: list[dict]) -> dict[str, float]:
    """Compute replacement-level z-scores per hitter roster slot.

    Groups players by their roster slot (LF/CF/RF → OF, DH → UTIL),
    sorts each group by raw z-score, and finds the replacement-level
    player at rank (slots_per_team × num_teams).

    A hitter baseline from total hitter demand acts as a floor — no
    position's replacement level can be lower than the overall baseline.

    Returns:
        {slot: replacement_z} mapping.
    """
    # Group by roster slot
    by_slot = defaultdict(list)
    all_zscores = []
    for p in results:
        slot = POSITION_TO_SLOT.get(p["primary_position"], "UTIL")
        by_slot[slot].append(p["total_zscore"])
        all_zscores.append(p["total_zscore"])

    # Sort each group descending
    for zscores in by_slot.values():
        zscores.sort(reverse=True)
    all_zscores.sort(reverse=True)

    # Hitter baseline: the (total_hitter_demand)th best hitter overall
    total_demand = sum(HITTER_SLOTS.values()) * NUM_TEAMS
    hitter_baseline = (
        all_zscores[total_demand - 1]
        if len(all_zscores) >= total_demand
        else all_zscores[-1]
    )

    # Position-specific replacement levels (floored by hitter baseline)
    replacement = {}
    for slot, count in HITTER_SLOTS.items():
        demand = count * NUM_TEAMS
        zscores = by_slot.get(slot, [])
        if len(zscores) >= demand:
            replacement[slot] = max(zscores[demand - 1], hitter_baseline)
        else:
            # Not enough players at this position — use baseline
            replacement[slot] = hitter_baseline

    parts = ", ".join(f"{s}: {z:+.2f}" for s, z in sorted(replacement.items()))
    logger.info(f"Hitter replacement levels: {parts} (baseline: {hitter_baseline:+.2f})")
    return replacement


def _compute_pitcher_replacement_levels(
    sp_results: list[dict], rp_results: list[dict]
) -> dict[str, float]:
    """Compute replacement-level z-scores per pitcher roster slot.

    Handles flex P slots (fillable by SP or RP) using a pitcher baseline
    floor, mirroring how UTIL works for hitters.

    SP replacement = rank (SP_slots × teams) among SP pool, floored by baseline
    RP replacement = rank (RP_slots × teams) among RP pool, floored by baseline
    Pitcher baseline = rank (total_pitcher_demand) across all pitchers

    Returns:
        {"SP": replacement_z, "RP": replacement_z} mapping.
    """
    sp_zscores = sorted([r["total_zscore"] for r in sp_results], reverse=True)
    rp_zscores = sorted([r["total_zscore"] for r in rp_results], reverse=True)
    all_zscores = sorted(sp_zscores + rp_zscores, reverse=True)

    # Pitcher baseline: total pitcher demand across all slots (SP + RP + P)
    total_demand = sum(PITCHER_SLOTS.values()) * NUM_TEAMS
    pitcher_baseline = (
        all_zscores[total_demand - 1]
        if len(all_zscores) >= total_demand
        else all_zscores[-1] if all_zscores else 0.0
    )

    replacement = {}

    # SP replacement (floored by pitcher baseline)
    sp_demand = PITCHER_SLOTS.get("SP", 0) * NUM_TEAMS
    if sp_demand > 0 and len(sp_zscores) >= sp_demand:
        replacement["SP"] = max(sp_zscores[sp_demand - 1], pitcher_baseline)
    else:
        replacement["SP"] = pitcher_baseline

    # RP replacement (floored by pitcher baseline)
    rp_demand = PITCHER_SLOTS.get("RP", 0) * NUM_TEAMS
    if rp_demand > 0 and len(rp_zscores) >= rp_demand:
        replacement["RP"] = max(rp_zscores[rp_demand - 1], pitcher_baseline)
    else:
        replacement["RP"] = pitcher_baseline

    parts = ", ".join(f"{s}: {z:+.2f}" for s, z in sorted(replacement.items()))
    logger.info(f"Pitcher replacement levels: {parts} (baseline: {pitcher_baseline:+.2f})")
    return replacement


def calculate_hitter_zscores(season: int = 2026, source: str = None,
                             excluded_ids: set[int] | None = None) -> list[dict]:
    """Calculate z-scores for all hitters with projections.

    Categories: R, TB, RBI, SB, OBP (weighted by PA)

    Args:
        excluded_ids: If provided, exclude these mlb_ids after blending but
                      before z-score computation (for draft recalculation).
    """
    conn = get_connection()

    _HITTER_NUMERIC = [
        "proj_pa", "proj_runs", "proj_total_bases", "proj_rbi",
        "proj_stolen_bases", "proj_obp",
        "proj_hits", "proj_walks", "proj_hbp", "proj_sac_flies", "proj_at_bats",
    ]

    # Build query - prefer specific source, fall back to any
    if source:
        query = """
            SELECT p.mlb_id, p.full_name, p.primary_position, p.team,
                   p.eligible_positions,
                   pr.proj_pa, pr.proj_runs, pr.proj_total_bases, pr.proj_rbi,
                   pr.proj_stolen_bases, pr.proj_obp,
                   pr.proj_hits, pr.proj_walks, pr.proj_hbp, pr.proj_sac_flies, pr.proj_at_bats
            FROM projections pr
            JOIN players p ON pr.mlb_id = p.mlb_id
            WHERE pr.season = ? AND pr.player_type = 'hitter' AND pr.source = ?
              AND pr.proj_pa >= ?
        """
        rows = conn.execute(query, (season, source, MIN_PA)).fetchall()
    else:
        query = """
            SELECT p.mlb_id, p.full_name, p.primary_position, p.team,
                   p.eligible_positions,
                   pr.proj_pa, pr.proj_runs, pr.proj_total_bases, pr.proj_rbi,
                   pr.proj_stolen_bases, pr.proj_obp,
                   pr.proj_hits, pr.proj_walks, pr.proj_hbp, pr.proj_sac_flies, pr.proj_at_bats,
                   pr.source
            FROM projections pr
            JOIN players p ON pr.mlb_id = p.mlb_id
            WHERE pr.season = ? AND pr.player_type = 'hitter'
        """
        rows = conn.execute(query, (season,)).fetchall()

    conn.close()

    if not rows:
        logger.warning(f"No hitter projections found for {season}")
        return []

    # Blend multiple sources or use single-source rows as-is
    if source:
        rows = [dict(r) for r in rows]
    else:
        rows, n_players, avg_src = _blend_projection_rows(rows, _HITTER_NUMERIC)
        logger.info(
            f"Blended projections from multiple sources for {n_players} hitters "
            f"(avg {avg_src:.1f} sources/player)"
        )
        # Apply MIN_PA filter after blending
        rows = [r for r in rows if (r["proj_pa"] or 0) >= MIN_PA]

    # Exclude drafted players (after blending, before z-score computation)
    if excluded_ids:
        rows = [r for r in rows if r["mlb_id"] not in excluded_ids]

    n = len(rows)
    logger.info(f"Calculating SGP values for {n} hitters")

    # Compute SGP denominators from league standings
    sgp_denoms = _compute_sgp_denominators(["R", "TB", "RBI", "SB", "OBP"])

    # Extract arrays
    mlb_ids = [r["mlb_id"] for r in rows]
    names = [r["full_name"] for r in rows]
    positions = [r["primary_position"] for r in rows]
    teams = [r["team"] for r in rows]
    elig_positions = [r.get("eligible_positions") for r in rows]
    pa = np.array([r["proj_pa"] or 0 for r in rows], dtype=float)

    runs = np.array([r["proj_runs"] or 0 for r in rows], dtype=float)
    tb = np.array([r["proj_total_bases"] or 0 for r in rows], dtype=float)
    rbi = np.array([r["proj_rbi"] or 0 for r in rows], dtype=float)
    sb = np.array([r["proj_stolen_bases"] or 0 for r in rows], dtype=float)

    # OBP: marginal approach — (player_OBP - league_avg) * (PA / avg_team_PA)
    obp_raw = np.array([r["proj_obp"] or 0 for r in rows], dtype=float)

    # Calculate league average OBP weighted by PA
    total_h = sum(r["proj_hits"] or 0 for r in rows)
    total_bb = sum(r["proj_walks"] or 0 for r in rows)
    total_hbp = sum(r["proj_hbp"] or 0 for r in rows)
    total_ab = sum(r["proj_at_bats"] or 0 for r in rows)
    total_sf = sum(r["proj_sac_flies"] or 0 for r in rows)
    denom = total_ab + total_bb + total_hbp + total_sf
    league_obp = (total_h + total_bb + total_hbp) / denom if denom > 0 else 0.320

    # SGP for counting stats: raw value / SGP denominator
    sgp_r = runs / sgp_denoms["R"]
    sgp_tb = tb / sgp_denoms["TB"]
    sgp_rbi = rbi / sgp_denoms["RBI"]
    sgp_sb = sb / sgp_denoms["SB"]

    # SGP for rate stat (OBP): marginal contribution / SGP denominator
    avg_team_pa = np.sum(pa) / NUM_TEAMS
    obp_marginal = (obp_raw - league_obp) * (pa / avg_team_pa) if avg_team_pa > 0 else obp_raw
    sgp_obp = obp_marginal / sgp_denoms["OBP"]

    # Build results with raw SGP values (no position adjustment yet)
    results = []
    for i in range(n):
        raw_sgp = float(sgp_r[i] + sgp_tb[i] + sgp_rbi[i] + sgp_sb[i] + sgp_obp[i])
        results.append({
            "mlb_id": mlb_ids[i],
            "full_name": names[i],
            "primary_position": positions[i],
            "eligible_positions": elig_positions[i],
            "team": teams[i],
            "player_type": "hitter",
            "zscore_r": round(float(sgp_r[i]), 3),
            "zscore_tb": round(float(sgp_tb[i]), 3),
            "zscore_rbi": round(float(sgp_rbi[i]), 3),
            "zscore_sb": round(float(sgp_sb[i]), 3),
            "zscore_obp": round(float(sgp_obp[i]), 3),
            "total_zscore": round(raw_sgp, 3),
            "replacement_adj": 0.0,
            # Raw projections for display
            "proj_pa": int(pa[i]),
            "proj_r": int(runs[i]),
            "proj_tb": int(tb[i]),
            "proj_rbi": int(rbi[i]),
            "proj_sb": int(sb[i]),
            "proj_obp": round(float(obp_raw[i]), 3),
        })

    # Apply playing time risk discount — linear ramp to full credit at FULL_CREDIT_PA
    discounted = 0
    for p in results:
        confidence = min(1.0, p["proj_pa"] / FULL_CREDIT_PA)
        if confidence < 1.0:
            discounted += 1
            for cat in ("zscore_r", "zscore_tb", "zscore_rbi", "zscore_sb", "zscore_obp"):
                p[cat] = round(p[cat] * confidence, 3)
            p["total_zscore"] = round(p["total_zscore"] * confidence, 3)
    if discounted:
        logger.info(f"Applied playing time discount to {discounted} hitters (< {FULL_CREDIT_PA} PA)")

    # Apply replacement-level baselines
    repl = _compute_hitter_replacement_levels(results)
    for p in results:
        slot = _best_slot(p.get("eligible_positions"), p["primary_position"], repl)
        repl_z = repl.get(slot, 0.0)
        p["replacement_adj"] = round(-repl_z, 3)
        p["total_zscore"] = round(p["total_zscore"] - repl_z, 3)

    results.sort(key=lambda x: x["total_zscore"], reverse=True)
    return results


def _compute_pitcher_pool_zscores(
    rows: list, pool_label: str, categories: set[str], min_ip: float
) -> list[dict]:
    """Compute z-scores for a single pitcher pool (SP or RP).

    Args:
        rows: list of DB rows (dicts) for this pool
        pool_label: "SP" or "RP" for logging
        categories: set of active categories, e.g. {"k", "qs", "era", "whip"}
        min_ip: minimum innings pitched to include

    Returns:
        List of player dicts with z-scores (excluded categories set to 0.0)
    """
    # Filter by minimum IP
    rows = [r for r in rows if (r["proj_ip"] or 0) >= min_ip]

    if not rows:
        logger.warning(f"No {pool_label} pitchers met min IP threshold ({min_ip})")
        return []

    n = len(rows)
    logger.info(f"Computing SGP values for {n} {pool_label}s (categories: {sorted(categories)})")

    # Compute SGP denominators for this pool's categories
    sgp_cats = [c.upper() for c in categories]
    sgp_denoms = _compute_sgp_denominators(sgp_cats)

    # Extract common arrays
    mlb_ids = [r["mlb_id"] for r in rows]
    names = [r["full_name"] for r in rows]
    positions = [r["primary_position"] for r in rows]
    teams = [r["team"] for r in rows]
    ip = np.array([r["proj_ip"] or 0 for r in rows], dtype=float)

    # Counting stats
    k = np.array([r["proj_pitcher_strikeouts"] or 0 for r in rows], dtype=float)
    qs = np.array([r["proj_quality_starts"] or 0 for r in rows], dtype=float)
    svhd = np.array(
        [(r["proj_saves"] or 0) + (r["proj_holds"] or 0) for r in rows], dtype=float
    )

    # Rate stats — marginal approach weighted by IP (pool-specific averages)
    era_raw = np.array([r["proj_era"] or 0 for r in rows], dtype=float)
    whip_raw = np.array([r["proj_whip"] or 0 for r in rows], dtype=float)

    total_er = sum(r["proj_earned_runs"] or 0 for r in rows)
    total_ip = float(np.sum(ip))
    total_ha = sum(r["proj_hits_allowed"] or 0 for r in rows)
    total_bba = sum(r["proj_walks_allowed"] or 0 for r in rows)
    league_era = (total_er * 9 / total_ip) if total_ip > 0 else 4.00
    league_whip = ((total_ha + total_bba) / total_ip) if total_ip > 0 else 1.25

    # SGP for counting stats (only for active categories)
    sgp_k = (k / sgp_denoms["K"]) if "k" in categories else np.zeros(n)
    sgp_qs = (qs / sgp_denoms["QS"]) if "qs" in categories else np.zeros(n)
    sgp_svhd = (svhd / sgp_denoms["SVHD"]) if "svhd" in categories else np.zeros(n)

    # SGP for rate stats: marginal contribution / SGP denominator
    # Inverted — lower ERA/WHIP = positive SGP
    avg_team_ip = np.sum(ip) / NUM_TEAMS
    if "era" in categories and avg_team_ip > 0:
        era_marginal = (league_era - era_raw) * (ip / avg_team_ip)
        sgp_era = era_marginal / sgp_denoms["ERA"]
    else:
        sgp_era = np.zeros(n)

    if "whip" in categories and avg_team_ip > 0:
        whip_marginal = (league_whip - whip_raw) * (ip / avg_team_ip)
        sgp_whip = whip_marginal / sgp_denoms["WHIP"]
    else:
        sgp_whip = np.zeros(n)

    # Build results with raw SGP values
    results = []
    for i in range(n):
        raw_sgp = float(sgp_k[i] + sgp_qs[i] + sgp_era[i] + sgp_whip[i] + sgp_svhd[i])
        results.append({
            "mlb_id": mlb_ids[i],
            "full_name": names[i],
            "primary_position": positions[i],
            "team": teams[i],
            "player_type": "pitcher",
            "zscore_k": round(float(sgp_k[i]), 3),
            "zscore_qs": round(float(sgp_qs[i]), 3),
            "zscore_era": round(float(sgp_era[i]), 3),
            "zscore_whip": round(float(sgp_whip[i]), 3),
            "zscore_svhd": round(float(sgp_svhd[i]), 3),
            "total_zscore": round(raw_sgp, 3),
            "replacement_adj": 0.0,
            # Raw projections
            "proj_ip": round(float(ip[i]), 1),
            "proj_k": int(k[i]),
            "proj_qs": int(qs[i]),
            "proj_era": round(float(era_raw[i]), 2),
            "proj_whip": round(float(whip_raw[i]), 2),
            "proj_svhd": int(svhd[i]),
        })

    # Apply playing time risk discount
    full_credit_ip = FULL_CREDIT_IP_SP if pool_label == "SP" else FULL_CREDIT_IP_RP
    discounted = 0
    for p in results:
        confidence = min(1.0, p["proj_ip"] / full_credit_ip)
        if confidence < 1.0:
            discounted += 1
            for cat in ("zscore_k", "zscore_qs", "zscore_era", "zscore_whip", "zscore_svhd"):
                p[cat] = round(p[cat] * confidence, 3)
            p["total_zscore"] = round(p["total_zscore"] * confidence, 3)
    if discounted:
        logger.info(f"Applied playing time discount to {discounted} {pool_label}s (< {full_credit_ip} IP)")

    return results


def calculate_pitcher_zscores(season: int = 2026, source: str = None,
                              excluded_ids: set[int] | None = None) -> list[dict]:
    """Calculate z-scores for all pitchers, split into SP and RP pools.

    SP categories: K, QS, ERA, WHIP (min 30 IP)
    RP categories: K, SVHD, ERA, WHIP (min 15 IP)

    Each pool computes z-scores independently against its peers,
    then results are combined and sorted by total z-score.

    Args:
        excluded_ids: If provided, exclude these mlb_ids after blending but
                      before pool splitting (for draft recalculation).
    """
    _PITCHER_NUMERIC = [
        "proj_ip", "proj_pitcher_strikeouts", "proj_quality_starts",
        "proj_era", "proj_whip", "proj_saves", "proj_holds",
        "proj_hits_allowed", "proj_walks_allowed", "proj_earned_runs",
    ]

    conn = get_connection()

    # Query all pitchers without IP filter — filtering happens per-pool
    if source:
        query = """
            SELECT p.mlb_id, p.full_name, p.primary_position, p.team,
                   pr.proj_ip, pr.proj_pitcher_strikeouts, pr.proj_quality_starts,
                   pr.proj_era, pr.proj_whip, pr.proj_saves, pr.proj_holds,
                   pr.proj_hits_allowed, pr.proj_walks_allowed, pr.proj_earned_runs
            FROM projections pr
            JOIN players p ON pr.mlb_id = p.mlb_id
            WHERE pr.season = ? AND pr.player_type = 'pitcher' AND pr.source = ?
        """
        rows = conn.execute(query, (season, source)).fetchall()
    else:
        query = """
            SELECT p.mlb_id, p.full_name, p.primary_position, p.team,
                   pr.proj_ip, pr.proj_pitcher_strikeouts, pr.proj_quality_starts,
                   pr.proj_era, pr.proj_whip, pr.proj_saves, pr.proj_holds,
                   pr.proj_hits_allowed, pr.proj_walks_allowed, pr.proj_earned_runs,
                   pr.source
            FROM projections pr
            JOIN players p ON pr.mlb_id = p.mlb_id
            WHERE pr.season = ? AND pr.player_type = 'pitcher'
        """
        rows = conn.execute(query, (season,)).fetchall()

    conn.close()

    if not rows:
        logger.warning(f"No pitcher projections found for {season}")
        return []

    # Blend multiple sources or use single-source rows as-is
    if source:
        rows = [dict(r) for r in rows]
    else:
        rows, n_players, avg_src = _blend_projection_rows(rows, _PITCHER_NUMERIC)
        logger.info(
            f"Blended projections from multiple sources for {n_players} pitchers "
            f"(avg {avg_src:.1f} sources/player)"
        )

    # Exclude drafted players (after blending, before pool splitting)
    if excluded_ids:
        rows = [r for r in rows if r["mlb_id"] not in excluded_ids]

    # Classify into SP/RP pools
    sp_rows = []
    rp_rows = []
    for row in rows:
        role = _classify_pitcher(
            row["primary_position"],
            row["proj_ip"] or 0,
            row["proj_quality_starts"] or 0,
        )
        if role == "SP":
            sp_rows.append(row)
        else:
            rp_rows.append(row)

    logger.info(
        f"Pitcher pool split: {len(sp_rows)} SP candidates, {len(rp_rows)} RP candidates"
    )

    # Compute z-scores within each pool using only relevant categories
    sp_results = _compute_pitcher_pool_zscores(
        sp_rows, "SP", {"k", "qs", "era", "whip"}, MIN_IP_SP
    )
    rp_results = _compute_pitcher_pool_zscores(
        rp_rows, "RP", {"k", "svhd", "era", "whip"}, MIN_IP_RP
    )

    # Compute replacement levels across both pools (handles flex P slots)
    repl = _compute_pitcher_replacement_levels(sp_results, rp_results)

    for p in sp_results:
        repl_z = repl["SP"]
        p["replacement_adj"] = round(-repl_z, 3)
        p["total_zscore"] = round(p["total_zscore"] - repl_z, 3)

    for p in rp_results:
        repl_z = repl["RP"]
        p["replacement_adj"] = round(-repl_z, 3)
        p["total_zscore"] = round(p["total_zscore"] - repl_z, 3)

    # Combine and sort
    results = sp_results + rp_results
    results.sort(key=lambda x: x["total_zscore"], reverse=True)
    return results


def calculate_all_zscores(season: int = 2026, source: str = None,
                          excluded_ids: set[int] | None = None,
                          save_to_db: bool = True):
    """Calculate z-scores for all players and optionally save to rankings table.

    Args:
        excluded_ids: If provided, exclude these mlb_ids from the player pool
                      before computing z-scores (for draft recalculation).
        save_to_db: If False, skip writing to the rankings table (ephemeral results).
    """
    hitters = calculate_hitter_zscores(season, source, excluded_ids)
    pitchers = calculate_pitcher_zscores(season, source, excluded_ids)

    # Combine and rank overall
    all_players = hitters + pitchers
    all_players.sort(key=lambda x: x["total_zscore"], reverse=True)

    # Assign overall ranks
    for rank, player in enumerate(all_players, 1):
        player["overall_rank"] = rank

    # Assign position ranks
    pos_counters: dict[str, int] = {}
    # Sort within type for position ranking
    for player in sorted(hitters, key=lambda x: x["total_zscore"], reverse=True):
        pos = player["primary_position"]
        pos_counters[pos] = pos_counters.get(pos, 0) + 1
        player["position_rank"] = pos_counters[pos]

    for player in sorted(pitchers, key=lambda x: x["total_zscore"], reverse=True):
        pos = player["primary_position"]
        pos_counters[pos] = pos_counters.get(pos, 0) + 1
        player["position_rank"] = pos_counters[pos]

    if save_to_db:
        conn = get_connection()
        for p in all_players:
            conn.execute(
                """INSERT OR REPLACE INTO rankings
                   (mlb_id, season, overall_rank, position_rank, total_zscore,
                    zscore_r, zscore_tb, zscore_rbi, zscore_sb, zscore_obp,
                    zscore_k, zscore_qs, zscore_era, zscore_whip, zscore_svhd,
                    player_type)
                   VALUES (?, ?, ?, ?, ?,
                           ?, ?, ?, ?, ?,
                           ?, ?, ?, ?, ?,
                           ?)""",
                (
                    p["mlb_id"], season, p["overall_rank"], p["position_rank"],
                    p["total_zscore"],
                    p.get("zscore_r", 0), p.get("zscore_tb", 0),
                    p.get("zscore_rbi", 0), p.get("zscore_sb", 0),
                    p.get("zscore_obp", 0), p.get("zscore_k", 0),
                    p.get("zscore_qs", 0), p.get("zscore_era", 0),
                    p.get("zscore_whip", 0), p.get("zscore_svhd", 0),
                    p["player_type"],
                ),
            )
        conn.commit()
        conn.close()
        logger.info(
            f"Saved rankings: {len(hitters)} hitters + {len(pitchers)} pitchers = {len(all_players)} total"
        )
    else:
        logger.info(
            f"Computed rankings (ephemeral): {len(hitters)} hitters + {len(pitchers)} pitchers = {len(all_players)} total"
        )

    return all_players
