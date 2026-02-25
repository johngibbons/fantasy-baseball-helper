"""In-season analysis engine.

Provides free agent rankings, add/drop recommendations, trade evaluation,
matchup analysis, strategy detection, and roster signals — all powered by
the existing MCW model and SGP z-score engine.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from backend.database import get_connection
from backend.simulation.scoring_model import (
    analyze_category_standings,
    compute_mcw,
    compute_rank,
    detect_strategy,
    win_prob_from_rank,
    ALL_CAT_KEYS,
    CategoryStanding,
)
from backend.simulation.config import SimConfig
from backend.simulation.player_pool import HITTING_CAT_KEYS, PITCHING_CAT_KEYS, CAT_LABELS

logger = logging.getLogger(__name__)

# ── Swing category thresholds (for weekly matchup analysis) ──
# If the projected margin is within this range, the category is a "swing"
_SWING_THRESHOLDS = {
    "R": 3.0, "TB": 8.0, "RBI": 3.0, "SB": 2.0, "OBP": 0.004,
    "K": 5.0, "QS": 1.0, "ERA": 0.15, "WHIP": 0.020, "SVHD": 2.0,
}

# Map zscore key → category short name used in standings/matchups
_ZSCORE_TO_CAT = {k: v for k, v in CAT_LABELS.items()}
_CAT_TO_ZSCORE = {v: k for k, v in CAT_LABELS.items()}


# ── Data loading helpers ──


def _load_team_standings(league_external_id: str, season: int, num_teams: int = 10
                         ) -> dict:
    """Load team season stats and compute category totals for MCW analysis.

    Returns:
        {
            "my_totals": {zscore_key: value},
            "other_team_totals": {zscore_key: [values]},
            "teams": {team_id: {zscore_key: value}},
        }
    """
    conn = get_connection()
    rows = conn.execute(
        """SELECT * FROM team_season_stats
           WHERE league_external_id = ? AND season = ?""",
        (league_external_id, season),
    ).fetchall()
    conn.close()

    if not rows:
        return {"my_totals": {}, "other_team_totals": {}, "teams": {}}

    # Convert raw stats to category values (matching zscore keys)
    teams: dict[int, dict[str, float]] = {}
    for row in rows:
        tid = row["team_id"]
        pa = row["stat_pa"] or 0
        ab = row["stat_ab"] or 0
        hits = row["stat_hits"] or 0
        walks = row["stat_walks"] or 0
        hbp = row["stat_hbp"] or 0
        sf = row["stat_sf"] or 0
        ip = row["stat_ip"] or 0
        er = row["stat_earned_runs"] or 0
        ha = row["stat_hits_allowed"] or 0
        wa = row["stat_walks_allowed"] or 0
        obp_denom = ab + walks + hbp + sf
        obp = (hits + walks + hbp) / obp_denom if obp_denom > 0 else 0
        era = (er * 9 / ip) if ip > 0 else 0
        whip = (ha + wa) / ip if ip > 0 else 0

        teams[tid] = {
            "zscore_r": float(row["stat_r"] or 0),
            "zscore_tb": float(row["stat_tb"] or 0),
            "zscore_rbi": float(row["stat_rbi"] or 0),
            "zscore_sb": float(row["stat_sb"] or 0),
            "zscore_obp": round(obp, 4),
            "zscore_k": float(row["stat_k"] or 0),
            "zscore_qs": float(row["stat_qs"] or 0),
            "zscore_era": round(era, 3),
            "zscore_whip": round(whip, 4),
            "zscore_svhd": float(row["stat_svhd"] or 0),
        }

    return {"teams": teams}


def _load_player_zscores(season: int) -> dict[int, dict]:
    """Load all player z-scores from rankings table.

    Returns:
        {mlb_id: {full_name, player_type, primary_position, zscores: {key: val}, ...}}
    """
    conn = get_connection()
    rows = conn.execute(
        """SELECT r.mlb_id, r.total_zscore, r.player_type,
                  r.zscore_r, r.zscore_tb, r.zscore_rbi, r.zscore_sb, r.zscore_obp,
                  r.zscore_k, r.zscore_qs, r.zscore_era, r.zscore_whip, r.zscore_svhd,
                  r.proj_pa, r.proj_r, r.proj_tb, r.proj_rbi, r.proj_sb, r.proj_obp,
                  r.proj_ip, r.proj_k, r.proj_qs, r.proj_era, r.proj_whip, r.proj_svhd,
                  p.full_name, p.primary_position, p.team, p.eligible_positions
           FROM rankings r
           JOIN players p ON r.mlb_id = p.mlb_id
           WHERE r.season = ?""",
        (season,),
    ).fetchall()
    conn.close()

    result = {}
    for row in rows:
        zscores = {}
        for k in ALL_CAT_KEYS:
            zscores[k] = row[k] or 0.0
        result[row["mlb_id"]] = {
            "mlb_id": row["mlb_id"],
            "full_name": row["full_name"],
            "primary_position": row["primary_position"],
            "team": row["team"],
            "player_type": row["player_type"],
            "total_zscore": row["total_zscore"],
            "eligible_positions": row["eligible_positions"],
            "zscores": zscores,
            "proj_pa": row["proj_pa"],
            "proj_r": row["proj_r"],
            "proj_tb": row["proj_tb"],
            "proj_rbi": row["proj_rbi"],
            "proj_sb": row["proj_sb"],
            "proj_obp": row["proj_obp"],
            "proj_ip": row["proj_ip"],
            "proj_k": row["proj_k"],
            "proj_qs": row["proj_qs"],
            "proj_era": row["proj_era"],
            "proj_whip": row["proj_whip"],
            "proj_svhd": row["proj_svhd"],
        }
    return result


def _load_ownership(league_external_id: str, season: int) -> dict[int, dict]:
    """Load player ownership data.

    Returns:
        {mlb_id: {owner_team_id, roster_status, lineup_slot}}
    """
    conn = get_connection()
    rows = conn.execute(
        """SELECT mlb_id, owner_team_id, roster_status, lineup_slot
           FROM player_ownership
           WHERE league_external_id = ? AND season = ?""",
        (league_external_id, season),
    ).fetchall()
    conn.close()
    return {
        row["mlb_id"]: {
            "owner_team_id": row["owner_team_id"],
            "roster_status": row["roster_status"],
            "lineup_slot": row["lineup_slot"],
        }
        for row in rows
    }


def _build_standings_context(
    teams: dict[int, dict[str, float]], my_team_id: int, num_teams: int
) -> tuple[dict[str, float], dict[str, list[float]], dict[str, str]]:
    """Build MCW context from team standings.

    Returns:
        (my_totals, other_team_totals, strategies)
    """
    my_totals = teams.get(my_team_id, {k: 0.0 for k in ALL_CAT_KEYS})
    other_totals: dict[str, list[float]] = {k: [] for k in ALL_CAT_KEYS}
    for tid, cat_vals in teams.items():
        if tid == my_team_id:
            continue
        for k in ALL_CAT_KEYS:
            other_totals[k].append(cat_vals.get(k, 0.0))

    standings = analyze_category_standings(my_totals, other_totals, num_teams)
    standings = detect_strategy(standings, num_teams, num_teams)
    strategies = {s.cat_key: s.strategy for s in standings}

    return my_totals, other_totals, strategies


# ── Phase 2a: Free Agent Rankings ──


@dataclass
class FreeAgentRanking:
    mlb_id: int
    full_name: str
    primary_position: str
    team: str
    player_type: str
    total_zscore: float
    mcw: float
    category_impact: dict[str, float] = field(default_factory=dict)
    eligible_positions: Optional[str] = None
    proj_pa: int = 0
    proj_ip: float = 0


def get_free_agent_rankings(
    league_external_id: str,
    season: int,
    my_team_id: int,
    num_teams: int = 10,
    position: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """Rank free agents by MCW relative to my team's standings.

    Args:
        league_external_id: ESPN league ID
        season: Current season
        my_team_id: My team's ESPN team ID
        num_teams: League size
        position: Optional position filter
        limit: Max results

    Returns:
        List of free agents ranked by MCW.
    """
    standings_data = _load_team_standings(league_external_id, season)
    teams = standings_data.get("teams", {})
    if not teams:
        return []

    my_totals, other_totals, strategies = _build_standings_context(
        teams, my_team_id, num_teams
    )

    all_zscores = _load_player_zscores(season)
    ownership = _load_ownership(league_external_id, season)

    config = SimConfig(NUM_TEAMS=num_teams)
    results = []

    for mlb_id, player in all_zscores.items():
        # Filter to free agents only
        own = ownership.get(mlb_id, {})
        if own.get("roster_status") not in (None, "FREEAGENT", "WAIVERS"):
            continue
        if own.get("owner_team_id") is not None:
            continue

        # Position filter
        if position:
            pos = player["primary_position"]
            elig = player.get("eligible_positions", "") or ""
            if position != pos and position not in elig.split("/"):
                continue

        mcw = compute_mcw(
            player["zscores"], my_totals, other_totals, strategies, num_teams, config
        )

        # Compute per-category impact
        cat_impact = {}
        for cat_key in ALL_CAT_KEYS:
            val = player["zscores"].get(cat_key, 0.0)
            if val != 0 and strategies.get(cat_key) != "punt":
                my_val = my_totals.get(cat_key, 0.0)
                others = other_totals.get(cat_key, [])
                rank_before = compute_rank(my_val, others)
                rank_after = compute_rank(my_val + val, others)
                wp_before = win_prob_from_rank(rank_before, num_teams)
                wp_after = win_prob_from_rank(rank_after, num_teams)
                cat_label = CAT_LABELS.get(cat_key, cat_key)
                cat_impact[cat_label] = round(wp_after - wp_before, 4)

        results.append({
            "mlb_id": mlb_id,
            "full_name": player["full_name"],
            "primary_position": player["primary_position"],
            "team": player["team"],
            "player_type": player["player_type"],
            "total_zscore": player["total_zscore"],
            "eligible_positions": player.get("eligible_positions"),
            "mcw": round(mcw, 4),
            "category_impact": cat_impact,
            "proj_pa": player.get("proj_pa", 0),
            "proj_ip": player.get("proj_ip", 0),
        })

    results.sort(key=lambda x: x["mcw"], reverse=True)
    return results[:limit]


# ── Phase 2b: Add/Drop Recommendations ──


def get_add_drop_recommendations(
    league_external_id: str,
    season: int,
    my_team_id: int,
    num_teams: int = 10,
    horizon: str = "ros",
    limit: int = 20,
    matchup_scores: Optional[dict] = None,
) -> list[dict]:
    """Generate add/drop swap recommendations ranked by net MCW gain.

    Args:
        horizon: 'ros' for season-long, 'week' for current matchup
        matchup_scores: Required for horizon='week' — {category: my_score, opp_score}
        limit: Max recommendations

    Returns:
        List of {add_player, drop_player, net_mcw, category_impact} dicts.
    """
    standings_data = _load_team_standings(league_external_id, season)
    teams = standings_data.get("teams", {})
    if not teams:
        return []

    my_totals, other_totals, strategies = _build_standings_context(
        teams, my_team_id, num_teams
    )

    all_zscores = _load_player_zscores(season)
    ownership = _load_ownership(league_external_id, season)
    config = SimConfig(NUM_TEAMS=num_teams)

    # Identify my roster and free agents
    my_roster = []
    free_agents = []
    for mlb_id, player in all_zscores.items():
        own = ownership.get(mlb_id, {})
        if own.get("owner_team_id") == my_team_id:
            my_roster.append(player)
        elif own.get("owner_team_id") is None:
            free_agents.append(player)

    if not my_roster or not free_agents:
        return []

    # For weekly horizon, modify strategies to focus on swing categories
    if horizon == "week" and matchup_scores:
        strategies = _swing_weighted_strategies(matchup_scores, strategies)

    # Score free agents by MCW
    fa_with_mcw = []
    for fa in free_agents:
        mcw = compute_mcw(
            fa["zscores"], my_totals, other_totals, strategies, num_teams, config
        )
        if mcw > 0:
            fa_with_mcw.append((fa, mcw))

    fa_with_mcw.sort(key=lambda x: x[1], reverse=True)
    # Only consider top free agents to limit computation
    fa_with_mcw = fa_with_mcw[:50]

    recommendations = []
    for fa, fa_mcw in fa_with_mcw:
        best_drop = None
        best_net_mcw = -float("inf")

        for roster_player in my_roster:
            # Compute MCW of the player we'd drop
            drop_mcw = compute_mcw(
                roster_player["zscores"], my_totals, other_totals,
                strategies, num_teams, config
            )
            net = fa_mcw - drop_mcw
            if net > best_net_mcw:
                best_net_mcw = net
                best_drop = roster_player

        if best_drop and best_net_mcw > 0:
            # Compute per-category impact
            cat_impact = {}
            for cat_key in ALL_CAT_KEYS:
                fa_val = fa["zscores"].get(cat_key, 0.0)
                drop_val = best_drop["zscores"].get(cat_key, 0.0)
                net_val = fa_val - drop_val
                if net_val != 0:
                    cat_label = CAT_LABELS.get(cat_key, cat_key)
                    cat_impact[cat_label] = round(net_val, 3)

            recommendations.append({
                "add_player": {
                    "mlb_id": fa["mlb_id"],
                    "full_name": fa["full_name"],
                    "primary_position": fa["primary_position"],
                    "team": fa["team"],
                    "player_type": fa["player_type"],
                    "mcw": round(fa_mcw, 4),
                },
                "drop_player": {
                    "mlb_id": best_drop["mlb_id"],
                    "full_name": best_drop["full_name"],
                    "primary_position": best_drop["primary_position"],
                    "team": best_drop["team"],
                    "player_type": best_drop["player_type"],
                },
                "net_mcw": round(best_net_mcw, 4),
                "category_impact": cat_impact,
                "horizon": horizon,
            })

    recommendations.sort(key=lambda x: x["net_mcw"], reverse=True)
    return recommendations[:limit]


def _swing_weighted_strategies(
    matchup_scores: dict, base_strategies: dict[str, str]
) -> dict[str, str]:
    """For weekly horizon, punt categories we're already winning/losing comfortably."""
    result = dict(base_strategies)
    for cat_label, threshold in _SWING_THRESHOLDS.items():
        zscore_key = _CAT_TO_ZSCORE.get(cat_label)
        if not zscore_key:
            continue
        my_score = matchup_scores.get(f"my_{cat_label.lower()}", 0)
        opp_score = matchup_scores.get(f"opp_{cat_label.lower()}", 0)
        margin = my_score - opp_score
        # For inverted stats (ERA/WHIP), lower is better
        if cat_label in ("ERA", "WHIP"):
            margin = opp_score - my_score
        if abs(margin) > threshold * 2:
            # Comfortable margin — treat as irrelevant for weekly decisions
            result[zscore_key] = "punt"
    return result


# ── Phase 2c: Trade Evaluator ──


def evaluate_trade(
    league_external_id: str,
    season: int,
    my_team_id: int,
    partner_team_id: int,
    give_ids: list[int],
    receive_ids: list[int],
    num_teams: int = 10,
) -> dict:
    """Evaluate a proposed trade between two teams.

    Returns:
        {
            my_mcw_change: float,
            partner_mcw_change: float,
            my_category_impact: {cat: before/after},
            partner_category_impact: {cat: before/after},
        }
    """
    standings_data = _load_team_standings(league_external_id, season)
    teams = standings_data.get("teams", {})
    if not teams:
        return {"error": "No standings data available"}

    all_zscores = _load_player_zscores(season)
    config = SimConfig(NUM_TEAMS=num_teams)

    # Compute MCW impact for my team
    my_totals, my_others, my_strategies = _build_standings_context(
        teams, my_team_id, num_teams
    )

    # Compute MCW of players I'm giving away
    give_mcw = 0.0
    for mid in give_ids:
        p = all_zscores.get(mid)
        if p:
            give_mcw += compute_mcw(
                p["zscores"], my_totals, my_others, my_strategies, num_teams, config
            )

    # Compute MCW of players I'm receiving
    receive_mcw = 0.0
    for mid in receive_ids:
        p = all_zscores.get(mid)
        if p:
            receive_mcw += compute_mcw(
                p["zscores"], my_totals, my_others, my_strategies, num_teams, config
            )

    my_mcw_change = receive_mcw - give_mcw

    # Compute MCW impact for partner team
    partner_totals, partner_others, partner_strategies = _build_standings_context(
        teams, partner_team_id, num_teams
    )

    # Partner gives the players I receive, receives the players I give
    partner_give_mcw = 0.0
    for mid in receive_ids:
        p = all_zscores.get(mid)
        if p:
            partner_give_mcw += compute_mcw(
                p["zscores"], partner_totals, partner_others,
                partner_strategies, num_teams, config
            )

    partner_receive_mcw = 0.0
    for mid in give_ids:
        p = all_zscores.get(mid)
        if p:
            partner_receive_mcw += compute_mcw(
                p["zscores"], partner_totals, partner_others,
                partner_strategies, num_teams, config
            )

    partner_mcw_change = partner_receive_mcw - partner_give_mcw

    # Build category-level impact for both sides
    my_cat_impact = {}
    partner_cat_impact = {}
    for cat_key in ALL_CAT_KEYS:
        cat_label = CAT_LABELS.get(cat_key, cat_key)
        give_val = sum(
            all_zscores.get(mid, {}).get("zscores", {}).get(cat_key, 0.0)
            for mid in give_ids
        )
        receive_val = sum(
            all_zscores.get(mid, {}).get("zscores", {}).get(cat_key, 0.0)
            for mid in receive_ids
        )
        my_cat_impact[cat_label] = round(receive_val - give_val, 3)
        partner_cat_impact[cat_label] = round(give_val - receive_val, 3)

    # Build player details
    give_players = [
        {"mlb_id": mid, "full_name": all_zscores.get(mid, {}).get("full_name", "Unknown")}
        for mid in give_ids
    ]
    receive_players = [
        {"mlb_id": mid, "full_name": all_zscores.get(mid, {}).get("full_name", "Unknown")}
        for mid in receive_ids
    ]

    return {
        "give_players": give_players,
        "receive_players": receive_players,
        "my_mcw_change": round(my_mcw_change, 4),
        "partner_mcw_change": round(partner_mcw_change, 4),
        "my_category_impact": my_cat_impact,
        "partner_category_impact": partner_cat_impact,
        "is_positive_sum": my_mcw_change > -0.01 and partner_mcw_change > -0.01,
    }


def find_trades(
    league_external_id: str,
    season: int,
    my_team_id: int,
    num_teams: int = 10,
    limit: int = 20,
) -> list[dict]:
    """Auto-discover positive-sum trade opportunities.

    For each opponent, find 1-for-1 swaps where both teams gain MCW.

    Returns:
        List of trade proposals ranked by my MCW gain.
    """
    standings_data = _load_team_standings(league_external_id, season)
    teams = standings_data.get("teams", {})
    if not teams:
        return []

    all_zscores = _load_player_zscores(season)
    ownership = _load_ownership(league_external_id, season)
    config = SimConfig(NUM_TEAMS=num_teams)

    # My context
    my_totals, my_others, my_strategies = _build_standings_context(
        teams, my_team_id, num_teams
    )

    # Identify my roster players
    my_roster = {
        mid: p for mid, p in all_zscores.items()
        if ownership.get(mid, {}).get("owner_team_id") == my_team_id
    }

    trades = []
    opponent_ids = [tid for tid in teams if tid != my_team_id]

    for opp_id in opponent_ids:
        opp_totals, opp_others, opp_strategies = _build_standings_context(
            teams, opp_id, num_teams
        )

        # Identify opponent's roster
        opp_roster = {
            mid: p for mid, p in all_zscores.items()
            if ownership.get(mid, {}).get("owner_team_id") == opp_id
        }

        # Try all 1-for-1 swaps
        for my_mid, my_player in my_roster.items():
            my_player_mcw_for_me = compute_mcw(
                my_player["zscores"], my_totals, my_others, my_strategies,
                num_teams, config
            )

            for opp_mid, opp_player in opp_roster.items():
                # Same player type preferred
                if my_player["player_type"] != opp_player["player_type"]:
                    continue

                # MCW of opp player for me (what I gain)
                opp_player_mcw_for_me = compute_mcw(
                    opp_player["zscores"], my_totals, my_others, my_strategies,
                    num_teams, config
                )
                my_net = opp_player_mcw_for_me - my_player_mcw_for_me

                # MCW of my player for opponent (what they gain)
                my_player_mcw_for_opp = compute_mcw(
                    my_player["zscores"], opp_totals, opp_others, opp_strategies,
                    num_teams, config
                )
                opp_player_mcw_for_opp = compute_mcw(
                    opp_player["zscores"], opp_totals, opp_others, opp_strategies,
                    num_teams, config
                )
                opp_net = my_player_mcw_for_opp - opp_player_mcw_for_opp

                # Both sides must benefit (or be roughly neutral)
                if my_net > 0.001 and opp_net > -0.01:
                    trades.append({
                        "give_player": {
                            "mlb_id": my_mid,
                            "full_name": my_player["full_name"],
                            "primary_position": my_player["primary_position"],
                            "team": my_player["team"],
                        },
                        "receive_player": {
                            "mlb_id": opp_mid,
                            "full_name": opp_player["full_name"],
                            "primary_position": opp_player["primary_position"],
                            "team": opp_player["team"],
                        },
                        "partner_team_id": opp_id,
                        "my_mcw_gain": round(my_net, 4),
                        "partner_mcw_gain": round(opp_net, 4),
                    })

    trades.sort(key=lambda x: x["my_mcw_gain"], reverse=True)
    return trades[:limit]


# ── Phase 3: Weekly Matchup Analysis ──


def analyze_matchup(
    league_external_id: str,
    season: int,
    matchup_period: int,
    my_team_id: int,
) -> dict:
    """Analyze the current week's H2H matchup.

    Returns per-category status (winning/losing/swing) and projected outcome.
    """
    conn = get_connection()

    # Load matchup
    matchup_row = conn.execute(
        """SELECT id, home_team_id, away_team_id FROM matchups
           WHERE league_external_id = ? AND season = ? AND matchup_period = ?
             AND (home_team_id = ? OR away_team_id = ?)""",
        (league_external_id, season, matchup_period, my_team_id, my_team_id),
    ).fetchone()

    if not matchup_row:
        conn.close()
        return {"error": "Matchup not found"}

    matchup_id = matchup_row["id"]
    opp_team_id = (
        matchup_row["away_team_id"]
        if matchup_row["home_team_id"] == my_team_id
        else matchup_row["home_team_id"]
    )

    # Load category scores for both teams
    scores = conn.execute(
        """SELECT team_id, category, value FROM matchup_category_scores
           WHERE matchup_id = ?""",
        (matchup_id,),
    ).fetchall()
    conn.close()

    my_scores: dict[str, float] = {}
    opp_scores: dict[str, float] = {}
    for row in scores:
        if row["team_id"] == my_team_id:
            my_scores[row["category"]] = row["value"] or 0
        elif row["team_id"] == opp_team_id:
            opp_scores[row["category"]] = row["value"] or 0

    # Classify each category
    categories = []
    wins = 0
    losses = 0
    ties = 0

    for cat_label, threshold in _SWING_THRESHOLDS.items():
        my_val = my_scores.get(cat_label, 0)
        opp_val = opp_scores.get(cat_label, 0)
        margin = my_val - opp_val
        # Inverted categories: lower is better
        if cat_label in ("ERA", "WHIP"):
            margin = opp_val - my_val

        if abs(margin) <= threshold:
            status = "swing"
            ties += 1
        elif margin > 0:
            status = "winning"
            wins += 1
        else:
            status = "losing"
            losses += 1

        categories.append({
            "category": cat_label,
            "my_value": round(my_val, 3),
            "opp_value": round(opp_val, 3),
            "margin": round(margin, 3),
            "threshold": threshold,
            "status": status,
        })

    return {
        "matchup_period": matchup_period,
        "my_team_id": my_team_id,
        "opp_team_id": opp_team_id,
        "categories": categories,
        "projected_result": f"{wins}-{losses}-{ties}",
        "wins": wins,
        "losses": losses,
        "ties": ties,
    }


# ── Phase 4a: Season Strategy ──


def get_season_strategy(
    league_external_id: str,
    season: int,
    my_team_id: int,
    num_teams: int = 10,
    playoff_spots: int = 6,
) -> dict:
    """Analyze season-long category strategy from actual standings.

    Returns category-by-category strategy recommendations.
    """
    standings_data = _load_team_standings(league_external_id, season)
    teams = standings_data.get("teams", {})
    if not teams:
        return {"error": "No standings data available"}

    my_totals = teams.get(my_team_id, {k: 0.0 for k in ALL_CAT_KEYS})
    other_totals: dict[str, list[float]] = {k: [] for k in ALL_CAT_KEYS}
    for tid, cat_vals in teams.items():
        if tid == my_team_id:
            continue
        for k in ALL_CAT_KEYS:
            other_totals[k].append(cat_vals.get(k, 0.0))

    standings = analyze_category_standings(my_totals, other_totals, num_teams)
    standings = detect_strategy(standings, num_teams, num_teams, playoff_spots)

    categories = []
    for s in standings:
        cat_label = CAT_LABELS.get(s.cat_key, s.cat_key)
        categories.append({
            "category": cat_label,
            "cat_key": s.cat_key,
            "my_total": round(s.my_total, 3),
            "rank": s.my_rank,
            "win_prob": round(s.win_prob, 3),
            "gap_above": round(s.gap_above, 3),
            "gap_below": round(s.gap_below, 3),
            "strategy": s.strategy,
        })

    # Compute overall position
    total_wins = sum(s.win_prob for s in standings)
    categories.sort(key=lambda c: c["rank"])

    return {
        "my_team_id": my_team_id,
        "num_teams": num_teams,
        "expected_category_wins": round(total_wins, 1),
        "categories": categories,
        "target_categories": [c["category"] for c in categories if c["strategy"] == "target"],
        "lock_categories": [c["category"] for c in categories if c["strategy"] == "lock"],
        "punt_categories": [c["category"] for c in categories if c["strategy"] == "punt"],
    }


# ── Phase 4b: Timing Signals ──


def get_roster_signals(
    league_external_id: str,
    season: int,
    my_team_id: int,
    num_teams: int = 10,
    limit: int = 30,
) -> list[dict]:
    """Detect roster-relevant signals from projection vs actual performance.

    Types:
    - 'drop_candidate': Rostered player with low MCW
    - 'add_target': Free agent with high MCW
    - 'underperformer': Rostered player with significantly negative z-scores
    """
    standings_data = _load_team_standings(league_external_id, season)
    teams = standings_data.get("teams", {})
    if not teams:
        return []

    my_totals, other_totals, strategies = _build_standings_context(
        teams, my_team_id, num_teams
    )

    all_zscores = _load_player_zscores(season)
    ownership = _load_ownership(league_external_id, season)
    config = SimConfig(NUM_TEAMS=num_teams)

    signals = []

    for mlb_id, player in all_zscores.items():
        own = ownership.get(mlb_id, {})
        is_mine = own.get("owner_team_id") == my_team_id
        is_free = own.get("owner_team_id") is None

        mcw = compute_mcw(
            player["zscores"], my_totals, other_totals, strategies, num_teams, config
        )

        if is_mine:
            # Drop candidate: rostered player with very low or negative MCW
            if mcw < 0.005:
                signals.append({
                    "mlb_id": mlb_id,
                    "full_name": player["full_name"],
                    "primary_position": player["primary_position"],
                    "team": player["team"],
                    "player_type": player["player_type"],
                    "signal_type": "drop_candidate",
                    "severity": "high" if mcw < -0.01 else "medium",
                    "mcw": round(mcw, 4),
                    "action": "drop",
                    "description": f"Low projected value (MCW: {mcw:.3f})",
                })

        elif is_free:
            # High-value free agent
            if mcw > 0.02:
                signals.append({
                    "mlb_id": mlb_id,
                    "full_name": player["full_name"],
                    "primary_position": player["primary_position"],
                    "team": player["team"],
                    "player_type": player["player_type"],
                    "signal_type": "add_target",
                    "severity": "high" if mcw > 0.05 else "medium",
                    "mcw": round(mcw, 4),
                    "action": "add",
                    "description": f"High value free agent (MCW: {mcw:.3f})",
                })

    # Sort by severity (high first), then by absolute MCW
    severity_order = {"high": 0, "medium": 1, "low": 2}
    signals.sort(key=lambda s: (severity_order.get(s["severity"], 3), -abs(s["mcw"])))
    return signals[:limit]
