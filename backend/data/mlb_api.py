"""Fetch player data and stats from the MLB Stats API (statsapi.mlb.com)."""

import httpx
import logging
from typing import Optional

logger = logging.getLogger(__name__)

BASE_URL = "https://statsapi.mlb.com/api/v1"

PITCHER_POSITIONS = {"P", "SP", "RP", "CP"}

# A quality start is a start of at least 6 innings allowing 3 earned runs or fewer.
QS_MIN_INNINGS = 6.0
QS_MAX_EARNED_RUNS = 3


def parse_innings_pitched(value) -> float:
    """Convert MLB's innings notation to a real number.

    MLB writes partial innings as thirds after the decimal point: "6.1" is six
    and one third, not six and one tenth. Parsing it as a plain float is close
    enough for a >= 6.0 threshold but wrong for arithmetic, so do it properly.
    """
    if value is None:
        return 0.0
    try:
        text = str(value)
        if "." in text:
            whole, outs = text.split(".", 1)
            outs_val = int(outs[0]) if outs[:1].isdigit() else 0
            return float(whole or 0) + min(outs_val, 2) / 3.0
        return float(text)
    except (TypeError, ValueError):
        return 0.0


def count_quality_starts(game_log: list[dict]) -> int:
    """Count quality starts in a pitching game log.

    The MLB Stats API's season-stats endpoint does not expose quality starts,
    but the league scores the category, so it has to be derived per game.
    """
    quality = 0
    for game in game_log:
        stat = game.get("stat", {})
        if not stat.get("gamesStarted"):
            continue
        innings = parse_innings_pitched(stat.get("inningsPitched"))
        try:
            earned = int(stat.get("earnedRuns", 0) or 0)
        except (TypeError, ValueError):
            continue
        if innings >= QS_MIN_INNINGS and earned <= QS_MAX_EARNED_RUNS:
            quality += 1
    return quality


async def get_pitching_game_log(mlb_id: int, season: int = 2025) -> list[dict]:
    """Fetch a pitcher's per-game log for a season."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/people/{mlb_id}/stats",
            params={"stats": "gameLog", "season": season, "group": "pitching"},
        )
        resp.raise_for_status()
        data = resp.json()

    stats_list = data.get("stats", [])
    if not stats_list:
        return []
    return stats_list[0].get("splits", [])


async def get_all_teams(season: int = 2025) -> list[dict]:
    """Fetch all MLB teams for a given season."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/teams",
            params={"sportId": 1, "season": season},
        )
        resp.raise_for_status()
        return resp.json().get("teams", [])


async def get_team_roster(team_id: int, season: int = 2025) -> list[dict]:
    """Fetch the 40-man roster for a team."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/teams/{team_id}/roster",
            params={"rosterType": "40Man", "season": season},
        )
        resp.raise_for_status()
        roster = resp.json().get("roster", [])

    players = []
    for entry in roster:
        person = entry.get("person", {})
        position = entry.get("position", {})
        pos_abbr = position.get("abbreviation", "")
        player_type = "pitcher" if pos_abbr in PITCHER_POSITIONS else "hitter"

        players.append({
            "mlb_id": person.get("id"),
            "full_name": person.get("fullName", ""),
            "primary_position": pos_abbr,
            "player_type": player_type,
        })
    return players


async def get_player_info(mlb_id: int) -> Optional[dict]:
    """Fetch detailed player info."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{BASE_URL}/people/{mlb_id}")
        resp.raise_for_status()
        people = resp.json().get("people", [])
        if not people:
            return None

    p = people[0]
    pos = p.get("primaryPosition", {}).get("abbreviation", "")
    return {
        "mlb_id": p.get("id"),
        "full_name": p.get("fullFMLName", p.get("fullName", "")),
        "first_name": p.get("firstName", ""),
        "last_name": p.get("lastName", ""),
        "primary_position": pos,
        "team": p.get("currentTeam", {}).get("name", ""),
        "team_id": p.get("currentTeam", {}).get("id"),
        "bats": p.get("batSide", {}).get("code", ""),
        "throws": p.get("pitchHand", {}).get("code", ""),
        "birth_date": p.get("birthDate", ""),
        "player_type": "pitcher" if pos in PITCHER_POSITIONS else "hitter",
        "is_active": 1 if p.get("active") else 0,
    }


async def get_batting_stats(mlb_id: int, season: int = 2025) -> Optional[dict]:
    """Fetch season batting stats for a player."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/people/{mlb_id}/stats",
            params={"stats": "season", "season": season, "group": "hitting"},
        )
        resp.raise_for_status()
        data = resp.json()

    stats_list = data.get("stats", [])
    if not stats_list:
        return None

    splits = stats_list[0].get("splits", [])
    if not splits:
        return None

    s = splits[0].get("stat", {})
    doubles = s.get("doubles", 0)
    triples = s.get("triples", 0)
    home_runs = s.get("homeRuns", 0)
    hits = s.get("hits", 0)
    singles = hits - doubles - triples - home_runs
    total_bases = singles + (2 * doubles) + (3 * triples) + (4 * home_runs)

    def _safe_float(val, default=0.0):
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    return {
        "mlb_id": mlb_id,
        "season": season,
        "games": s.get("gamesPlayed", 0),
        "plate_appearances": s.get("plateAppearances", 0),
        "at_bats": s.get("atBats", 0),
        "runs": s.get("runs", 0),
        "hits": hits,
        "doubles": doubles,
        "triples": triples,
        "home_runs": home_runs,
        "rbi": s.get("rbi", 0),
        "stolen_bases": s.get("stolenBases", 0),
        "caught_stealing": s.get("caughtStealing", 0),
        "walks": s.get("baseOnBalls", 0),
        "strikeouts": s.get("strikeOuts", 0),
        "hit_by_pitch": s.get("hitByPitch", 0),
        "sac_flies": s.get("sacFlies", 0),
        "batting_average": _safe_float(s.get("avg", 0), 0.0),
        "obp": _safe_float(s.get("obp", 0), 0.0),
        "slg": _safe_float(s.get("slg", 0), 0.0),
        "ops": _safe_float(s.get("ops", 0), 0.0),
        "total_bases": total_bases,
    }


async def get_pitching_stats(mlb_id: int, season: int = 2025,
                             include_quality_starts: bool = False) -> Optional[dict]:
    """Fetch season pitching stats for a player.

    include_quality_starts: also pull the game log and derive QS. Off by
        default because it doubles the number of API calls; the season
        retrospective turns it on since QS is one of the ten scored categories.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/people/{mlb_id}/stats",
            params={"stats": "season", "season": season, "group": "pitching"},
        )
        resp.raise_for_status()
        data = resp.json()

    stats_list = data.get("stats", [])
    if not stats_list:
        return None

    splits = stats_list[0].get("splits", [])
    if not splits:
        return None

    s = splits[0].get("stat", {})

    ip_str = s.get("inningsPitched", "0")
    try:
        ip = float(ip_str)
    except (ValueError, TypeError):
        ip = 0.0

    quality_starts = 0
    if include_quality_starts and s.get("gamesStarted"):
        try:
            quality_starts = count_quality_starts(
                await get_pitching_game_log(mlb_id, season))
        except Exception as e:
            logger.warning(f"Quality-start derivation failed for {mlb_id}: {e}")

    def _safe_float(val, default=0.0):
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    return {
        "mlb_id": mlb_id,
        "season": season,
        "games": s.get("gamesPlayed", 0),
        "games_started": s.get("gamesStarted", 0),
        "wins": s.get("wins", 0),
        "losses": s.get("losses", 0),
        "era": _safe_float(s.get("era", 0), 0.0),
        "whip": _safe_float(s.get("whip", 0), 0.0),
        "innings_pitched": ip,
        "hits_allowed": s.get("hits", 0),
        "runs_allowed": s.get("runs", 0),
        "earned_runs": s.get("earnedRuns", 0),
        "walks_allowed": s.get("baseOnBalls", 0),
        "strikeouts": s.get("strikeOuts", 0),
        "home_runs_allowed": s.get("homeRuns", 0),
        "saves": s.get("saves", 0),
        "holds": s.get("holds", 0),
        # Not exposed by the season-stats endpoint; derived from the game log
        # when include_quality_starts is set, otherwise left at 0.
        "quality_starts": quality_starts,
    }


async def fetch_all_players(season: int = 2025) -> list[dict]:
    """Fetch all MLB players from all team rosters."""
    teams = await get_all_teams(season)
    all_players = []
    seen_ids = set()

    for team in teams:
        team_id = team["id"]
        team_name = team.get("name", "")
        try:
            roster = await get_team_roster(team_id, season)
            for player in roster:
                pid = player["mlb_id"]
                if pid not in seen_ids:
                    seen_ids.add(pid)
                    player["team"] = team_name
                    player["team_id"] = team_id
                    all_players.append(player)
        except Exception as e:
            logger.warning(f"Failed to fetch roster for {team_name}: {e}")

    logger.info(f"Fetched {len(all_players)} players from {len(teams)} teams")
    return all_players
