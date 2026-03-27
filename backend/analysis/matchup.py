# backend/analysis/matchup.py
"""Weekly matchup projection engine.

Combines ESPN live actuals with RoS projections (ATC DC) to project
category finals and win/loss outcomes for the current H2H matchup.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Optional

from backend.database import get_connection
from backend.analysis.waivers import (
    PlayerProjection,
    HITTING_CATS,
    PITCHING_CATS,
    ALL_CATS,
    INVERTED_CATS,
    resolve_espn_names_to_mlbid,
)

logger = logging.getLogger(__name__)

# Roster slot capacities for daily lineup optimization
# (same as roster-optimizer.ts ROSTER_SLOTS, minus bench)
DAILY_HITTING_SLOTS = {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "UTIL": 2}
DAILY_PITCHING_SLOTS = {"SP": 3, "RP": 2, "P": 2}

# Position → eligible slots (most constrained first), matching roster-optimizer.ts
POSITION_TO_SLOTS: dict[str, list[str]] = {
    "C": ["C", "UTIL"], "1B": ["1B", "UTIL"], "2B": ["2B", "UTIL"],
    "3B": ["3B", "UTIL"], "SS": ["SS", "UTIL"],
    "OF": ["OF", "UTIL"], "LF": ["OF", "UTIL"], "CF": ["OF", "UTIL"], "RF": ["OF", "UTIL"],
    "DH": ["UTIL"],
    "SP": ["SP", "P"], "RP": ["RP", "P"],
}

# Weekly variance sigma values per category (for win probability sigmoid)
CATEGORY_SIGMA: dict[str, float] = {
    "R": 5.0, "TB": 10.0, "RBI": 5.0, "SB": 2.0, "OBP": 0.015,
    "K": 8.0, "QS": 1.5, "ERA": 1.0, "WHIP": 0.15, "SVHD": 2.0,
}


# ── Per-game projection ─────────────────────────────────────────────────────


def compute_per_game_projections(
    player: PlayerProjection,
    remaining_season_games: int,
) -> dict[str, float]:
    """Pro-rate a player's RoS projection to per-game (hitters/RPs) or per-start (SPs).

    Hitters and RPs: divide by remaining_season_games for their team.
    SPs: divide by projected remaining starts (proj_ip / 6).

    Returns dict of per-unit stat values (one game or one start).
    """
    if remaining_season_games <= 0:
        return {"pa": 0, "r": 0, "tb": 0, "rbi": 0, "sb": 0, "obp": 0,
                "ip": 0, "k": 0, "qs": 0, "era": 0, "whip": 0, "svhd": 0}

    is_sp = player.player_type == "pitcher" and player.position == "SP"

    if is_sp:
        projected_starts = round(player.ip / 6) if player.ip > 0 else 0
        if projected_starts == 0:
            return {"pa": 0, "r": 0, "tb": 0, "rbi": 0, "sb": 0, "obp": 0,
                    "ip": 0, "k": 0, "qs": 0, "era": 0, "whip": 0, "svhd": 0}
        divisor = projected_starts
    else:
        divisor = remaining_season_games

    return {
        "pa": player.pa / divisor,
        "r": player.r / divisor,
        "tb": player.tb / divisor,
        "rbi": player.rbi / divisor,
        "sb": player.sb / divisor,
        "obp": player.obp,  # rate stat — carried as-is, weighted by PA when aggregating
        "ip": player.ip / divisor,
        "k": player.k / divisor,
        "qs": player.qs / divisor,
        "era": player.era,  # rate stat — carried as-is, weighted by IP when aggregating
        "whip": player.whip,  # rate stat — carried as-is, weighted by IP when aggregating
        "svhd": player.svhd / divisor,
    }


# ── Rate stat blending ───────────────────────────────────────────────────────


def blend_rate_stat(
    actual_value: float,
    actual_weight: float,
    projected_value: float,
    projected_weight: float,
) -> float:
    """Blend an actual rate stat with projected using PA/IP weighting.

    Example: blend_rate_stat(actual_OBP, actual_PA, proj_OBP, proj_PA)
    """
    total_weight = actual_weight + projected_weight
    if total_weight <= 0:
        return 0.0
    return (actual_value * actual_weight + projected_value * projected_weight) / total_weight


# ── Win probability ──────────────────────────────────────────────────────────


def compute_win_probability(
    my_value: float,
    opponent_value: float,
    sigma: float,
    inverted: bool = False,
) -> float:
    """Compute win probability for a category using a sigmoid function.

    For inverted categories (ERA, WHIP), lower is better.
    """
    margin = my_value - opponent_value
    if inverted:
        margin = -margin  # flip: if my ERA < theirs, that's good

    if sigma <= 0:
        return 0.5
    return 1.0 / (1.0 + math.exp(-margin / sigma))


# ── Daily lineup optimizer ───────────────────────────────────────────────────


def optimize_daily_lineup(
    available_players: list[dict],
) -> dict[str, list[dict]]:
    """Assign available players to optimal starting lineup for a single day.

    Uses greedy most-constrained-first algorithm matching roster-optimizer.ts.
    Players that don't fit in starting slots go to bench (contribute 0).

    Each player dict must have: mlb_id, position, player_type, eligible_positions (str).
    """
    # Build slot capacities
    capacity: dict[str, int] = {}
    for slot, count in DAILY_HITTING_SLOTS.items():
        capacity[slot] = count
    for slot, count in DAILY_PITCHING_SLOTS.items():
        capacity[slot] = count

    def _get_eligible_slots(player: dict) -> list[str]:
        positions = player.get("eligible_positions", player["position"]).split("/")
        slot_set: list[str] = []
        seen: set[str] = set()
        for pos in positions:
            for slot in POSITION_TO_SLOTS.get(pos, []):
                if slot not in seen:
                    seen.add(slot)
                    slot_set.append(slot)
        return slot_set

    # Sort by fewest eligible slots (most constrained first)
    sorted_players = sorted(available_players, key=lambda p: len(_get_eligible_slots(p)))

    starters: list[dict] = []
    bench: list[dict] = []

    for player in sorted_players:
        eligible = _get_eligible_slots(player)
        placed = False
        for slot in eligible:
            if capacity.get(slot, 0) > 0:
                capacity[slot] -= 1
                starters.append(player)
                placed = True
                break
        if not placed:
            bench.append(player)

    return {"starters": starters, "bench": bench}


# ── Projection loading ───────────────────────────────────────────────────────


def _load_projections(mlb_ids: list[int], season: int) -> dict[int, PlayerProjection]:
    """Load RoS projections from the rankings table for a set of player IDs."""
    if not mlb_ids:
        return {}
    conn = get_connection()
    placeholders = ",".join("?" * len(mlb_ids))
    rows = conn.execute(
        f"""
        SELECT r.mlb_id, p.full_name, p.primary_position, r.player_type, p.team,
               p.eligible_positions,
               r.proj_pa, r.proj_r, r.proj_tb, r.proj_rbi, r.proj_sb, r.proj_obp,
               r.proj_ip, r.proj_k, r.proj_qs, r.proj_era, r.proj_whip, r.proj_svhd
        FROM rankings r
        JOIN players p ON p.mlb_id = r.mlb_id
        WHERE r.mlb_id IN ({placeholders}) AND r.season = ?
        """,
        [*mlb_ids, season],
    ).fetchall()
    conn.close()

    projections: dict[int, PlayerProjection] = {}
    for row in rows:
        projections[row["mlb_id"]] = PlayerProjection(
            mlb_id=row["mlb_id"],
            name=row["full_name"],
            position=row["primary_position"] or "",
            player_type=row["player_type"] or "hitter",
            pa=row["proj_pa"] or 0,
            r=row["proj_r"] or 0,
            tb=row["proj_tb"] or 0,
            rbi=row["proj_rbi"] or 0,
            sb=row["proj_sb"] or 0,
            obp=row["proj_obp"] or 0.0,
            ip=row["proj_ip"] or 0.0,
            k=row["proj_k"] or 0,
            qs=row["proj_qs"] or 0,
            era=row["proj_era"] or 0.0,
            whip=row["proj_whip"] or 0.0,
            svhd=row["proj_svhd"] or 0,
        )
        # Attach team and eligible_positions as extra attributes for lineup optimization
        projections[row["mlb_id"]]._team = row["team"]  # type: ignore[attr-defined]
        projections[row["mlb_id"]]._eligible_positions = row["eligible_positions"] or row["primary_position"] or ""  # type: ignore[attr-defined]
    return projections


# ── Main projection computation ──────────────────────────────────────────────


def compute_matchup_projections(
    my_roster: list[dict],
    opponent_roster: list[dict],
    actuals: dict[str, dict[str, float]],
    team_games_remaining: dict[str, int],
    probable_pitcher_ids: dict[str, list[int]],
    remaining_season_games: dict[str, int],
    days_remaining: int,
    remaining_dates: list[str],
    season: int = 2026,
) -> dict:
    """Compute projected matchup finals by combining actuals with remaining-week projections.

    Args:
        my_roster: List of dicts with mlb_id, name, position, player_type,
                   lineup_slot_id, mlb_team, eligible_positions.
        opponent_roster: Same structure as my_roster.
        actuals: {"my": {"R": 18, ..., "IP": 30.0, "PA": 150}, "opponent": {...}}
        team_games_remaining: MLB team abbreviation → remaining games in matchup period.
        probable_pitcher_ids: date string → list of mlb_ids who are probable pitchers.
        remaining_season_games: MLB team abbreviation → remaining regular season games.
        days_remaining: Number of days left in matchup period.
        remaining_dates: List of remaining date strings (YYYY-MM-DD).
        season: Season year.

    Returns:
        Dict with projected_score, categories, my_roster_projections.
    """
    # Collect all mlb_ids and load projections
    all_ids = [p["mlb_id"] for p in my_roster + opponent_roster if p.get("mlb_id")]
    projections = _load_projections(all_ids, season)

    # Build a set of all probable pitcher IDs across remaining dates
    all_probable_ids: set[int] = set()
    for ids in probable_pitcher_ids.values():
        all_probable_ids.update(ids)

    def _project_team_remaining(
        roster: list[dict],
        team_label: str,
    ) -> tuple[dict[str, float], list[dict]]:
        """Project remaining-week stats for a team.

        Returns (aggregated_remaining_stats, player_projection_details).
        """
        # Accumulate counting stats and rate-stat components
        total_remaining = {cat: 0.0 for cat in ALL_CATS}
        total_remaining_pa = 0.0
        total_remaining_ip = 0.0
        weighted_obp = 0.0
        weighted_era = 0.0
        weighted_whip = 0.0

        player_details: list[dict] = []

        for roster_entry in roster:
            mid = roster_entry.get("mlb_id")
            if not mid or mid not in projections:
                player_details.append({
                    "mlb_id": mid,
                    "name": roster_entry.get("name", "Unknown"),
                    "position": roster_entry.get("position", ""),
                    "games_remaining": 0,
                    "projected_stats": {},
                    "is_active": False,
                })
                continue

            proj = projections[mid]
            team_abbrev = roster_entry.get("mlb_team", getattr(proj, "_team", ""))
            eligible_pos = roster_entry.get("eligible_positions", getattr(proj, "_eligible_positions", proj.position))
            team_ros_games = remaining_season_games.get(team_abbrev, 80)

            is_sp = proj.player_type == "pitcher" and proj.position == "SP"
            per_unit = compute_per_game_projections(proj, team_ros_games)

            # Determine how many games/starts this player has remaining in matchup
            if is_sp:
                # Count probable starts in remaining dates
                starts = sum(
                    1 for date in remaining_dates
                    if mid in probable_pitcher_ids.get(date, [])
                )
                units_remaining = starts
            else:
                # Count team games in remaining period
                units_remaining = team_games_remaining.get(team_abbrev, 0)

            # Player stats for remaining week
            player_remaining = {
                stat: per_unit.get(stat, 0.0) * units_remaining
                for stat in ["r", "tb", "rbi", "sb", "k", "qs", "svhd"]
            }
            player_remaining["pa"] = per_unit["pa"] * units_remaining
            player_remaining["ip"] = per_unit["ip"] * units_remaining
            player_remaining["obp"] = per_unit["obp"]
            player_remaining["era"] = per_unit["era"]
            player_remaining["whip"] = per_unit["whip"]

            player_details.append({
                "mlb_id": mid,
                "name": proj.name,
                "position": proj.position,
                "games_remaining": units_remaining,
                "projected_stats": {
                    k: round(v, 2) for k, v in player_remaining.items()
                },
                "is_active": units_remaining > 0,
                "eligible_positions": eligible_pos,
                "player_type": proj.player_type,
                "mlb_team": team_abbrev,
            })

        # Now simulate optimal daily lineups for remaining dates
        for date in remaining_dates:
            date_probable_ids = set(probable_pitcher_ids.get(date, []))

            # Filter to players who have a game today
            available_today = []
            for detail in player_details:
                mid = detail.get("mlb_id")
                if not mid or mid not in projections:
                    continue
                proj = projections[mid]
                team_abbrev = detail.get("mlb_team", "")
                # NOTE: team_games_remaining is a total for the remaining matchup period,
                # not per-date. This means a player is considered "available" on any
                # remaining date if their team has games left this week, even if
                # the team doesn't play on this specific date. This slightly
                # overestimates contribution but is acceptable for v1.
                team_has_game = team_games_remaining.get(team_abbrev, 0) > 0

                if not team_has_game:
                    continue

                is_sp = proj.player_type == "pitcher" and proj.position == "SP"
                if is_sp and mid not in date_probable_ids:
                    continue  # SP not pitching today

                available_today.append({
                    "mlb_id": mid,
                    "position": proj.position,
                    "player_type": proj.player_type,
                    "eligible_positions": detail.get("eligible_positions", proj.position),
                })

            lineup = optimize_daily_lineup(available_today)

            # Accumulate stats from starters only
            starting_ids = {p["mlb_id"] for p in lineup["starters"]}
            for detail in player_details:
                mid = detail.get("mlb_id")
                if mid not in starting_ids or mid not in projections:
                    continue

                proj = projections[mid]
                team_ros_games = remaining_season_games.get(detail.get("mlb_team", ""), 80)
                per_unit = compute_per_game_projections(proj, team_ros_games)

                # Add counting stats
                for stat in ["r", "tb", "rbi", "sb", "k", "qs", "svhd"]:
                    total_remaining[stat.upper()] += per_unit[stat]

                # Accumulate rate stat components
                day_pa = per_unit["pa"]
                day_ip = per_unit["ip"]
                total_remaining_pa += day_pa
                total_remaining_ip += day_ip
                weighted_obp += per_unit["obp"] * day_pa
                weighted_era += per_unit["era"] * day_ip
                weighted_whip += per_unit["whip"] * day_ip

        # Compute remaining-week rate stats
        total_remaining["OBP"] = weighted_obp / total_remaining_pa if total_remaining_pa > 0 else 0.0
        total_remaining["ERA"] = weighted_era / total_remaining_ip if total_remaining_ip > 0 else 0.0
        total_remaining["WHIP"] = weighted_whip / total_remaining_ip if total_remaining_ip > 0 else 0.0

        # Attach PA/IP for blending with actuals
        total_remaining["_PA"] = total_remaining_pa
        total_remaining["_IP"] = total_remaining_ip

        return total_remaining, player_details

    # Project remaining stats for both teams
    my_remaining, my_player_details = _project_team_remaining(my_roster, "my")
    opp_remaining, opp_player_details = _project_team_remaining(opponent_roster, "opponent")

    # Compute projected finals by blending actuals + remaining projections
    my_actuals = actuals.get("my", {})
    opp_actuals = actuals.get("opponent", {})

    categories: dict[str, dict] = {}
    my_wins = 0
    my_losses = 0
    ties = 0

    for cat in ALL_CATS:
        inverted = cat in INVERTED_CATS
        sigma = CATEGORY_SIGMA.get(cat, 5.0)

        if cat == "OBP":
            my_final = blend_rate_stat(
                my_actuals.get("OBP", 0), my_actuals.get("PA", 0),
                my_remaining.get("OBP", 0), my_remaining.get("_PA", 0),
            )
            opp_final = blend_rate_stat(
                opp_actuals.get("OBP", 0), opp_actuals.get("PA", 0),
                opp_remaining.get("OBP", 0), opp_remaining.get("_PA", 0),
            )
        elif cat == "ERA":
            my_final = blend_rate_stat(
                my_actuals.get("ERA", 0), my_actuals.get("IP", 0),
                my_remaining.get("ERA", 0), my_remaining.get("_IP", 0),
            )
            opp_final = blend_rate_stat(
                opp_actuals.get("ERA", 0), opp_actuals.get("IP", 0),
                opp_remaining.get("ERA", 0), opp_remaining.get("_IP", 0),
            )
        elif cat == "WHIP":
            my_final = blend_rate_stat(
                my_actuals.get("WHIP", 0), my_actuals.get("IP", 0),
                my_remaining.get("WHIP", 0), my_remaining.get("_IP", 0),
            )
            opp_final = blend_rate_stat(
                opp_actuals.get("WHIP", 0), opp_actuals.get("IP", 0),
                opp_remaining.get("WHIP", 0), opp_remaining.get("_IP", 0),
            )
        else:
            # Counting stat: actual + remaining projection
            my_final = my_actuals.get(cat, 0) + my_remaining.get(cat, 0)
            opp_final = opp_actuals.get(cat, 0) + opp_remaining.get(cat, 0)

        win_prob = compute_win_probability(my_final, opp_final, sigma, inverted)

        if win_prob >= 0.6:
            status = "winning"
            my_wins += 1
        elif win_prob <= 0.4:
            status = "losing"
            my_losses += 1
        else:
            status = "tossup"
            ties += 1

        categories[cat] = {
            "my_actual": round(my_actuals.get(cat, 0), 3),
            "opponent_actual": round(opp_actuals.get(cat, 0), 3),
            "my_projected_final": round(my_final, 3),
            "opponent_projected_final": round(opp_final, 3),
            "win_probability": round(win_prob, 3),
            "status": status,
        }

    # Overall win probability: average of category win probs
    all_probs = [categories[cat]["win_probability"] for cat in ALL_CATS]
    overall_win_prob = sum(all_probs) / len(all_probs) if all_probs else 0.5

    return {
        "projected_score": {"wins": my_wins, "losses": my_losses, "ties": ties},
        "overall_win_probability": round(overall_win_prob, 3),
        "categories": categories,
        "my_roster_projections": my_player_details,
    }
