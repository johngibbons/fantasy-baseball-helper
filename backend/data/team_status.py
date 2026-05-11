"""Pull current team + IL status from MLB Stats API team rosters and write to
analytics.player_status.

Daily sync calls sync_player_status(season). Pure parsing logic is kept separate
so it can be unit-tested without network calls.

The team-roster endpoint (/api/v1/teams/{id}/roster?rosterType=fullRoster) is
authoritative for IL status — it returns a status code per player like 'A' for
active, 'D10' for 10-day IL, 'D60' for 60-day IL, etc. Iterating 30 teams is
~30 HTTP calls (vs. ~1500 if we hit /people per player).
"""
from __future__ import annotations
import concurrent.futures
import datetime as dt
import json
import logging
import urllib.request
from typing import Iterable, Optional

from backend.database import get_connection

logger = logging.getLogger(__name__)

_BASE = "https://statsapi.mlb.com/api/v1"

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS analytics.player_status (
  mlb_id           INTEGER PRIMARY KEY REFERENCES analytics.players(mlb_id),
  current_team     TEXT,
  status_code      TEXT,
  is_on_il         BOOLEAN DEFAULT FALSE,
  last_played_date DATE,
  il_eta_date      DATE,
  updated_at       TIMESTAMP DEFAULT NOW()
);
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_player_status_il ON analytics.player_status(is_on_il);
"""

_UPSERT_SQL = """
INSERT INTO analytics.player_status
  (mlb_id, current_team, status_code, is_on_il, last_played_date, il_eta_date)
VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT (mlb_id) DO UPDATE SET
  current_team = EXCLUDED.current_team,
  status_code = EXCLUDED.status_code,
  is_on_il = EXCLUDED.is_on_il,
  last_played_date = EXCLUDED.last_played_date,
  il_eta_date = EXCLUDED.il_eta_date,
  updated_at = NOW();
"""


def parse_roster_entry(entry: dict, team_abbrev: str) -> Optional[dict]:
    """Extract status fields from one entry in an MLB Stats API team-roster response.

    The entry shape: {"person": {"id": ...}, "status": {"code": ..., "description": ...}, ...}.
    Returns None if mlb_id can't be determined. is_on_il is True for D-prefix codes
    or legacy IL-prefix codes.
    """
    person = entry.get("person") or {}
    mlb_id = person.get("id")
    if not isinstance(mlb_id, int):
        return None
    status = entry.get("status") or {}
    raw_status = (status.get("code") or "A").upper()
    is_on_il = raw_status.startswith(("D", "IL"))
    return {
        "mlb_id": mlb_id,
        "current_team": team_abbrev,
        "status_code": raw_status,
        "is_on_il": is_on_il,
        "il_eta_date": None,
    }


def derive_last_played_date(game_log: list[dict]) -> Optional[dt.date]:
    """Return the most recent game date from an MLB Stats API gameLog response.

    Currently unused by sync_player_status (team-roster is authoritative for IL),
    kept as a pure helper for downstream features that need last-played-date.
    """
    if not game_log:
        return None
    dates = []
    for entry in game_log:
        raw = entry.get("date")
        if not raw:
            continue
        try:
            dates.append(dt.date.fromisoformat(raw))
        except ValueError:
            continue
    return max(dates) if dates else None


def ensure_table(conn) -> None:
    """Idempotent table + index creation for analytics.player_status."""
    conn.execute(_CREATE_TABLE_SQL)
    conn.execute(_CREATE_INDEX_SQL)
    conn.commit()


def upsert_player_status(conn, record: dict, last_played: Optional[dt.date]) -> None:
    conn.execute(_UPSERT_SQL, (
        record["mlb_id"],
        record["current_team"],
        record["status_code"],
        record["is_on_il"],
        last_played,
        record["il_eta_date"],
    ))


def propagate_team_to_players(conn) -> int:
    """Copy current_team from player_status into analytics.players.team so
    existing queries that join players don't need refactoring."""
    cur = conn.execute("""
        UPDATE analytics.players p
           SET team = ps.current_team
          FROM analytics.player_status ps
         WHERE ps.mlb_id = p.mlb_id
           AND COALESCE(p.team, '') <> COALESCE(ps.current_team, '');
    """)
    return cur.rowcount if cur.rowcount is not None else 0


def _fetch_team_id_to_abbrev(season: int) -> dict[int, str]:
    """Return {team_id: abbreviation} for all 30 MLB teams in the given season."""
    url = f"{_BASE}/teams?sportId=1&season={season}"
    with urllib.request.urlopen(url, timeout=10) as r:
        d = json.load(r)
    return {
        t["id"]: t["abbreviation"]
        for t in d.get("teams", [])
        if "id" in t and "abbreviation" in t
    }


def _fetch_team_roster(team_id: int, season: int) -> list[dict]:
    """Fetch a single team's full roster for the given season."""
    url = f"{_BASE}/teams/{team_id}/roster?rosterType=fullRoster&season={season}"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            d = json.load(r)
        return d.get("roster") or []
    except Exception as e:
        logger.warning(f"roster fetch failed for team {team_id}: {e}")
        return []


def sync_player_status(season: int) -> int:
    """Fetch all 30 team rosters and upsert {mlb_id, team, IL status} rows.

    Only writes rows for players that already exist in analytics.players
    (the table has a FK to players). MLB roster entries for players we
    don't track (rookies / non-fantasy-relevant) are silently dropped.

    Returns the number of rows written.
    """
    conn = get_connection()
    try:
        ensure_table(conn)
        team_map = _fetch_team_id_to_abbrev(season)
        if not team_map:
            logger.warning("No teams returned from /teams endpoint")
            return 0

        # FK filter: only upsert players already in analytics.players.
        rows = conn.execute("SELECT mlb_id FROM analytics.players").fetchall()
        known_ids: set[int] = {r["mlb_id"] for r in rows}

        written = 0
        skipped_unknown = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
            futures = {
                ex.submit(_fetch_team_roster, tid, season): (tid, abbrev)
                for tid, abbrev in team_map.items()
            }
            for fut in concurrent.futures.as_completed(futures):
                tid, abbrev = futures[fut]
                for entry in fut.result():
                    rec = parse_roster_entry(entry, abbrev)
                    if rec is None:
                        continue
                    if rec["mlb_id"] not in known_ids:
                        skipped_unknown += 1
                        continue
                    upsert_player_status(conn, rec, last_played=None)
                    written += 1
        conn.commit()
        logger.info(
            f"sync_player_status: wrote {written} rows for season {season} "
            f"(skipped {skipped_unknown} not in analytics.players)"
        )
        return written
    finally:
        conn.close()
