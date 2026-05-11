"""Pull current team + IL status from MLB Stats API and write to analytics.player_status.

Daily sync calls sync_player_status(season). Pure parsing logic is kept separate
so it can be unit-tested without network calls.
"""
from __future__ import annotations
import datetime as dt
import logging
from typing import Optional, Iterable
from backend.database import get_connection

logger = logging.getLogger(__name__)

_IL_PREFIXES = ("IL", "60-DAY", "10-DAY", "15-DAY")


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
