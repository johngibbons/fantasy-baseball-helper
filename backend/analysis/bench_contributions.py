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


HITTING_CATS = ["R", "TB", "RBI", "SB", "OBP"]
PITCHING_CATS = ["K", "QS", "ERA", "WHIP", "SVHD"]
ALL_CATS = HITTING_CATS + PITCHING_CATS

_CAT_TO_FIELD: dict[str, str] = {
    "R": "proj_r", "TB": "proj_tb", "RBI": "proj_rbi", "SB": "proj_sb",
    "K": "proj_k", "QS": "proj_qs", "SVHD": "proj_svhd",
}

_RATE_CATS = {"OBP", "ERA", "WHIP"}


def compute_stat_impact(
    players: list[RosterPlayer],
    contribution_rates: dict[int, float],
) -> dict[str, float]:
    """Compute total season stat contribution for a group of players.

    Counting stats are multiplied by contribution rate.
    Rate stats (OBP, ERA, WHIP) are PA/IP-weighted averages.
    """
    totals: dict[str, float] = {cat: 0.0 for cat in ALL_CATS}
    total_pa = 0.0
    total_ip = 0.0
    weighted_obp = 0.0
    weighted_era = 0.0
    weighted_whip = 0.0

    for p in players:
        rate = contribution_rates.get(p.mlb_id, 0.0)
        for cat, field in _CAT_TO_FIELD.items():
            totals[cat] += getattr(p, field, 0) * rate
        if p.player_type == "hitter" and p.proj_pa > 0:
            pa_contrib = p.proj_pa * rate
            total_pa += pa_contrib
            weighted_obp += p.proj_obp * pa_contrib
        if p.player_type == "pitcher" and p.proj_ip > 0:
            ip_contrib = p.proj_ip * rate
            total_ip += ip_contrib
            weighted_era += p.proj_era * ip_contrib
            weighted_whip += p.proj_whip * ip_contrib

    totals["OBP"] = weighted_obp / total_pa if total_pa > 0 else 0.0
    totals["ERA"] = weighted_era / total_ip if total_ip > 0 else 0.0
    totals["WHIP"] = weighted_whip / total_ip if total_ip > 0 else 0.0

    return totals


@dataclass
class SweepConfig:
    """A roster configuration to test in the sweep."""
    label: str
    roster: list[RosterPlayer]


def _replacement_level_hitter(team: str) -> RosterPlayer:
    return RosterPlayer(
        mlb_id=-1, name="Repl. Hitter", position="OF", player_type="hitter",
        eligible_positions="OF/DH", team=team,
        proj_pa=350, proj_r=40, proj_tb=100, proj_rbi=35,
        proj_sb=5, proj_obp=0.300, overall_rank=300,
    )


def _replacement_level_pitcher(team: str) -> RosterPlayer:
    return RosterPlayer(
        mlb_id=-2, name="Repl. Pitcher", position="SP", player_type="pitcher",
        eligible_positions="SP", team=team,
        proj_ip=100.0, proj_k=80, proj_qs=6,
        proj_era=4.50, proj_whip=1.35, proj_svhd=0,
        overall_rank=350,
    )


def build_sweep_configs(roster: list[RosterPlayer]) -> list[SweepConfig]:
    """Build roster variations for the bench composition sweep."""
    configs: list[SweepConfig] = [SweepConfig(label="baseline", roster=list(roster))]

    pitchers_by_rank = sorted(
        [p for p in roster if p.player_type == "pitcher"],
        key=lambda p: p.overall_rank, reverse=True,
    )
    hitters_by_rank = sorted(
        [p for p in roster if p.player_type == "hitter"],
        key=lambda p: p.overall_rank, reverse=True,
    )

    team_counts: dict[str, int] = {}
    for p in roster:
        team_counts[p.team] = team_counts.get(p.team, 0) + 1
    default_team = max(team_counts, key=team_counts.get) if team_counts else "NYY"

    if pitchers_by_rank:
        drop = pitchers_by_rank[0]
        repl = _replacement_level_hitter(default_team)
        repl.mlb_id = -(drop.mlb_id * 10 + 1)
        new_roster = [p for p in roster if p.mlb_id != drop.mlb_id] + [repl]
        configs.append(SweepConfig(label="+1 hitter", roster=new_roster))

    if len(pitchers_by_rank) >= 2:
        drop_ids = {pitchers_by_rank[0].mlb_id, pitchers_by_rank[1].mlb_id}
        repl1 = _replacement_level_hitter(default_team)
        repl1.mlb_id = -(pitchers_by_rank[0].mlb_id * 10 + 1)
        repl2 = _replacement_level_hitter(default_team)
        repl2.mlb_id = -(pitchers_by_rank[1].mlb_id * 10 + 2)
        new_roster = [p for p in roster if p.mlb_id not in drop_ids] + [repl1, repl2]
        configs.append(SweepConfig(label="+2 hitters", roster=new_roster))

    if hitters_by_rank:
        drop = hitters_by_rank[0]
        repl = _replacement_level_pitcher(default_team)
        repl.mlb_id = -(drop.mlb_id * 10 + 3)
        new_roster = [p for p in roster if p.mlb_id != drop.mlb_id] + [repl]
        configs.append(SweepConfig(label="-1 hitter", roster=new_roster))

    return configs


# Replacement-level SP full-season projections (same as _replacement_level_pitcher)
_REPL_SP_IP = 100.0
_REPL_SP_K = 80
_REPL_SP_QS = 6
_REPL_SP_ERA = 4.50
_REPL_SP_WHIP = 1.35
_REPL_SP_SVHD = 0
_REPL_SP_STARTS = round(_REPL_SP_IP / IP_PER_START)  # ~18


def replacement_level_per_start_stats() -> dict[str, float]:
    """Return per-start stat line for a replacement-level streaming SP."""
    return {
        "ip": _REPL_SP_IP / _REPL_SP_STARTS,
        "k": _REPL_SP_K / _REPL_SP_STARTS,
        "qs": _REPL_SP_QS / _REPL_SP_STARTS,
        "era": _REPL_SP_ERA,
        "whip": _REPL_SP_WHIP,
        "svhd": 0.0,
    }


def allocate_weekly_streams(
    streaming_slot_ids: list[int],
    sp_start_dates: dict[int, set[str]],
    week_dates: list[str],
    schedule: dict[str, set[str]],
    max_transactions: int,
) -> dict[str, list[dict]]:
    """Greedily assign streaming SP pickups across a week within the transaction budget.

    For each streaming slot, on days when the slot's anchored SP is NOT pitching
    and there are teams playing, assign a replacement-level streamer.

    Returns dict mapping date -> list of streamer dicts with "slot_id" and "player" keys.
    """
    if max_transactions <= 0 or not streaming_slot_ids:
        return {}

    streamable: list[tuple[str, int]] = []
    for date in week_dates:
        if not schedule.get(date):
            continue
        for slot_id in streaming_slot_ids:
            if date in sp_start_dates.get(slot_id, set()):
                continue
            streamable.append((date, slot_id))

    streams: dict[str, list[dict]] = {}
    used = 0
    for date, slot_id in streamable:
        if used >= max_transactions:
            break
        streamer_id = -(slot_id * 1000 + used)
        entry = {
            "slot_id": slot_id,
            "player": {
                "mlb_id": streamer_id,
                "position": "SP",
                "player_type": "pitcher",
                "eligible_positions": "SP",
            },
        }
        streams.setdefault(date, []).append(entry)
        used += 1

    return streams


def fetch_season_schedule(start_date: str, end_date: str) -> dict[str, set[str]]:
    """Fetch full-season MLB schedule from Stats API."""
    url = f"{MLB_API_BASE}/schedule"
    resp = httpx.get(url, params={"sportId": 1, "startDate": start_date, "endDate": end_date})
    resp.raise_for_status()
    return parse_schedule_response(resp.json())


