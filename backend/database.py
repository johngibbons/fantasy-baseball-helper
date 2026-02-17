import os
import re

import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://localhost:5432/fantasy_baseball",
)


class _CursorWrapper:
    """Thin wrapper around a psycopg2 RealDictCursor that handles
    None-description cases (INSERT/UPDATE with no RETURNING)."""

    def __init__(self, cursor):
        self._cursor = cursor

    def fetchall(self):
        if self._cursor.description is None:
            return []
        return self._cursor.fetchall()

    def fetchone(self):
        if self._cursor.description is None:
            return None
        return self._cursor.fetchone()


class ConnectionWrapper:
    """Wraps a psycopg2 connection to preserve the conn.execute().fetchall() API
    used throughout the codebase, and auto-converts ? → %s placeholders."""

    def __init__(self, conn):
        self._conn = conn

    @staticmethod
    def _convert_placeholders(sql):
        """Convert sqlite-style ? placeholders to psycopg2-style %s.
        Also escapes literal % signs (e.g. in LIKE '%foo%') so psycopg2
        doesn't interpret them as format specifiers."""
        sql = sql.replace('%', '%%')
        return re.sub(r'\?', '%s', sql)

    def execute(self, sql, params=None):
        sql = self._convert_placeholders(sql)
        cursor = self._conn.cursor()
        cursor.execute(sql, params)
        return _CursorWrapper(cursor)

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


def get_connection() -> ConnectionWrapper:
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    return ConnectionWrapper(conn)


def init_db():
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS players (
            mlb_id INTEGER PRIMARY KEY,
            full_name TEXT NOT NULL,
            first_name TEXT,
            last_name TEXT,
            primary_position TEXT,
            team TEXT,
            team_id INTEGER,
            bats TEXT,
            throws TEXT,
            birth_date TEXT,
            player_type TEXT CHECK(player_type IN ('hitter', 'pitcher')),
            is_active INTEGER DEFAULT 1,
            eligible_positions TEXT,
            updated_at TIMESTAMP DEFAULT NOW()
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS batting_stats (
            id SERIAL PRIMARY KEY,
            mlb_id INTEGER NOT NULL,
            season INTEGER NOT NULL,
            games INTEGER DEFAULT 0,
            plate_appearances INTEGER DEFAULT 0,
            at_bats INTEGER DEFAULT 0,
            runs INTEGER DEFAULT 0,
            hits INTEGER DEFAULT 0,
            doubles INTEGER DEFAULT 0,
            triples INTEGER DEFAULT 0,
            home_runs INTEGER DEFAULT 0,
            rbi INTEGER DEFAULT 0,
            stolen_bases INTEGER DEFAULT 0,
            caught_stealing INTEGER DEFAULT 0,
            walks INTEGER DEFAULT 0,
            strikeouts INTEGER DEFAULT 0,
            hit_by_pitch INTEGER DEFAULT 0,
            sac_flies INTEGER DEFAULT 0,
            batting_average REAL DEFAULT 0,
            obp REAL DEFAULT 0,
            slg REAL DEFAULT 0,
            ops REAL DEFAULT 0,
            total_bases INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT NOW(),
            FOREIGN KEY (mlb_id) REFERENCES players(mlb_id),
            UNIQUE(mlb_id, season)
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pitching_stats (
            id SERIAL PRIMARY KEY,
            mlb_id INTEGER NOT NULL,
            season INTEGER NOT NULL,
            games INTEGER DEFAULT 0,
            games_started INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            era REAL DEFAULT 0,
            whip REAL DEFAULT 0,
            innings_pitched REAL DEFAULT 0,
            hits_allowed INTEGER DEFAULT 0,
            runs_allowed INTEGER DEFAULT 0,
            earned_runs INTEGER DEFAULT 0,
            walks_allowed INTEGER DEFAULT 0,
            strikeouts INTEGER DEFAULT 0,
            home_runs_allowed INTEGER DEFAULT 0,
            saves INTEGER DEFAULT 0,
            holds INTEGER DEFAULT 0,
            quality_starts INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT NOW(),
            FOREIGN KEY (mlb_id) REFERENCES players(mlb_id),
            UNIQUE(mlb_id, season)
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS projections (
            id SERIAL PRIMARY KEY,
            mlb_id INTEGER NOT NULL,
            source TEXT NOT NULL DEFAULT 'steamer',
            season INTEGER NOT NULL,
            player_type TEXT CHECK(player_type IN ('hitter', 'pitcher')),
            -- Hitting projections
            proj_pa INTEGER DEFAULT 0,
            proj_runs INTEGER DEFAULT 0,
            proj_hits INTEGER DEFAULT 0,
            proj_doubles INTEGER DEFAULT 0,
            proj_triples INTEGER DEFAULT 0,
            proj_home_runs INTEGER DEFAULT 0,
            proj_rbi INTEGER DEFAULT 0,
            proj_stolen_bases INTEGER DEFAULT 0,
            proj_walks INTEGER DEFAULT 0,
            proj_strikeouts INTEGER DEFAULT 0,
            proj_hbp INTEGER DEFAULT 0,
            proj_sac_flies INTEGER DEFAULT 0,
            proj_at_bats INTEGER DEFAULT 0,
            proj_obp REAL DEFAULT 0,
            proj_total_bases INTEGER DEFAULT 0,
            -- Pitching projections
            proj_ip REAL DEFAULT 0,
            proj_pitcher_strikeouts INTEGER DEFAULT 0,
            proj_quality_starts INTEGER DEFAULT 0,
            proj_era REAL DEFAULT 0,
            proj_whip REAL DEFAULT 0,
            proj_saves INTEGER DEFAULT 0,
            proj_holds INTEGER DEFAULT 0,
            proj_wins INTEGER DEFAULT 0,
            proj_hits_allowed INTEGER DEFAULT 0,
            proj_walks_allowed INTEGER DEFAULT 0,
            proj_earned_runs INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT NOW(),
            FOREIGN KEY (mlb_id) REFERENCES players(mlb_id),
            UNIQUE(mlb_id, source, season)
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rankings (
            id SERIAL PRIMARY KEY,
            mlb_id INTEGER NOT NULL,
            season INTEGER NOT NULL,
            overall_rank INTEGER,
            position_rank INTEGER,
            total_zscore REAL DEFAULT 0,
            zscore_r REAL DEFAULT 0,
            zscore_tb REAL DEFAULT 0,
            zscore_rbi REAL DEFAULT 0,
            zscore_sb REAL DEFAULT 0,
            zscore_obp REAL DEFAULT 0,
            zscore_k REAL DEFAULT 0,
            zscore_qs REAL DEFAULT 0,
            zscore_era REAL DEFAULT 0,
            zscore_whip REAL DEFAULT 0,
            zscore_svhd REAL DEFAULT 0,
            espn_adp REAL,
            adp_diff REAL,
            player_type TEXT CHECK(player_type IN ('hitter', 'pitcher')),
            updated_at TIMESTAMP DEFAULT NOW(),
            FOREIGN KEY (mlb_id) REFERENCES players(mlb_id),
            UNIQUE(mlb_id, season)
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS statcast_batting (
            mlb_id INTEGER NOT NULL,
            season INTEGER NOT NULL,
            xwoba REAL, xba REAL, xslg REAL,
            barrel_pct REAL, hard_hit_pct REAL,
            avg_exit_velocity REAL, max_exit_velocity REAL,
            sprint_speed REAL, sweet_spot_pct REAL,
            launch_angle REAL, woba REAL,
            updated_at TIMESTAMP DEFAULT NOW(),
            PRIMARY KEY (mlb_id, season),
            FOREIGN KEY (mlb_id) REFERENCES players(mlb_id)
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS statcast_pitching (
            mlb_id INTEGER NOT NULL,
            season INTEGER NOT NULL,
            xera REAL, xwoba_against REAL, xba_against REAL,
            barrel_pct_against REAL, hard_hit_pct_against REAL,
            whiff_pct REAL, k_pct REAL, bb_pct REAL,
            avg_exit_velocity_against REAL, chase_rate REAL,
            csw_pct REAL,
            updated_at TIMESTAMP DEFAULT NOW(),
            PRIMARY KEY (mlb_id, season),
            FOREIGN KEY (mlb_id) REFERENCES players(mlb_id)
        );
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_batting_stats_season ON batting_stats(season);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pitching_stats_season ON pitching_stats(season);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_projections_season ON projections(season);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_rankings_season ON rankings(season);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_players_position ON players(primary_position);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_players_type ON players(player_type);")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS league_season_totals (
            id SERIAL PRIMARY KEY,
            season INTEGER NOT NULL,
            team_name TEXT NOT NULL,
            team_r INTEGER DEFAULT 0,
            team_tb INTEGER DEFAULT 0,
            team_rbi INTEGER DEFAULT 0,
            team_sb INTEGER DEFAULT 0,
            team_obp REAL DEFAULT 0,
            team_k INTEGER DEFAULT 0,
            team_qs INTEGER DEFAULT 0,
            team_era REAL DEFAULT 0,
            team_whip REAL DEFAULT 0,
            team_svhd INTEGER DEFAULT 0,
            UNIQUE(season, team_name)
        );
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_statcast_batting_season ON statcast_batting(season);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_statcast_pitching_season ON statcast_pitching(season);")

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Database initialized (PostgreSQL: {DATABASE_URL})")
