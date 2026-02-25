"""API route definitions."""

import difflib
import json
import logging
import unicodedata
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
from typing import Any, Optional
from backend.analysis.rankings import (
    get_rankings,
    get_player_detail,
    get_adp_comparison,
    get_position_summary,
)
from backend.analysis.zscores import (
    calculate_hitter_zscores,
    calculate_pitcher_zscores,
    calculate_all_zscores,
)
from backend.analysis.inseason import (
    get_free_agent_rankings,
    get_add_drop_recommendations,
    evaluate_trade,
    find_trades,
    analyze_matchup,
    get_season_strategy,
    get_roster_signals,
)
from backend.database import get_connection

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/players")
def list_players(
    season: int = Query(2026, description="Target season"),
    player_type: Optional[str] = Query(None, description="'hitter' or 'pitcher'"),
    position: Optional[str] = Query(None, description="Position filter (e.g., SS, SP)"),
    search: Optional[str] = Query(None, description="Search player name"),
    limit: int = Query(300, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """List all players with projections and z-score values."""
    if search:
        conn = get_connection()
        rows = conn.execute(
            """SELECT r.*, p.full_name, p.primary_position, p.team, p.player_type as ptype
               FROM rankings r
               JOIN players p ON r.mlb_id = p.mlb_id
               WHERE r.season = ? AND p.full_name LIKE ?
               ORDER BY r.overall_rank ASC
               LIMIT ?""",
            (season, f"%{search}%", limit),
        ).fetchall()
        conn.close()
        return {"players": [dict(r) for r in rows], "total": len(rows)}

    players = get_rankings(season, player_type, position, limit, offset)

    # Get total count
    conn = get_connection()
    count_query = "SELECT COUNT(*) as cnt FROM rankings WHERE season = ?"
    params: list = [season]
    if player_type:
        count_query += " AND player_type = ?"
        params.append(player_type)
    total = conn.execute(count_query, params).fetchone()["cnt"]
    conn.close()

    return {"players": players, "total": total, "limit": limit, "offset": offset}


@router.get("/players/{mlb_id}")
def player_detail(mlb_id: int, season: int = Query(2026)):
    """Get full player detail with stat breakdown."""
    player = get_player_detail(mlb_id, season)
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    return player


@router.get("/rankings")
def rankings(
    season: int = Query(2026),
    player_type: Optional[str] = Query(None),
    position: Optional[str] = Query(None),
    sort_by: Optional[str] = Query(None, description="Sort by z-score category (e.g., zscore_sb)"),
    limit: int = Query(300, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """Ranked player list with filters."""
    players = get_rankings(season, player_type, position, limit, offset)

    if sort_by and sort_by.startswith("zscore_"):
        players.sort(key=lambda p: p.get(sort_by, 0) or 0, reverse=True)

    return {"rankings": players, "total": len(players)}


@router.get("/rankings/positions")
def position_rankings(season: int = Query(2026)):
    """Get top players at each position."""
    return get_position_summary(season)


@router.get("/draft/value")
def draft_value(
    season: int = Query(2026),
    limit: int = Query(200),
):
    """Players sorted by value vs ADP — find the biggest steals."""
    steals = get_adp_comparison(season, limit)

    # If no ADP data, return players sorted by z-score (our rankings vs typical order)
    if not steals:
        all_players = get_rankings(season, limit=limit)
        return {
            "players": all_players,
            "note": "No ADP data loaded. Showing players ranked by z-score value.",
        }

    return {"players": steals}


@router.get("/draft/board")
def draft_board(season: int = Query(2026)):
    """Full draft board with all players for live draft tracking."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT r.mlb_id, r.overall_rank, r.position_rank, r.total_zscore,
                  r.zscore_r, r.zscore_tb, r.zscore_rbi, r.zscore_sb, r.zscore_obp,
                  r.zscore_k, r.zscore_qs, r.zscore_era, r.zscore_whip, r.zscore_svhd,
                  r.proj_pa, r.proj_r, r.proj_tb, r.proj_rbi, r.proj_sb, r.proj_obp,
                  r.proj_ip, r.proj_k, r.proj_qs, r.proj_era, r.proj_whip, r.proj_svhd,
                  r.player_type, r.espn_adp, r.adp_diff,
                  p.full_name, p.primary_position, p.team, p.eligible_positions
           FROM rankings r
           JOIN players p ON r.mlb_id = p.mlb_id
           WHERE r.season = ?
           ORDER BY r.overall_rank ASC""",
        (season,),
    ).fetchall()
    conn.close()

    return {"players": [dict(r) for r in rows], "total": len(rows)}


@router.get("/players/{mlb_id}/statcast")
def player_statcast(mlb_id: int, season: int = Query(2025)):
    """Get Statcast metrics for a player."""
    conn = get_connection()

    # Check player type
    player = conn.execute(
        "SELECT player_type FROM players WHERE mlb_id = ?", (mlb_id,)
    ).fetchone()
    if not player:
        conn.close()
        raise HTTPException(status_code=404, detail="Player not found")

    if player["player_type"] == "hitter":
        row = conn.execute(
            """SELECT * FROM statcast_batting
               WHERE mlb_id = ? AND season = ?""",
            (mlb_id, season),
        ).fetchone()
    else:
        row = conn.execute(
            """SELECT * FROM statcast_pitching
               WHERE mlb_id = ? AND season = ?""",
            (mlb_id, season),
        ).fetchone()

    conn.close()

    if not row:
        return {"mlb_id": mlb_id, "season": season, "data": None}

    return {"mlb_id": mlb_id, "season": season, "player_type": player["player_type"], "data": dict(row)}


class RecalculateRequest(BaseModel):
    excluded_ids: list[int]
    season: int = 2026


@router.post("/draft/recalculate")
def draft_recalculate(body: RecalculateRequest):
    """Re-run the z-score engine excluding drafted players.

    Returns fresh rankings without writing to DB — ephemeral draft-time values.
    """
    results = calculate_all_zscores(
        season=body.season,
        excluded_ids=set(body.excluded_ids),
        save_to_db=False,
    )
    return {"players": results}


class DraftStateBody(BaseModel):
    season: int
    state: Any


def _ensure_draft_state_table(conn):
    """Create the draft_state table if it doesn't exist (self-healing migration)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS draft_state (
            season INTEGER PRIMARY KEY,
            state_json TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()


@router.get("/draft/state")
def get_draft_state(season: int = Query(2026)):
    """Fetch persisted draft state for a season."""
    conn = get_connection()
    _ensure_draft_state_table(conn)
    row = conn.execute(
        "SELECT state_json FROM draft_state WHERE season = ?", (season,)
    ).fetchone()
    conn.close()
    if not row:
        return {"state": None}
    return {"state": json.loads(row["state_json"])}


@router.put("/draft/state")
def put_draft_state(body: DraftStateBody):
    """Upsert draft state for a season."""
    state_json = json.dumps(body.state)
    conn = get_connection()
    _ensure_draft_state_table(conn)
    conn.execute(
        """INSERT INTO draft_state (season, state_json) VALUES (?, ?)
           ON CONFLICT (season) DO UPDATE SET state_json = ?, updated_at = CURRENT_TIMESTAMP""",
        (body.season, state_json, state_json),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


# ── Keepers state persistence ──


class KeepersStateBody(BaseModel):
    season: int
    state: Any


def _ensure_keepers_state_table(conn):
    """Create the keepers_state table if it doesn't exist (self-healing migration)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS keepers_state (
            season INTEGER PRIMARY KEY,
            state_json TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()


@router.get("/keepers/state")
def get_keepers_state(season: int = Query(2026)):
    """Fetch persisted keepers state for a season."""
    conn = get_connection()
    _ensure_keepers_state_table(conn)
    row = conn.execute(
        "SELECT state_json FROM keepers_state WHERE season = ?", (season,)
    ).fetchone()
    conn.close()
    if not row:
        return {"state": None}
    return {"state": json.loads(row["state_json"])}


@router.put("/keepers/state")
def put_keepers_state(body: KeepersStateBody):
    """Upsert keepers state for a season."""
    state_json = json.dumps(body.state)
    conn = get_connection()
    _ensure_keepers_state_table(conn)
    conn.execute(
        """INSERT INTO keepers_state (season, state_json) VALUES (?, ?)
           ON CONFLICT (season) DO UPDATE SET state_json = ?, updated_at = CURRENT_TIMESTAMP""",
        (body.season, state_json, state_json),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


@router.get("/stats/summary")
def stats_summary(season: int = Query(2026)):
    """Summary statistics for the dashboard."""
    conn = get_connection()

    total_players = conn.execute(
        "SELECT COUNT(*) as cnt FROM rankings WHERE season = ?", (season,)
    ).fetchone()["cnt"]

    total_hitters = conn.execute(
        "SELECT COUNT(*) as cnt FROM rankings WHERE season = ? AND player_type = 'hitter'",
        (season,),
    ).fetchone()["cnt"]

    total_pitchers = conn.execute(
        "SELECT COUNT(*) as cnt FROM rankings WHERE season = ? AND player_type = 'pitcher'",
        (season,),
    ).fetchone()["cnt"]

    # Top 5 overall
    top_5 = conn.execute(
        """SELECT r.mlb_id, r.overall_rank, r.total_zscore, r.player_type,
                  p.full_name, p.primary_position, p.team
           FROM rankings r JOIN players p ON r.mlb_id = p.mlb_id
           WHERE r.season = ?
           ORDER BY r.overall_rank ASC LIMIT 5""",
        (season,),
    ).fetchall()

    conn.close()

    return {
        "total_players": total_players,
        "total_hitters": total_hitters,
        "total_pitchers": total_pitchers,
        "top_5": [dict(r) for r in top_5],
    }


# ── Keeper resolution ──


def _normalize_name(name: str) -> str:
    """Strip accents, lowercase, remove suffixes like Jr./III for matching."""
    # Decompose unicode and strip combining marks (accents)
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_name = "".join(c for c in nfkd if not unicodedata.combining(c))
    ascii_name = ascii_name.lower().strip()
    # Remove common suffixes
    for suffix in [" jr.", " jr", " sr.", " sr", " ii", " iii", " iv"]:
        if ascii_name.endswith(suffix):
            ascii_name = ascii_name[: -len(suffix)].strip()
    return ascii_name


class KeeperCandidateIn(BaseModel):
    name: str
    draft_round: int | None = None
    keeper_season: int = 1


class KeeperResolveRequest(BaseModel):
    players: list[KeeperCandidateIn]
    season: int = 2026


@router.post("/keepers/resolve")
def resolve_keepers(body: KeeperResolveRequest):
    """Match player names against the DB and return ranking data."""
    conn = get_connection()

    # Load all players + rankings for matching
    all_rows = conn.execute(
        """SELECT p.mlb_id, p.full_name, p.primary_position, p.team,
                  p.player_type, p.eligible_positions,
                  r.overall_rank, r.total_zscore, r.position_rank,
                  r.zscore_r, r.zscore_tb, r.zscore_rbi, r.zscore_sb, r.zscore_obp,
                  r.zscore_k, r.zscore_qs, r.zscore_era, r.zscore_whip, r.zscore_svhd
           FROM players p
           LEFT JOIN rankings r ON p.mlb_id = r.mlb_id AND r.season = ?
           WHERE p.is_active = 1""",
        (body.season,),
    ).fetchall()
    conn.close()

    # Build lookup structures
    db_players = [dict(r) for r in all_rows]
    # exact normalized name -> player row
    exact_lookup: dict[str, dict] = {}
    all_names: list[str] = []
    name_to_player: dict[str, dict] = {}
    for p in db_players:
        norm = _normalize_name(p["full_name"])
        exact_lookup[norm] = p
        all_names.append(p["full_name"])
        name_to_player[p["full_name"]] = p

    resolved = []
    unmatched = []

    for candidate in body.players:
        norm_input = _normalize_name(candidate.name)
        match = None
        confidence = 0.0

        # Pass 1: exact normalized match
        if norm_input in exact_lookup:
            match = exact_lookup[norm_input]
            confidence = 1.0

        # Pass 2: LIKE-style substring match on last name
        if not match:
            parts = candidate.name.strip().split()
            if parts:
                last_name = parts[-1].lower()
                candidates_found = [
                    p for p in db_players
                    if last_name in p["full_name"].lower()
                ]
                if len(candidates_found) == 1:
                    match = candidates_found[0]
                    confidence = 0.9
                elif len(candidates_found) > 1:
                    # Try first + last name
                    first_name = parts[0].lower() if len(parts) > 1 else ""
                    refined = [
                        p for p in candidates_found
                        if first_name in p["full_name"].lower()
                    ]
                    if len(refined) == 1:
                        match = refined[0]
                        confidence = 0.9

        # Pass 3: fuzzy match with difflib
        if not match:
            close = difflib.get_close_matches(
                candidate.name, all_names, n=1, cutoff=0.6
            )
            if close:
                match = name_to_player[close[0]]
                confidence = difflib.SequenceMatcher(
                    None, _normalize_name(candidate.name),
                    _normalize_name(close[0])
                ).ratio()

        if match:
            resolved.append({
                "name": candidate.name,
                "mlb_id": match["mlb_id"],
                "matched_name": match["full_name"],
                "match_confidence": round(confidence, 3),
                "draft_round": candidate.draft_round,
                "keeper_season": candidate.keeper_season,
                "overall_rank": match.get("overall_rank"),
                "total_zscore": match.get("total_zscore"),
                "primary_position": match["primary_position"],
                "team": match["team"],
                "player_type": match["player_type"],
                "eligible_positions": match.get("eligible_positions"),
                "zscore_r": match.get("zscore_r"),
                "zscore_tb": match.get("zscore_tb"),
                "zscore_rbi": match.get("zscore_rbi"),
                "zscore_sb": match.get("zscore_sb"),
                "zscore_obp": match.get("zscore_obp"),
                "zscore_k": match.get("zscore_k"),
                "zscore_qs": match.get("zscore_qs"),
                "zscore_era": match.get("zscore_era"),
                "zscore_whip": match.get("zscore_whip"),
                "zscore_svhd": match.get("zscore_svhd"),
            })
        else:
            unmatched.append({
                "name": candidate.name,
                "draft_round": candidate.draft_round,
                "keeper_season": candidate.keeper_season,
            })

    return {"resolved": resolved, "unmatched": unmatched}


# ── In-Season Management Endpoints ──


@router.post("/inseason/sync")
def inseason_sync(
    season: int = Query(2026),
):
    """Fetch ROS projections from FanGraphs and recalculate rankings.

    Called by the Next.js /api/leagues/[leagueId]/inseason-sync route
    after it has already fetched ESPN data.
    """
    from backend.data.fangraphs_api import fetch_all_ros_projections

    try:
        results = fetch_all_ros_projections(season)
    except Exception as e:
        logger.warning(f"FanGraphs ROS fetch failed (non-fatal): {e}")
        results = {}

    # Recalculate z-scores using ROS projections
    try:
        calculate_all_zscores(season)
    except Exception as e:
        logger.error(f"Z-score recalculation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Ranking recalculation failed: {e}")

    # Get last update timestamp
    conn = get_connection()
    state = conn.execute(
        "SELECT last_ros_update FROM season_state WHERE season = ?", (season,)
    ).fetchone()
    conn.close()

    return {
        "ok": True,
        "ros_projections": results,
        "last_ros_update": state["last_ros_update"] if state else None,
    }


@router.get("/inseason/free-agents")
def inseason_free_agents(
    league_id: str = Query(..., description="ESPN league external ID"),
    season: int = Query(2026),
    my_team_id: int = Query(..., description="My ESPN team ID"),
    num_teams: int = Query(10),
    position: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """Rank free agents by MCW relative to my team's standings."""
    return {
        "free_agents": get_free_agent_rankings(
            league_id, season, my_team_id, num_teams, position, limit
        )
    }


@router.get("/inseason/recommendations")
def inseason_recommendations(
    league_id: str = Query(..., description="ESPN league external ID"),
    season: int = Query(2026),
    my_team_id: int = Query(..., description="My ESPN team ID"),
    num_teams: int = Query(10),
    horizon: str = Query("ros", description="'ros' or 'week'"),
    limit: int = Query(20, ge=1, le=50),
):
    """Get add/drop swap recommendations ranked by net MCW gain."""
    return {
        "recommendations": get_add_drop_recommendations(
            league_id, season, my_team_id, num_teams, horizon, limit
        )
    }


class TradeEvalRequest(BaseModel):
    league_id: str
    season: int = 2026
    my_team_id: int
    partner_team_id: int
    give_ids: list[int]
    receive_ids: list[int]
    num_teams: int = 10


@router.post("/inseason/trade-eval")
def inseason_trade_eval(body: TradeEvalRequest):
    """Evaluate a proposed trade between two teams."""
    return evaluate_trade(
        body.league_id, body.season, body.my_team_id,
        body.partner_team_id, body.give_ids, body.receive_ids, body.num_teams
    )


@router.get("/inseason/trade-finder")
def inseason_trade_finder(
    league_id: str = Query(...),
    season: int = Query(2026),
    my_team_id: int = Query(...),
    num_teams: int = Query(10),
    limit: int = Query(20, ge=1, le=50),
):
    """Auto-discover positive-sum trade opportunities."""
    return {"trades": find_trades(league_id, season, my_team_id, num_teams, limit)}


@router.get("/inseason/matchup")
def inseason_matchup(
    league_id: str = Query(...),
    season: int = Query(2026),
    matchup_period: int = Query(...),
    my_team_id: int = Query(...),
):
    """Analyze the current week's H2H matchup."""
    return analyze_matchup(league_id, season, matchup_period, my_team_id)


@router.get("/inseason/strategy")
def inseason_strategy(
    league_id: str = Query(...),
    season: int = Query(2026),
    my_team_id: int = Query(...),
    num_teams: int = Query(10),
    playoff_spots: int = Query(6),
):
    """Get season-long category strategy analysis."""
    return get_season_strategy(league_id, season, my_team_id, num_teams, playoff_spots)


class StoreMatchupRequest(BaseModel):
    league_external_id: str
    season: int
    matchup_period: int
    home_team_id: int
    away_team_id: int
    home_scores: dict[str, float] = {}
    away_scores: dict[str, float] = {}


@router.post("/inseason/store-matchup")
def store_matchup(body: StoreMatchupRequest):
    """Store matchup data from ESPN (called by Next.js inseason-sync route)."""
    conn = get_connection()
    conn.execute(
        """INSERT INTO matchups (league_external_id, season, matchup_period, home_team_id, away_team_id)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT (league_external_id, season, matchup_period, home_team_id) DO UPDATE SET
             away_team_id = EXCLUDED.away_team_id""",
        (body.league_external_id, body.season, body.matchup_period,
         body.home_team_id, body.away_team_id),
    )
    # Get the matchup ID
    matchup = conn.execute(
        """SELECT id FROM matchups
           WHERE league_external_id = ? AND season = ? AND matchup_period = ? AND home_team_id = ?""",
        (body.league_external_id, body.season, body.matchup_period, body.home_team_id),
    ).fetchone()
    if matchup:
        mid = matchup["id"]
        for cat, val in body.home_scores.items():
            conn.execute(
                """INSERT INTO matchup_category_scores (matchup_id, team_id, category, value)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT (matchup_id, team_id, category) DO UPDATE SET value = EXCLUDED.value""",
                (mid, body.home_team_id, cat, val),
            )
        for cat, val in body.away_scores.items():
            conn.execute(
                """INSERT INTO matchup_category_scores (matchup_id, team_id, category, value)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT (matchup_id, team_id, category) DO UPDATE SET value = EXCLUDED.value""",
                (mid, body.away_team_id, cat, val),
            )
    conn.commit()
    conn.close()
    return {"ok": True}


class StoreOwnershipRequest(BaseModel):
    espn_player_id: int
    league_external_id: str
    season: int
    owner_team_id: int
    roster_status: str = "ROSTERED"
    lineup_slot: Optional[str] = None


@router.post("/inseason/store-ownership")
def store_ownership(body: StoreOwnershipRequest):
    """Store player ownership data from ESPN (called by Next.js inseason-sync route).

    Maps ESPN player ID to our mlb_id via the players table.
    """
    conn = get_connection()
    # ESPN player IDs map to mlb_id in our system
    # Try direct match first (ESPN IDs often ARE MLB IDs for recent players)
    player = conn.execute(
        "SELECT mlb_id FROM players WHERE mlb_id = ?", (body.espn_player_id,)
    ).fetchone()

    if player:
        conn.execute(
            """INSERT INTO player_ownership (mlb_id, league_external_id, season, owner_team_id, roster_status, lineup_slot)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT (mlb_id, league_external_id, season) DO UPDATE SET
                 owner_team_id = EXCLUDED.owner_team_id,
                 roster_status = EXCLUDED.roster_status,
                 lineup_slot = EXCLUDED.lineup_slot""",
            (player["mlb_id"], body.league_external_id, body.season,
             body.owner_team_id, body.roster_status, body.lineup_slot),
        )
    conn.commit()
    conn.close()
    return {"ok": True}


class StoreStandingsRequest(BaseModel):
    league_external_id: str
    season: int
    team_id: int
    category_values: dict[str, float] = {}


# ESPN stat IDs to our stat column mapping
_ESPN_STAT_TO_COLUMN = {
    "R": "stat_r", "TB": "stat_tb", "RBI": "stat_rbi", "SB": "stat_sb",
    "K": "stat_k", "QS": "stat_qs", "SVHD": "stat_svhd",
}


@router.post("/inseason/store-standings")
def store_standings(body: StoreStandingsRequest):
    """Store team season stats from ESPN standings (called by Next.js inseason-sync route)."""
    conn = get_connection()

    # Extract category values from ESPN's valuesByStat format
    vals = body.category_values
    stat_r = int(vals.get("R", vals.get("20", 0)))
    stat_tb = int(vals.get("TB", vals.get("12", 0)))
    stat_rbi = int(vals.get("RBI", vals.get("13", 0)))
    stat_sb = int(vals.get("SB", vals.get("16", 0)))
    stat_k = int(vals.get("K", vals.get("48", 0)))
    stat_qs = int(vals.get("QS", vals.get("63", 0)))
    stat_svhd = int(vals.get("SVHD", 0))
    if stat_svhd == 0:
        stat_svhd = int(vals.get("57", 0)) + int(vals.get("60", 0))  # SV + HLD

    conn.execute(
        """INSERT INTO team_season_stats
           (league_external_id, season, team_id,
            stat_r, stat_tb, stat_rbi, stat_sb, stat_k, stat_qs, stat_svhd)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (league_external_id, season, team_id) DO UPDATE SET
             stat_r = EXCLUDED.stat_r, stat_tb = EXCLUDED.stat_tb,
             stat_rbi = EXCLUDED.stat_rbi, stat_sb = EXCLUDED.stat_sb,
             stat_k = EXCLUDED.stat_k, stat_qs = EXCLUDED.stat_qs,
             stat_svhd = EXCLUDED.stat_svhd""",
        (body.league_external_id, body.season, body.team_id,
         stat_r, stat_tb, stat_rbi, stat_sb, stat_k, stat_qs, stat_svhd),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


@router.get("/inseason/signals")
def inseason_signals(
    league_id: str = Query(...),
    season: int = Query(2026),
    my_team_id: int = Query(...),
    num_teams: int = Query(10),
    limit: int = Query(30, ge=1, le=100),
):
    """Detect roster-relevant signals (drop candidates, add targets, etc.)."""
    return {"signals": get_roster_signals(league_id, season, my_team_id, num_teams, limit)}
