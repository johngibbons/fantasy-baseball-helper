"""Parse and import projection data from CSV files (Steamer, ZiPS, THE BAT X, etc.)
and generate simple trend-based projections from historical stats."""

import csv
import logging
from pathlib import Path
from typing import Optional
from backend.database import get_connection

logger = logging.getLogger(__name__)

PROJECTIONS_DIR = Path(__file__).parent.parent / "projection_data"


def _safe_int(val):
    """Convert a value to int, handling floats like '633.319' and missing values."""
    try:
        return int(round(float(val))) if val else 0
    except (ValueError, TypeError):
        return 0


def _safe_float(val):
    """Convert a value to float, handling missing values."""
    try:
        return float(val) if val else 0.0
    except (ValueError, TypeError):
        return 0.0


def _resolve_mlb_id(conn, row) -> Optional[int]:
    """Resolve a player's mlb_id from a CSV row.

    Uses MLBAMID column if available (direct match), otherwise falls back
    to name-based lookup.
    """
    # Prefer MLBAMID (exact match, no ambiguity)
    mlbamid = row.get("MLBAMID", "").strip()
    if mlbamid:
        try:
            mid = int(mlbamid)
            player = conn.execute(
                "SELECT mlb_id FROM players WHERE mlb_id = ?", (mid,)
            ).fetchone()
            if player:
                return player["mlb_id"]
        except (ValueError, TypeError):
            pass

    # Fall back to name lookup
    name = row.get("Name", "").strip().strip('"')
    if not name:
        return None
    player = conn.execute(
        "SELECT mlb_id FROM players WHERE full_name = ? OR full_name LIKE ?",
        (name, f"%{name}%"),
    ).fetchone()
    if player:
        return player["mlb_id"]

    logger.debug(f"Player not found in DB: {name} (MLBAMID={mlbamid})")
    return None


def import_fangraphs_batting(filepath: str, source: str, season: int = 2025):
    """Import FanGraphs batting projections from CSV.

    Works with any FanGraphs projection system (Steamer, ZiPS, THE BAT X, etc.)
    since they all share the same CSV export format.

    Args:
        filepath: Path to the FanGraphs CSV export.
        source: Projection system identifier ("steamer", "zips", "thebatx").
        season: Projection season year.
    """
    valid_sources = {"steamer", "zips", "thebatx"}
    if source not in valid_sources:
        raise ValueError(f"Invalid source '{source}', must be one of {sorted(valid_sources)}")

    conn = get_connection()
    imported = 0
    skipped = 0

    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            mlb_id = _resolve_mlb_id(conn, row)
            if mlb_id is None:
                skipped += 1
                continue

            pa = _safe_int(row.get("PA"))
            ab = _safe_int(row.get("AB"))
            hits = _safe_int(row.get("H"))
            doubles = _safe_int(row.get("2B"))
            triples = _safe_int(row.get("3B"))
            hr = _safe_int(row.get("HR"))
            singles = hits - doubles - triples - hr
            tb = singles + (2 * doubles) + (3 * triples) + (4 * hr)

            conn.execute(
                """INSERT OR REPLACE INTO projections
                   (mlb_id, source, season, player_type,
                    proj_pa, proj_at_bats, proj_runs, proj_hits, proj_doubles, proj_triples,
                    proj_home_runs, proj_rbi, proj_stolen_bases, proj_walks,
                    proj_strikeouts, proj_hbp, proj_sac_flies, proj_obp, proj_total_bases)
                   VALUES (?, ?, ?, 'hitter',
                           ?, ?, ?, ?, ?, ?,
                           ?, ?, ?, ?,
                           ?, ?, ?, ?, ?)""",
                (
                    mlb_id, source, season,
                    pa, ab,
                    _safe_int(row.get("R")),
                    hits, doubles, triples, hr,
                    _safe_int(row.get("RBI")),
                    _safe_int(row.get("SB")),
                    _safe_int(row.get("BB")),
                    _safe_int(row.get("SO")),
                    _safe_int(row.get("HBP")),
                    _safe_int(row.get("SF")),
                    _safe_float(row.get("OBP")),
                    tb,
                ),
            )
            imported += 1

    conn.commit()
    conn.close()
    logger.info(f"Imported {imported} {source} batting projections from {filepath} ({skipped} skipped)")
    return imported


def import_fangraphs_pitching(filepath: str, source: str, season: int = 2025):
    """Import FanGraphs pitching projections from CSV.

    Works with any FanGraphs projection system (Steamer, ZiPS, THE BAT X, etc.)
    since they all share the same CSV export format.

    Args:
        filepath: Path to the FanGraphs CSV export.
        source: Projection system identifier ("steamer", "zips", "thebatx").
        season: Projection season year.
    """
    valid_sources = {"steamer", "zips", "thebatx"}
    if source not in valid_sources:
        raise ValueError(f"Invalid source '{source}', must be one of {sorted(valid_sources)}")

    conn = get_connection()
    imported = 0
    skipped = 0

    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            mlb_id = _resolve_mlb_id(conn, row)
            if mlb_id is None:
                skipped += 1
                continue

            conn.execute(
                """INSERT OR REPLACE INTO projections
                   (mlb_id, source, season, player_type,
                    proj_ip, proj_pitcher_strikeouts, proj_quality_starts,
                    proj_era, proj_whip, proj_saves, proj_holds, proj_wins,
                    proj_hits_allowed, proj_walks_allowed, proj_earned_runs)
                   VALUES (?, ?, ?, 'pitcher',
                           ?, ?, ?,
                           ?, ?, ?, ?, ?,
                           ?, ?, ?)""",
                (
                    mlb_id, source, season,
                    _safe_float(row.get("IP")),
                    _safe_int(row.get("SO")),
                    _safe_int(row.get("QS")),
                    _safe_float(row.get("ERA")),
                    _safe_float(row.get("WHIP")),
                    _safe_int(row.get("SV")),
                    _safe_int(row.get("HLD")),
                    _safe_int(row.get("W")),
                    _safe_int(row.get("H")),
                    _safe_int(row.get("BB")),
                    _safe_int(row.get("ER")),
                ),
            )
            imported += 1

    conn.commit()
    conn.close()
    logger.info(f"Imported {imported} {source} pitching projections from {filepath} ({skipped} skipped)")
    return imported


def import_position_eligibility(filepath: str):
    """Import ESPN position eligibility from CSV.

    CSV format:
        player_name,team,eligible_positions
        Aaron Judge,NYY,OF/DH

    Updates the eligible_positions column in the players table.
    Matches players by full_name (exact or LIKE match).

    Args:
        filepath: Path to the eligibility CSV file.
    """
    conn = get_connection()
    updated = 0
    skipped = 0

    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("player_name", "").strip()
            positions = row.get("eligible_positions", "").strip()
            if not name or not positions:
                continue

            # Try exact match first, then LIKE
            player = conn.execute(
                "SELECT mlb_id FROM players WHERE full_name = ?", (name,)
            ).fetchone()
            if not player:
                player = conn.execute(
                    "SELECT mlb_id FROM players WHERE full_name LIKE ?",
                    (f"%{name}%",),
                ).fetchone()

            if player:
                conn.execute(
                    "UPDATE players SET eligible_positions = ? WHERE mlb_id = ?",
                    (positions, player["mlb_id"]),
                )
                updated += 1
            else:
                skipped += 1
                logger.debug(f"Player not found for eligibility: {name}")

    conn.commit()
    conn.close()
    logger.info(f"Updated position eligibility for {updated} players ({skipped} not found)")
    return updated


def import_league_standings(filepath: str, season: int):
    """Import league standings (team category totals) from CSV.

    CSV format (matching ESPN layout):
        season,team,R,TB,RBI,SB,OBP,K,QS,ERA,WHIP,SVHD

    Inserts or replaces rows in league_season_totals.
    Multiple seasons can be imported to improve SGP denominator accuracy.

    Args:
        filepath: Path to the standings CSV file.
        season: Season year (used as default if CSV lacks a season column).
    """
    conn = get_connection()
    imported = 0

    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row_season = _safe_int(row.get("season")) or season
            team = row.get("team", "").strip()
            if not team:
                continue

            conn.execute(
                """INSERT OR REPLACE INTO league_season_totals
                   (season, team_name, team_r, team_tb, team_rbi, team_sb, team_obp,
                    team_k, team_qs, team_era, team_whip, team_svhd)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    row_season, team,
                    _safe_int(row.get("R")),
                    _safe_int(row.get("TB")),
                    _safe_int(row.get("RBI")),
                    _safe_int(row.get("SB")),
                    _safe_float(row.get("OBP")),
                    _safe_int(row.get("K")),
                    _safe_int(row.get("QS")),
                    _safe_float(row.get("ERA")),
                    _safe_float(row.get("WHIP")),
                    _safe_int(row.get("SVHD")),
                ),
            )
            imported += 1

    conn.commit()
    conn.close()
    logger.info(f"Imported {imported} team standings rows for season {season} from {filepath}")
    return imported


def generate_projections_from_stats(season: int = 2025):
    """Generate simple projections based on recent historical stats.

    Uses a weighted average of last 3 seasons (if available) with recency bias.
    This is a fallback when external projections aren't loaded.
    """
    conn = get_connection()
    weights = {0: 0.5, 1: 0.3, 2: 0.2}  # most recent season gets highest weight
    seasons_back = [season - 1, season - 2, season - 3]

    # Generate hitter projections
    hitters = conn.execute(
        "SELECT mlb_id FROM players WHERE player_type = 'hitter' AND is_active = 1"
    ).fetchall()

    hitter_count = 0
    for h in hitters:
        mlb_id = h["mlb_id"]
        stats_rows = conn.execute(
            """SELECT * FROM batting_stats
               WHERE mlb_id = ? AND season IN (?, ?, ?)
               ORDER BY season DESC""",
            (mlb_id, *seasons_back),
        ).fetchall()

        if not stats_rows:
            continue

        # Weighted average
        proj = {}
        fields = [
            "plate_appearances", "at_bats", "runs", "hits", "doubles", "triples",
            "home_runs", "rbi", "stolen_bases", "walks", "strikeouts",
            "hit_by_pitch", "sac_flies",
        ]
        total_weight = 0
        for i, row in enumerate(stats_rows):
            w = weights.get(i, 0.1)
            total_weight += w
            for field in fields:
                proj[field] = proj.get(field, 0) + (row[field] or 0) * w

        if total_weight > 0:
            for field in fields:
                proj[field] = round(proj[field] / total_weight)

        # Calculate derived stats
        singles = proj["hits"] - proj["doubles"] - proj["triples"] - proj["home_runs"]
        tb = singles + 2 * proj["doubles"] + 3 * proj["triples"] + 4 * proj["home_runs"]

        # OBP = (H + BB + HBP) / (AB + BB + HBP + SF)
        obp_denom = proj["at_bats"] + proj["walks"] + proj["hit_by_pitch"] + proj["sac_flies"]
        obp = (proj["hits"] + proj["walks"] + proj["hit_by_pitch"]) / obp_denom if obp_denom > 0 else 0

        conn.execute(
            """INSERT OR REPLACE INTO projections
               (mlb_id, source, season, player_type,
                proj_pa, proj_at_bats, proj_runs, proj_hits, proj_doubles, proj_triples,
                proj_home_runs, proj_rbi, proj_stolen_bases, proj_walks,
                proj_strikeouts, proj_hbp, proj_sac_flies, proj_obp, proj_total_bases)
               VALUES (?, 'trend', ?, 'hitter',
                       ?, ?, ?, ?, ?, ?,
                       ?, ?, ?, ?,
                       ?, ?, ?, ?, ?)""",
            (
                mlb_id, season,
                proj["plate_appearances"], proj["at_bats"],
                proj["runs"], proj["hits"], proj["doubles"], proj["triples"],
                proj["home_runs"], proj["rbi"], proj["stolen_bases"], proj["walks"],
                proj["strikeouts"], proj["hit_by_pitch"], proj["sac_flies"],
                round(obp, 3), tb,
            ),
        )
        hitter_count += 1

    # Generate pitcher projections
    pitchers = conn.execute(
        "SELECT mlb_id FROM players WHERE player_type = 'pitcher' AND is_active = 1"
    ).fetchall()

    pitcher_count = 0
    for p in pitchers:
        mlb_id = p["mlb_id"]
        stats_rows = conn.execute(
            """SELECT * FROM pitching_stats
               WHERE mlb_id = ? AND season IN (?, ?, ?)
               ORDER BY season DESC""",
            (mlb_id, *seasons_back),
        ).fetchall()

        if not stats_rows:
            continue

        proj = {}
        fields = [
            "innings_pitched", "strikeouts", "quality_starts", "saves", "holds",
            "wins", "hits_allowed", "walks_allowed", "earned_runs",
        ]
        total_weight = 0
        for i, row in enumerate(stats_rows):
            w = weights.get(i, 0.1)
            total_weight += w
            for field in fields:
                proj[field] = proj.get(field, 0) + (row[field] or 0) * w

        if total_weight > 0:
            for field in fields:
                proj[field] = proj[field] / total_weight
                if field != "innings_pitched":
                    proj[field] = round(proj[field])
                else:
                    proj[field] = round(proj[field], 1)

        # ERA = (ER * 9) / IP
        era = (proj["earned_runs"] * 9) / proj["innings_pitched"] if proj["innings_pitched"] > 0 else 0
        # WHIP = (H + BB) / IP
        whip = (proj["hits_allowed"] + proj["walks_allowed"]) / proj["innings_pitched"] if proj["innings_pitched"] > 0 else 0

        conn.execute(
            """INSERT OR REPLACE INTO projections
               (mlb_id, source, season, player_type,
                proj_ip, proj_pitcher_strikeouts, proj_quality_starts,
                proj_era, proj_whip, proj_saves, proj_holds, proj_wins,
                proj_hits_allowed, proj_walks_allowed, proj_earned_runs)
               VALUES (?, 'trend', ?, 'pitcher',
                       ?, ?, ?,
                       ?, ?, ?, ?, ?,
                       ?, ?, ?)""",
            (
                mlb_id, season,
                proj["innings_pitched"], proj["strikeouts"], proj["quality_starts"],
                round(era, 2), round(whip, 2), proj["saves"], proj["holds"], proj["wins"],
                proj["hits_allowed"], proj["walks_allowed"], proj["earned_runs"],
            ),
        )
        pitcher_count += 1

    conn.commit()
    conn.close()
    logger.info(f"Generated trend projections: {hitter_count} hitters, {pitcher_count} pitchers")
    return hitter_count + pitcher_count
