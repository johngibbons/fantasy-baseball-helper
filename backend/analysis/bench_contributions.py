"""Bench contribution rate analysis via full-season daily lineup simulation.

Calculates empirical bench player contribution rates by simulating optimal
daily lineups across a full MLB season using Monte Carlo methods.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

MLB_API_BASE = "https://statsapi.mlb.com/api/v1"

# MLB team ID -> abbreviation (matches mlb-schedule.ts)
MLB_TEAM_ABBREVS: dict[int, str] = {
    108: "LAA", 109: "ARI", 110: "BAL", 111: "BOS", 112: "CHC",
    113: "CIN", 114: "CLE", 115: "COL", 116: "DET", 117: "HOU",
    118: "KC", 119: "LAD", 120: "WSH", 121: "NYM", 133: "OAK",
    134: "PIT", 135: "SD", 136: "SEA", 137: "SF", 138: "STL",
    139: "TB", 140: "TEX", 141: "TOR", 142: "MIN", 143: "PHI",
    144: "ATL", 145: "CWS", 146: "MIA", 147: "NYY", 158: "MIL",
}

IP_PER_START = 5.5  # Modern MLB average innings per start


def parse_schedule_response(data: dict) -> dict[str, set[str]]:
    """Parse MLB Stats API schedule response into date -> set of team abbrevs.

    Only includes regular-season games that haven't finished yet.
    """
    schedule: dict[str, set[str]] = {}
    for date_entry in data.get("dates", []):
        date = date_entry["date"]
        teams_today: set[str] = set()
        for game in date_entry.get("games", []):
            if game.get("gameType") != "R":
                continue
            if game.get("status", {}).get("abstractGameCode") == "F":
                continue
            home_id = game.get("teams", {}).get("home", {}).get("team", {}).get("id")
            away_id = game.get("teams", {}).get("away", {}).get("team", {}).get("id")
            if home_id and home_id in MLB_TEAM_ABBREVS:
                teams_today.add(MLB_TEAM_ABBREVS[home_id])
            if away_id and away_id in MLB_TEAM_ABBREVS:
                teams_today.add(MLB_TEAM_ABBREVS[away_id])
        if teams_today:
            schedule[date] = teams_today
    return schedule


@dataclass
class RosterPlayer:
    """Player on a fantasy roster with projection data for simulation."""
    mlb_id: int
    name: str
    position: str
    player_type: str
    eligible_positions: str
    team: str
    proj_pa: int = 0
    proj_ip: float = 0.0
    overall_rank: int = 9999
    proj_r: int = 0
    proj_tb: int = 0
    proj_rbi: int = 0
    proj_sb: int = 0
    proj_obp: float = 0.0
    proj_k: int = 0
    proj_qs: int = 0
    proj_era: float = 0.0
    proj_whip: float = 0.0
    proj_svhd: int = 0


def _is_sp(player: RosterPlayer) -> bool:
    """Determine if a pitcher is an SP (vs RP)."""
    if player.player_type != "pitcher":
        return False
    if "SP" in player.eligible_positions.split("/"):
        return True
    return player.proj_ip >= 80


def compute_availability_rate(player: RosterPlayer, team_season_games: int) -> float:
    """Compute how often a player is available to play on days their team has a game."""
    if team_season_games <= 0:
        return 0.0
    if player.player_type == "hitter":
        games_played = player.proj_pa / 4.0
        return min(1.0, games_played / team_season_games)
    if _is_sp(player):
        projected_starts = round(player.proj_ip / IP_PER_START)
        return projected_starts / team_season_games
    return 1.0


def fetch_season_schedule(start_date: str, end_date: str) -> dict[str, set[str]]:
    """Fetch full-season MLB schedule from Stats API."""
    url = f"{MLB_API_BASE}/schedule"
    resp = httpx.get(url, params={"sportId": 1, "startDate": start_date, "endDate": end_date})
    resp.raise_for_status()
    return parse_schedule_response(resp.json())
