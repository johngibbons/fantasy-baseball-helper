"""CLI command to sync data from MLB Stats API and generate projections."""

import asyncio
import logging
import sys
import argparse
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.database import get_connection, init_db
from backend.data.mlb_api import (
    fetch_all_players,
    get_player_info,
    get_batting_stats,
    get_pitching_stats,
)
from backend.data.projections import (
    generate_projections_from_stats,
    import_adp_from_csv,
    import_fangraphs_batting,
    import_fangraphs_pitching,
    fetch_all_fangraphs_projections,
)
from backend.data.statcast import sync_statcast_data
from backend.data.statcast_adjustments import apply_statcast_adjustments
from backend.analysis.zscores import calculate_all_zscores

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def sync_players(season: int = 2025):
    """Fetch all players from MLB team rosters and store in DB."""
    logger.info(f"Fetching all players for {season}...")
    players = await fetch_all_players(season)

    conn = get_connection()
    count = 0
    for p in players:
        conn.execute(
            """INSERT INTO players
               (mlb_id, full_name, primary_position, player_type, team, team_id, is_active)
               VALUES (?, ?, ?, ?, ?, ?, 1)
               ON CONFLICT (mlb_id) DO UPDATE SET
                 full_name = EXCLUDED.full_name,
                 primary_position = EXCLUDED.primary_position,
                 player_type = EXCLUDED.player_type,
                 team = EXCLUDED.team,
                 team_id = EXCLUDED.team_id,
                 is_active = EXCLUDED.is_active""",
            (p["mlb_id"], p["full_name"], p["primary_position"],
             p["player_type"], p.get("team", ""), p.get("team_id")),
        )
        count += 1
    conn.commit()
    conn.close()
    logger.info(f"Synced {count} players")
    return count


async def sync_stats(season: int = 2025, player_type: str = "all"):
    """Fetch season stats for all players in the database."""
    conn = get_connection()

    if player_type in ("all", "hitter"):
        hitters = conn.execute(
            "SELECT mlb_id, full_name FROM players WHERE player_type = 'hitter' AND is_active = 1"
        ).fetchall()
        logger.info(f"Fetching batting stats for {len(hitters)} hitters...")

        for i, h in enumerate(hitters):
            try:
                stats = await get_batting_stats(h["mlb_id"], season)
                if stats:
                    conn.execute(
                        """INSERT INTO batting_stats
                           (mlb_id, season, games, plate_appearances, at_bats,
                            runs, hits, doubles, triples, home_runs,
                            rbi, stolen_bases, caught_stealing, walks, strikeouts,
                            hit_by_pitch, sac_flies, batting_average, obp, slg, ops, total_bases)
                           VALUES (?, ?, ?, ?, ?,
                                   ?, ?, ?, ?, ?,
                                   ?, ?, ?, ?, ?,
                                   ?, ?, ?, ?, ?, ?, ?)
                           ON CONFLICT (mlb_id, season) DO UPDATE SET
                             games = EXCLUDED.games, plate_appearances = EXCLUDED.plate_appearances,
                             at_bats = EXCLUDED.at_bats, runs = EXCLUDED.runs, hits = EXCLUDED.hits,
                             doubles = EXCLUDED.doubles, triples = EXCLUDED.triples,
                             home_runs = EXCLUDED.home_runs, rbi = EXCLUDED.rbi,
                             stolen_bases = EXCLUDED.stolen_bases, caught_stealing = EXCLUDED.caught_stealing,
                             walks = EXCLUDED.walks, strikeouts = EXCLUDED.strikeouts,
                             hit_by_pitch = EXCLUDED.hit_by_pitch, sac_flies = EXCLUDED.sac_flies,
                             batting_average = EXCLUDED.batting_average, obp = EXCLUDED.obp,
                             slg = EXCLUDED.slg, ops = EXCLUDED.ops, total_bases = EXCLUDED.total_bases""",
                        (
                            stats["mlb_id"], stats["season"], stats["games"],
                            stats["plate_appearances"], stats["at_bats"],
                            stats["runs"], stats["hits"], stats["doubles"],
                            stats["triples"], stats["home_runs"],
                            stats["rbi"], stats["stolen_bases"], stats["caught_stealing"],
                            stats["walks"], stats["strikeouts"],
                            stats["hit_by_pitch"], stats["sac_flies"],
                            stats["batting_average"], stats["obp"], stats["slg"],
                            stats["ops"], stats["total_bases"],
                        ),
                    )
                if (i + 1) % 50 == 0:
                    conn.commit()
                    logger.info(f"  Batting: {i + 1}/{len(hitters)}")
            except Exception as e:
                logger.warning(f"Failed to fetch batting stats for {h['full_name']}: {e}")

        conn.commit()
        logger.info(f"Finished batting stats")

    if player_type in ("all", "pitcher"):
        pitchers = conn.execute(
            "SELECT mlb_id, full_name FROM players WHERE player_type = 'pitcher' AND is_active = 1"
        ).fetchall()
        logger.info(f"Fetching pitching stats for {len(pitchers)} pitchers...")

        for i, p in enumerate(pitchers):
            try:
                stats = await get_pitching_stats(p["mlb_id"], season)
                if stats:
                    conn.execute(
                        """INSERT INTO pitching_stats
                           (mlb_id, season, games, games_started, wins, losses,
                            era, whip, innings_pitched, hits_allowed,
                            runs_allowed, earned_runs, walks_allowed, strikeouts,
                            home_runs_allowed, saves, holds, quality_starts)
                           VALUES (?, ?, ?, ?, ?, ?,
                                   ?, ?, ?, ?,
                                   ?, ?, ?, ?,
                                   ?, ?, ?, ?)
                           ON CONFLICT (mlb_id, season) DO UPDATE SET
                             games = EXCLUDED.games, games_started = EXCLUDED.games_started,
                             wins = EXCLUDED.wins, losses = EXCLUDED.losses,
                             era = EXCLUDED.era, whip = EXCLUDED.whip,
                             innings_pitched = EXCLUDED.innings_pitched, hits_allowed = EXCLUDED.hits_allowed,
                             runs_allowed = EXCLUDED.runs_allowed, earned_runs = EXCLUDED.earned_runs,
                             walks_allowed = EXCLUDED.walks_allowed, strikeouts = EXCLUDED.strikeouts,
                             home_runs_allowed = EXCLUDED.home_runs_allowed,
                             saves = EXCLUDED.saves, holds = EXCLUDED.holds,
                             quality_starts = EXCLUDED.quality_starts""",
                        (
                            stats["mlb_id"], stats["season"], stats["games"],
                            stats["games_started"], stats["wins"], stats["losses"],
                            stats["era"], stats["whip"], stats["innings_pitched"],
                            stats["hits_allowed"], stats["runs_allowed"],
                            stats["earned_runs"], stats["walks_allowed"],
                            stats["strikeouts"], stats["home_runs_allowed"],
                            stats["saves"], stats["holds"], stats["quality_starts"],
                        ),
                    )
                if (i + 1) % 50 == 0:
                    conn.commit()
                    logger.info(f"  Pitching: {i + 1}/{len(pitchers)}")
            except Exception as e:
                logger.warning(f"Failed to fetch pitching stats for {p['full_name']}: {e}")

        conn.commit()
        logger.info(f"Finished pitching stats")

    # Two-way players: fetch the "other" stat type for players with dual roles.
    # Hitters with pitching history need pitching stats synced, and pitchers with
    # batting history need batting stats synced.
    if player_type == "all":
        # Find hitters who have pitching stats in other seasons (two-way players)
        twp_hitters = conn.execute(
            """SELECT DISTINCT p.mlb_id, p.full_name FROM players p
               JOIN pitching_stats ps ON p.mlb_id = ps.mlb_id
               WHERE p.player_type = 'hitter' AND p.is_active = 1"""
        ).fetchall()
        if twp_hitters:
            logger.info(f"Fetching pitching stats for {len(twp_hitters)} two-way hitters...")
            for p in twp_hitters:
                try:
                    stats = await get_pitching_stats(p["mlb_id"], season)
                    if stats:
                        conn.execute(
                            """INSERT INTO pitching_stats
                               (mlb_id, season, games, games_started, wins, losses,
                                era, whip, innings_pitched, hits_allowed,
                                runs_allowed, earned_runs, walks_allowed, strikeouts,
                                home_runs_allowed, saves, holds, quality_starts)
                               VALUES (?, ?, ?, ?, ?, ?,
                                       ?, ?, ?, ?,
                                       ?, ?, ?, ?,
                                       ?, ?, ?, ?)
                               ON CONFLICT (mlb_id, season) DO UPDATE SET
                                 games = EXCLUDED.games, games_started = EXCLUDED.games_started,
                                 wins = EXCLUDED.wins, losses = EXCLUDED.losses,
                                 era = EXCLUDED.era, whip = EXCLUDED.whip,
                                 innings_pitched = EXCLUDED.innings_pitched, hits_allowed = EXCLUDED.hits_allowed,
                                 runs_allowed = EXCLUDED.runs_allowed, earned_runs = EXCLUDED.earned_runs,
                                 walks_allowed = EXCLUDED.walks_allowed, strikeouts = EXCLUDED.strikeouts,
                                 home_runs_allowed = EXCLUDED.home_runs_allowed,
                                 saves = EXCLUDED.saves, holds = EXCLUDED.holds,
                                 quality_starts = EXCLUDED.quality_starts""",
                            (
                                stats["mlb_id"], stats["season"], stats["games"],
                                stats["games_started"], stats["wins"], stats["losses"],
                                stats["era"], stats["whip"], stats["innings_pitched"],
                                stats["hits_allowed"], stats["runs_allowed"],
                                stats["earned_runs"], stats["walks_allowed"],
                                stats["strikeouts"], stats["home_runs_allowed"],
                                stats["saves"], stats["holds"], stats["quality_starts"],
                            ),
                        )
                except Exception as e:
                    logger.warning(f"Failed to fetch pitching stats for TWP {p['full_name']}: {e}")
            conn.commit()

        # Find pitchers who have batting stats in other seasons (two-way players)
        twp_pitchers = conn.execute(
            """SELECT DISTINCT p.mlb_id, p.full_name FROM players p
               JOIN batting_stats bs ON p.mlb_id = bs.mlb_id
               WHERE p.player_type = 'pitcher' AND p.is_active = 1"""
        ).fetchall()
        if twp_pitchers:
            logger.info(f"Fetching batting stats for {len(twp_pitchers)} two-way pitchers...")
            for h in twp_pitchers:
                try:
                    stats = await get_batting_stats(h["mlb_id"], season)
                    if stats:
                        conn.execute(
                            """INSERT INTO batting_stats
                               (mlb_id, season, games, plate_appearances, at_bats,
                                runs, hits, doubles, triples, home_runs,
                                rbi, stolen_bases, caught_stealing, walks, strikeouts,
                                hit_by_pitch, sac_flies, batting_average, obp, slg, ops, total_bases)
                               VALUES (?, ?, ?, ?, ?,
                                       ?, ?, ?, ?, ?,
                                       ?, ?, ?, ?, ?,
                                       ?, ?, ?, ?, ?, ?, ?)
                               ON CONFLICT (mlb_id, season) DO UPDATE SET
                                 games = EXCLUDED.games, plate_appearances = EXCLUDED.plate_appearances,
                                 at_bats = EXCLUDED.at_bats, runs = EXCLUDED.runs, hits = EXCLUDED.hits,
                                 doubles = EXCLUDED.doubles, triples = EXCLUDED.triples,
                                 home_runs = EXCLUDED.home_runs, rbi = EXCLUDED.rbi,
                                 stolen_bases = EXCLUDED.stolen_bases, caught_stealing = EXCLUDED.caught_stealing,
                                 walks = EXCLUDED.walks, strikeouts = EXCLUDED.strikeouts,
                                 hit_by_pitch = EXCLUDED.hit_by_pitch, sac_flies = EXCLUDED.sac_flies,
                                 batting_average = EXCLUDED.batting_average, obp = EXCLUDED.obp,
                                 slg = EXCLUDED.slg, ops = EXCLUDED.ops, total_bases = EXCLUDED.total_bases""",
                            (
                                stats["mlb_id"], stats["season"], stats["games"],
                                stats["plate_appearances"], stats["at_bats"],
                                stats["runs"], stats["hits"], stats["doubles"],
                                stats["triples"], stats["home_runs"],
                                stats["rbi"], stats["stolen_bases"], stats["caught_stealing"],
                                stats["walks"], stats["strikeouts"],
                                stats["hit_by_pitch"], stats["sac_flies"],
                                stats["batting_average"], stats["obp"], stats["slg"],
                                stats["ops"], stats["total_bases"],
                            ),
                        )
                except Exception as e:
                    logger.warning(f"Failed to fetch batting stats for TWP {h['full_name']}: {e}")
            conn.commit()

    conn.close()


def import_csv_projections(season: int = 2026):
    """Import FanGraphs CSV projections (steamer, thebatx, zips) if files exist."""
    csv_dir = Path(__file__).parent.parent / "projection_data"
    sources = ["steamer", "thebatx", "zips"]
    count = 0
    for source in sources:
        batting_file = csv_dir / f"{source}_batting_{season}.csv"
        pitching_file = csv_dir / f"{source}_pitching_{season}.csv"
        if batting_file.exists():
            try:
                import_fangraphs_batting(str(batting_file), source, season)
                count += 1
                logger.info(f"Imported {source} batting projections from {batting_file.name}")
            except Exception as e:
                logger.warning(f"Failed to import {batting_file.name}: {e}")
        if pitching_file.exists():
            try:
                import_fangraphs_pitching(str(pitching_file), source, season)
                count += 1
                logger.info(f"Imported {source} pitching projections from {pitching_file.name}")
            except Exception as e:
                logger.warning(f"Failed to import {pitching_file.name}: {e}")
    if count == 0:
        logger.info(f"No CSV projection files found in {csv_dir} for {season}")
    return count


async def run_full_sync(season: int = 2025, stats_seasons: list[int] = None):
    """Run the full data pipeline: players → stats → projections → rankings."""
    init_db()

    # 1. Sync players
    await sync_players(season)

    # 2. Sync stats for requested seasons
    if stats_seasons is None:
        stats_seasons = [season - 1]  # Default: last completed season
    for s in stats_seasons:
        logger.info(f"Syncing stats for {s} season...")
        await sync_stats(s)

    # 3. Sync Statcast data
    logger.info("Syncing Statcast data...")
    for s in stats_seasons:
        try:
            sync_statcast_data(s)
        except Exception as e:
            logger.warning(f"Statcast sync failed for {s} (non-fatal): {e}")

    # 4. Import FanGraphs projections (API first, CSV fallback)
    logger.info("Importing FanGraphs projections...")
    api_results = {}
    try:
        api_results = fetch_all_fangraphs_projections(season)
    except Exception as e:
        logger.warning(f"FanGraphs API fetch failed (non-fatal): {e}")
    if sum(api_results.values()) == 0:
        logger.info("Falling back to CSV projections...")
        import_csv_projections(season)

    # 5. Generate projections from historical stats
    logger.info("Generating trend-based projections...")
    generate_projections_from_stats(season)

    # 6. Apply Statcast adjustments to projections
    logger.info("Applying Statcast adjustments...")
    try:
        apply_statcast_adjustments(season)
    except Exception as e:
        logger.warning(f"Statcast adjustments failed (non-fatal): {e}")

    # 7. Calculate z-scores and rankings
    logger.info("Calculating z-scores and rankings...")
    calculate_all_zscores(season)

    # 8. Import ADP data
    logger.info("Importing ADP data...")
    try:
        import_adp_from_csv(season=season)
    except Exception as e:
        logger.warning(f"ADP import failed (non-fatal): {e}")

    logger.info("Full sync complete!")


def main():
    parser = argparse.ArgumentParser(description="Sync fantasy baseball data")
    parser.add_argument("--season", type=int, default=2025, help="Target season (default: 2025)")
    parser.add_argument(
        "--stats-seasons",
        type=int,
        nargs="+",
        default=None,
        help="Seasons to fetch stats for (default: previous season)",
    )
    parser.add_argument("--players-only", action="store_true", help="Only sync player rosters")
    parser.add_argument("--stats-only", action="store_true", help="Only sync stats")
    parser.add_argument("--statcast-only", action="store_true", help="Only sync Statcast data")
    parser.add_argument("--projections-only", action="store_true", help="Only generate projections")
    parser.add_argument("--rankings-only", action="store_true", help="Only calculate rankings")
    parser.add_argument("--adp-only", action="store_true", help="Only import ADP data from projection CSVs")
    parser.add_argument("--fetch-projections", action="store_true",
                        help="Fetch projections from FanGraphs API (replaces manual CSV download)")

    args = parser.parse_args()

    if args.fetch_projections:
        init_db()
        results = fetch_all_fangraphs_projections(args.season)
        total = sum(results.values())
        if total > 0:
            logger.info(f"Fetched {total} projections from FanGraphs API: {results}")
            logger.info("Recalculating rankings...")
            calculate_all_zscores(args.season)
        else:
            logger.warning("No projections fetched from FanGraphs API")
    elif args.players_only:
        asyncio.run(sync_players(args.season))
    elif args.stats_only:
        seasons = args.stats_seasons or [args.season - 1]
        for s in seasons:
            asyncio.run(sync_stats(s))
    elif args.statcast_only:
        init_db()
        seasons = args.stats_seasons or [args.season - 1]
        for s in seasons:
            sync_statcast_data(s)
        apply_statcast_adjustments(args.season)
    elif args.projections_only:
        init_db()
        generate_projections_from_stats(args.season)
    elif args.rankings_only:
        init_db()
        calculate_all_zscores(args.season)
    elif args.adp_only:
        init_db()
        import_adp_from_csv(season=args.season)
    else:
        asyncio.run(run_full_sync(args.season, args.stats_seasons))


if __name__ == "__main__":
    main()
