"""Sweep bench contribution rates by simulating daily lineups across a full MLB season.

Fetches your ESPN roster, loads projections from the rankings DB, fetches the
MLB schedule, and runs Monte Carlo simulations to determine how often each
bench player actually starts.

Usage:
    python3 sweep_bench_contributions.py --league-id 123 --team-id 4 --swid '{...}' --espn-s2 '...'
    python3 sweep_bench_contributions.py --league-id 123 --team-id 4 --swid '{...}' --espn-s2 '...' --sims 500 --seed 42
"""

from __future__ import annotations

import argparse
import sys

import httpx

from backend.analysis.bench_contributions import (
    ALL_CATS,
    HITTING_CATS,
    PITCHING_CATS,
    RosterPlayer,
    SimulationResult,
    SweepConfig,
    aggregate_by_role,
    build_sweep_configs,
    compute_stat_impact,
    fetch_season_schedule,
    simulate_season,
)
from backend.analysis.waivers import (
    load_projections_for_players,
    resolve_espn_names_to_mlbid,
)

ESPN_API_BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb"

ESPN_POS_MAP: dict[int, str] = {
    1: "SP", 2: "C", 3: "1B", 4: "2B", 5: "3B",
    6: "SS", 7: "LF", 8: "CF", 9: "RF", 10: "DH", 11: "RP",
}

ESPN_TEAM_MAP: dict[int, str] = {
    1: "BAL", 2: "BOS", 3: "LAA", 4: "CWS", 5: "CLE", 6: "DET",
    7: "KC", 8: "MIL", 9: "MIN", 10: "NYY", 11: "OAK", 12: "SEA",
    13: "TEX", 14: "TOR", 15: "ATL", 16: "CHC", 17: "CIN", 18: "HOU",
    19: "LAD", 20: "WSH", 21: "NYM", 22: "PHI", 23: "PIT", 24: "STL",
    25: "SD", 26: "SF", 27: "COL", 28: "MIA", 29: "ARI", 30: "TB",
}

SEASON_START = "2026-03-26"
SEASON_END = "2026-09-27"

STREAMING_LEVELS = [0, 3, 6, 10]


def compute_total_impact(
    config: SweepConfig,
    result: SimulationResult,
) -> dict[str, float]:
    """Compute total stat impact: roster player contributions + streaming stats."""
    impact = compute_stat_impact(config.roster, result.player_contribution_rates)
    if result.streaming_stats:
        for cat in ["K", "QS", "SVHD"]:
            impact[cat] += result.streaming_stats.get(cat, 0.0)
        stream_ip = result.streaming_stats.get("IP", 0.0)
        if stream_ip > 0:
            roster_ip = sum(
                p.proj_ip * result.player_contribution_rates.get(p.mlb_id, 0.0)
                for p in config.roster if p.player_type == "pitcher" and p.proj_ip > 0
            )
            total_ip = roster_ip + stream_ip
            if total_ip > 0:
                impact["ERA"] = (impact["ERA"] * roster_ip + result.streaming_stats["ERA"] * stream_ip) / total_ip
                impact["WHIP"] = (impact["WHIP"] * roster_ip + result.streaming_stats["WHIP"] * stream_ip) / total_ip
    return impact


def fetch_espn_roster(
    league_id: str,
    team_id: int,
    season: str,
    swid: str,
    espn_s2: str,
) -> list[dict]:
    """Fetch roster entries from ESPN Fantasy API."""
    url = f"{ESPN_API_BASE}/seasons/{season}/segments/0/leagues/{league_id}"
    headers = {
        "Cookie": f"swid={swid}; espn_s2={espn_s2}",
        "Content-Type": "application/json",
    }
    resp = httpx.get(url, params=[("view", "mRoster"), ("view", "kona_player_info")], headers=headers)
    resp.raise_for_status()
    data = resp.json()

    for team in data.get("teams", []):
        if team["id"] == team_id:
            entries = team.get("roster", {}).get("entries", [])
            result = []
            for entry in entries:
                player_data = entry.get("playerPoolEntry", {}).get("player", {})
                if not player_data:
                    continue
                pos_id = player_data.get("defaultPositionId", 0)
                player_type = "pitcher" if pos_id in (1, 11) else "hitter"
                pro_team_id = player_data.get("proTeamId", 0)
                result.append({
                    "name": player_data.get("fullName", "Unknown"),
                    "player_type": player_type,
                    "position": ESPN_POS_MAP.get(pos_id, "UTIL"),
                    "team": ESPN_TEAM_MAP.get(pro_team_id, ""),
                    "lineup_slot_id": entry.get("lineupSlotId", 0),
                    "eligible_slots": player_data.get("eligibleSlots", []),
                })
            return result
    return []


def build_roster_players(
    espn_entries: list[dict],
    season: int,
) -> list[RosterPlayer]:
    """Resolve ESPN roster entries to RosterPlayer objects with projections."""
    name_to_id = resolve_espn_names_to_mlbid(espn_entries, season=season)
    mlb_ids = list(name_to_id.values())
    projections = load_projections_for_players(mlb_ids, season)

    roster: list[RosterPlayer] = []
    for entry in espn_entries:
        mlb_id = name_to_id.get(entry["name"])
        if not mlb_id:
            print(f"  WARN: Could not resolve '{entry['name']}' -- skipping")
            continue
        proj = projections.get(mlb_id)
        if not proj:
            print(f"  WARN: No projections for '{entry['name']}' (mlb_id={mlb_id}) -- skipping")
            continue
        if entry.get("lineup_slot_id", 0) >= 17:
            continue

        roster.append(RosterPlayer(
            mlb_id=mlb_id, name=proj.name, position=proj.position,
            player_type=proj.player_type, eligible_positions=proj.eligible_positions,
            team=entry.get("team", ""),
            proj_pa=proj.pa, proj_ip=proj.ip, overall_rank=proj.overall_rank,
            proj_r=proj.r, proj_tb=proj.tb, proj_rbi=proj.rbi,
            proj_sb=proj.sb, proj_obp=proj.obp,
            proj_k=proj.k, proj_qs=proj.qs, proj_era=proj.era,
            proj_whip=proj.whip, proj_svhd=proj.svhd,
        ))
    return roster


def print_contribution_report(
    label: str,
    roster: list[RosterPlayer],
    result: SimulationResult,
) -> None:
    """Print per-player contribution rates and role averages."""
    agg = aggregate_by_role(result.player_contribution_rates, roster)

    print(f"\n{'=' * 78}")
    print(f"  {label}")
    print(f"{'=' * 78}")
    print(f"  {'Player':<25} {'Pos':<6} {'Type':<8} {'Rank':>5} {'Rate':>6} {'Days':>6}")
    print(f"  {'-' * 72}")

    sorted_players = sorted(
        roster,
        key=lambda p: result.player_contribution_rates.get(p.mlb_id, 0.0),
        reverse=True,
    )
    for p in sorted_players:
        rate = result.player_contribution_rates.get(p.mlb_id, 0.0)
        days = result.player_days_started.get(p.mlb_id, 0.0)
        print(f"  {p.name:<25} {p.position:<6} {p.player_type:<8} {p.overall_rank:>5} {rate:>6.1%} {days:>6.1f}")

    print(f"\n  Role Averages:")
    print(f"    Bench Hitter: {agg.avg_bench_hitter_rate:.1%}  ({len(agg.bench_hitters)} players)")
    print(f"    Bench SP:     {agg.avg_bench_sp_rate:.1%}  ({len(agg.bench_sps)} players)")
    print(f"    Bench RP:     {agg.avg_bench_rp_rate:.1%}  ({len(agg.bench_rps)} players)")


def print_streaming_sweep_summary(
    configs: list[SweepConfig],
    all_results: dict[str, dict[int, SimulationResult]],
) -> None:
    """Print 2D grid: rows = compositions, columns = streaming levels."""
    cats = ["R", "TB", "RBI", "SB", "OBP", "K", "QS", "ERA", "WHIP", "SVHD"]

    print(f"\n{'=' * 100}")
    print(f"{'BENCH COMPOSITION x STREAMING SWEEP':^100}")
    print(f"{'=' * 100}")

    baseline_config = configs[0]
    baseline_result = all_results[baseline_config.label][0]
    baseline_impact = compute_total_impact(baseline_config, baseline_result)

    for stream_level in STREAMING_LEVELS:
        print(f"\n  --- {stream_level} streams/week ---")
        header = f"  {'Config':<14}"
        for cat in cats:
            header += f" {cat:>6}"
        header += f" {'StrmK':>6} {'StrmQS':>6}"
        print(header)
        print(f"  {'-' * 96}")

        for config in configs:
            result = all_results[config.label][stream_level]
            impact = compute_total_impact(config, result)

            line = f"  {config.label:<14}"
            for cat in cats:
                delta = impact[cat] - baseline_impact[cat]
                if config.label == "baseline" and stream_level == 0:
                    if cat in ("OBP", "ERA", "WHIP"):
                        line += f" {impact[cat]:>6.3f}"
                    else:
                        line += f" {impact[cat]:>6.1f}"
                else:
                    if cat in ("OBP", "ERA", "WHIP"):
                        line += f" {delta:>+6.3f}"
                    else:
                        line += f" {delta:>+6.1f}"

            stream_k = result.streaming_stats.get("K", 0.0) if result.streaming_stats else 0.0
            stream_qs = result.streaming_stats.get("QS", 0.0) if result.streaming_stats else 0.0
            line += f" {stream_k:>6.1f} {stream_qs:>6.1f}"
            print(line)

    print(f"\n  Baseline = current roster with 0 streams. All other cells show delta vs baseline.")
    print(f"  StrmK/StrmQS = K and QS contributed by streamers only.")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Sweep bench contribution rates via daily lineup simulation")
    parser.add_argument("--league-id", required=True, help="ESPN league ID")
    parser.add_argument("--team-id", type=int, required=True, help="ESPN team ID")
    parser.add_argument("--swid", required=True, help="ESPN SWID cookie")
    parser.add_argument("--espn-s2", required=True, help="ESPN espn_s2 cookie")
    parser.add_argument("--season", default="2026", help="Season year (default: 2026)")
    parser.add_argument("--sims", type=int, default=200, help="Monte Carlo iterations (default: 200)")
    parser.add_argument("--seed", type=int, default=None, help="RNG seed for reproducibility")
    parser.add_argument("--no-sweep", action="store_true", help="Only run baseline (skip composition sweep)")
    args = parser.parse_args()

    season_int = int(args.season)

    print(f"Fetching ESPN roster for league {args.league_id}, team {args.team_id}...")
    espn_entries = fetch_espn_roster(args.league_id, args.team_id, args.season, args.swid, args.espn_s2)
    if not espn_entries:
        print("ERROR: No roster entries found. Check league ID, team ID, and credentials.")
        sys.exit(1)
    print(f"  Found {len(espn_entries)} roster entries")

    print("Resolving players and loading projections...")
    roster = build_roster_players(espn_entries, season_int)
    print(f"  Resolved {len(roster)} players with projections")

    hitter_count = sum(1 for p in roster if p.player_type == "hitter")
    pitcher_count = sum(1 for p in roster if p.player_type == "pitcher")
    print(f"  Composition: {hitter_count} hitters, {pitcher_count} pitchers")

    print(f"Fetching MLB schedule ({SEASON_START} to {SEASON_END})...")
    schedule = fetch_season_schedule(SEASON_START, SEASON_END)
    print(f"  {len(schedule)} game dates loaded")

    team_season_games: dict[str, int] = {}
    for teams in schedule.values():
        for team in teams:
            team_season_games[team] = team_season_games.get(team, 0) + 1

    if args.no_sweep:
        configs = [SweepConfig(label="baseline", roster=roster)]
        stream_levels = [0]
    else:
        configs = build_sweep_configs(roster)
        stream_levels = STREAMING_LEVELS

    all_results: dict[str, dict[int, SimulationResult]] = {}
    total_runs = len(configs) * len(stream_levels)
    run_num = 0

    for config in configs:
        all_results[config.label] = {}
        for stream_level in stream_levels:
            run_num += 1
            print(f"\n[{run_num}/{total_runs}] '{config.label}' @ {stream_level} streams/week ({args.sims} sims)...")
            result = simulate_season(
                config.roster, schedule, team_season_games,
                args.sims, args.seed, streams_per_week=stream_level,
            )
            all_results[config.label][stream_level] = result

            if config.label == "baseline" and stream_level == 0:
                print_contribution_report(config.label, config.roster, result)

    if len(configs) > 1 or len(stream_levels) > 1:
        print_streaming_sweep_summary(configs, all_results)


if __name__ == "__main__":
    main()
