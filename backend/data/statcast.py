"""Fetch Statcast leaderboard data from Baseball Savant via pybaseball."""

import logging
from backend.database import get_connection

logger = logging.getLogger(__name__)


def _safe_float(val):
    """Convert a value to float, returning None for missing/NaN."""
    if val is None:
        return None
    try:
        import math
        f = float(val)
        return None if math.isnan(f) else f
    except (ValueError, TypeError):
        return None


def sync_statcast_batting(season: int):
    """Fetch and store Statcast batting metrics for a season.

    Pulls expected stats (xwOBA, xBA, xSLG), exit velocity/barrel data,
    and sprint speed from Baseball Savant leaderboards.
    """
    from pybaseball import (
        statcast_batter_expected_stats,
        statcast_batter_exitvelo_barrels,
        statcast_sprint_speed,
    )

    conn = get_connection()

    # Get existing MLB IDs so we only store data for players in our DB
    known_ids = {
        row["mlb_id"]
        for row in conn.execute("SELECT mlb_id FROM players WHERE player_type = 'hitter'").fetchall()
    }

    # --- Expected stats: xwOBA, xBA, xSLG, wOBA ---
    logger.info(f"Fetching Statcast expected batting stats for {season}...")
    try:
        expected = statcast_batter_expected_stats(season, minPA=100)
    except Exception as e:
        logger.error(f"Failed to fetch expected batting stats: {e}")
        expected = None

    player_data: dict[int, dict] = {}

    if expected is not None and not expected.empty:
        for _, row in expected.iterrows():
            pid = int(row.get("player_id", 0) or row.get("batter", 0))
            if pid not in known_ids:
                continue
            player_data[pid] = {
                "xwoba": _safe_float(row.get("est_woba")),
                "xba": _safe_float(row.get("est_ba")),
                "xslg": _safe_float(row.get("est_slg")),
                "woba": _safe_float(row.get("woba")),
            }
        logger.info(f"  Expected stats: {len(player_data)} hitters matched")

    # --- Exit velocity & barrels ---
    logger.info(f"Fetching Statcast exit velo / barrel data for {season}...")
    try:
        ev_barrels = statcast_batter_exitvelo_barrels(season, minBBE=50)
    except Exception as e:
        logger.error(f"Failed to fetch exit velo/barrel data: {e}")
        ev_barrels = None

    if ev_barrels is not None and not ev_barrels.empty:
        matched = 0
        for _, row in ev_barrels.iterrows():
            pid = int(row.get("player_id", 0) or row.get("batter", 0))
            if pid not in known_ids:
                continue
            if pid not in player_data:
                player_data[pid] = {}
            player_data[pid].update({
                "barrel_pct": _safe_float(row.get("barrel_batted_rate")),
                "hard_hit_pct": _safe_float(row.get("hard_hit_percent")),
                "avg_exit_velocity": _safe_float(row.get("avg_hit_speed")),
                "max_exit_velocity": _safe_float(row.get("max_hit_speed")),
                "sweet_spot_pct": _safe_float(row.get("sweet_spot_percent")),
                "launch_angle": _safe_float(row.get("avg_launch_angle")),
            })
            matched += 1
        logger.info(f"  Exit velo/barrels: {matched} hitters matched")

    # --- Sprint speed ---
    logger.info(f"Fetching Statcast sprint speed for {season}...")
    try:
        sprint = statcast_sprint_speed(season, min_opp=5)
    except Exception as e:
        logger.error(f"Failed to fetch sprint speed: {e}")
        sprint = None

    if sprint is not None and not sprint.empty:
        matched = 0
        for _, row in sprint.iterrows():
            pid = int(row.get("player_id", 0) or row.get("batter", 0))
            if pid not in known_ids:
                continue
            if pid not in player_data:
                player_data[pid] = {}
            player_data[pid]["sprint_speed"] = _safe_float(row.get("hp_to_1b", row.get("sprint_speed")))
            matched += 1
        logger.info(f"  Sprint speed: {matched} hitters matched")

    # --- Write to DB ---
    count = 0
    for mlb_id, data in player_data.items():
        conn.execute(
            """INSERT OR REPLACE INTO statcast_batting
               (mlb_id, season, xwoba, xba, xslg, barrel_pct, hard_hit_pct,
                avg_exit_velocity, max_exit_velocity, sprint_speed,
                sweet_spot_pct, launch_angle, woba)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                mlb_id, season,
                data.get("xwoba"), data.get("xba"), data.get("xslg"),
                data.get("barrel_pct"), data.get("hard_hit_pct"),
                data.get("avg_exit_velocity"), data.get("max_exit_velocity"),
                data.get("sprint_speed"), data.get("sweet_spot_pct"),
                data.get("launch_angle"), data.get("woba"),
            ),
        )
        count += 1

    conn.commit()
    conn.close()
    logger.info(f"Saved Statcast batting data for {count} hitters ({season})")
    return count


def sync_statcast_pitching(season: int):
    """Fetch and store Statcast pitching metrics for a season.

    Pulls expected stats (xERA, xwOBA against, xBA against), barrel/hard-hit
    against, and pitch-level metrics (whiff%, CSW%).
    """
    from pybaseball import (
        statcast_pitcher_expected_stats,
        statcast_pitcher_exitvelo_barrels,
    )

    conn = get_connection()

    known_ids = {
        row["mlb_id"]
        for row in conn.execute("SELECT mlb_id FROM players WHERE player_type = 'pitcher'").fetchall()
    }

    player_data: dict[int, dict] = {}

    # --- Expected stats: xERA, xwOBA against, xBA against ---
    logger.info(f"Fetching Statcast expected pitching stats for {season}...")
    try:
        expected = statcast_pitcher_expected_stats(season, minPA=100)
    except Exception as e:
        logger.error(f"Failed to fetch expected pitching stats: {e}")
        expected = None

    if expected is not None and not expected.empty:
        for _, row in expected.iterrows():
            pid = int(row.get("player_id", 0) or row.get("pitcher", 0))
            if pid not in known_ids:
                continue
            player_data[pid] = {
                "xera": _safe_float(row.get("xera", row.get("est_era"))),
                "xwoba_against": _safe_float(row.get("est_woba")),
                "xba_against": _safe_float(row.get("est_ba")),
                "k_pct": _safe_float(row.get("k_percent")),
                "bb_pct": _safe_float(row.get("bb_percent")),
            }
        logger.info(f"  Expected stats: {len(player_data)} pitchers matched")

    # --- Exit velo / barrels against ---
    logger.info(f"Fetching Statcast exit velo / barrel against data for {season}...")
    try:
        ev_barrels = statcast_pitcher_exitvelo_barrels(season, minBBE=50)
    except Exception as e:
        logger.error(f"Failed to fetch pitcher exit velo/barrel data: {e}")
        ev_barrels = None

    if ev_barrels is not None and not ev_barrels.empty:
        matched = 0
        for _, row in ev_barrels.iterrows():
            pid = int(row.get("player_id", 0) or row.get("pitcher", 0))
            if pid not in known_ids:
                continue
            if pid not in player_data:
                player_data[pid] = {}
            player_data[pid].update({
                "barrel_pct_against": _safe_float(row.get("barrel_batted_rate")),
                "hard_hit_pct_against": _safe_float(row.get("hard_hit_percent")),
                "avg_exit_velocity_against": _safe_float(row.get("avg_hit_speed")),
            })
            matched += 1
        logger.info(f"  Exit velo/barrels against: {matched} pitchers matched")

    # --- Pitch-level metrics (whiff%, CSW%) via pitching stats ---
    # pybaseball's pitcher arsenal stats may not always be available,
    # so we try to get whiff/chase data from the expected stats or
    # fall back to per-pitcher statcast queries
    logger.info(f"Fetching Statcast pitch-level metrics for {season}...")
    try:
        from pybaseball import statcast_pitcher_arsenal_stats
        arsenal = statcast_pitcher_arsenal_stats(season, minPA=100)
        if arsenal is not None and not arsenal.empty:
            # Arsenal stats are per-pitch-type; aggregate to pitcher level
            # by taking the PA-weighted average across pitch types
            grouped = arsenal.groupby("player_id" if "player_id" in arsenal.columns else "pitcher")
            matched = 0
            for pid_raw, group in grouped:
                pid = int(pid_raw)
                if pid not in known_ids:
                    continue
                if pid not in player_data:
                    player_data[pid] = {}

                # Weighted average whiff% across pitch types
                if "whiff_percent" in group.columns and "pa" in group.columns:
                    total_pa = group["pa"].sum()
                    if total_pa > 0:
                        w_whiff = (group["whiff_percent"] * group["pa"]).sum() / total_pa
                        player_data[pid]["whiff_pct"] = _safe_float(w_whiff)

                if "csw_rate" in group.columns and "pa" in group.columns:
                    total_pa = group["pa"].sum()
                    if total_pa > 0:
                        w_csw = (group["csw_rate"] * group["pa"]).sum() / total_pa
                        player_data[pid]["csw_pct"] = _safe_float(w_csw)

                if "chase_rate" in group.columns and "pa" in group.columns:
                    total_pa = group["pa"].sum()
                    if total_pa > 0:
                        w_chase = (group["chase_rate"] * group["pa"]).sum() / total_pa
                        player_data[pid]["chase_rate"] = _safe_float(w_chase)

                matched += 1
            logger.info(f"  Arsenal stats: {matched} pitchers matched")
    except Exception as e:
        logger.warning(f"Could not fetch arsenal stats (may not be available): {e}")

    # --- Write to DB ---
    count = 0
    for mlb_id, data in player_data.items():
        conn.execute(
            """INSERT OR REPLACE INTO statcast_pitching
               (mlb_id, season, xera, xwoba_against, xba_against,
                barrel_pct_against, hard_hit_pct_against,
                whiff_pct, k_pct, bb_pct,
                avg_exit_velocity_against, chase_rate, csw_pct)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                mlb_id, season,
                data.get("xera"), data.get("xwoba_against"), data.get("xba_against"),
                data.get("barrel_pct_against"), data.get("hard_hit_pct_against"),
                data.get("whiff_pct"), data.get("k_pct"), data.get("bb_pct"),
                data.get("avg_exit_velocity_against"), data.get("chase_rate"),
                data.get("csw_pct"),
            ),
        )
        count += 1

    conn.commit()
    conn.close()
    logger.info(f"Saved Statcast pitching data for {count} pitchers ({season})")
    return count


def sync_statcast_data(season: int):
    """Fetch all Statcast data for a season (batting + pitching)."""
    batting_count = sync_statcast_batting(season)
    pitching_count = sync_statcast_pitching(season)
    logger.info(f"Statcast sync complete: {batting_count} hitters, {pitching_count} pitchers")
    return batting_count + pitching_count
