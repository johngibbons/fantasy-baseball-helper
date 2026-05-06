"""Schema smoke tests for new breakout-finder tables."""

from backend.database import init_db, get_connection


def test_rolling_batting_stats_table_exists():
    init_db()
    conn = get_connection()
    cols = {row["column_name"] for row in conn.execute(
        """SELECT column_name FROM information_schema.columns
           WHERE table_schema = 'analytics' AND table_name = 'rolling_batting_stats'"""
    ).fetchall()}
    conn.close()
    assert {"mlb_id", "season", "window_days", "as_of_date",
            "pa", "r", "tb", "rbi", "sb", "obp"}.issubset(cols)


def test_rolling_pitching_stats_table_exists():
    init_db()
    conn = get_connection()
    cols = {row["column_name"] for row in conn.execute(
        """SELECT column_name FROM information_schema.columns
           WHERE table_schema = 'analytics' AND table_name = 'rolling_pitching_stats'"""
    ).fetchall()}
    conn.close()
    assert {"mlb_id", "season", "window_days", "as_of_date",
            "ip", "k", "era", "whip", "quality_starts"}.issubset(cols)


def test_statcast_baselines_table_exists():
    init_db()
    conn = get_connection()
    cols = {row["column_name"] for row in conn.execute(
        """SELECT column_name FROM information_schema.columns
           WHERE table_schema = 'analytics' AND table_name = 'statcast_baselines'"""
    ).fetchall()}
    conn.close()
    assert {"mlb_id", "season", "player_type",
            "delta_xwoba", "delta_barrel_pct", "delta_xera", "delta_whiff_pct",
            "skill_change_zscore", "sustainability_score", "baseline_source"}.issubset(cols)
