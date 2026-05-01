# backend/analysis/playoff_odds.py
"""Playoff odds Monte Carlo simulator.

Given each team's roster, current cumulative W/L/T, and the remaining matchup
schedule, runs N trials of the rest of the season and reports each team's
probability of finishing in the top K (playoff slots).
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from backend.analysis.matchup import (
    CATEGORY_SIGMA,
    optimize_daily_lineup,
    _load_projections,
)
from backend.analysis.waivers import (
    ALL_CATS,
    HITTER_BENCH_WEIGHT,
    INVERTED_CATS,
    PlayerProjection,
    TeamTotals,
    resolve_espn_names_to_mlbid,
)

IL_LINEUP_SLOT_MIN = 17  # ESPN lineupSlotId 17+ are IL slots
# Bench contribution for pitchers — kept as separate SP/RP knobs to mirror
# roster-optimizer.ts (PITCHER_BENCH_CONTRIBUTION + RP_BENCH_CONTRIBUTION).
# Equal today; future calibration may diverge them.
PITCHER_BENCH_WEIGHT_SP = 0.95
PITCHER_BENCH_WEIGHT_RP = 0.95


def _bench_weight(player: PlayerProjection) -> float:
    """Bench contribution weight matching roster-optimizer.ts."""
    if player.player_type == "hitter":
        return HITTER_BENCH_WEIGHT
    # SP and RP both use ~0.95 per memory and roster-optimizer.ts
    return PITCHER_BENCH_WEIGHT_SP if player.qs > 0 else PITCHER_BENCH_WEIGHT_RP


def project_team_period(
    roster: list[PlayerProjection],
    period_weight: float,
    il_mlb_ids: Optional[dict[int, bool]] = None,
) -> dict[str, float]:
    """Project a team's category totals for one matchup period.

    Args:
        roster: All non-IL players on the team for this period.
        period_weight: Fraction of full RoS this period represents (e.g. 7/91).
        il_mlb_ids: Mapping of mlb_id → True for IL players. IL players
            contribute 0. Pass None or empty dict for no IL.

    Returns:
        Dict with the 10 H2H category keys (R, TB, RBI, SB, OBP, K, QS,
        ERA, WHIP, SVHD).
    """
    il = il_mlb_ids or {}
    active = [p for p in roster if not il.get(p.mlb_id, False)]

    # Run greedy lineup optimizer on the active roster to identify starters.
    # `optimize_daily_lineup` accepts a list of dicts; convert.
    as_dicts = [
        {
            "mlb_id": p.mlb_id,
            "position": p.position,
            "player_type": p.player_type,
            "eligible_positions": p.eligible_positions or p.position,
        }
        for p in active
    ]
    lineup = optimize_daily_lineup(as_dicts)
    starter_ids = {d["mlb_id"] for d in lineup["starters"]}

    # Build a TeamTotals scaled by period_weight
    totals = TeamTotals()
    for p in active:
        weight = period_weight if p.mlb_id in starter_ids else period_weight * _bench_weight(p)
        totals.add_player(p, weight=weight)

    return totals.category_values()


def simulate_head_to_head(
    team_a_cats: dict[str, float],
    team_b_cats: dict[str, float],
    rng: np.random.Generator,
) -> tuple[int, int, int]:
    """Simulate one matchup. Returns team_a's (wins, losses, ties) over 10 cats.

    For each category, draw a normal noise term scaled by CATEGORY_SIGMA from
    matchup.py and add to each team's projected value. Compare and tally W/L/T.
    """
    wins = losses = ties = 0
    for cat in ALL_CATS:
        sigma = CATEGORY_SIGMA[cat]
        a_draw = team_a_cats[cat] + rng.normal(0.0, sigma)
        b_draw = team_b_cats[cat] + rng.normal(0.0, sigma)
        if cat in INVERTED_CATS:
            # Lower wins
            if a_draw < b_draw:
                wins += 1
            elif a_draw > b_draw:
                losses += 1
            else:
                ties += 1
        else:
            if a_draw > b_draw:
                wins += 1
            elif a_draw < b_draw:
                losses += 1
            else:
                ties += 1
    return wins, losses, ties


def simulate_one_season(
    rosters: dict[int, list[PlayerProjection]],
    current_records: dict[int, tuple[int, int, int]],
    remaining_schedule: list[tuple[int, int, int]],
    period_weights: dict[int, float],
    rng: np.random.Generator,
    il_by_team: Optional[dict[int, dict[int, bool]]] = None,
) -> dict[int, tuple[int, int, int]]:
    """Run one full simulation of the rest of the regular season.

    Args:
        rosters: team_id → list of PlayerProjection.
        current_records: team_id → (wins, losses, ties) at start of sim.
        remaining_schedule: list of (matchup_period_id, home_team_id, away_team_id).
        period_weights: matchup_period_id → fraction-of-RoS this period covers.
        rng: numpy Generator for noise draws.
        il_by_team: team_id → {mlb_id: True} for IL players. Optional.

    Returns:
        team_id → final cumulative (wins, losses, ties).
    """
    il_by_team = il_by_team or {}
    final = {tid: list(rec) for tid, rec in current_records.items()}

    # Group periods so we project once per (team, period) pair (caching).
    period_projections: dict[tuple[int, int], dict[str, float]] = {}

    for period_id, home_id, away_id in remaining_schedule:
        weight = period_weights[period_id]
        # Project each team for this period (cache to avoid recomputation)
        for team_id in (home_id, away_id):
            key = (team_id, period_id)
            if key not in period_projections:
                period_projections[key] = project_team_period(
                    roster=rosters[team_id],
                    period_weight=weight,
                    il_mlb_ids=il_by_team.get(team_id),
                )
        a_cats = period_projections[(home_id, period_id)]
        b_cats = period_projections[(away_id, period_id)]
        a_w, a_l, a_t = simulate_head_to_head(a_cats, b_cats, rng)
        # Home gets a_w/a_l/a_t; away is the inverse (a_l wins, a_w losses, a_t ties)
        final[home_id][0] += a_w
        final[home_id][1] += a_l
        final[home_id][2] += a_t
        final[away_id][0] += a_l
        final[away_id][1] += a_w
        final[away_id][2] += a_t

    return {tid: tuple(rec) for tid, rec in final.items()}


def compute_playoff_odds(
    rosters: dict[int, list[PlayerProjection]],
    current_records: dict[int, tuple[int, int, int]],
    remaining_schedule: list[tuple[int, int, int]],
    period_weights: dict[int, float],
    playoff_slots: int = 6,
    n_trials: int = 5000,
    seed: Optional[int] = None,
    il_by_team: Optional[dict[int, dict[int, bool]]] = None,
    team_names: Optional[dict[int, str]] = None,
) -> list[dict]:
    """Run Monte Carlo and return per-team playoff odds.

    Tiebreaker for top-K cut: total wins, then ties (more ties = tied teams
    treated as ahead of fewer-ties), then random. Approximates ESPN cat-format
    tiebreakers, which compare head-to-head record then total points-for.
    """
    team_ids = list(rosters.keys())
    team_names = team_names or {tid: f"Team {tid}" for tid in team_ids}

    playoff_count = {tid: 0 for tid in team_ids}
    sum_wins = {tid: 0.0 for tid in team_ids}
    sum_losses = {tid: 0.0 for tid in team_ids}
    sum_ties = {tid: 0.0 for tid in team_ids}
    sum_rank = {tid: 0.0 for tid in team_ids}

    rng = np.random.default_rng(seed)

    for _ in range(n_trials):
        finals = simulate_one_season(
            rosters=rosters,
            current_records=current_records,
            remaining_schedule=remaining_schedule,
            period_weights=period_weights,
            rng=rng,
            il_by_team=il_by_team,
        )
        # Rank teams: more wins is better, more ties as secondary, random tiebreak.
        # Use a stable shuffle then sort to break exact ties uniformly.
        shuffled = list(team_ids)
        rng.shuffle(shuffled)
        ranked = sorted(
            shuffled,
            key=lambda tid: (-finals[tid][0], -finals[tid][2]),
        )
        for rank, tid in enumerate(ranked, start=1):
            sum_rank[tid] += rank
            if rank <= playoff_slots:
                playoff_count[tid] += 1
            w, l, t = finals[tid]
            sum_wins[tid] += w
            sum_losses[tid] += l
            sum_ties[tid] += t

    out: list[dict] = []
    for tid in team_ids:
        cur_w, cur_l, cur_t = current_records[tid]
        out.append({
            "team_id": tid,
            "team_name": team_names[tid],
            "current_wins": cur_w,
            "current_losses": cur_l,
            "current_ties": cur_t,
            "playoff_odds": playoff_count[tid] / n_trials,
            "avg_final_wins": sum_wins[tid] / n_trials,
            "avg_final_losses": sum_losses[tid] / n_trials,
            "avg_final_ties": sum_ties[tid] / n_trials,
            "avg_final_rank": sum_rank[tid] / n_trials,
        })
    out.sort(key=lambda r: -r["playoff_odds"])
    return out


def compute_playoff_odds_from_request(payload: dict) -> dict:
    """Resolve names → mlb_ids, load projections, run sim, return response dict."""
    season = payload["season"]
    teams = payload["teams"]

    # Flatten all roster players for name resolution
    all_roster_dicts: list[dict] = []
    for t in teams:
        for p in t["roster"]:
            all_roster_dicts.append({
                "name": p["name"],
                "player_type": p.get("player_type", "hitter"),
            })

    name_to_id = resolve_espn_names_to_mlbid(all_roster_dicts, season=season)
    matched_ids = list(set(name_to_id.values()))
    projections = _load_projections(matched_ids, season=season)

    # Build per-team PlayerProjection lists; track IL and unmatched
    rosters: dict[int, list[PlayerProjection]] = {}
    il_by_team: dict[int, dict[int, bool]] = {}
    current_records: dict[int, tuple[int, int, int]] = {}
    team_names: dict[int, str] = {}
    unmatched_names: set[str] = set()
    matched_count = 0

    for t in teams:
        tid = t["team_id"]
        team_names[tid] = t["team_name"]
        current_records[tid] = (
            t.get("current_wins", 0),
            t.get("current_losses", 0),
            t.get("current_ties", 0),
        )
        rosters[tid] = []
        il_by_team[tid] = {}
        for p in t["roster"]:
            mlb_id = name_to_id.get(p["name"])
            if mlb_id is None or mlb_id not in projections:
                unmatched_names.add(p["name"])
                continue
            proj = projections[mlb_id]
            # Override position with ESPN-derived eligible_positions for lineup opt
            proj_with_elig = PlayerProjection(
                mlb_id=proj.mlb_id, name=proj.name, position=proj.position,
                player_type=proj.player_type,
                pa=proj.pa, r=proj.r, tb=proj.tb, rbi=proj.rbi, sb=proj.sb,
                obp=proj.obp, ip=proj.ip, k=proj.k, qs=proj.qs, era=proj.era,
                whip=proj.whip, svhd=proj.svhd,
                eligible_positions=p.get("eligible_positions") or proj.eligible_positions or proj.position,
                overall_rank=proj.overall_rank,
            )
            rosters[tid].append(proj_with_elig)
            matched_count += 1
            if p.get("lineup_slot_id", 0) >= IL_LINEUP_SLOT_MIN:
                il_by_team[tid][mlb_id] = True

    # Build remaining_schedule as tuples
    schedule = [
        (m["matchup_period_id"], m["home_team_id"], m["away_team_id"])
        for m in payload["remaining_schedule"]
    ]
    # period_weights keys may be strings via JSON
    period_weights = {int(k): float(v) for k, v in payload["period_weights"].items()}

    teams_out = compute_playoff_odds(
        rosters=rosters,
        current_records=current_records,
        remaining_schedule=schedule,
        period_weights=period_weights,
        playoff_slots=payload.get("playoff_slots", 6),
        n_trials=payload.get("n_trials", 5000),
        seed=payload.get("seed"),
        il_by_team=il_by_team,
        team_names=team_names,
    )

    return {
        "teams": teams_out,
        "n_trials": payload.get("n_trials", 5000),
        "matched_player_count": matched_count,
        "unmatched_player_names": sorted(unmatched_names),
    }
