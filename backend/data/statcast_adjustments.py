"""Adjust trend-based projections using Statcast data.

Reads 'trend' projections and Statcast metrics, then writes new projections
with source='statcast_adjusted'. All adjustments blend 50/50 between the
trend projection and the Statcast-implied value (conservative regression).
"""

import logging
from backend.database import get_connection

logger = logging.getLogger(__name__)

# Blend factor: 0.5 means 50% trend + 50% Statcast-implied value
BLEND = 0.5

# League average baselines (approximate MLB averages)
LEAGUE_AVG_SLG = 0.400
LEAGUE_AVG_WOBA = 0.310
LEAGUE_AVG_BARREL_PCT = 7.0  # percent
LEAGUE_AVG_HARD_HIT_PCT = 35.0  # percent
LEAGUE_AVG_SPRINT_SPEED = 27.0  # ft/s
LEAGUE_AVG_WHIFF_PCT = 25.0  # percent
LEAGUE_AVG_BA_AGAINST = 0.250

# wOBA-to-OBP scale factor.  wOBA uses linear weights that compress the
# scale relative to OBP (league-avg wOBA ~.310 vs OBP ~.320, and the SD
# of wOBA is ~1.2× that of OBP).  Dividing by this factor converts a
# wOBA-space difference into the approximate OBP-space equivalent.
WOBA_TO_OBP_SCALE = 1.2


def apply_statcast_adjustments(season: int):
    """Apply Statcast-based adjustments to trend projections.

    Creates new projection rows with source='statcast_adjusted' that the
    z-score engine will prefer over plain 'trend' projections.
    """
    conn = get_connection()

    hitter_count = _adjust_hitters(conn, season)
    pitcher_count = _adjust_pitchers(conn, season)

    conn.commit()
    conn.close()
    logger.info(
        f"Statcast adjustments complete: {hitter_count} hitters, {pitcher_count} pitchers"
    )
    return hitter_count + pitcher_count


def _adjust_hitters(conn, season: int) -> int:
    """Adjust hitter trend projections using Statcast batting data.

    Adjustments:
    - TB: Regress toward xSLG-implied total bases if xSLG diverges from SLG
    - OBP: Regress toward xwOBA-implied OBP if xwOBA diverges from wOBA
    - SB: Scale by sprint speed (elite speed → more SB, slow → fewer)
    - R/RBI: Mild adjustment based on barrel% / hard_hit% deviation from average
    """
    # Get trend projections for hitters
    projections = conn.execute(
        """SELECT p.mlb_id, pr.*
           FROM projections pr
           JOIN players p ON pr.mlb_id = p.mlb_id
           WHERE pr.season = ? AND pr.source = 'trend' AND pr.player_type = 'hitter'""",
        (season,),
    ).fetchall()

    if not projections:
        logger.warning(f"No trend hitter projections found for {season}")
        return 0

    # Get the most recent season of Statcast data (prefer season-1 for projecting next year)
    statcast_season = season - 1
    statcast = {}
    rows = conn.execute(
        "SELECT * FROM statcast_batting WHERE season = ?", (statcast_season,)
    ).fetchall()
    if not rows:
        # Try season - 2 as fallback
        statcast_season = season - 2
        rows = conn.execute(
            "SELECT * FROM statcast_batting WHERE season = ?", (statcast_season,)
        ).fetchall()
    for row in rows:
        statcast[row["mlb_id"]] = dict(row)

    if not statcast:
        logger.warning(f"No Statcast batting data found for adjustment")
        return 0

    logger.info(f"Adjusting {len(projections)} hitter projections using {statcast_season} Statcast data")

    # Also load actual batting stats for the Statcast season to get actual SLG
    actual_stats = {}
    for row in conn.execute(
        "SELECT mlb_id, slg, obp, batting_average FROM batting_stats WHERE season = ?",
        (statcast_season,),
    ).fetchall():
        actual_stats[row["mlb_id"]] = dict(row)

    count = 0
    for proj in projections:
        mlb_id = proj["mlb_id"]
        sc = statcast.get(mlb_id)
        if not sc:
            # No Statcast data — copy trend projection as-is
            _copy_projection_as_adjusted(conn, proj)
            count += 1
            continue

        actual = actual_stats.get(mlb_id, {})

        # Start with trend projection values
        adj_tb = proj["proj_total_bases"] or 0
        adj_obp = proj["proj_obp"] or 0
        adj_sb = proj["proj_stolen_bases"] or 0
        adj_runs = proj["proj_runs"] or 0
        adj_rbi = proj["proj_rbi"] or 0

        # --- TB adjustment via xSLG ---
        xslg = sc.get("xslg")
        actual_slg = actual.get("slg")
        if xslg is not None and actual_slg is not None and actual_slg > 0:
            slg_diff = xslg - actual_slg
            if abs(slg_diff) > 0.030:  # Only adjust if meaningful gap
                adj_tb = adj_tb * (1 + slg_diff * BLEND)

        # --- OBP adjustment via xwOBA ---
        xwoba = sc.get("xwoba")
        actual_woba = sc.get("woba")
        if xwoba is not None and actual_woba is not None and actual_woba > 0:
            woba_diff = xwoba - actual_woba
            if abs(woba_diff) > 0.015:  # Meaningful gap
                # Convert wOBA-space diff to OBP-space, then apply blend
                obp_adjustment = woba_diff / WOBA_TO_OBP_SCALE * BLEND
                adj_obp = adj_obp + obp_adjustment

        # --- SB adjustment via sprint speed ---
        sprint = sc.get("sprint_speed")
        if sprint is not None and adj_sb > 0:
            speed_diff = sprint - LEAGUE_AVG_SPRINT_SPEED
            # Scale: each ft/s above/below average shifts SB by ~8%
            sb_multiplier = 1 + (speed_diff * 0.08 * BLEND)
            adj_sb = adj_sb * max(sb_multiplier, 0.5)  # floor at 50% reduction

        # --- R/RBI adjustment via barrel% / hard_hit% ---
        barrel_pct = sc.get("barrel_pct")
        hard_hit_pct = sc.get("hard_hit_pct")
        if barrel_pct is not None and hard_hit_pct is not None:
            # Combined quality-of-contact deviation from average
            barrel_dev = (barrel_pct - LEAGUE_AVG_BARREL_PCT) / LEAGUE_AVG_BARREL_PCT
            hh_dev = (hard_hit_pct - LEAGUE_AVG_HARD_HIT_PCT) / LEAGUE_AVG_HARD_HIT_PCT
            contact_quality = (barrel_dev + hh_dev) / 2
            # Mild multiplier: max ~10% adjustment
            rbi_mult = 1 + (contact_quality * 0.10 * BLEND)
            run_mult = 1 + (contact_quality * 0.08 * BLEND)
            adj_rbi = adj_rbi * rbi_mult
            adj_runs = adj_runs * run_mult

        # Write adjusted projection
        conn.execute(
            """INSERT INTO projections
               (mlb_id, source, season, player_type,
                proj_pa, proj_at_bats, proj_runs, proj_hits, proj_doubles, proj_triples,
                proj_home_runs, proj_rbi, proj_stolen_bases, proj_walks,
                proj_strikeouts, proj_hbp, proj_sac_flies, proj_obp, proj_total_bases)
               VALUES (?, 'statcast_adjusted', ?, 'hitter',
                       ?, ?, ?, ?, ?, ?,
                       ?, ?, ?, ?,
                       ?, ?, ?, ?, ?)
               ON CONFLICT (mlb_id, source, season, player_type) DO UPDATE SET
                 proj_pa = EXCLUDED.proj_pa, proj_at_bats = EXCLUDED.proj_at_bats,
                 proj_runs = EXCLUDED.proj_runs, proj_hits = EXCLUDED.proj_hits,
                 proj_doubles = EXCLUDED.proj_doubles, proj_triples = EXCLUDED.proj_triples,
                 proj_home_runs = EXCLUDED.proj_home_runs, proj_rbi = EXCLUDED.proj_rbi,
                 proj_stolen_bases = EXCLUDED.proj_stolen_bases, proj_walks = EXCLUDED.proj_walks,
                 proj_strikeouts = EXCLUDED.proj_strikeouts, proj_hbp = EXCLUDED.proj_hbp,
                 proj_sac_flies = EXCLUDED.proj_sac_flies, proj_obp = EXCLUDED.proj_obp,
                 proj_total_bases = EXCLUDED.proj_total_bases""",
            (
                mlb_id, season,
                proj["proj_pa"], proj["proj_at_bats"],
                round(adj_runs), proj["proj_hits"], proj["proj_doubles"], proj["proj_triples"],
                proj["proj_home_runs"], round(adj_rbi), round(adj_sb),
                proj["proj_walks"], proj["proj_strikeouts"],
                proj["proj_hbp"], proj["proj_sac_flies"],
                round(adj_obp, 3), round(adj_tb),
            ),
        )
        count += 1

    return count


def _adjust_pitchers(conn, season: int) -> int:
    """Adjust pitcher trend projections using Statcast pitching data.

    Adjustments:
    - ERA: Regress toward xERA
    - WHIP: Adjust using xBA_against vs actual BA_against + BB%
    - K: Scale by whiff% / CSW% (elite whiff → more K)
    - QS: Adjust based on xERA + IP combination
    """
    projections = conn.execute(
        """SELECT p.mlb_id, pr.*
           FROM projections pr
           JOIN players p ON pr.mlb_id = p.mlb_id
           WHERE pr.season = ? AND pr.source = 'trend' AND pr.player_type = 'pitcher'""",
        (season,),
    ).fetchall()

    if not projections:
        logger.warning(f"No trend pitcher projections found for {season}")
        return 0

    statcast_season = season - 1
    statcast = {}
    rows = conn.execute(
        "SELECT * FROM statcast_pitching WHERE season = ?", (statcast_season,)
    ).fetchall()
    if not rows:
        statcast_season = season - 2
        rows = conn.execute(
            "SELECT * FROM statcast_pitching WHERE season = ?", (statcast_season,)
        ).fetchall()
    for row in rows:
        statcast[row["mlb_id"]] = dict(row)

    if not statcast:
        logger.warning(f"No Statcast pitching data found for adjustment")
        return 0

    logger.info(f"Adjusting {len(projections)} pitcher projections using {statcast_season} Statcast data")

    # Load actual pitching stats for the Statcast season
    actual_stats = {}
    for row in conn.execute(
        "SELECT mlb_id, era, whip FROM pitching_stats WHERE season = ?",
        (statcast_season,),
    ).fetchall():
        actual_stats[row["mlb_id"]] = dict(row)

    count = 0
    for proj in projections:
        mlb_id = proj["mlb_id"]
        sc = statcast.get(mlb_id)
        if not sc:
            _copy_projection_as_adjusted_pitcher(conn, proj)
            count += 1
            continue

        proj_era = proj["proj_era"] or 0
        proj_whip = proj["proj_whip"] or 0
        proj_k = proj["proj_pitcher_strikeouts"] or 0
        proj_qs = proj["proj_quality_starts"] or 0
        proj_ip = proj["proj_ip"] or 0

        # --- ERA adjustment via xERA ---
        xera = sc.get("xera")
        if xera is not None and proj_era > 0:
            # Blend: move halfway from trend ERA toward xERA
            adj_era = proj_era + (xera - proj_era) * BLEND
        else:
            adj_era = proj_era

        # --- WHIP adjustment via xBA_against ---
        xba_against = sc.get("xba_against")
        actual = actual_stats.get(mlb_id, {})
        actual_ba_against = None
        if actual.get("whip") and proj_ip > 0:
            # Estimate BA_against from actual stats
            actual_ba_against = LEAGUE_AVG_BA_AGAINST  # rough fallback
        if xba_against is not None:
            # If xBA_against is lower than league average, pitcher was unlucky → lower WHIP
            ba_diff = xba_against - LEAGUE_AVG_BA_AGAINST
            whip_adjustment = ba_diff * BLEND  # ~50% credit
            adj_whip = proj_whip + whip_adjustment
        else:
            adj_whip = proj_whip

        # Also factor in BB% if available
        bb_pct = sc.get("bb_pct")
        if bb_pct is not None and adj_whip > 0:
            # League avg BB% ~8.5%. If pitcher has lower BB%, slight WHIP reduction
            league_bb_pct = 8.5
            bb_diff = (bb_pct - league_bb_pct) / 100  # convert to a small multiplier
            adj_whip = adj_whip * (1 + bb_diff * BLEND)

        # --- K adjustment via whiff% / CSW% ---
        whiff_pct = sc.get("whiff_pct")
        csw_pct = sc.get("csw_pct")
        adj_k = proj_k

        if whiff_pct is not None:
            whiff_diff = whiff_pct - LEAGUE_AVG_WHIFF_PCT
            # Each point of whiff% above/below average shifts K by ~2%
            k_multiplier = 1 + (whiff_diff * 0.02 * BLEND)
            adj_k = adj_k * max(k_multiplier, 0.5)

        if csw_pct is not None:
            # CSW% (called strikes + whiffs %) — league avg ~28%
            league_csw = 28.0
            csw_diff = csw_pct - league_csw
            # Secondary adjustment, smaller weight
            csw_mult = 1 + (csw_diff * 0.01 * BLEND)
            adj_k = adj_k * max(csw_mult, 0.8)

        # --- QS adjustment via xERA + IP ---
        adj_qs = proj_qs
        if xera is not None and proj_ip > 0:
            # Lower xERA + more IP = more likely to get QS
            # Compare to threshold: a pitcher with 3.50 xERA and 180 IP should get ~20 QS
            if proj_ip >= 100:  # Only adjust for starters with meaningful IP
                era_factor = max(0, (4.50 - adj_era) / 4.50)  # 0 at 4.50 ERA, ~0.33 at 3.0
                ip_factor = min(proj_ip / 180, 1.0)  # scales up to 180 IP
                implied_qs = 32 * era_factor * ip_factor  # ~32 starts max
                adj_qs = proj_qs + (implied_qs - proj_qs) * BLEND

        # Recalculate earned_runs from adjusted ERA
        adj_earned_runs = (adj_era * proj_ip / 9) if proj_ip > 0 else proj["proj_earned_runs"]
        # Recalculate hits_allowed + walks_allowed from adjusted WHIP
        adj_h_bb = adj_whip * proj_ip if proj_ip > 0 else (proj["proj_hits_allowed"] or 0) + (proj["proj_walks_allowed"] or 0)
        # Split hits/walks proportionally to original
        orig_h = proj["proj_hits_allowed"] or 0
        orig_bb = proj["proj_walks_allowed"] or 0
        orig_total = orig_h + orig_bb
        if orig_total > 0:
            adj_hits_allowed = adj_h_bb * (orig_h / orig_total)
            adj_walks_allowed = adj_h_bb * (orig_bb / orig_total)
        else:
            adj_hits_allowed = orig_h
            adj_walks_allowed = orig_bb

        conn.execute(
            """INSERT INTO projections
               (mlb_id, source, season, player_type,
                proj_ip, proj_pitcher_strikeouts, proj_quality_starts,
                proj_era, proj_whip, proj_saves, proj_holds, proj_wins,
                proj_hits_allowed, proj_walks_allowed, proj_earned_runs)
               VALUES (?, 'statcast_adjusted', ?, 'pitcher',
                       ?, ?, ?,
                       ?, ?, ?, ?, ?,
                       ?, ?, ?)
               ON CONFLICT (mlb_id, source, season, player_type) DO UPDATE SET
                 proj_ip = EXCLUDED.proj_ip, proj_pitcher_strikeouts = EXCLUDED.proj_pitcher_strikeouts,
                 proj_quality_starts = EXCLUDED.proj_quality_starts,
                 proj_era = EXCLUDED.proj_era, proj_whip = EXCLUDED.proj_whip,
                 proj_saves = EXCLUDED.proj_saves, proj_holds = EXCLUDED.proj_holds,
                 proj_wins = EXCLUDED.proj_wins, proj_hits_allowed = EXCLUDED.proj_hits_allowed,
                 proj_walks_allowed = EXCLUDED.proj_walks_allowed,
                 proj_earned_runs = EXCLUDED.proj_earned_runs""",
            (
                mlb_id, season,
                proj["proj_ip"], round(adj_k), round(adj_qs),
                round(adj_era, 2), round(adj_whip, 2),
                proj["proj_saves"], proj["proj_holds"], proj["proj_wins"],
                round(adj_hits_allowed), round(adj_walks_allowed), round(adj_earned_runs),
            ),
        )
        count += 1

    return count


def _copy_projection_as_adjusted(conn, proj):
    """Copy a hitter trend projection as statcast_adjusted (no Statcast data available)."""
    conn.execute(
        """INSERT INTO projections
           (mlb_id, source, season, player_type,
            proj_pa, proj_at_bats, proj_runs, proj_hits, proj_doubles, proj_triples,
            proj_home_runs, proj_rbi, proj_stolen_bases, proj_walks,
            proj_strikeouts, proj_hbp, proj_sac_flies, proj_obp, proj_total_bases)
           VALUES (?, 'statcast_adjusted', ?, 'hitter',
                   ?, ?, ?, ?, ?, ?,
                   ?, ?, ?, ?,
                   ?, ?, ?, ?, ?)
           ON CONFLICT (mlb_id, source, season, player_type) DO UPDATE SET
             proj_pa = EXCLUDED.proj_pa, proj_at_bats = EXCLUDED.proj_at_bats,
             proj_runs = EXCLUDED.proj_runs, proj_hits = EXCLUDED.proj_hits,
             proj_doubles = EXCLUDED.proj_doubles, proj_triples = EXCLUDED.proj_triples,
             proj_home_runs = EXCLUDED.proj_home_runs, proj_rbi = EXCLUDED.proj_rbi,
             proj_stolen_bases = EXCLUDED.proj_stolen_bases, proj_walks = EXCLUDED.proj_walks,
             proj_strikeouts = EXCLUDED.proj_strikeouts, proj_hbp = EXCLUDED.proj_hbp,
             proj_sac_flies = EXCLUDED.proj_sac_flies, proj_obp = EXCLUDED.proj_obp,
             proj_total_bases = EXCLUDED.proj_total_bases""",
        (
            proj["mlb_id"], proj["season"],
            proj["proj_pa"], proj["proj_at_bats"],
            proj["proj_runs"], proj["proj_hits"], proj["proj_doubles"], proj["proj_triples"],
            proj["proj_home_runs"], proj["proj_rbi"], proj["proj_stolen_bases"],
            proj["proj_walks"], proj["proj_strikeouts"],
            proj["proj_hbp"], proj["proj_sac_flies"],
            proj["proj_obp"], proj["proj_total_bases"],
        ),
    )


def _copy_projection_as_adjusted_pitcher(conn, proj):
    """Copy a pitcher trend projection as statcast_adjusted (no Statcast data available)."""
    conn.execute(
        """INSERT INTO projections
           (mlb_id, source, season, player_type,
            proj_ip, proj_pitcher_strikeouts, proj_quality_starts,
            proj_era, proj_whip, proj_saves, proj_holds, proj_wins,
            proj_hits_allowed, proj_walks_allowed, proj_earned_runs)
           VALUES (?, 'statcast_adjusted', ?, 'pitcher',
                   ?, ?, ?,
                   ?, ?, ?, ?, ?,
                   ?, ?, ?)
           ON CONFLICT (mlb_id, source, season, player_type) DO UPDATE SET
             proj_ip = EXCLUDED.proj_ip, proj_pitcher_strikeouts = EXCLUDED.proj_pitcher_strikeouts,
             proj_quality_starts = EXCLUDED.proj_quality_starts,
             proj_era = EXCLUDED.proj_era, proj_whip = EXCLUDED.proj_whip,
             proj_saves = EXCLUDED.proj_saves, proj_holds = EXCLUDED.proj_holds,
             proj_wins = EXCLUDED.proj_wins, proj_hits_allowed = EXCLUDED.proj_hits_allowed,
             proj_walks_allowed = EXCLUDED.proj_walks_allowed,
             proj_earned_runs = EXCLUDED.proj_earned_runs""",
        (
            proj["mlb_id"], proj["season"],
            proj["proj_ip"], proj["proj_pitcher_strikeouts"], proj["proj_quality_starts"],
            proj["proj_era"], proj["proj_whip"],
            proj["proj_saves"], proj["proj_holds"], proj["proj_wins"],
            proj["proj_hits_allowed"], proj["proj_walks_allowed"], proj["proj_earned_runs"],
        ),
    )
