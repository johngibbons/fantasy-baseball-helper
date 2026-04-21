"""API route definitions."""

import difflib
import json
import logging
import unicodedata

logger = logging.getLogger(__name__)
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
from typing import Any, Optional
from backend.analysis.rankings import (
    get_rankings,
    get_player_detail,
    get_adp_comparison,
    get_position_summary,
)
from backend.analysis.waivers import (
    compute_waiver_recommendations,
    resolve_espn_names_to_mlbid,
)
from backend.analysis.trades import compute_trade_suggestions
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
    limit: int = Query(300, ge=1, le=10000),
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
    limit: int = Query(300, ge=1, le=10000),
    offset: int = Query(0, ge=0),
):
    """Ranked player list with filters."""
    players = get_rankings(season, player_type, position, limit, offset)

    if sort_by and sort_by.startswith("zscore_"):
        players.sort(key=lambda p: p.get(sort_by, 0) or 0, reverse=True)

    return {"rankings": players, "total": len(players)}


@router.get("/rankings/comparison")
def rankings_comparison(season: int = Query(2026)):
    """Compute THE BAT X rankings ephemerally for side-by-side comparison with ATC."""
    results = calculate_all_zscores(season=season, source="thebatx", save_to_db=False)
    return {
        "comparison": {
            p["mlb_id"]: {"rank": p["overall_rank"], "value": round(p["total_zscore"], 2)}
            for p in results
        }
    }


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
                  r.player_type, r.espn_adp, r.adp_diff, r.fangraphs_adp,
                  p.full_name, p.primary_position, p.team, p.eligible_positions
           FROM rankings r
           JOIN players p ON r.mlb_id = p.mlb_id
           WHERE r.season = ?
           ORDER BY r.overall_rank ASC""",
        (season,),
    ).fetchall()
    conn.close()

    players = []
    for r in rows:
        p = dict(r)
        espn = p.get("espn_adp")
        nfbc = p.get("fangraphs_adp")
        if espn is not None and nfbc is not None:
            p["blended_adp"] = 0.65 * espn + 0.35 * nfbc
        else:
            p["blended_adp"] = espn if espn is not None else nfbc
        players.append(p)

    return {"players": players, "total": len(players)}


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


@router.post("/draft/reseed")
def force_reseed_draft(season: int = Query(2026)):
    """Force reseed the draft state from server-side KEEPERS config."""
    from backend.data.seed_draft_order import seed_draft_state
    state = seed_draft_state(force=True)
    if state:
        return {
            "ok": True,
            "keepers": len(state.get("keeperMlbIds", [])),
            "schedule": len(state.get("pickSchedule", [])),
        }
    return {"ok": False, "error": "seed_draft_state returned None"}


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


# ── Diagnostics ──


@router.get("/debug/player/{mlb_id}")
def debug_player(mlb_id: int, season: int = Query(2026)):
    """Diagnose why a player might be missing from rankings."""
    conn = get_connection()
    player = conn.execute(
        "SELECT * FROM players WHERE mlb_id = ?", (mlb_id,)
    ).fetchone()
    projections = conn.execute(
        "SELECT source, player_type, proj_pa, proj_ip FROM projections "
        "WHERE mlb_id = ? AND season = ?", (mlb_id, season)
    ).fetchall()
    ranking = conn.execute(
        "SELECT overall_rank, total_zscore, player_type FROM rankings "
        "WHERE mlb_id = ? AND season = ?", (mlb_id, season)
    ).fetchone()
    conn.close()
    return {
        "mlb_id": mlb_id,
        "player": dict(player) if player else None,
        "projections": [dict(p) for p in projections],
        "ranking": dict(ranking) if ranking else None,
    }


# ── Projection refresh ──


@router.post("/projections/refresh")
def refresh_projections(season: int = Query(2026)):
    """Fetch latest projections from FanGraphs API and recalculate rankings.

    Replaces the need to manually download and import CSV files.
    """
    import logging
    import traceback
    from backend.data.projections import fetch_all_fangraphs_projections, import_adp_from_api, import_espn_adp
    from backend.data.sync import import_csv_projections

    logger = logging.getLogger(__name__)

    try:
        results = fetch_all_fangraphs_projections(season)
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"FanGraphs API error: {e}\n{tb}")
        raise HTTPException(status_code=502, detail=f"FanGraphs API error: {e}")

    adp_map = results.pop("_adp_map", {})
    total = sum(results.values())
    if total == 0:
        raise HTTPException(status_code=502, detail="FanGraphs API returned no projection data")

    # Supplement with CSV projections (Steamer, ZiPS, THE BAT X) which
    # include prospects that ATC may not cover
    try:
        import_csv_projections(season)
    except Exception as e:
        logger.warning(f"CSV projection supplement failed (non-fatal): {e}")

    try:
        calculate_all_zscores(season)
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"Ranking recalculation failed: {e}\n{tb}")
        raise HTTPException(status_code=500, detail=f"Ranking recalculation failed: {e}")

    # Apply ADP after rankings exist
    adp_updated = 0
    if adp_map:
        try:
            adp_updated = import_adp_from_api(adp_map, season)
        except Exception as e:
            logger.warning(f"ADP import failed (non-fatal): {e}")

    # ESPN ADP overwrites FanGraphs ADP (ESPN is authoritative for our league)
    espn_adp_updated = 0
    try:
        espn_adp_updated = import_espn_adp(season)
        logger.info(f"Imported ESPN ADP for {espn_adp_updated} players")
    except Exception as e:
        logger.warning(f"ESPN ADP import failed (non-fatal): {e}")

    total_adp = espn_adp_updated or adp_updated
    sources_used = sorted(k for k, v in results.items() if v > 0)
    return {
        "ok": True,
        "projections_imported": results,
        "total_players": total,
        "adp_updated": total_adp,
        "sources": sources_used,
        "message": f"Fetched {total} projections + {total_adp} ADP values (ESPN)",
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
    # exact normalized name -> player row (best-ranked wins ties)
    exact_lookup: dict[str, dict] = {}
    all_names: list[str] = []
    name_to_player: dict[str, dict] = {}
    for p in db_players:
        norm = _normalize_name(p["full_name"])
        if norm in exact_lookup:
            # Name collision — keep the player with the better ranking
            existing = exact_lookup[norm]
            existing_rank = existing.get("overall_rank") or 999999
            new_rank = p.get("overall_rank") or 999999
            if new_rank < existing_rank:
                exact_lookup[norm] = p
        else:
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


# ── Waiver Wire Recommendations ──


class WaiverRosterPlayer(BaseModel):
    mlb_id: Optional[int] = None
    name: str
    lineup_slot_id: int = 0
    player_type: Optional[str] = None  # 'hitter' or 'pitcher' from ESPN for disambiguation


class WaiverTeamRoster(BaseModel):
    players: list[WaiverRosterPlayer]


class WaiverRequest(BaseModel):
    my_roster: list[WaiverRosterPlayer]
    other_team_rosters: list[WaiverTeamRoster]
    free_agents: list[WaiverRosterPlayer]
    remaining_faab: float = 100.0
    season: int = 2026
    open_roster_slots: int = 0


@router.post("/waivers/recommendations")
def waiver_recommendations(req: WaiverRequest):
    """Compute waiver wire recommendations ranked by expected wins improvement."""
    # Resolve ESPN names to mlb_ids
    all_espn_players = (
        [{"name": p.name, "player_type": p.player_type} for p in req.my_roster]
        + [{"name": p.name, "player_type": p.player_type} for team in req.other_team_rosters for p in team.players]
        + [{"name": p.name, "player_type": p.player_type} for p in req.free_agents]
    )
    name_to_id = resolve_espn_names_to_mlbid(all_espn_players, season=req.season)

    # Build resolved ID lists
    my_roster_ids = []
    my_roster_slots = []
    for p in req.my_roster:
        mid = p.mlb_id or name_to_id.get(p.name)
        if mid:
            my_roster_ids.append(mid)
            my_roster_slots.append({"mlb_id": mid, "lineup_slot_id": p.lineup_slot_id})

    other_team_rosters = []
    for team in req.other_team_rosters:
        team_slots = []
        for p in team.players:
            mid = p.mlb_id or name_to_id.get(p.name)
            if mid:
                team_slots.append({"mlb_id": mid, "lineup_slot_id": p.lineup_slot_id})
        other_team_rosters.append(team_slots)

    fa_ids = []
    for p in req.free_agents:
        mid = p.mlb_id or name_to_id.get(p.name)
        if mid:
            fa_ids.append(mid)

    # Log unresolved roster players for debugging
    unresolved_roster = [p.name for p in req.my_roster if not (p.mlb_id or name_to_id.get(p.name))]
    logger.info(
        f"Waiver resolution: {len(my_roster_ids)}/{len(req.my_roster)} roster, "
        f"{len(fa_ids)}/{len(req.free_agents)} FAs, "
        f"{len(name_to_id)} total names resolved"
    )
    if unresolved_roster:
        logger.warning(f"Unresolved roster players: {unresolved_roster}")
    if not my_roster_ids:
        sample_names = [p.name for p in req.my_roster[:5]]
        raise HTTPException(
            status_code=400,
            detail=f"No roster players could be resolved. Sample names: {sample_names}",
        )
    if not fa_ids:
        sample_names = [p.name for p in req.free_agents[:5]]
        raise HTTPException(
            status_code=400,
            detail=f"No free agents could be resolved. Sample names: {sample_names}",
        )

    # Pass name→mlb_id mapping so frontend can link roster players
    result_name_to_id = name_to_id

    result = compute_waiver_recommendations(
        my_roster_ids=my_roster_ids,
        my_roster_slots=my_roster_slots,
        all_team_roster_slots=other_team_rosters,
        free_agent_ids=fa_ids,
        season=req.season,
        remaining_faab=req.remaining_faab,
        open_roster_slots=req.open_roster_slots,
    )
    # Collect lineup slot distribution for diagnostics
    my_slot_ids = [p.lineup_slot_id for p in req.my_roster]
    other_slot_samples = [
        [p.lineup_slot_id for p in team.players]
        for team in req.other_team_rosters[:2]  # first 2 teams
    ]
    result["name_to_mlb_id"] = result_name_to_id
    result["diagnostics"] = {
        "roster_resolved": len(my_roster_ids),
        "roster_total": len(req.my_roster),
        "fa_resolved": len(fa_ids),
        "fa_total": len(req.free_agents),
        "unresolved_roster": unresolved_roster[:10],
        "roster_names_sent": [p.name for p in req.my_roster[:5]],
        "my_lineup_slot_ids": my_slot_ids,
        "other_team_slot_samples": other_slot_samples,
    }
    return result


# ── Matchup Projections ──


class MatchupRosterPlayer(BaseModel):
    mlb_id: Optional[int] = None
    name: str
    position: str = ""
    player_type: Optional[str] = None
    lineup_slot_id: int = 0
    mlb_team: str = ""
    injury_status: str = "ACTIVE"
    eligible_positions: str = ""


class MatchupActuals(BaseModel):
    my: dict[str, float] = {}
    opponent: dict[str, float] = {}


class MatchupRequest(BaseModel):
    my_roster: list[MatchupRosterPlayer]
    opponent_roster: list[MatchupRosterPlayer]
    actuals: MatchupActuals
    team_games_remaining: dict[str, int] = {}
    probable_pitcher_ids: dict[str, list[int]] = {}  # deprecated, kept for compat
    espn_pp_starts_by_name: dict[str, int] = {}  # pitcher name → PP start count
    remaining_season_games: dict[str, int] = {}
    days_remaining: int = 0
    remaining_dates: list[str] = []
    season: int = 2026


@router.post("/matchup/projections")
def matchup_projections(req: MatchupRequest):
    """Compute projected matchup category finals and win/loss outcome."""
    from backend.analysis.matchup import compute_matchup_projections

    # Resolve ESPN names to mlb_ids
    all_espn_players = (
        [{"name": p.name, "player_type": p.player_type} for p in req.my_roster]
        + [{"name": p.name, "player_type": p.player_type} for p in req.opponent_roster]
    )
    name_to_id = resolve_espn_names_to_mlbid(all_espn_players, season=req.season)

    def _resolve_roster(players: list[MatchupRosterPlayer]) -> list[dict]:
        resolved = []
        for p in players:
            mid = p.mlb_id or name_to_id.get(p.name)
            if mid:
                resolved.append({
                    "mlb_id": mid,
                    "name": p.name,
                    "position": p.position,
                    "player_type": p.player_type,
                    "lineup_slot_id": p.lineup_slot_id,
                    "mlb_team": p.mlb_team,
                    "injury_status": p.injury_status,
                    "eligible_positions": p.eligible_positions,
                })
        return resolved

    my_resolved = _resolve_roster(req.my_roster)
    opp_resolved = _resolve_roster(req.opponent_roster)

    if not my_resolved:
        raise HTTPException(status_code=400, detail="No roster players could be resolved.")

    result = compute_matchup_projections(
        my_roster=my_resolved,
        opponent_roster=opp_resolved,
        actuals=req.actuals.dict(),
        team_games_remaining=req.team_games_remaining,
        probable_pitcher_ids=req.probable_pitcher_ids,
        espn_pp_starts_by_name=req.espn_pp_starts_by_name,
        remaining_season_games=req.remaining_season_games,
        days_remaining=req.days_remaining,
        remaining_dates=req.remaining_dates,
        season=req.season,
    )
    result["name_to_mlb_id"] = name_to_id
    return result


# ── Trade Suggestions ──


class TradeRosterPlayer(BaseModel):
    mlb_id: Optional[int] = None
    name: str
    lineup_slot_id: int = 0
    player_type: Optional[str] = None


class TradeTeamRoster(BaseModel):
    team_id: int
    team_name: str = ""
    players: list[TradeRosterPlayer]


class TradeRequest(BaseModel):
    my_roster: list[TradeRosterPlayer]
    all_team_rosters: list[TradeTeamRoster]
    my_team_index: int
    season: int = 2026
    max_trade_size: int = 2
    fairness_threshold: float = 0.5
    include_draft_picks: bool = False
    max_tradeable_per_team: int = 15


@router.post("/trades/suggestions")
def trade_suggestions(req: TradeRequest):
    """Compute trade suggestions ranked by expected wins improvement for both teams."""
    # Resolve ESPN names to mlb_ids
    all_espn_players = (
        [{"name": p.name, "player_type": p.player_type} for p in req.my_roster]
        + [
            {"name": p.name, "player_type": p.player_type}
            for team in req.all_team_rosters
            for p in team.players
        ]
    )
    name_to_id = resolve_espn_names_to_mlbid(all_espn_players, season=req.season)

    # Build resolved roster structures
    my_roster = []
    for p in req.my_roster:
        mid = p.mlb_id or name_to_id.get(p.name)
        if mid:
            my_roster.append({"mlb_id": mid, "lineup_slot_id": p.lineup_slot_id})

    all_team_rosters = []
    for team in req.all_team_rosters:
        team_players = []
        for p in team.players:
            mid = p.mlb_id or name_to_id.get(p.name)
            if mid:
                team_players.append({"mlb_id": mid, "lineup_slot_id": p.lineup_slot_id})
        all_team_rosters.append({
            "team_id": team.team_id,
            "team_name": team.team_name,
            "players": team_players,
        })

    if not my_roster:
        raise HTTPException(status_code=400, detail="No roster players could be resolved.")

    result = compute_trade_suggestions(
        my_roster=my_roster,
        all_team_rosters=all_team_rosters,
        my_team_index=req.my_team_index,
        season=req.season,
        max_trade_size=req.max_trade_size,
        fairness_threshold=req.fairness_threshold,
        include_draft_picks=req.include_draft_picks,
        max_tradeable_per_team=req.max_tradeable_per_team,
    )
    result["name_to_mlb_id"] = name_to_id
    return result


@router.post("/waivers/refresh-projections")
def refresh_ros_projections(season: int = Query(2026)):
    """Fetch latest ATC RoS DC projections from FanGraphs and recalculate rankings.

    The waiver analysis reads from the rankings table, so we must run the
    full pipeline: fetch projections → recalculate z-scores/rankings.
    """
    import traceback
    from backend.data.projections import fetch_all_fangraphs_projections

    try:
        results = fetch_all_fangraphs_projections(season)
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"FanGraphs API error: {e}\n{tb}")
        raise HTTPException(status_code=502, detail=f"FanGraphs API error: {e}")

    adp_map = results.pop("_adp_map", {})
    total = sum(results.values())
    if total == 0:
        raise HTTPException(status_code=502, detail="FanGraphs API returned no projection data")

    try:
        calculate_all_zscores(season)
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"Ranking recalculation failed: {e}\n{tb}")
        raise HTTPException(status_code=500, detail=f"Ranking recalculation failed: {e}")

    return {"status": "ok", "results": {"batting_and_pitching": total}}


# ── Start/Sit Recommendations ──


class StartSitRequest(BaseModel):
    roster_pitcher_names: list[str]
    opponent_pitcher_names: list[str] = []
    matchup_categories: dict[str, dict[str, float]]
    team_ip: dict[str, float]
    days_remaining: int
    opponent_name: str
    today_date: str
    matchup_end_date: str
    all_rostered_names: list[str] = []
    streaming_target_date: str | None = None
    streaming_end_date: str | None = None
    espn_starts_by_date: dict[str, list[str]] | None = None  # date → pitcher names with ESPN PP tag


@router.post("/start-sit")
def start_sit_recommendations(req: StartSitRequest):
    """Compute start/sit recommendations for today's SP matchups."""
    from backend.analysis.start_sit import compute_start_sit_recommendations

    return compute_start_sit_recommendations(
        roster_pitcher_names=req.roster_pitcher_names,
        opponent_pitcher_names=req.opponent_pitcher_names,
        matchup_categories=req.matchup_categories,
        team_ip=req.team_ip["yours"],
        days_remaining=req.days_remaining,
        opponent_name=req.opponent_name,
        today_date=req.today_date,
        matchup_end_date=req.matchup_end_date,
        all_rostered_names=req.all_rostered_names,
        streaming_target_date=req.streaming_target_date,
        streaming_end_date=req.streaming_end_date,
        espn_starts_by_date=req.espn_starts_by_date,
    )


# ── Next Week Preview ──


class StartSitPreviewRequest(BaseModel):
    roster_pitcher_names: list[str]
    opponent_pitcher_names: list[str] = []
    start_date: str
    end_date: str
    all_rostered_names: list[str] = []


@router.post("/start-sit/preview")
def start_sit_preview(req: StartSitPreviewRequest):
    """Compute next week SP schedule preview."""
    from backend.analysis.start_sit import compute_next_week_preview

    return compute_next_week_preview(
        roster_pitcher_names=req.roster_pitcher_names,
        opponent_pitcher_names=req.opponent_pitcher_names,
        start_date=req.start_date,
        end_date=req.end_date,
        all_rostered_names=req.all_rostered_names,
    )
