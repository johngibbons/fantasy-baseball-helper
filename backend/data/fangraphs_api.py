"""Fetch Rest-of-Season (ROS) projections from the FanGraphs API.

ROS projection types:
  - rsteamer     — Steamer ROS
  - rzips        — ZiPS ROS
  - rthebatx     — THE BAT X ROS
  - rfangraphsdc — Depth Charts ROS (FanGraphs composite)

The API returns JSON with xMLBAMID (maps to our mlb_id), plus all stat
columns.  We store results in the projections table with source values
'steamer_ros', 'zips_ros', 'thebatx_ros'.
"""

import logging
import time
from datetime import datetime
from typing import Optional

import httpx

from backend.database import get_connection

logger = logging.getLogger(__name__)

_FG_BASE = "https://www.fangraphs.com/api/projections"

# Map FanGraphs ROS type parameter to our source name
_ROS_SOURCES = {
    "rsteamer": "steamer_ros",
    "rzips": "zips_ros",
    "rthebatx": "thebatx_ros",
}

# Delay between API requests to be polite
_REQUEST_DELAY = 1.5


def _safe_int(val) -> int:
    try:
        return int(round(float(val))) if val else 0
    except (ValueError, TypeError):
        return 0


def _safe_float(val) -> float:
    try:
        return float(val) if val else 0.0
    except (ValueError, TypeError):
        return 0.0


def _fetch_fangraphs_json(fg_type: str, stats: str) -> list[dict]:
    """Fetch projection data from FanGraphs API.

    Args:
        fg_type: Projection type (e.g. 'rsteamer', 'rzips', 'rthebatx')
        stats: 'bat' for batting, 'pit' for pitching

    Returns:
        List of player projection dicts.
    """
    url = f"{_FG_BASE}?type={fg_type}&stats={stats}&pos=all&team=0&players=0"
    headers = {
        "User-Agent": "FantasyBaseballHelper/1.0",
        "Accept": "application/json",
    }
    logger.info(f"Fetching FanGraphs {fg_type} {stats} from {url}")
    resp = httpx.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    logger.info(f"  Got {len(data)} rows")
    return data


def _resolve_mlb_id(conn, row: dict) -> Optional[int]:
    """Resolve a FanGraphs player to our mlb_id via xMLBAMID."""
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

    # Fallback: name match
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


def import_ros_batting(fg_type: str, source: str, season: int) -> int:
    """Import ROS batting projections from FanGraphs API.

    Args:
        fg_type: FanGraphs projection type (e.g. 'rsteamer')
        source: Our source identifier (e.g. 'steamer_ros')
        season: Season year

    Returns:
        Number of players imported.
    """
    data = _fetch_fangraphs_json(fg_type, "bat")
    conn = get_connection()
    imported = 0
    skipped = 0

    for row in data:
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
    logger.info(f"Imported {imported} {source} ROS batting projections ({skipped} skipped)")
    return imported


def import_ros_pitching(fg_type: str, source: str, season: int) -> int:
    """Import ROS pitching projections from FanGraphs API.

    Args:
        fg_type: FanGraphs projection type (e.g. 'rsteamer')
        source: Our source identifier (e.g. 'steamer_ros')
        season: Season year

    Returns:
        Number of players imported.
    """
    data = _fetch_fangraphs_json(fg_type, "pit")
    conn = get_connection()
    imported = 0
    skipped = 0

    for row in data:
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
    logger.info(f"Imported {imported} {source} ROS pitching projections ({skipped} skipped)")
    return imported


def fetch_all_ros_projections(season: int) -> dict[str, int]:
    """Fetch all ROS projection sources from FanGraphs and store in DB.

    Returns:
        Dict mapping source name to total players imported.
    """
    results = {}
    for fg_type, source in _ROS_SOURCES.items():
        try:
            bat_count = import_ros_batting(fg_type, source, season)
            time.sleep(_REQUEST_DELAY)
            pit_count = import_ros_pitching(fg_type, source, season)
            time.sleep(_REQUEST_DELAY)
            results[source] = bat_count + pit_count
            logger.info(f"  {source}: {bat_count} batters + {pit_count} pitchers")
        except Exception as e:
            logger.warning(f"Failed to fetch {source} ROS projections: {e}")
            results[source] = 0

    # Update season_state with last ROS update timestamp
    conn = get_connection()
    now = datetime.utcnow().isoformat()
    conn.execute(
        """INSERT INTO season_state (season, last_ros_update)
           VALUES (?, ?)
           ON CONFLICT (season) DO UPDATE SET last_ros_update = ?""",
        (season, now, now),
    )
    conn.commit()
    conn.close()

    total = sum(results.values())
    logger.info(f"ROS projection fetch complete: {total} total players across {len(results)} sources")
    return results
