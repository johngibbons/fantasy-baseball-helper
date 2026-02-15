import sqlite3
import os
from pathlib import Path

DB_PATH = Path(__file__).parent / "fantasy_baseball.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_connection()
    conn.executescript("""
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
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS batting_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (mlb_id) REFERENCES players(mlb_id),
            UNIQUE(mlb_id, season)
        );

        CREATE TABLE IF NOT EXISTS pitching_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (mlb_id) REFERENCES players(mlb_id),
            UNIQUE(mlb_id, season)
        );

        CREATE TABLE IF NOT EXISTS projections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (mlb_id) REFERENCES players(mlb_id),
            UNIQUE(mlb_id, source, season)
        );

        CREATE TABLE IF NOT EXISTS rankings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (mlb_id) REFERENCES players(mlb_id),
            UNIQUE(mlb_id, season)
        );

        CREATE TABLE IF NOT EXISTS statcast_batting (
            mlb_id INTEGER NOT NULL,
            season INTEGER NOT NULL,
            xwoba REAL, xba REAL, xslg REAL,
            barrel_pct REAL, hard_hit_pct REAL,
            avg_exit_velocity REAL, max_exit_velocity REAL,
            sprint_speed REAL, sweet_spot_pct REAL,
            launch_angle REAL, woba REAL,
            updated_at TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (mlb_id, season),
            FOREIGN KEY (mlb_id) REFERENCES players(mlb_id)
        );

        CREATE TABLE IF NOT EXISTS statcast_pitching (
            mlb_id INTEGER NOT NULL,
            season INTEGER NOT NULL,
            xera REAL, xwoba_against REAL, xba_against REAL,
            barrel_pct_against REAL, hard_hit_pct_against REAL,
            whiff_pct REAL, k_pct REAL, bb_pct REAL,
            avg_exit_velocity_against REAL, chase_rate REAL,
            csw_pct REAL,
            updated_at TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (mlb_id, season),
            FOREIGN KEY (mlb_id) REFERENCES players(mlb_id)
        );

        CREATE INDEX IF NOT EXISTS idx_batting_stats_season ON batting_stats(season);
        CREATE INDEX IF NOT EXISTS idx_pitching_stats_season ON pitching_stats(season);
        CREATE INDEX IF NOT EXISTS idx_projections_season ON projections(season);
        CREATE INDEX IF NOT EXISTS idx_rankings_season ON rankings(season);
        CREATE INDEX IF NOT EXISTS idx_players_position ON players(primary_position);
        CREATE INDEX IF NOT EXISTS idx_players_type ON players(player_type);
        CREATE TABLE IF NOT EXISTS league_season_totals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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

        CREATE INDEX IF NOT EXISTS idx_statcast_batting_season ON statcast_batting(season);
        CREATE INDEX IF NOT EXISTS idx_statcast_pitching_season ON statcast_pitching(season);
    """)
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")
