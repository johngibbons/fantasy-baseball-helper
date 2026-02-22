"""Rankings module — query and filter player rankings from the database."""

from typing import Optional
from backend.database import get_connection


def get_rankings(
    season: int = 2026,
    player_type: Optional[str] = None,
    position: Optional[str] = None,
    limit: int = 300,
    offset: int = 0,
) -> list[dict]:
    """Get ranked players with z-score breakdowns.

    Args:
        season: Target season
        player_type: 'hitter' or 'pitcher' or None for all
        position: Position filter (e.g., 'SS', 'SP')
        limit: Max results
        offset: Pagination offset
    """
    conn = get_connection()

    query = """
        SELECT r.*, p.full_name, p.primary_position, p.team, p.player_type as ptype,
               p.eligible_positions
        FROM rankings r
        JOIN players p ON r.mlb_id = p.mlb_id
        WHERE r.season = ?
    """
    params: list = [season]

    if player_type:
        query += " AND r.player_type = ?"
        params.append(player_type)

    if position:
        if position == "SP":
            # Pitchers with primary_position 'P' who have QS z-scores are starters
            query += """ AND (p.primary_position = 'SP'
                         OR (p.primary_position = 'P' AND r.zscore_qs IS NOT NULL AND r.zscore_qs != 0)
                         OR (p.eligible_positions LIKE '%SP%'))"""
        elif position == "RP":
            query += """ AND (p.primary_position = 'RP'
                         OR (p.primary_position = 'P' AND (r.zscore_qs IS NULL OR r.zscore_qs = 0)
                             AND r.zscore_svhd IS NOT NULL AND r.zscore_svhd != 0)
                         OR (p.eligible_positions LIKE '%RP%'))"""
        elif position == "OF":
            query += """ AND (p.primary_position IN ('OF', 'LF', 'CF', 'RF')
                         OR p.eligible_positions LIKE '%OF%')"""
        else:
            query += """ AND (p.primary_position = ?
                         OR ('/' || p.eligible_positions || '/') LIKE ?)"""
            params.extend([position, f"%/{position}/%"])

    query += " ORDER BY r.overall_rank ASC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = conn.execute(query, params).fetchall()
    conn.close()

    return [dict(row) for row in rows]


def get_player_detail(mlb_id: int, season: int = 2026) -> Optional[dict]:
    """Get full detail for a single player including rankings, projections, and historical stats."""
    conn = get_connection()

    player = conn.execute(
        "SELECT * FROM players WHERE mlb_id = ?", (mlb_id,)
    ).fetchone()

    if not player:
        conn.close()
        return None

    ranking = conn.execute(
        "SELECT * FROM rankings WHERE mlb_id = ? AND season = ?",
        (mlb_id, season),
    ).fetchone()

    projection = conn.execute(
        "SELECT * FROM projections WHERE mlb_id = ? AND season = ? ORDER BY source ASC LIMIT 1",
        (mlb_id, season),
    ).fetchone()

    # Historical stats (last 3 seasons)
    batting_history = conn.execute(
        "SELECT * FROM batting_stats WHERE mlb_id = ? ORDER BY season DESC LIMIT 3",
        (mlb_id,),
    ).fetchall()

    pitching_history = conn.execute(
        "SELECT * FROM pitching_stats WHERE mlb_id = ? ORDER BY season DESC LIMIT 3",
        (mlb_id,),
    ).fetchall()

    conn.close()

    result = dict(player)
    result["ranking"] = dict(ranking) if ranking else None
    result["projection"] = dict(projection) if projection else None
    result["batting_history"] = [dict(r) for r in batting_history]
    result["pitching_history"] = [dict(r) for r in pitching_history]

    return result


def get_adp_comparison(season: int = 2026, limit: int = 200) -> list[dict]:
    """Get players sorted by value vs ADP (biggest steals/busts).

    Returns players where our ranking differs most from ESPN ADP.
    adp_diff = overall_rank - espn_adp:
      Negative = model ranks better than ADP (potential steal)
      Positive = model ranks worse than ADP (potentially over-drafted)
    """
    conn = get_connection()

    rows = conn.execute(
        """SELECT r.*, p.full_name, p.primary_position, p.team
           FROM rankings r
           JOIN players p ON r.mlb_id = p.mlb_id
           WHERE r.season = ? AND r.espn_adp IS NOT NULL
           ORDER BY r.adp_diff DESC
           LIMIT ?""",
        (season, limit),
    ).fetchall()

    conn.close()
    return [dict(row) for row in rows]


def get_position_summary(season: int = 2026) -> dict:
    """Get top players at each position with their z-scores."""
    conn = get_connection()

    positions = ["C", "1B", "2B", "3B", "SS", "OF", "LF", "CF", "RF", "DH", "SP", "RP"]
    summary = {}

    for pos in positions:
        if pos == "SP":
            pos_clause = """(p.primary_position = 'SP'
                            OR (p.primary_position = 'P' AND r.zscore_qs IS NOT NULL AND r.zscore_qs != 0)
                            OR (p.eligible_positions LIKE '%SP%'))"""
            pos_params: list = [season]
        elif pos == "RP":
            pos_clause = """(p.primary_position = 'RP'
                            OR (p.primary_position = 'P' AND (r.zscore_qs IS NULL OR r.zscore_qs = 0)
                                AND r.zscore_svhd IS NOT NULL AND r.zscore_svhd != 0)
                            OR (p.eligible_positions LIKE '%RP%'))"""
            pos_params = [season]
        elif pos in ("OF", "LF", "CF", "RF"):
            pos_clause = """(p.primary_position IN ('OF', 'LF', 'CF', 'RF')
                            OR p.eligible_positions LIKE '%OF%')"""
            pos_params = [season]
        else:
            pos_clause = """(p.primary_position = ?
                            OR ('/' || p.eligible_positions || '/') LIKE ?)"""
            pos_params = [season, pos, f"%/{pos}/%"]

        rows = conn.execute(
            f"""SELECT r.mlb_id, r.overall_rank, r.total_zscore,
                      p.full_name, p.team
               FROM rankings r
               JOIN players p ON r.mlb_id = p.mlb_id
               WHERE r.season = ? AND {pos_clause}
               ORDER BY r.total_zscore DESC
               LIMIT 10""",
            pos_params,
        ).fetchall()

        if rows:
            summary[pos] = [dict(r) for r in rows]

    conn.close()
    return summary
