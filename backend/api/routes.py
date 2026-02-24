"""API route definitions."""

import difflib
import json
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
from backend.database import get_connection

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
