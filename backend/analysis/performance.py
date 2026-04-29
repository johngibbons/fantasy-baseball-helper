"""Projection vs. actual performance analysis.

Joins rankings (preseason projections) with batting_stats / pitching_stats
(season-to-date actuals) and computes volume + rate deltas per category.

Volume framing: actual vs. (full-season projection × season-elapsed fraction).
Rate framing:   per-PA / per-IP rate of actual vs. per-PA / per-IP rate of projection.
"""

import asyncio
import logging
import time
from typing import Literal

from backend.data.mlb_api import get_batting_stats, get_pitching_stats
from backend.database import get_connection

logger = logging.getLogger(__name__)

# In-memory state for the background refresh job. Survives across requests in
# a single process, which is good enough — Railway runs one worker.
_refresh_state = {
    "status": "idle",        # idle | running | completed | failed
    "started_at": None,      # epoch seconds
    "finished_at": None,
    "season": None,
    "total": 0,
    "done": 0,
    "errors": 0,
    "error_message": None,
}


def get_refresh_state() -> dict:
    """Return a copy of the current refresh state."""
    return dict(_refresh_state)

HITTER_COUNTING_CATS = ["r", "tb", "rbi", "sb"]
PITCHER_COUNTING_CATS = ["k", "qs", "svhd"]


def _safe_div(num, denom):
    if not denom:
        return None
    try:
        return num / denom
    except (TypeError, ZeroDivisionError):
        return None


def _delta(actual, expected):
    if actual is None or expected is None:
        return None
    return actual - expected


def _compute_population_zscores(values: list[float | None]) -> list[float | None]:
    """Convert a list of values to population z-scores.

    None values pass through as None and are excluded from the
    mean/stddev calculation. If fewer than 2 non-null values exist,
    or if stddev is 0 (all values identical), every non-null entry
    maps to 0.0.

    Uses population stddev (divide by N), not sample stddev (N-1) —
    the ranked player pool *is* the population, not a sample of one.
    """
    non_null = [v for v in values if v is not None]
    if len(non_null) < 2:
        return [None if v is None else 0.0 for v in values]
    mean = sum(non_null) / len(non_null)
    var = sum((v - mean) ** 2 for v in non_null) / len(non_null)
    stddev = var ** 0.5
    if stddev == 0:
        return [None if v is None else 0.0 for v in values]
    return [None if v is None else (v - mean) / stddev for v in values]


# Categories where lower is better — sign-flip the z-score so that
# positive z always means "performed better than expected" everywhere.
_INVERTED_FOR_PERFORMANCE = {"era", "whip"}


def _attach_delta_zscores(rows: list[dict], cats: list[str]) -> None:
    """Mutate each row to add delta_volume_z and delta_rate_z under
    each categories[cat] dict, computed against the population of all
    rows for that cat.

    For inverted categories (ERA, WHIP), z-scores are sign-flipped so
    positive means "better than expected" for every category.
    """
    for cat in cats:
        for delta_field, z_field in (
            ("delta_volume", "delta_volume_z"),
            ("delta_rate",   "delta_rate_z"),
        ):
            values = [row["categories"][cat].get(delta_field) for row in rows]
            zs = _compute_population_zscores(values)
            if cat in _INVERTED_FOR_PERFORMANCE:
                zs = [None if z is None else -z for z in zs]
            for row, z in zip(rows, zs):
                row["categories"][cat][z_field] = z


def compute_hitter_performance(season: int, season_elapsed_fraction: float) -> list[dict]:
    """Return one row per ranked hitter for the given season."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT
            r.mlb_id, r.overall_rank, r.position_rank,
            r.proj_pa, r.proj_r, r.proj_tb, r.proj_rbi, r.proj_sb, r.proj_obp,
            p.full_name, p.primary_position, p.team, p.eligible_positions,
            b.games AS a_g,
            b.plate_appearances AS a_pa,
            b.runs AS a_r,
            b.total_bases AS a_tb,
            b.rbi AS a_rbi,
            b.stolen_bases AS a_sb,
            b.obp AS a_obp,
            b.batting_average AS a_avg,
            b.home_runs AS a_hr
        FROM rankings r
        JOIN players p ON r.mlb_id = p.mlb_id
        LEFT JOIN batting_stats b ON b.mlb_id = r.mlb_id AND b.season = r.season
        WHERE r.season = ? AND r.player_type = 'hitter'
        ORDER BY r.overall_rank ASC
        """,
        (season,),
    ).fetchall()
    conn.close()

    out = []
    for r in rows:
        d = dict(r)
        proj_pa = d.get("proj_pa") or 0
        a_pa = d.get("a_pa") or 0

        # Per-PA projected rates (excluding OBP which is already a rate).
        proj_rates = {}
        actual_rates = {}
        for cat in HITTER_COUNTING_CATS:
            proj_total = d.get(f"proj_{cat}") or 0
            proj_rates[cat] = _safe_div(proj_total, proj_pa)
            actual_total = d.get(f"a_{cat}") or 0
            actual_rates[cat] = _safe_div(actual_total, a_pa)

        proj_rates["obp"] = d.get("proj_obp")
        actual_rates["obp"] = d.get("a_obp")

        # Build per-category breakdown
        cats = {}
        for cat in HITTER_COUNTING_CATS:
            proj_total = d.get(f"proj_{cat}") or 0
            proj_to_date = proj_total * season_elapsed_fraction
            actual = d.get(f"a_{cat}") or 0
            cats[cat] = {
                "proj_total": proj_total,
                "proj_to_date": proj_to_date,
                "actual": actual,
                "delta_volume": actual - proj_to_date,
                "proj_rate": proj_rates[cat],
                "actual_rate": actual_rates[cat] if a_pa > 0 else None,
                "delta_rate": (
                    (actual_rates[cat] - proj_rates[cat])
                    if (a_pa > 0 and proj_rates[cat] is not None and actual_rates[cat] is not None)
                    else None
                ),
            }

        # OBP — rate stat only
        proj_obp = d.get("proj_obp")
        a_obp = d.get("a_obp") if a_pa > 0 else None
        cats["obp"] = {
            "proj_total": proj_obp,
            "proj_to_date": proj_obp,  # rate stats don't accumulate
            "actual": a_obp,
            "delta_volume": None,  # not meaningful for rate stat
            "proj_rate": proj_obp,
            "actual_rate": a_obp,
            "delta_rate": _delta(a_obp, proj_obp) if (proj_obp is not None and a_obp is not None) else None,
        }

        out.append({
            "mlb_id": d["mlb_id"],
            "name": d["full_name"],
            "team": d.get("team"),
            "primary_position": d.get("primary_position"),
            "eligible_positions": d.get("eligible_positions"),
            "player_type": "hitter",
            "overall_rank": d.get("overall_rank"),
            "position_rank": d.get("position_rank"),
            "proj_pa": proj_pa,
            "actual_pa": a_pa,
            "actual_g": d.get("a_g") or 0,
            "actual_avg": d.get("a_avg"),
            "actual_hr": d.get("a_hr") or 0,
            "expected_pa_to_date": proj_pa * season_elapsed_fraction,
            "categories": cats,
        })

    return out


def compute_pitcher_performance(season: int, season_elapsed_fraction: float) -> list[dict]:
    """Return one row per ranked pitcher for the given season."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT
            r.mlb_id, r.overall_rank, r.position_rank,
            r.proj_ip, r.proj_k, r.proj_qs, r.proj_era, r.proj_whip, r.proj_svhd,
            p.full_name, p.primary_position, p.team, p.eligible_positions,
            ps.games AS a_g,
            ps.games_started AS a_gs,
            ps.innings_pitched AS a_ip,
            ps.strikeouts AS a_k,
            ps.quality_starts AS a_qs,
            ps.era AS a_era,
            ps.whip AS a_whip,
            ps.saves AS a_sv,
            ps.holds AS a_hld,
            ps.earned_runs AS a_er,
            ps.walks_allowed AS a_bb,
            ps.hits_allowed AS a_h
        FROM rankings r
        JOIN players p ON r.mlb_id = p.mlb_id
        LEFT JOIN pitching_stats ps ON ps.mlb_id = r.mlb_id AND ps.season = r.season
        WHERE r.season = ? AND r.player_type = 'pitcher'
        ORDER BY r.overall_rank ASC
        """,
        (season,),
    ).fetchall()
    conn.close()

    out = []
    for r in rows:
        d = dict(r)
        proj_ip = d.get("proj_ip") or 0
        a_ip = d.get("a_ip") or 0
        a_sv = d.get("a_sv") or 0
        a_hld = d.get("a_hld") or 0
        a_svhd = a_sv + a_hld

        cats = {}

        # K — counting stat with rate framing (K/9)
        proj_k = d.get("proj_k") or 0
        a_k = d.get("a_k") or 0
        cats["k"] = {
            "proj_total": proj_k,
            "proj_to_date": proj_k * season_elapsed_fraction,
            "actual": a_k,
            "delta_volume": a_k - (proj_k * season_elapsed_fraction),
            "proj_rate": _safe_div(proj_k * 9, proj_ip),  # K/9
            "actual_rate": _safe_div(a_k * 9, a_ip) if a_ip > 0 else None,
            "delta_rate": None,
        }
        if cats["k"]["proj_rate"] is not None and cats["k"]["actual_rate"] is not None:
            cats["k"]["delta_rate"] = cats["k"]["actual_rate"] - cats["k"]["proj_rate"]

        # QS — counting stat
        proj_qs = d.get("proj_qs") or 0
        a_qs = d.get("a_qs") or 0
        cats["qs"] = {
            "proj_total": proj_qs,
            "proj_to_date": proj_qs * season_elapsed_fraction,
            "actual": a_qs,
            "delta_volume": a_qs - (proj_qs * season_elapsed_fraction),
            # Rate proxy: QS per start. Use proj_ip / 6 as proxy for projected starts.
            "proj_rate": _safe_div(proj_qs, (proj_ip / 6.0) if proj_ip else 0),
            "actual_rate": _safe_div(a_qs, d.get("a_gs") or 0) if (d.get("a_gs") or 0) > 0 else None,
            "delta_rate": None,
        }
        if cats["qs"]["proj_rate"] is not None and cats["qs"]["actual_rate"] is not None:
            cats["qs"]["delta_rate"] = cats["qs"]["actual_rate"] - cats["qs"]["proj_rate"]

        # SVHD — counting stat
        proj_svhd = d.get("proj_svhd") or 0
        cats["svhd"] = {
            "proj_total": proj_svhd,
            "proj_to_date": proj_svhd * season_elapsed_fraction,
            "actual": a_svhd,
            "delta_volume": a_svhd - (proj_svhd * season_elapsed_fraction),
            # Rate proxy: SVHD per appearance.
            "proj_rate": None,  # not meaningful as a sustainable rate
            "actual_rate": None,
            "delta_rate": None,
        }

        # ERA — pure rate stat (lower is better)
        proj_era = d.get("proj_era")
        a_era = d.get("a_era") if a_ip > 0 else None
        cats["era"] = {
            "proj_total": proj_era,
            "proj_to_date": proj_era,
            "actual": a_era,
            "delta_volume": None,
            "proj_rate": proj_era,
            "actual_rate": a_era,
            "delta_rate": _delta(a_era, proj_era) if (proj_era is not None and a_era is not None) else None,
        }

        # WHIP — pure rate stat (lower is better)
        proj_whip = d.get("proj_whip")
        a_whip = d.get("a_whip") if a_ip > 0 else None
        cats["whip"] = {
            "proj_total": proj_whip,
            "proj_to_date": proj_whip,
            "actual": a_whip,
            "delta_volume": None,
            "proj_rate": proj_whip,
            "actual_rate": a_whip,
            "delta_rate": _delta(a_whip, proj_whip) if (proj_whip is not None and a_whip is not None) else None,
        }

        out.append({
            "mlb_id": d["mlb_id"],
            "name": d["full_name"],
            "team": d.get("team"),
            "primary_position": d.get("primary_position"),
            "eligible_positions": d.get("eligible_positions"),
            "player_type": "pitcher",
            "overall_rank": d.get("overall_rank"),
            "position_rank": d.get("position_rank"),
            "proj_ip": proj_ip,
            "actual_ip": a_ip,
            "actual_g": d.get("a_g") or 0,
            "actual_gs": d.get("a_gs") or 0,
            "expected_ip_to_date": proj_ip * season_elapsed_fraction,
            "categories": cats,
        })

    return out


def compute_performance(
    season: int,
    player_type: Literal["hitter", "pitcher"],
    season_elapsed_fraction: float,
) -> list[dict]:
    if player_type == "hitter":
        return compute_hitter_performance(season, season_elapsed_fraction)
    return compute_pitcher_performance(season, season_elapsed_fraction)


# ── Focused, concurrent refresh of season-to-date actuals ──


_HITTER_UPSERT = """
    INSERT INTO batting_stats
      (mlb_id, season, games, plate_appearances, at_bats, runs, hits,
       doubles, triples, home_runs, rbi, stolen_bases, caught_stealing,
       walks, strikeouts, hit_by_pitch, sac_flies, batting_average,
       obp, slg, ops, total_bases)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT (mlb_id, season) DO UPDATE SET
      games = EXCLUDED.games,
      plate_appearances = EXCLUDED.plate_appearances,
      at_bats = EXCLUDED.at_bats, runs = EXCLUDED.runs, hits = EXCLUDED.hits,
      doubles = EXCLUDED.doubles, triples = EXCLUDED.triples,
      home_runs = EXCLUDED.home_runs, rbi = EXCLUDED.rbi,
      stolen_bases = EXCLUDED.stolen_bases, caught_stealing = EXCLUDED.caught_stealing,
      walks = EXCLUDED.walks, strikeouts = EXCLUDED.strikeouts,
      hit_by_pitch = EXCLUDED.hit_by_pitch, sac_flies = EXCLUDED.sac_flies,
      batting_average = EXCLUDED.batting_average, obp = EXCLUDED.obp,
      slg = EXCLUDED.slg, ops = EXCLUDED.ops, total_bases = EXCLUDED.total_bases
"""

_PITCHER_UPSERT = """
    INSERT INTO pitching_stats
      (mlb_id, season, games, games_started, wins, losses, era, whip,
       innings_pitched, hits_allowed, runs_allowed, earned_runs,
       walks_allowed, strikeouts, home_runs_allowed, saves, holds, quality_starts)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT (mlb_id, season) DO UPDATE SET
      games = EXCLUDED.games, games_started = EXCLUDED.games_started,
      wins = EXCLUDED.wins, losses = EXCLUDED.losses,
      era = EXCLUDED.era, whip = EXCLUDED.whip,
      innings_pitched = EXCLUDED.innings_pitched, hits_allowed = EXCLUDED.hits_allowed,
      runs_allowed = EXCLUDED.runs_allowed, earned_runs = EXCLUDED.earned_runs,
      walks_allowed = EXCLUDED.walks_allowed, strikeouts = EXCLUDED.strikeouts,
      home_runs_allowed = EXCLUDED.home_runs_allowed,
      saves = EXCLUDED.saves, holds = EXCLUDED.holds,
      quality_starts = EXCLUDED.quality_starts
"""


async def _fetch_one(sem: asyncio.Semaphore, mlb_id: int, player_type: str, season: int):
    async with sem:
        try:
            if player_type == "hitter":
                return ("hitter", await get_batting_stats(mlb_id, season))
            return ("pitcher", await get_pitching_stats(mlb_id, season))
        except Exception as e:
            logger.warning(f"Failed to fetch {player_type} stats for {mlb_id}: {e}")
            return (player_type, None)


async def refresh_actuals_for_rankings(season: int, concurrency: int = 12) -> None:
    """Concurrently re-pull season-to-date actuals from MLB Stats API for every
    player ranked for `season`, then upsert into batting_stats / pitching_stats.

    Updates the module-level _refresh_state dict so callers can poll progress.
    """
    _refresh_state.update({
        "status": "running",
        "started_at": time.time(),
        "finished_at": None,
        "season": season,
        "total": 0,
        "done": 0,
        "errors": 0,
        "error_message": None,
    })
    try:
        conn = get_connection()
        rows = conn.execute(
            "SELECT mlb_id, player_type FROM rankings WHERE season = ?",
            (season,),
        ).fetchall()
        conn.close()
        targets = [(r["mlb_id"], r["player_type"]) for r in rows]
        _refresh_state["total"] = len(targets)
        logger.info(f"Refreshing 2026 actuals for {len(targets)} ranked players (concurrency={concurrency})")

        sem = asyncio.Semaphore(concurrency)
        tasks = [_fetch_one(sem, mlb_id, ptype, season) for mlb_id, ptype in targets]

        # Process and upsert as results come in (avoids holding 1300 dicts in memory).
        conn = get_connection()
        for fut in asyncio.as_completed(tasks):
            ptype, stats = await fut
            _refresh_state["done"] += 1
            if not stats:
                _refresh_state["errors"] += 1
                continue
            try:
                if ptype == "hitter":
                    conn.execute(_HITTER_UPSERT, (
                        stats["mlb_id"], stats["season"], stats["games"],
                        stats["plate_appearances"], stats["at_bats"],
                        stats["runs"], stats["hits"], stats["doubles"],
                        stats["triples"], stats["home_runs"],
                        stats["rbi"], stats["stolen_bases"], stats["caught_stealing"],
                        stats["walks"], stats["strikeouts"],
                        stats["hit_by_pitch"], stats["sac_flies"],
                        stats["batting_average"], stats["obp"], stats["slg"],
                        stats["ops"], stats["total_bases"],
                    ))
                else:
                    conn.execute(_PITCHER_UPSERT, (
                        stats["mlb_id"], stats["season"], stats["games"],
                        stats["games_started"], stats["wins"], stats["losses"],
                        stats["era"], stats["whip"], stats["innings_pitched"],
                        stats["hits_allowed"], stats["runs_allowed"],
                        stats["earned_runs"], stats["walks_allowed"],
                        stats["strikeouts"], stats["home_runs_allowed"],
                        stats["saves"], stats["holds"], stats["quality_starts"],
                    ))
            except Exception as e:
                _refresh_state["errors"] += 1
                logger.warning(f"Upsert failed for {stats.get('mlb_id')}: {e}")

            if _refresh_state["done"] % 100 == 0:
                conn.commit()
                logger.info(
                    f"  Refresh progress: {_refresh_state['done']}/{len(targets)}"
                )

        conn.commit()
        conn.close()

        _refresh_state["status"] = "completed"
        _refresh_state["finished_at"] = time.time()
        elapsed = _refresh_state["finished_at"] - _refresh_state["started_at"]
        logger.info(
            f"Refresh complete: {_refresh_state['done']} updated, "
            f"{_refresh_state['errors']} errors in {elapsed:.1f}s"
        )
    except Exception as e:
        _refresh_state["status"] = "failed"
        _refresh_state["finished_at"] = time.time()
        _refresh_state["error_message"] = str(e)
        logger.exception("Refresh failed")
