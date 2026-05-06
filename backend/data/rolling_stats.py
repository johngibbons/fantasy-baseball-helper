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

import pandas as pd

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
