"""Schema smoke tests for new breakout-finder tables."""

from backend.database import init_db, get_connection, _USE_PG


def _get_columns(table_name: str) -> set[str]:
    """Return the set of column names for *table_name*, works for both SQLite and Postgres."""
    conn = get_connection()
    try:
        if _USE_PG:
            rows = conn.execute(
                """SELECT column_name FROM information_schema.columns
                   WHERE table_schema = 'analytics' AND table_name = ?""",
                (table_name,),
            ).fetchall()
            return {row["column_name"] for row in rows}
        else:
            rows = conn.execute(
                f"PRAGMA table_info('{table_name}')"
            ).fetchall()
            return {row["name"] for row in rows}
    finally:
        conn.close()


def test_rolling_batting_stats_table_exists():
    init_db()
    cols = _get_columns("rolling_batting_stats")
    assert {"mlb_id", "season", "window_days", "as_of_date",
            "pa", "r", "tb", "rbi", "sb", "obp"}.issubset(cols)


def test_rolling_pitching_stats_table_exists():
    init_db()
    cols = _get_columns("rolling_pitching_stats")
    assert {"mlb_id", "season", "window_days", "as_of_date",
            "ip", "k", "era", "whip", "quality_starts"}.issubset(cols)


def test_statcast_baselines_table_exists():
    init_db()
    cols = _get_columns("statcast_baselines")
    assert {"mlb_id", "season", "player_type",
            "delta_xwoba", "delta_barrel_pct", "delta_xera", "delta_whiff_pct",
            "skill_change_zscore", "sustainability_score", "baseline_source"}.issubset(cols)
