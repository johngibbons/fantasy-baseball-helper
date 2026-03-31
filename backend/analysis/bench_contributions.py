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


def distribute_sp_starts(
    projected_starts: int,
    team_game_dates: list[str],
    rng: random.Random,
) -> set[str]:
    """Distribute an SP's projected starts evenly across their team's schedule with jitter."""
    num_games = len(team_game_dates)
    if num_games == 0 or projected_starts <= 0:
        return set()
    if projected_starts >= num_games:
        return set(team_game_dates)

    interval = num_games / projected_starts
    ideal_indices = [round(i * interval) for i in range(projected_starts)]

    jittered: list[int] = []
    for idx in ideal_indices:
        shift = rng.choice([-1, 0, 1])
        new_idx = max(0, min(num_games - 1, idx + shift))
        jittered.append(new_idx)

    used: set[int] = set()
    final_indices: list[int] = []
    for idx in sorted(jittered):
        while idx in used and idx < num_games - 1:
            idx += 1
        if idx not in used:
            used.add(idx)
            final_indices.append(idx)

    return {team_game_dates[i] for i in final_indices}


@dataclass
class SimulationResult:
    """Results from a full-season Monte Carlo lineup simulation."""
    player_contribution_rates: dict[int, float]
    player_days_started: dict[int, float]
    player_days_available: dict[int, float]


def simulate_season(
    roster: list[RosterPlayer],
    schedule: dict[str, set[str]],
    team_season_games: dict[str, int],
    num_sims: int = 200,
    seed: int | None = None,
) -> SimulationResult:
    """Run Monte Carlo daily lineup simulation across a full MLB season.

    For each iteration:
    1. Distribute each SP's projected starts across their team's schedule (with jitter)
    2. For each day, determine which players are available
    3. Run the lineup optimizer on available players
    4. Track starts vs bench
    """
    from backend.analysis.matchup import optimize_daily_lineup

    rng = random.Random(seed)
    sorted_dates = sorted(schedule.keys())

    # Pre-compute team game dates
    team_game_dates: dict[str, list[str]] = {}
    for date in sorted_dates:
        for team in schedule[date]:
            team_game_dates.setdefault(team, []).append(date)

    # Pre-compute availability rates for hitters
    availability_rates: dict[int, float] = {}
    for p in roster:
        games = team_season_games.get(p.team, 162)
        availability_rates[p.mlb_id] = compute_availability_rate(p, games)

    # Track starts across all simulations
    total_starts: dict[int, int] = {p.mlb_id: 0 for p in roster}
    total_team_days: dict[int, int] = {p.mlb_id: 0 for p in roster}

    player_by_id = {p.mlb_id: p for p in roster}

    for _sim in range(num_sims):
        # Distribute SP starts for this iteration
        sp_start_dates: dict[int, set[str]] = {}
        for p in roster:
            if _is_sp(p):
                full_season_starts = round(p.proj_ip / IP_PER_START)
                dates = team_game_dates.get(p.team, [])
                # Scale projected starts to the simulation window
                season_games = team_season_games.get(p.team, 162)
                if season_games > 0:
                    sim_starts = max(1, round(full_season_starts * len(dates) / season_games))
                else:
                    sim_starts = full_season_starts
                sp_start_dates[p.mlb_id] = distribute_sp_starts(sim_starts, dates, rng)

        for date in sorted_dates:
            teams_playing = schedule[date]
            available_today: list[dict] = []

            for p in roster:
                if p.team not in teams_playing:
                    continue
                total_team_days[p.mlb_id] += 1

                if p.player_type == "hitter":
                    if rng.random() > availability_rates[p.mlb_id]:
                        continue
                elif _is_sp(p):
                    if date not in sp_start_dates.get(p.mlb_id, set()):
                        continue

                available_today.append({
                    "mlb_id": p.mlb_id,
                    "position": p.position,
                    "player_type": p.player_type,
                    "eligible_positions": p.eligible_positions,
                })

            lineup = optimize_daily_lineup(available_today)
            starting_ids = {pl["mlb_id"] for pl in lineup["starters"]}
            for mid in starting_ids:
                total_starts[mid] += 1

    contribution_rates: dict[int, float] = {}
    avg_starts: dict[int, float] = {}
    avg_available: dict[int, float] = {}

    for p in roster:
        mid = p.mlb_id
        team_days = total_team_days[mid]
        avg_available[mid] = team_days / num_sims
        avg_starts[mid] = total_starts[mid] / num_sims
        contribution_rates[mid] = total_starts[mid] / team_days if team_days > 0 else 0.0

    return SimulationResult(
        player_contribution_rates=contribution_rates,
        player_days_started=avg_starts,
        player_days_available=avg_available,
    )


STARTER_THRESHOLD = 0.75


@dataclass
class RoleAggregation:
    """Aggregated contribution rates by player role."""
    bench_hitters: list[RosterPlayer]
    bench_sps: list[RosterPlayer]
    bench_rps: list[RosterPlayer]
    starter_hitters: list[RosterPlayer]
    starter_pitchers: list[RosterPlayer]
    avg_bench_hitter_rate: float
    avg_bench_sp_rate: float
    avg_bench_rp_rate: float


def aggregate_by_role(
    contribution_rates: dict[int, float],
    roster: list[RosterPlayer],
) -> RoleAggregation:
    """Classify players as starter/bench and compute per-role average contribution rates."""
    bench_hitters: list[RosterPlayer] = []
    bench_sps: list[RosterPlayer] = []
    bench_rps: list[RosterPlayer] = []
    starter_hitters: list[RosterPlayer] = []
    starter_pitchers: list[RosterPlayer] = []

    for p in roster:
        rate = contribution_rates.get(p.mlb_id, 0.0)
        if p.player_type == "hitter":
            if rate >= STARTER_THRESHOLD:
                starter_hitters.append(p)
            else:
                bench_hitters.append(p)
        else:
            if rate >= STARTER_THRESHOLD:
                starter_pitchers.append(p)
            elif _is_sp(p):
                bench_sps.append(p)
            else:
                bench_rps.append(p)

    def _avg_rate(players: list[RosterPlayer]) -> float:
        if not players:
            return 0.0
        return sum(contribution_rates.get(p.mlb_id, 0.0) for p in players) / len(players)

    bench_hitters.sort(key=lambda p: p.overall_rank)
    bench_sps.sort(key=lambda p: p.overall_rank)
    bench_rps.sort(key=lambda p: p.overall_rank)

    return RoleAggregation(
        bench_hitters=bench_hitters, bench_sps=bench_sps, bench_rps=bench_rps,
        starter_hitters=starter_hitters, starter_pitchers=starter_pitchers,
        avg_bench_hitter_rate=_avg_rate(bench_hitters),
        avg_bench_sp_rate=_avg_rate(bench_sps),
        avg_bench_rp_rate=_avg_rate(bench_rps),
    )


def fetch_season_schedule(start_date: str, end_date: str) -> dict[str, set[str]]:
    """Fetch full-season MLB schedule from Stats API."""
    url = f"{MLB_API_BASE}/schedule"
    resp = httpx.get(url, params={"sportId": 1, "startDate": start_date, "endDate": end_date})
    resp.raise_for_status()
    return parse_schedule_response(resp.json())


