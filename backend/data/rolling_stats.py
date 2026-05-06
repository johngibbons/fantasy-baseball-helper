"""Fetch and aggregate game-log data into rolling windows for breakout detection.

This module is two layers:
  * Pure aggregation (`aggregate_batting_window`, `aggregate_pitching_window`):
    take a DataFrame of per-player game-log rows and produce a dict keyed by
    mlb_id. Easy to unit test without network calls.
  * Data fetch + persistence (`sync_rolling_stats`): wraps pybaseball calls,
    aggregates, and upserts into the rolling_*_stats tables. (Added in Task 3.)
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Iterable

import pandas as pd

from backend.database import get_connection

logger = logging.getLogger(__name__)

DEFAULT_WINDOWS = (7, 14, 30)


def _safe_int(val) -> int:
    try:
        return int(val) if val is not None and not pd.isna(val) else 0
    except (TypeError, ValueError):
        return 0


def _safe_float(val) -> float:
    try:
        return float(val) if val is not None and not pd.isna(val) else 0.0
    except (TypeError, ValueError):
        return 0.0


def aggregate_batting_window(df: pd.DataFrame) -> dict[int, dict]:
    """Aggregate per-game batting rows into per-player window totals.

    Expects columns: mlb_id, G, PA, AB, H, 2B, 3B, HR, R, RBI, SB, BB, SO,
    HBP, SF. Rows with missing mlb_id are dropped.
    """
    if df.empty:
        return {}

    valid = df.dropna(subset=["mlb_id"])
    if valid.empty:
        return {}

    out: dict[int, dict] = {}
    grouped = valid.groupby("mlb_id")
    for raw_pid, group in grouped:
        pid = _safe_int(raw_pid)
        if pid == 0:
            continue
        games = _safe_int(group["G"].sum())
        pa = _safe_int(group["PA"].sum())
        ab = _safe_int(group["AB"].sum())
        h = _safe_int(group["H"].sum())
        doubles = _safe_int(group["2B"].sum())
        triples = _safe_int(group["3B"].sum())
        hr = _safe_int(group["HR"].sum())
        r = _safe_int(group["R"].sum())
        rbi = _safe_int(group["RBI"].sum())
        sb = _safe_int(group["SB"].sum())
        bb = _safe_int(group["BB"].sum())
        k = _safe_int(group["SO"].sum())
        hbp = _safe_int(group["HBP"].sum())
        sf = _safe_int(group["SF"].sum())

        singles = h - doubles - triples - hr
        total_bases = singles + 2 * doubles + 3 * triples + 4 * hr

        batting_avg = (h / ab) if ab > 0 else 0.0
        obp_denom = ab + bb + hbp + sf
        obp = ((h + bb + hbp) / obp_denom) if obp_denom > 0 else 0.0
        slg = (total_bases / ab) if ab > 0 else 0.0
        ops = obp + slg

        out[pid] = {
            "games": games, "pa": pa, "ab": ab, "h": h, "hr": hr,
            "r": r, "rbi": rbi, "sb": sb, "bb": bb, "k": k,
            "hbp": hbp, "sf": sf, "total_bases": total_bases,
            "batting_avg": round(batting_avg, 4),
            "obp": round(obp, 4),
            "slg": round(slg, 4),
            "ops": round(ops, 4),
        }
    return out


def aggregate_pitching_window(df: pd.DataFrame) -> dict[int, dict]:
    """Aggregate per-game pitching rows into per-player window totals.

    Expects columns: mlb_id, G, GS, IP, SO, BB, H, ER, HR, SV, HLD, QS.
    """
    if df.empty:
        return {}

    valid = df.dropna(subset=["mlb_id"])
    if valid.empty:
        return {}

    out: dict[int, dict] = {}
    for raw_pid, group in valid.groupby("mlb_id"):
        pid = _safe_int(raw_pid)
        if pid == 0:
            continue
        games = _safe_int(group["G"].sum())
        games_started = _safe_int(group["GS"].sum())
        ip = _safe_float(group["IP"].sum())
        k = _safe_int(group["SO"].sum())
        bb = _safe_int(group["BB"].sum())
        h = _safe_int(group["H"].sum())
        er = _safe_int(group["ER"].sum())
        hr = _safe_int(group["HR"].sum())
        sv = _safe_int(group["SV"].sum())
        hld = _safe_int(group["HLD"].sum())
        qs = _safe_int(group["QS"].sum())

        era = (er * 9 / ip) if ip > 0 else 0.0
        whip = ((h + bb) / ip) if ip > 0 else 0.0
        k_per_9 = (k * 9 / ip) if ip > 0 else 0.0
        bb_per_9 = (bb * 9 / ip) if ip > 0 else 0.0

        out[pid] = {
            "games": games, "games_started": games_started,
            "ip": round(ip, 2),
            "k": k, "bb": bb, "h_allowed": h, "er": er, "hr_allowed": hr,
            "saves": sv, "holds": hld, "quality_starts": qs,
            "era": era,
            "whip": whip,
            "k_per_9": k_per_9,
            "bb_per_9": bb_per_9,
        }
    return out


def _fetch_batting_window(start_dt: date, end_dt: date) -> dict[int, dict]:
    """Fetch per-player batting aggregates for the date range from pybaseball.

    Uses ``batting_stats_range`` which scrapes Baseball Reference and returns
    one row per player aggregated over the date window.
    """
    try:
        from pybaseball import batting_stats_range
    except ImportError:
        logger.error("pybaseball not installed; cannot fetch rolling batting stats")
        return {}

    try:
        df = batting_stats_range(start_dt.isoformat(), end_dt.isoformat())
    except Exception as e:
        logger.error(f"batting_stats_range failed for {start_dt}..{end_dt}: {e}")
        return {}

    if df is None or df.empty:
        return {}

    # batting_stats_range returns "mlbID" — rename so aggregate_batting_window finds it
    if "mlbID" in df.columns:
        df = df.rename(columns={"mlbID": "mlb_id"})
    elif "mlb_id" not in df.columns:
        logger.error("batting_stats_range returned no mlb_id column; got: %s",
                     list(df.columns))
        return {}

    # Coerce required columns to numeric, filling missing with 0
    required = ["G", "PA", "AB", "H", "2B", "3B", "HR", "R", "RBI", "SB",
                "BB", "SO", "HBP", "SF"]
    for col in required:
        if col not in df.columns:
            df[col] = 0

    return aggregate_batting_window(df)


def _fetch_pitching_window(start_dt: date, end_dt: date) -> dict[int, dict]:
    """Fetch per-player pitching aggregates for the date range."""
    try:
        from pybaseball import pitching_stats_range
    except ImportError:
        logger.error("pybaseball not installed; cannot fetch rolling pitching stats")
        return {}

    try:
        df = pitching_stats_range(start_dt.isoformat(), end_dt.isoformat())
    except Exception as e:
        logger.error(f"pitching_stats_range failed for {start_dt}..{end_dt}: {e}")
        return {}

    if df is None or df.empty:
        return {}

    if "mlbID" in df.columns:
        df = df.rename(columns={"mlbID": "mlb_id"})
    elif "mlb_id" not in df.columns:
        logger.error("pitching_stats_range returned no mlb_id column; got: %s",
                     list(df.columns))
        return {}

    required = ["G", "GS", "IP", "SO", "BB", "H", "ER", "HR", "SV", "HLD", "QS"]
    for col in required:
        if col not in df.columns:
            df[col] = 0

    return aggregate_pitching_window(df)


def sync_rolling_stats(
    season: int,
    windows: Iterable[int] = DEFAULT_WINDOWS,
    today: date | None = None,
) -> None:
    """Fetch + upsert rolling stats for each window.

    Idempotent — re-running same day overwrites existing rows for that
    (mlb_id, season, window_days). Sets as_of_date to ``today``.
    """
    today = today or date.today()
    conn = get_connection()

    for window_days in windows:
        start_dt = today - timedelta(days=window_days)
        end_dt = today

        bat = _fetch_batting_window(start_dt, end_dt)
        logger.info(f"Window {window_days}d batting: {len(bat)} players")
        for mlb_id, row in bat.items():
            conn.execute(
                """INSERT INTO rolling_batting_stats
                   (mlb_id, season, window_days, as_of_date,
                    games, pa, ab, r, h, hr, rbi, sb, bb, k, hbp, sf,
                    total_bases, batting_avg, obp, slg, ops)
                   VALUES (?, ?, ?, ?,
                           ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                           ?, ?, ?, ?, ?)
                   ON CONFLICT (mlb_id, season, window_days) DO UPDATE SET
                     as_of_date = EXCLUDED.as_of_date,
                     games = EXCLUDED.games, pa = EXCLUDED.pa, ab = EXCLUDED.ab,
                     r = EXCLUDED.r, h = EXCLUDED.h, hr = EXCLUDED.hr,
                     rbi = EXCLUDED.rbi, sb = EXCLUDED.sb, bb = EXCLUDED.bb,
                     k = EXCLUDED.k, hbp = EXCLUDED.hbp, sf = EXCLUDED.sf,
                     total_bases = EXCLUDED.total_bases,
                     batting_avg = EXCLUDED.batting_avg, obp = EXCLUDED.obp,
                     slg = EXCLUDED.slg, ops = EXCLUDED.ops""",
                (
                    mlb_id, season, window_days, today.isoformat(),
                    row["games"], row["pa"], row["ab"], row["r"], row["h"],
                    row["hr"], row["rbi"], row["sb"], row["bb"], row["k"],
                    row["hbp"], row["sf"], row["total_bases"],
                    row["batting_avg"], row["obp"], row["slg"], row["ops"],
                ),
            )

        pit = _fetch_pitching_window(start_dt, end_dt)
        logger.info(f"Window {window_days}d pitching: {len(pit)} players")
        for mlb_id, row in pit.items():
            conn.execute(
                """INSERT INTO rolling_pitching_stats
                   (mlb_id, season, window_days, as_of_date,
                    games, games_started, ip, k, bb, h_allowed, er, hr_allowed,
                    saves, holds, quality_starts, era, whip, k_per_9, bb_per_9)
                   VALUES (?, ?, ?, ?,
                           ?, ?, ?, ?, ?, ?, ?, ?,
                           ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (mlb_id, season, window_days) DO UPDATE SET
                     as_of_date = EXCLUDED.as_of_date,
                     games = EXCLUDED.games, games_started = EXCLUDED.games_started,
                     ip = EXCLUDED.ip, k = EXCLUDED.k, bb = EXCLUDED.bb,
                     h_allowed = EXCLUDED.h_allowed, er = EXCLUDED.er,
                     hr_allowed = EXCLUDED.hr_allowed, saves = EXCLUDED.saves,
                     holds = EXCLUDED.holds, quality_starts = EXCLUDED.quality_starts,
                     era = EXCLUDED.era, whip = EXCLUDED.whip,
                     k_per_9 = EXCLUDED.k_per_9, bb_per_9 = EXCLUDED.bb_per_9""",
                (
                    mlb_id, season, window_days, today.isoformat(),
                    row["games"], row["games_started"], row["ip"], row["k"],
                    row["bb"], row["h_allowed"], row["er"], row["hr_allowed"],
                    row["saves"], row["holds"], row["quality_starts"],
                    row["era"], row["whip"], row["k_per_9"], row["bb_per_9"],
                ),
            )

    conn.commit()
    conn.close()
