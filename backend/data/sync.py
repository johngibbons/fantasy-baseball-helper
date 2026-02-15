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
from backend.data.projections import generate_projections_from_stats
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
            """INSERT OR REPLACE INTO players
               (mlb_id, full_name, primary_position, player_type, team, team_id, is_active)
               VALUES (?, ?, ?, ?, ?, ?, 1)""",
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
                        """INSERT OR REPLACE INTO batting_stats
                           (mlb_id, season, games, plate_appearances, at_bats,
                            runs, hits, doubles, triples, home_runs,
                            rbi, stolen_bases, caught_stealing, walks, strikeouts,
                            hit_by_pitch, sac_flies, batting_average, obp, slg, ops, total_bases)
                           VALUES (?, ?, ?, ?, ?,
                                   ?, ?, ?, ?, ?,
                                   ?, ?, ?, ?, ?,
                                   ?, ?, ?, ?, ?, ?, ?)""",
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
                        """INSERT OR REPLACE INTO pitching_stats
                           (mlb_id, season, games, games_started, wins, losses,
                            era, whip, innings_pitched, hits_allowed,
                            runs_allowed, earned_runs, walks_allowed, strikeouts,
                            home_runs_allowed, saves, holds, quality_starts)
                           VALUES (?, ?, ?, ?, ?, ?,
                                   ?, ?, ?, ?,
                                   ?, ?, ?, ?,
                                   ?, ?, ?, ?)""",
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

    conn.close()


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

    # 4. Generate projections from historical stats
    logger.info("Generating trend-based projections...")
    generate_projections_from_stats(season)

    # 5. Apply Statcast adjustments to projections
    logger.info("Applying Statcast adjustments...")
    try:
        apply_statcast_adjustments(season)
    except Exception as e:
        logger.warning(f"Statcast adjustments failed (non-fatal): {e}")

    # 6. Calculate z-scores and rankings
    logger.info("Calculating z-scores and rankings...")
    calculate_all_zscores(season)

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

    args = parser.parse_args()

    if args.players_only:
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
    else:
        asyncio.run(run_full_sync(args.season, args.stats_seasons))


if __name__ == "__main__":
    main()
