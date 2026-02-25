"""Parse and import projection data from CSV files or FanGraphs API
(Steamer, ZiPS, THE BAT X, etc.) and generate simple trend-based
projections from historical stats."""

import csv
import logging
import time
import unicodedata
from datetime import date
from pathlib import Path
from typing import Optional

import httpx

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
                """INSERT INTO projections
                   (mlb_id, source, season, player_type,
                    proj_pa, proj_at_bats, proj_runs, proj_hits, proj_doubles, proj_triples,
                    proj_home_runs, proj_rbi, proj_stolen_bases, proj_walks,
                    proj_strikeouts, proj_hbp, proj_sac_flies, proj_obp, proj_total_bases)
                   VALUES (?, ?, ?, 'hitter',
                           ?, ?, ?, ?, ?, ?,
                           ?, ?, ?, ?,
                           ?, ?, ?, ?, ?)
                   ON CONFLICT (mlb_id, source, season, player_type) DO UPDATE SET
                     proj_pa = EXCLUDED.proj_pa, proj_at_bats = EXCLUDED.proj_at_bats,
                     proj_runs = EXCLUDED.proj_runs, proj_hits = EXCLUDED.proj_hits,
                     proj_doubles = EXCLUDED.proj_doubles, proj_triples = EXCLUDED.proj_triples,
                     proj_home_runs = EXCLUDED.proj_home_runs, proj_rbi = EXCLUDED.proj_rbi,
                     proj_stolen_bases = EXCLUDED.proj_stolen_bases, proj_walks = EXCLUDED.proj_walks,
                     proj_strikeouts = EXCLUDED.proj_strikeouts, proj_hbp = EXCLUDED.proj_hbp,
                     proj_sac_flies = EXCLUDED.proj_sac_flies, proj_obp = EXCLUDED.proj_obp,
                     proj_total_bases = EXCLUDED.proj_total_bases""",
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
                """INSERT INTO projections
                   (mlb_id, source, season, player_type,
                    proj_ip, proj_pitcher_strikeouts, proj_quality_starts,
                    proj_era, proj_whip, proj_saves, proj_holds, proj_wins,
                    proj_hits_allowed, proj_walks_allowed, proj_earned_runs)
                   VALUES (?, ?, ?, 'pitcher',
                           ?, ?, ?,
                           ?, ?, ?, ?, ?,
                           ?, ?, ?)
                   ON CONFLICT (mlb_id, source, season, player_type) DO UPDATE SET
                     proj_ip = EXCLUDED.proj_ip, proj_pitcher_strikeouts = EXCLUDED.proj_pitcher_strikeouts,
                     proj_quality_starts = EXCLUDED.proj_quality_starts,
                     proj_era = EXCLUDED.proj_era, proj_whip = EXCLUDED.proj_whip,
                     proj_saves = EXCLUDED.proj_saves, proj_holds = EXCLUDED.proj_holds,
                     proj_wins = EXCLUDED.proj_wins, proj_hits_allowed = EXCLUDED.proj_hits_allowed,
                     proj_walks_allowed = EXCLUDED.proj_walks_allowed,
                     proj_earned_runs = EXCLUDED.proj_earned_runs""",
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


# ── FanGraphs API Fetch ──

_FG_API_BASE = "https://www.fangraphs.com/api/projections"

# FanGraphs projection type parameter → our source name
_FG_SOURCES = {
    "steamer": "steamer",
    "zips": "zips",
    "thebatx": "thebatx",
}

# Delay between API requests (be polite)
_FG_REQUEST_DELAY = 1.5


def _fetch_fg_json(fg_type: str, stats: str) -> list[dict]:
    """Fetch projection JSON from FanGraphs API.

    Args:
        fg_type: Projection type param (e.g. 'steamer', 'zips', 'thebatx')
        stats: 'bat' for batting, 'pit' for pitching

    Returns:
        List of player projection dicts.
    """
    url = f"{_FG_API_BASE}?type={fg_type}&stats={stats}&pos=all&team=0&players=0"
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; FantasyBaseballHelper/1.0)",
        "Accept": "application/json",
        "Referer": "https://www.fangraphs.com/projections",
    }
    logger.info(f"Fetching FanGraphs {fg_type} {stats}: {url}")
    resp = httpx.get(url, headers=headers, timeout=30, follow_redirects=True)
    if resp.status_code != 200:
        logger.error(f"FanGraphs returned {resp.status_code} for {fg_type} {stats}: {resp.text[:500]}")
    resp.raise_for_status()
    data = resp.json()
    logger.info(f"  Got {len(data)} rows")
    return data


def _fg_resolve_mlb_id(conn, row: dict) -> Optional[int]:
    """Resolve a FanGraphs API player to our mlb_id via xMLBAMID or name."""
    mlbam_id = row.get("xMLBAMID") or row.get("mlbamid")
    if mlbam_id:
        try:
            mid = int(mlbam_id)
            player = conn.execute(
                "SELECT mlb_id FROM players WHERE mlb_id = ?", (mid,)
            ).fetchone()
            if player:
                return player["mlb_id"]
        except (ValueError, TypeError):
            pass

    name = row.get("PlayerName", "").strip()
    if not name:
        return None
    player = conn.execute(
        "SELECT mlb_id FROM players WHERE full_name = ? OR full_name LIKE ?",
        (name, f"%{name}%"),
    ).fetchone()
    if player:
        return player["mlb_id"]
    return None


def fetch_fangraphs_batting(
    fg_type: str, source: str, season: int, adp_map: dict[int, float] | None = None,
) -> int:
    """Fetch batting projections from FanGraphs API and store in DB.

    Uses the exact same DB schema as import_fangraphs_batting (CSV version).

    Args:
        fg_type: FanGraphs type parameter (e.g. 'steamer')
        source: Our source name (e.g. 'steamer')
        season: Projection season year
        adp_map: If provided, collects {mlb_id: ADP} from the response.

    Returns:
        Number of players imported.
    """
    data = _fetch_fg_json(fg_type, "bat")
    conn = get_connection()
    imported = 0
    skipped = 0

    for row in data:
        mlb_id = _fg_resolve_mlb_id(conn, row)
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
            """INSERT INTO projections
               (mlb_id, source, season, player_type,
                proj_pa, proj_at_bats, proj_runs, proj_hits, proj_doubles, proj_triples,
                proj_home_runs, proj_rbi, proj_stolen_bases, proj_walks,
                proj_strikeouts, proj_hbp, proj_sac_flies, proj_obp, proj_total_bases)
               VALUES (?, ?, ?, 'hitter',
                       ?, ?, ?, ?, ?, ?,
                       ?, ?, ?, ?,
                       ?, ?, ?, ?, ?)
               ON CONFLICT (mlb_id, source, season, player_type) DO UPDATE SET
                 proj_pa = EXCLUDED.proj_pa, proj_at_bats = EXCLUDED.proj_at_bats,
                 proj_runs = EXCLUDED.proj_runs, proj_hits = EXCLUDED.proj_hits,
                 proj_doubles = EXCLUDED.proj_doubles, proj_triples = EXCLUDED.proj_triples,
                 proj_home_runs = EXCLUDED.proj_home_runs, proj_rbi = EXCLUDED.proj_rbi,
                 proj_stolen_bases = EXCLUDED.proj_stolen_bases, proj_walks = EXCLUDED.proj_walks,
                 proj_strikeouts = EXCLUDED.proj_strikeouts, proj_hbp = EXCLUDED.proj_hbp,
                 proj_sac_flies = EXCLUDED.proj_sac_flies, proj_obp = EXCLUDED.proj_obp,
                 proj_total_bases = EXCLUDED.proj_total_bases""",
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

        # Collect ADP if present
        if adp_map is not None:
            adp_val = _safe_float(row.get("ADP"))
            if adp_val > 0:
                if mlb_id not in adp_map or adp_val < adp_map[mlb_id]:
                    adp_map[mlb_id] = adp_val

    conn.commit()
    conn.close()
    logger.info(f"Imported {imported} {source} batting projections from FanGraphs API ({skipped} skipped)")
    return imported


def fetch_fangraphs_pitching(
    fg_type: str, source: str, season: int, adp_map: dict[int, float] | None = None,
) -> int:
    """Fetch pitching projections from FanGraphs API and store in DB.

    Uses the exact same DB schema as import_fangraphs_pitching (CSV version).

    Args:
        fg_type: FanGraphs type parameter (e.g. 'steamer')
        source: Our source name (e.g. 'steamer')
        season: Projection season year
        adp_map: If provided, collects {mlb_id: ADP} from the response.

    Returns:
        Number of players imported.
    """
    data = _fetch_fg_json(fg_type, "pit")
    conn = get_connection()
    imported = 0
    skipped = 0

    for row in data:
        mlb_id = _fg_resolve_mlb_id(conn, row)
        if mlb_id is None:
            skipped += 1
            continue

        conn.execute(
            """INSERT INTO projections
               (mlb_id, source, season, player_type,
                proj_ip, proj_pitcher_strikeouts, proj_quality_starts,
                proj_era, proj_whip, proj_saves, proj_holds, proj_wins,
                proj_hits_allowed, proj_walks_allowed, proj_earned_runs)
               VALUES (?, ?, ?, 'pitcher',
                       ?, ?, ?,
                       ?, ?, ?, ?, ?,
                       ?, ?, ?)
               ON CONFLICT (mlb_id, source, season, player_type) DO UPDATE SET
                 proj_ip = EXCLUDED.proj_ip, proj_pitcher_strikeouts = EXCLUDED.proj_pitcher_strikeouts,
                 proj_quality_starts = EXCLUDED.proj_quality_starts,
                 proj_era = EXCLUDED.proj_era, proj_whip = EXCLUDED.proj_whip,
                 proj_saves = EXCLUDED.proj_saves, proj_holds = EXCLUDED.proj_holds,
                 proj_wins = EXCLUDED.proj_wins, proj_hits_allowed = EXCLUDED.proj_hits_allowed,
                 proj_walks_allowed = EXCLUDED.proj_walks_allowed,
                 proj_earned_runs = EXCLUDED.proj_earned_runs""",
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

        # Collect ADP if present
        if adp_map is not None:
            adp_val = _safe_float(row.get("ADP"))
            if adp_val > 0:
                if mlb_id not in adp_map or adp_val < adp_map[mlb_id]:
                    adp_map[mlb_id] = adp_val

    conn.commit()
    conn.close()
    logger.info(f"Imported {imported} {source} pitching projections from FanGraphs API ({skipped} skipped)")
    return imported


def import_adp_from_api(adp_map: dict[int, float], season: int) -> int:
    """Write ADP data collected from FanGraphs API into the rankings table.

    Args:
        adp_map: {mlb_id: ADP} — lowest ADP across all sources/player types
        season: Season year

    Returns:
        Number of players updated.
    """
    conn = get_connection()
    updated = 0
    for mlb_id, adp in adp_map.items():
        result = conn.execute(
            """UPDATE rankings
               SET espn_adp = ?, adp_diff = overall_rank - ?
               WHERE mlb_id = ? AND season = ?""",
            (adp, adp, mlb_id, season),
        )
        if result.rowcount > 0:
            updated += 1
    conn.commit()
    conn.close()
    logger.info(f"Imported ADP for {updated} players from FanGraphs API ({len(adp_map)} total)")
    return updated


def fetch_all_fangraphs_projections(season: int) -> dict[str, int]:
    """Fetch all projection sources from FanGraphs API.

    Fetches Steamer, ZiPS, and THE BAT X batting + pitching projections,
    plus ADP data from whichever source provides it.

    Args:
        season: Projection season year

    Returns:
        Dict mapping source name to total players imported.
    """
    results = {}
    adp_map: dict[int, float] = {}

    for fg_type, source in _FG_SOURCES.items():
        try:
            bat = fetch_fangraphs_batting(fg_type, source, season, adp_map)
            time.sleep(_FG_REQUEST_DELAY)
            pit = fetch_fangraphs_pitching(fg_type, source, season, adp_map)
            time.sleep(_FG_REQUEST_DELAY)
            results[source] = bat + pit
            logger.info(f"  {source}: {bat} batters + {pit} pitchers")
        except Exception as e:
            logger.warning(f"Failed to fetch {source} projections from FanGraphs: {e}")
            results[source] = 0

    # Store collected ADP data for later (after rankings are computed)
    results["_adp_map"] = adp_map  # type: ignore[assignment]

    total = sum(v for k, v in results.items() if k != "_adp_map")
    logger.info(f"FanGraphs API projection fetch complete: {total} total across {len(_FG_SOURCES)} sources, {len(adp_map)} players with ADP")
    return results


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

    def _strip_accents(s: str) -> str:
        return "".join(
            c for c in unicodedata.normalize("NFD", s)
            if unicodedata.category(c) != "Mn"
        ).lower()

    # Build accent-insensitive lookup from all players in DB
    all_players = conn.execute("SELECT mlb_id, full_name FROM players").fetchall()
    name_to_id: dict[str, int] = {}
    stripped_to_id: dict[str, int] = {}
    for p in all_players:
        name_to_id[p["full_name"].lower()] = p["mlb_id"]
        stripped_to_id[_strip_accents(p["full_name"])] = p["mlb_id"]

    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("player_name", "").strip()
            positions = row.get("eligible_positions", "").strip()
            if not name or not positions:
                continue

            # Try exact match, then accent-stripped match
            mlb_id = name_to_id.get(name.lower())
            if not mlb_id:
                mlb_id = stripped_to_id.get(_strip_accents(name))

            if mlb_id:
                conn.execute(
                    "UPDATE players SET eligible_positions = ? WHERE mlb_id = ?",
                    (positions, mlb_id),
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
                """INSERT INTO league_season_totals
                   (season, team_name, team_r, team_tb, team_rbi, team_sb, team_obp,
                    team_k, team_qs, team_era, team_whip, team_svhd)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (season, team_name) DO UPDATE SET
                     team_r = EXCLUDED.team_r, team_tb = EXCLUDED.team_tb,
                     team_rbi = EXCLUDED.team_rbi, team_sb = EXCLUDED.team_sb,
                     team_obp = EXCLUDED.team_obp, team_k = EXCLUDED.team_k,
                     team_qs = EXCLUDED.team_qs, team_era = EXCLUDED.team_era,
                     team_whip = EXCLUDED.team_whip, team_svhd = EXCLUDED.team_svhd""",
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


# ── Age-curve weights for trend projections ──
# Young players (22-26): lean harder on most recent season — breakouts more
# likely to sustain.  Older players (32+): also lean on recent season since
# decline is likely to accelerate.  Prime-age (27-31): balanced weights.
_AGE_WEIGHTS = {
    "young":  {0: 0.60, 1: 0.25, 2: 0.15},
    "prime":  {0: 0.50, 1: 0.30, 2: 0.20},
    "older":  {0: 0.60, 1: 0.25, 2: 0.15},
}

# Small growth/decline multiplier applied to counting stats after weighting.
# Rate stats (OBP, ERA, WHIP) are NOT multiplied — aging affects rate stats
# primarily through playing-time loss, which is already captured by the PA/IP
# projection.
_AGE_COUNTING_MULTIPLIER = {
    "young": 1.03,   # +3% growth expectation
    "prime": 1.00,
    "older": 0.97,   # -3% decline expectation
}


def _player_age(birth_date_str: str, season: int) -> Optional[int]:
    """Compute a player's age as of July 1 of the projection season."""
    if not birth_date_str:
        return None
    try:
        bd = date.fromisoformat(birth_date_str)
        midseason = date(season, 7, 1)
        return midseason.year - bd.year - ((midseason.month, midseason.day) < (bd.month, bd.day))
    except (ValueError, TypeError):
        return None


def _age_tier(age: Optional[int]) -> str:
    if age is None:
        return "prime"  # default when unknown
    if age <= 26:
        return "young"
    if age <= 31:
        return "prime"
    return "older"


def generate_projections_from_stats(season: int = 2025):
    """Generate simple projections based on recent historical stats.

    Uses a weighted average of last 3 seasons (if available) with age-adjusted
    recency bias.  Young players weight the most recent season more heavily
    (breakouts sustain), older players do the same (declines accelerate), and
    a small counting-stat multiplier nudges projections in the expected
    direction of the aging curve.
    """
    conn = get_connection()
    seasons_back = [season - 1, season - 2, season - 3]

    # Pre-load birth dates for age lookup
    birth_dates: dict[int, str] = {}
    for row in conn.execute("SELECT mlb_id, birth_date FROM players WHERE birth_date IS NOT NULL").fetchall():
        birth_dates[row["mlb_id"]] = row["birth_date"]

    # Generate hitter projections — includes two-way players (pitchers with batting stats)
    hitter_ids = conn.execute(
        "SELECT mlb_id FROM players WHERE player_type = 'hitter' AND is_active = 1"
    ).fetchall()
    # Also find pitchers who have batting stats (two-way players like Ohtani)
    twp_hitter_ids = conn.execute(
        """SELECT DISTINCT bs.mlb_id FROM batting_stats bs
           JOIN players p ON bs.mlb_id = p.mlb_id
           WHERE p.player_type = 'pitcher' AND p.is_active = 1
             AND bs.season IN (?, ?, ?)""",
        (*seasons_back,),
    ).fetchall()
    all_hitter_ids = {h["mlb_id"] for h in hitter_ids} | {h["mlb_id"] for h in twp_hitter_ids}
    if twp_hitter_ids:
        logger.info(f"Found {len(twp_hitter_ids)} two-way players with batting stats for hitter trend generation")

    hitter_count = 0
    hitter_counting_fields = [
        "plate_appearances", "at_bats", "runs", "hits", "doubles", "triples",
        "home_runs", "rbi", "stolen_bases", "walks", "strikeouts",
        "hit_by_pitch", "sac_flies",
    ]
    for mlb_id in all_hitter_ids:
        stats_rows = conn.execute(
            """SELECT * FROM batting_stats
               WHERE mlb_id = ? AND season IN (?, ?, ?)
               ORDER BY season DESC""",
            (mlb_id, *seasons_back),
        ).fetchall()

        if not stats_rows:
            continue

        # Age-adjusted weighted average
        tier = _age_tier(_player_age(birth_dates.get(mlb_id, ""), season))
        weights = _AGE_WEIGHTS[tier]

        proj = {}
        total_weight = 0
        for i, row in enumerate(stats_rows):
            w = weights.get(i, 0.1)
            total_weight += w
            for field in hitter_counting_fields:
                proj[field] = proj.get(field, 0) + (row[field] or 0) * w

        if total_weight > 0:
            mult = _AGE_COUNTING_MULTIPLIER[tier]
            for field in hitter_counting_fields:
                proj[field] = round(proj[field] / total_weight * mult)

        # Calculate derived stats
        singles = proj["hits"] - proj["doubles"] - proj["triples"] - proj["home_runs"]
        tb = singles + 2 * proj["doubles"] + 3 * proj["triples"] + 4 * proj["home_runs"]

        # OBP = (H + BB + HBP) / (AB + BB + HBP + SF)
        obp_denom = proj["at_bats"] + proj["walks"] + proj["hit_by_pitch"] + proj["sac_flies"]
        obp = (proj["hits"] + proj["walks"] + proj["hit_by_pitch"]) / obp_denom if obp_denom > 0 else 0

        conn.execute(
            """INSERT INTO projections
               (mlb_id, source, season, player_type,
                proj_pa, proj_at_bats, proj_runs, proj_hits, proj_doubles, proj_triples,
                proj_home_runs, proj_rbi, proj_stolen_bases, proj_walks,
                proj_strikeouts, proj_hbp, proj_sac_flies, proj_obp, proj_total_bases)
               VALUES (?, 'trend', ?, 'hitter',
                       ?, ?, ?, ?, ?, ?,
                       ?, ?, ?, ?,
                       ?, ?, ?, ?, ?)
               ON CONFLICT (mlb_id, source, season, player_type) DO UPDATE SET
                 proj_pa = EXCLUDED.proj_pa, proj_at_bats = EXCLUDED.proj_at_bats,
                 proj_runs = EXCLUDED.proj_runs, proj_hits = EXCLUDED.proj_hits,
                 proj_doubles = EXCLUDED.proj_doubles, proj_triples = EXCLUDED.proj_triples,
                 proj_home_runs = EXCLUDED.proj_home_runs, proj_rbi = EXCLUDED.proj_rbi,
                 proj_stolen_bases = EXCLUDED.proj_stolen_bases, proj_walks = EXCLUDED.proj_walks,
                 proj_strikeouts = EXCLUDED.proj_strikeouts, proj_hbp = EXCLUDED.proj_hbp,
                 proj_sac_flies = EXCLUDED.proj_sac_flies, proj_obp = EXCLUDED.proj_obp,
                 proj_total_bases = EXCLUDED.proj_total_bases""",
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

    # Generate pitcher projections — includes two-way players (hitters with pitching stats)
    pitcher_ids = conn.execute(
        "SELECT mlb_id FROM players WHERE player_type = 'pitcher' AND is_active = 1"
    ).fetchall()
    # Also find hitters who have pitching stats (two-way players like Ohtani)
    twp_pitcher_ids = conn.execute(
        """SELECT DISTINCT ps.mlb_id FROM pitching_stats ps
           JOIN players p ON ps.mlb_id = p.mlb_id
           WHERE p.player_type = 'hitter' AND p.is_active = 1
             AND ps.season IN (?, ?, ?)""",
        (*seasons_back,),
    ).fetchall()
    all_pitcher_ids = {p["mlb_id"] for p in pitcher_ids} | {p["mlb_id"] for p in twp_pitcher_ids}
    if twp_pitcher_ids:
        logger.info(f"Found {len(twp_pitcher_ids)} two-way players with pitching stats for pitcher trend generation")

    pitcher_count = 0
    pitcher_counting_fields = [
        "innings_pitched", "strikeouts", "quality_starts", "saves", "holds",
        "wins", "hits_allowed", "walks_allowed", "earned_runs",
    ]
    for mlb_id in all_pitcher_ids:
        stats_rows = conn.execute(
            """SELECT * FROM pitching_stats
               WHERE mlb_id = ? AND season IN (?, ?, ?)
               ORDER BY season DESC""",
            (mlb_id, *seasons_back),
        ).fetchall()

        if not stats_rows:
            continue

        tier = _age_tier(_player_age(birth_dates.get(mlb_id, ""), season))
        weights = _AGE_WEIGHTS[tier]

        proj = {}
        total_weight = 0
        for i, row in enumerate(stats_rows):
            w = weights.get(i, 0.1)
            total_weight += w
            for field in pitcher_counting_fields:
                proj[field] = proj.get(field, 0) + (row[field] or 0) * w

        if total_weight > 0:
            mult = _AGE_COUNTING_MULTIPLIER[tier]
            for field in pitcher_counting_fields:
                proj[field] = proj[field] / total_weight * mult
                if field != "innings_pitched":
                    proj[field] = round(proj[field])
                else:
                    proj[field] = round(proj[field], 1)

        # ERA = (ER * 9) / IP
        era = (proj["earned_runs"] * 9) / proj["innings_pitched"] if proj["innings_pitched"] > 0 else 0
        # WHIP = (H + BB) / IP
        whip = (proj["hits_allowed"] + proj["walks_allowed"]) / proj["innings_pitched"] if proj["innings_pitched"] > 0 else 0

        conn.execute(
            """INSERT INTO projections
               (mlb_id, source, season, player_type,
                proj_ip, proj_pitcher_strikeouts, proj_quality_starts,
                proj_era, proj_whip, proj_saves, proj_holds, proj_wins,
                proj_hits_allowed, proj_walks_allowed, proj_earned_runs)
               VALUES (?, 'trend', ?, 'pitcher',
                       ?, ?, ?,
                       ?, ?, ?, ?, ?,
                       ?, ?, ?)
               ON CONFLICT (mlb_id, source, season, player_type) DO UPDATE SET
                 proj_ip = EXCLUDED.proj_ip, proj_pitcher_strikeouts = EXCLUDED.proj_pitcher_strikeouts,
                 proj_quality_starts = EXCLUDED.proj_quality_starts,
                 proj_era = EXCLUDED.proj_era, proj_whip = EXCLUDED.proj_whip,
                 proj_saves = EXCLUDED.proj_saves, proj_holds = EXCLUDED.proj_holds,
                 proj_wins = EXCLUDED.proj_wins, proj_hits_allowed = EXCLUDED.proj_hits_allowed,
                 proj_walks_allowed = EXCLUDED.proj_walks_allowed,
                 proj_earned_runs = EXCLUDED.proj_earned_runs""",
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


def import_adp_from_csv(source: str = "steamer", season: int = 2026):
    """Import ADP (Average Draft Position) from projection CSV files into rankings.

    Reads the ADP column from batting and pitching CSVs, matches players via
    _resolve_mlb_id(), and updates the rankings table with espn_adp and adp_diff.
    For two-way players appearing in both CSVs, keeps the lower (earlier) ADP.

    Args:
        source: Projection system identifier ("steamer", "zips", "thebatx").
        season: Season year.
    """
    valid_sources = {"steamer", "zips", "thebatx"}
    if source not in valid_sources:
        raise ValueError(f"Invalid source '{source}', must be one of {sorted(valid_sources)}")

    conn = get_connection()

    # Collect ADP values from both CSVs: mlb_id → best (lowest) ADP
    adp_map: dict[int, float] = {}

    for player_type in ("batting", "pitching"):
        filepath = PROJECTIONS_DIR / f"{source}_{player_type}_{season}.csv"
        if not filepath.exists():
            logger.warning(f"ADP file not found: {filepath}")
            continue

        with open(filepath, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                adp_val = _safe_float(row.get("ADP"))
                if adp_val <= 0:
                    continue

                mlb_id = _resolve_mlb_id(conn, row)
                if mlb_id is None:
                    continue

                # Keep the lower (earlier) ADP for two-way players
                if mlb_id not in adp_map or adp_val < adp_map[mlb_id]:
                    adp_map[mlb_id] = adp_val

    # Update rankings table
    updated = 0
    for mlb_id, adp in adp_map.items():
        result = conn.execute(
            """UPDATE rankings
               SET espn_adp = ?, adp_diff = overall_rank - ?
               WHERE mlb_id = ? AND season = ?""",
            (adp, adp, mlb_id, season),
        )
        if result.rowcount > 0:
            updated += 1

    conn.commit()
    conn.close()
    logger.info(f"Imported ADP for {updated} players from {source} ({len(adp_map)} found in CSVs)")
    return updated
