"""Pull current team + IL status from MLB Stats API and write to analytics.player_status.

Daily sync calls sync_player_status(season). Pure parsing logic is kept separate
so it can be unit-tested without network calls.
"""
from __future__ import annotations
import concurrent.futures
import datetime as dt
import json
import logging
import urllib.parse
import urllib.request
from typing import Iterable, Optional

from backend.database import get_connection

logger = logging.getLogger(__name__)

_IL_PREFIXES = ("IL", "60-DAY", "10-DAY", "15-DAY")

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


def parse_mlb_status_response(response: dict, mlb_id: int) -> Optional[dict]:
    """Extract status fields from an MLB Stats API /people response.

    Returns None if the player isn't in the response. is_on_il is True when
    currentRosterStatus starts with any IL prefix.
    """
    people = response.get("people", [])
    person = next((p for p in people if p.get("id") == mlb_id), None)
    if not person:
        return None
    team = (person.get("currentTeam") or {}).get("abbreviation")
    raw_status = person.get("currentRosterStatus") or "A"
    is_on_il = any(raw_status.upper().startswith(p) for p in _IL_PREFIXES)
    return {
        "mlb_id": mlb_id,
        "current_team": team,
        "status_code": raw_status,
        "is_on_il": is_on_il,
        "il_eta_date": None,
    }


def derive_last_played_date(game_log: list[dict]) -> Optional[dt.date]:
    """Return the most recent game date from an MLB Stats API gameLog response."""
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
    conn.commit()


def upsert_player_status(conn, record: dict, last_played: Optional[dt.date]) -> None:
    """Upsert a single player_status row. Postgres ON CONFLICT semantics."""
    conn.execute(
        _UPSERT_SQL,
        (
            record["mlb_id"],
            record["current_team"],
            record["status_code"],
            record["is_on_il"],
            last_played,
            record["il_eta_date"],
        ),
    )


def _fetch_status_one(mlb_id: int) -> Optional[dict]:
    url = f"{_BASE}/people/{mlb_id}?hydrate=currentTeam"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return parse_mlb_status_response(json.load(r), mlb_id)
    except Exception as e:
        logger.warning(f"status fetch failed for {mlb_id}: {e}")
        return None


def _fetch_last_played_one(mlb_id: int, season: int, group: str) -> Optional[dt.date]:
    url = f"{_BASE}/people/{mlb_id}/stats?stats=gameLog&season={season}&group={group}"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            d = json.load(r)
        splits = d.get("stats", [{}])[0].get("splits", [])
        return derive_last_played_date(splits)
    except Exception as e:
        logger.warning(f"gameLog fetch failed for {mlb_id}: {e}")
        return None


def sync_player_status(season: int, mlb_ids: Iterable[int]) -> int:
    """Fetch + upsert status for the given MLB ids. Returns number written."""
    conn = get_connection()
    try:
        ensure_table(conn)
        written = 0
        # Concurrent fetches for speed (MLB Stats API tolerates ~10 parallel)
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
            futures = {ex.submit(_fetch_status_one, mid): mid for mid in mlb_ids}
            for fut in concurrent.futures.as_completed(futures):
                rec = fut.result()
                if not rec:
                    continue
                # Derive last_played; try hitting first, fall back to pitching.
                last_played = _fetch_last_played_one(rec["mlb_id"], season, "hitting")
                if last_played is None:
                    last_played = _fetch_last_played_one(rec["mlb_id"], season, "pitching")
                upsert_player_status(conn, rec, last_played)
                written += 1
        conn.commit()
        logger.info(f"sync_player_status: wrote {written} rows for season {season}")
        return written
    finally:
        conn.close()
