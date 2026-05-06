# Breakout Finder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two new tabs to `/waivers` — "Hot + Sustainable" (recent production extrapolated to RoS via MCW, filtered by Statcast sustainability) and "Stealth Breakouts" (skill-change z-score watch list) — backed by a daily sync of rolling stats and per-player skill baselines.

**Architecture:** Three new tables (`rolling_batting_stats`, `rolling_pitching_stats`, `statcast_baselines`) populated by daily cron. Two new backend modules (`backend/data/rolling_stats.py`, `backend/analysis/skill_baselines.py`) plus a `breakouts.py` engine that branches on `view`. Frontend refactors `/waivers` into a tabbed page with three sibling components.

**Tech Stack:** Python 3.12, pytest, FastAPI, pybaseball (already installed); Next.js 15, React 19, Jest, React Testing Library.

**Spec:** `docs/superpowers/specs/2026-05-05-breakout-finder-design.md` — read this before starting.

**Why this matters (read before implementing):**
- The current `/waivers` page is excellent for "who improves my team based on full-season projections" but gives no signal on *current form*. Players in the middle of a real breakout (hot recent stats, with underlying metrics that suggest the run is not luck) are the highest-value waiver pickups, and the projections-based view often understates them because preseason ATC DC was set before the skill change appeared.
- We already pay the cost of pulling Statcast for the offseason draft tool — the data is sitting in the DB. The marginal cost of adding `compute_skill_baselines` and a daily rolling-stats sync is small, and unlocks an entirely new view.

---

## File Structure

**New backend files:**
- `backend/data/rolling_stats.py` — fetch + aggregate game logs into 7/14/30-day windows
- `backend/analysis/skill_baselines.py` — compute per-player metric deltas, z-scores, sustainability composites
- `backend/analysis/breakouts.py` — Hot + Stealth view engines
- `backend/scripts/daily_breakout_sync.py` — orchestrator script for the daily cron

**Modified backend files:**
- `backend/database.py` — add three new tables
- `backend/analysis/waivers.py` — refactor `_assign_faab_bids` into a public, parameterized helper
- `backend/api/routes.py` — add `POST /api/breakouts/recommendations`

**New backend tests:**
- `tests/backend/data/test_rolling_stats.py`
- `tests/backend/analysis/test_skill_baselines.py`
- `tests/backend/analysis/test_breakouts.py`

**New frontend files:**
- `src/app/api/breakouts/recommendations/route.ts` — Next.js orchestrator
- `src/app/waivers/_components/ProjectionsTab.tsx` — extracted from current page
- `src/app/waivers/_components/HotTab.tsx`
- `src/app/waivers/_components/StealthTab.tsx`

**Modified frontend files:**
- `src/app/waivers/page.tsx` — add tab strip, render active tab

---

## Task 1: Database schema for rolling stats and baselines

**Files:**
- Modify: `backend/database.py`
- Test: `tests/backend/test_database_schema.py`

- [ ] **Step 1: Write the failing test**

Create `tests/backend/test_database_schema.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/backend/test_database_schema.py -v`
Expected: FAIL — tables don't exist yet.

- [ ] **Step 3: Add new tables to `init_db()`**

Edit `backend/database.py`. Find the section after `statcast_pitching` table creation (around line 308 in the analytics schema branch) and add three new `CREATE TABLE` statements before the existing `CREATE INDEX` calls. Then mirror the same additions in the SQLite branch (around line 530+).

For the analytics (Postgres) branch, insert after the existing `statcast_pitching` CREATE TABLE:

```python
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rolling_batting_stats (
            mlb_id INTEGER NOT NULL,
            season INTEGER NOT NULL,
            window_days INTEGER NOT NULL,
            as_of_date DATE NOT NULL,
            games INTEGER DEFAULT 0,
            pa INTEGER DEFAULT 0,
            ab INTEGER DEFAULT 0,
            r INTEGER DEFAULT 0,
            h INTEGER DEFAULT 0,
            hr INTEGER DEFAULT 0,
            rbi INTEGER DEFAULT 0,
            sb INTEGER DEFAULT 0,
            bb INTEGER DEFAULT 0,
            k INTEGER DEFAULT 0,
            hbp INTEGER DEFAULT 0,
            sf INTEGER DEFAULT 0,
            total_bases INTEGER DEFAULT 0,
            batting_avg REAL DEFAULT 0,
            obp REAL DEFAULT 0,
            slg REAL DEFAULT 0,
            ops REAL DEFAULT 0,
            updated_at TIMESTAMP DEFAULT NOW(),
            PRIMARY KEY (mlb_id, season, window_days),
            FOREIGN KEY (mlb_id) REFERENCES players(mlb_id)
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rolling_pitching_stats (
            mlb_id INTEGER NOT NULL,
            season INTEGER NOT NULL,
            window_days INTEGER NOT NULL,
            as_of_date DATE NOT NULL,
            games INTEGER DEFAULT 0,
            games_started INTEGER DEFAULT 0,
            ip REAL DEFAULT 0,
            k INTEGER DEFAULT 0,
            bb INTEGER DEFAULT 0,
            h_allowed INTEGER DEFAULT 0,
            er INTEGER DEFAULT 0,
            hr_allowed INTEGER DEFAULT 0,
            saves INTEGER DEFAULT 0,
            holds INTEGER DEFAULT 0,
            quality_starts INTEGER DEFAULT 0,
            era REAL DEFAULT 0,
            whip REAL DEFAULT 0,
            k_per_9 REAL DEFAULT 0,
            bb_per_9 REAL DEFAULT 0,
            updated_at TIMESTAMP DEFAULT NOW(),
            PRIMARY KEY (mlb_id, season, window_days),
            FOREIGN KEY (mlb_id) REFERENCES players(mlb_id)
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS statcast_baselines (
            mlb_id INTEGER NOT NULL,
            season INTEGER NOT NULL,
            player_type TEXT CHECK(player_type IN ('hitter', 'pitcher')),
            delta_xwoba REAL,
            delta_barrel_pct REAL,
            delta_hard_hit_pct REAL,
            delta_sprint_speed REAL,
            delta_xera REAL,
            delta_whiff_pct REAL,
            delta_k_pct REAL,
            delta_bb_pct REAL,
            delta_chase_rate REAL,
            skill_change_zscore REAL,
            sustainability_score REAL,
            baseline_source TEXT,
            qualifies_pa_ip INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT NOW(),
            PRIMARY KEY (mlb_id, season),
            FOREIGN KEY (mlb_id) REFERENCES players(mlb_id)
        );
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_rolling_batting_window ON analytics.rolling_batting_stats(season, window_days);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_rolling_pitching_window ON analytics.rolling_pitching_stats(season, window_days);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_baselines_zscore ON analytics.statcast_baselines(season, skill_change_zscore DESC);")
```

For the SQLite branch (used for local dev/testing), add the same three CREATE TABLE statements with `NOW()` replaced by `CURRENT_TIMESTAMP` and SERIAL/REFERENCES dropped if needed — copy the existing `statcast_batting` table's SQLite definition style.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/backend/test_database_schema.py -v`
Expected: All three tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/database.py tests/backend/test_database_schema.py
git commit -m "feat(db): add rolling_stats and statcast_baselines tables"
```

---

## Task 2: Rolling stats — pure aggregation function

This task isolates the aggregation math from data fetching, so it's testable without mocking pybaseball.

**Files:**
- Create: `backend/data/rolling_stats.py`
- Test: `tests/backend/data/test_rolling_stats.py`

- [ ] **Step 1: Write the failing test**

Create `tests/backend/data/test_rolling_stats.py`:

```python
"""Tests for rolling-window stat aggregation."""

import pandas as pd
import pytest

from backend.data.rolling_stats import (
    aggregate_batting_window,
    aggregate_pitching_window,
)


def test_aggregate_batting_window_sums_counting_stats():
    df = pd.DataFrame([
        {"mlb_id": 100, "G": 5, "PA": 22, "AB": 18, "H": 7, "2B": 2, "3B": 0,
         "HR": 2, "R": 4, "RBI": 6, "SB": 1, "BB": 3, "SO": 4, "HBP": 1, "SF": 0},
        {"mlb_id": 100, "G": 3, "PA": 14, "AB": 12, "H": 4, "2B": 1, "3B": 0,
         "HR": 1, "R": 3, "RBI": 2, "SB": 0, "BB": 2, "SO": 3, "HBP": 0, "SF": 0},
    ])
    out = aggregate_batting_window(df)
    row = out[100]
    assert row["games"] == 8
    assert row["pa"] == 36
    assert row["ab"] == 30
    assert row["h"] == 11
    assert row["hr"] == 3
    assert row["r"] == 7
    assert row["rbi"] == 8
    assert row["sb"] == 1
    assert row["bb"] == 5
    assert row["k"] == 7
    assert row["hbp"] == 1
    assert row["sf"] == 0


def test_aggregate_batting_window_computes_rate_stats():
    df = pd.DataFrame([
        {"mlb_id": 100, "G": 1, "PA": 10, "AB": 8, "H": 4, "2B": 1, "3B": 0,
         "HR": 1, "R": 2, "RBI": 3, "SB": 0, "BB": 2, "SO": 2, "HBP": 0, "SF": 0},
    ])
    out = aggregate_batting_window(df)
    row = out[100]
    # batting_avg = 4/8 = .500
    assert row["batting_avg"] == pytest.approx(0.500)
    # OBP = (4 + 2 + 0) / (8 + 2 + 0 + 0) = 6/10 = .600
    assert row["obp"] == pytest.approx(0.600)
    # TB = 4 + 1 + 0 + 1*3 = 4 + 1 + 3 = 8 (singles=2, doubles=1, triples=0, hr=1)
    # singles = 4 - 1 - 0 - 1 = 2
    # TB = 2 + 2*1 + 3*0 + 4*1 = 2 + 2 + 0 + 4 = 8
    assert row["total_bases"] == 8
    # SLG = 8/8 = 1.000
    assert row["slg"] == pytest.approx(1.000)
    # OPS = .600 + 1.000 = 1.600
    assert row["ops"] == pytest.approx(1.600)


def test_aggregate_batting_window_skips_unknown_ids():
    df = pd.DataFrame([
        {"mlb_id": None, "G": 1, "PA": 4, "AB": 4, "H": 1, "2B": 0, "3B": 0,
         "HR": 0, "R": 0, "RBI": 0, "SB": 0, "BB": 0, "SO": 1, "HBP": 0, "SF": 0},
    ])
    out = aggregate_batting_window(df)
    assert out == {}


def test_aggregate_pitching_window_sums_and_rates():
    df = pd.DataFrame([
        {"mlb_id": 200, "G": 2, "GS": 2, "IP": 12.0, "SO": 14, "BB": 3, "H": 9,
         "ER": 3, "HR": 1, "SV": 0, "HLD": 0, "QS": 1},
        {"mlb_id": 200, "G": 1, "GS": 1, "IP": 6.0, "SO": 7, "BB": 1, "H": 4,
         "ER": 1, "HR": 0, "SV": 0, "HLD": 0, "QS": 1},
    ])
    out = aggregate_pitching_window(df)
    row = out[200]
    assert row["games"] == 3
    assert row["games_started"] == 3
    assert row["ip"] == pytest.approx(18.0)
    assert row["k"] == 21
    assert row["bb"] == 4
    assert row["h_allowed"] == 13
    assert row["er"] == 4
    assert row["hr_allowed"] == 1
    assert row["quality_starts"] == 2
    # ERA = (4 * 9) / 18 = 2.00
    assert row["era"] == pytest.approx(2.00)
    # WHIP = (13 + 4) / 18 = .944
    assert row["whip"] == pytest.approx(17 / 18)
    # K/9 = 21 * 9 / 18 = 10.5
    assert row["k_per_9"] == pytest.approx(10.5)
    # BB/9 = 4 * 9 / 18 = 2.0
    assert row["bb_per_9"] == pytest.approx(2.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/backend/data/test_rolling_stats.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement the aggregation functions**

Create `backend/data/rolling_stats.py`:

```python
"""Fetch and aggregate game-log data into rolling windows for breakout detection.

This module is two layers:
  * Pure aggregation (`aggregate_batting_window`, `aggregate_pitching_window`):
    take a DataFrame of per-player game-log rows and produce a dict keyed by
    mlb_id. Easy to unit test without network calls.
  * Data fetch + persistence (`sync_rolling_stats`): wraps pybaseball calls,
    aggregates, and upserts into the rolling_*_stats tables.
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
            "era": round(era, 3),
            "whip": round(whip, 3),
            "k_per_9": round(k_per_9, 2),
            "bb_per_9": round(bb_per_9, 2),
        }
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/backend/data/test_rolling_stats.py -v`
Expected: All four tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/data/rolling_stats.py tests/backend/data/test_rolling_stats.py
git commit -m "feat(rolling-stats): add per-window aggregation functions"
```

---

## Task 3: Rolling stats — fetch & persistence

**Files:**
- Modify: `backend/data/rolling_stats.py`
- Test: `tests/backend/data/test_rolling_stats.py` (add tests)

- [ ] **Step 1: Add the failing tests for `sync_rolling_stats`**

Append to `tests/backend/data/test_rolling_stats.py`:

```python
from unittest.mock import patch, MagicMock
from datetime import date


@patch("backend.data.rolling_stats._fetch_batting_window")
@patch("backend.data.rolling_stats._fetch_pitching_window")
@patch("backend.data.rolling_stats.get_connection")
def test_sync_rolling_stats_upserts_each_window(
    mock_get_conn, mock_fetch_pit, mock_fetch_bat
):
    # Two windows requested; each fetch returns a single-player aggregate
    mock_fetch_bat.side_effect = [
        {100: {"games": 5, "pa": 20, "ab": 18, "h": 7, "hr": 2, "r": 4,
               "rbi": 5, "sb": 1, "bb": 2, "k": 4, "hbp": 0, "sf": 0,
               "total_bases": 12, "batting_avg": 0.389, "obp": 0.450,
               "slg": 0.667, "ops": 1.117}},
        {100: {"games": 10, "pa": 40, "ab": 36, "h": 13, "hr": 4, "r": 8,
               "rbi": 10, "sb": 2, "bb": 4, "k": 8, "hbp": 0, "sf": 0,
               "total_bases": 24, "batting_avg": 0.361, "obp": 0.425,
               "slg": 0.667, "ops": 1.092}},
    ]
    mock_fetch_pit.side_effect = [{}, {}]

    conn = MagicMock()
    mock_get_conn.return_value = conn

    from backend.data.rolling_stats import sync_rolling_stats
    sync_rolling_stats(season=2026, windows=(7, 14), today=date(2026, 5, 5))

    # Two batting fetches, two pitching fetches (one per window)
    assert mock_fetch_bat.call_count == 2
    assert mock_fetch_pit.call_count == 2

    # Each upsert call uses the rolling_batting_stats table
    insert_calls = [c for c in conn.execute.call_args_list
                    if "rolling_batting_stats" in str(c.args[0])]
    assert len(insert_calls) == 2  # one per window per player

    conn.commit.assert_called()


@patch("backend.data.rolling_stats._fetch_batting_window")
@patch("backend.data.rolling_stats._fetch_pitching_window")
@patch("backend.data.rolling_stats.get_connection")
def test_sync_rolling_stats_handles_empty_window(
    mock_get_conn, mock_fetch_pit, mock_fetch_bat
):
    mock_fetch_bat.return_value = {}
    mock_fetch_pit.return_value = {}
    conn = MagicMock()
    mock_get_conn.return_value = conn

    from backend.data.rolling_stats import sync_rolling_stats
    # Should complete without error even when no data is returned
    sync_rolling_stats(season=2026, windows=(7,), today=date(2026, 5, 5))
    conn.commit.assert_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/backend/data/test_rolling_stats.py -v`
Expected: New tests FAIL — `sync_rolling_stats`, `_fetch_batting_window`, `_fetch_pitching_window` not defined.

- [ ] **Step 3: Implement the fetch + sync layer**

Append to `backend/data/rolling_stats.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/backend/data/test_rolling_stats.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/data/rolling_stats.py tests/backend/data/test_rolling_stats.py
git commit -m "feat(rolling-stats): add fetch + sync layer over pybaseball"
```

---

## Task 4: Skill baselines — pure delta math

**Files:**
- Create: `backend/analysis/skill_baselines.py`
- Test: `tests/backend/analysis/test_skill_baselines.py`

- [ ] **Step 1: Write the failing test**

Create `tests/backend/analysis/test_skill_baselines.py`:

```python
"""Tests for skill-baseline delta math and composites."""

import pytest

from backend.analysis.skill_baselines import (
    compute_metric_deltas,
    compute_skill_change_zscore,
    compute_sustainability_score,
    LEAGUE_AVG_BARREL_PCT,
    LEAGUE_AVG_HARD_HIT_PCT,
    LEAGUE_AVG_WHIFF_PCT,
)


class TestComputeMetricDeltas:
    def test_hitter_deltas_use_prior_season_when_available(self):
        current = {"xwoba": 0.380, "barrel_pct": 12.0,
                   "hard_hit_pct": 45.0, "sprint_speed": 28.0}
        prior = {"xwoba": 0.330, "barrel_pct": 8.0,
                 "hard_hit_pct": 40.0, "sprint_speed": 27.5}
        result = compute_metric_deltas(current, prior, player_type="hitter")
        assert result["delta_xwoba"] == pytest.approx(0.050)
        assert result["delta_barrel_pct"] == pytest.approx(4.0)
        assert result["delta_hard_hit_pct"] == pytest.approx(5.0)
        assert result["delta_sprint_speed"] == pytest.approx(0.5)
        assert result["baseline_source"] == "prior_season"

    def test_hitter_falls_back_to_league_avg_when_no_prior(self):
        current = {"xwoba": 0.350, "barrel_pct": 10.0,
                   "hard_hit_pct": 38.0, "sprint_speed": 27.0}
        result = compute_metric_deltas(current, prior=None, player_type="hitter")
        # delta = current - league_avg
        assert result["delta_barrel_pct"] == pytest.approx(10.0 - LEAGUE_AVG_BARREL_PCT)
        assert result["delta_hard_hit_pct"] == pytest.approx(38.0 - LEAGUE_AVG_HARD_HIT_PCT)
        assert result["baseline_source"] == "league_avg"

    def test_pitcher_deltas_use_prior_season_when_available(self):
        current = {"xera": 3.20, "whiff_pct": 30.0, "k_pct": 28.0,
                   "bb_pct": 7.0, "chase_rate": 32.0}
        prior = {"xera": 4.10, "whiff_pct": 25.0, "k_pct": 22.0,
                 "bb_pct": 8.5, "chase_rate": 30.0}
        result = compute_metric_deltas(current, prior, player_type="pitcher")
        # xERA delta is current - prior; lower is better, but we store the raw delta
        assert result["delta_xera"] == pytest.approx(-0.90)
        assert result["delta_whiff_pct"] == pytest.approx(5.0)
        assert result["delta_k_pct"] == pytest.approx(6.0)
        assert result["delta_bb_pct"] == pytest.approx(-1.5)
        assert result["delta_chase_rate"] == pytest.approx(2.0)


class TestComputeSkillChangeZscore:
    def test_hitter_zscore_aggregates_weighted_metrics(self):
        # Population stats: deltas have known mean/sd
        # Each metric's value is itself a z-score-like number for testing
        deltas = {
            "delta_xwoba": 0.050,    # weight 3
            "delta_barrel_pct": 5.0, # weight 2
            "delta_hard_hit_pct": 3.0,  # weight 1.5
            "delta_sprint_speed": 0.5,  # weight 1
        }
        # Caller provides population means + sds for each metric
        pop_stats = {
            "delta_xwoba": (0.0, 0.025),       # z = 0.050 / 0.025 = 2.0
            "delta_barrel_pct": (0.0, 2.5),     # z = 5.0 / 2.5 = 2.0
            "delta_hard_hit_pct": (0.0, 3.0),   # z = 3.0 / 3.0 = 1.0
            "delta_sprint_speed": (0.0, 0.5),   # z = 0.5 / 0.5 = 1.0
        }
        z = compute_skill_change_zscore(deltas, pop_stats, player_type="hitter")
        # Weighted avg: (3*2.0 + 2*2.0 + 1.5*1.0 + 1.0*1.0) / (3 + 2 + 1.5 + 1.0)
        # = (6 + 4 + 1.5 + 1.0) / 7.5 = 12.5 / 7.5 = 1.667
        assert z == pytest.approx(12.5 / 7.5, rel=1e-3)

    def test_pitcher_zscore_inverts_xera(self):
        # Lower xERA is better, so the contribution should be inverted
        deltas = {
            "delta_xera": -0.50,       # weight 3, lower is better
            "delta_whiff_pct": 4.0,    # weight 2
            "delta_k_pct": 2.0,        # weight 1
            "delta_bb_pct": -0.8,      # weight 1 (inverted: lower is better)
            "delta_chase_rate": 1.0,    # weight 1
        }
        pop_stats = {
            "delta_xera": (0.0, 0.50),
            "delta_whiff_pct": (0.0, 2.0),
            "delta_k_pct": (0.0, 2.0),
            "delta_bb_pct": (0.0, 0.8),
            "delta_chase_rate": (0.0, 1.0),
        }
        z = compute_skill_change_zscore(deltas, pop_stats, player_type="pitcher")
        # Inverted xERA: -(-0.50/0.50) = 1.0  (xERA dropped, that's good)
        # whiff: 4.0/2.0 = 2.0
        # k_pct - bb_pct: spec uses K%-BB% as one combined weight×2 metric.
        # k_pct delta z: 2.0/2.0 = 1.0
        # bb_pct (inverted): -(-0.8/0.8) = 1.0
        # combined K%-BB% z = (1.0 + 1.0) / 2 = 1.0, weight 2
        # chase_rate z: 1.0/1.0 = 1.0, weight 1
        # weighted avg = (3*1.0 + 2*2.0 + 2*1.0 + 1*1.0) / (3+2+2+1) = 10/8 = 1.25
        assert z == pytest.approx(1.25, rel=1e-3)

    def test_zscore_returns_none_when_no_metrics_available(self):
        z = compute_skill_change_zscore({}, {}, player_type="hitter")
        assert z is None


class TestComputeSustainabilityScore:
    def test_hitter_score_high_when_metrics_strong(self):
        current = {
            "xwoba": 0.385, "woba": 0.380,    # gap = +0.005 (good)
            "barrel_pct": 12.0,                # well above league avg 7.0
            "hard_hit_pct": 45.0,              # above league avg 35.0
        }
        score = compute_sustainability_score(current, player_type="hitter")
        assert score >= 70

    def test_hitter_score_low_when_overperforming(self):
        current = {
            "xwoba": 0.300, "woba": 0.380,    # gap = -0.080 (BABIP luck)
            "barrel_pct": 5.0,                 # below league avg
            "hard_hit_pct": 30.0,              # below league avg
        }
        score = compute_sustainability_score(current, player_type="hitter")
        assert score <= 40

    def test_pitcher_score_high_when_xera_below_era(self):
        current = {
            "xera": 2.80, "era": 3.50,    # xera below era is good for pitcher
            "whiff_pct": 32.0,             # well above league avg 25.0
            "csw_pct": 32.0,               # above league avg 28.0
            "bb_pct": 6.0,                 # below league avg 8.5
        }
        score = compute_sustainability_score(current, player_type="pitcher")
        assert score >= 70

    def test_returns_zero_when_metrics_missing(self):
        score = compute_sustainability_score({}, player_type="hitter")
        assert score == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/backend/analysis/test_skill_baselines.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement the math**

Create `backend/analysis/skill_baselines.py`:

```python
"""Compute per-player skill-change baselines: deltas vs prior season,
composite z-scores, and sustainability scores.

The Stealth Breakouts view ranks players by ``skill_change_zscore``.
The Hot + Sustainable view filters/sorts using ``sustainability_score``.
"""

from __future__ import annotations

import logging
import math
from typing import Optional

logger = logging.getLogger(__name__)

# League averages — refreshed annually, hardcoded constants are fine.
LEAGUE_AVG_BARREL_PCT = 7.0
LEAGUE_AVG_HARD_HIT_PCT = 35.0
LEAGUE_AVG_WHIFF_PCT = 25.0
LEAGUE_AVG_CSW_PCT = 28.0
LEAGUE_AVG_BB_PCT = 8.5
LEAGUE_AVG_K_PCT = 22.0
LEAGUE_AVG_XWOBA = 0.320
LEAGUE_AVG_XERA = 4.10
LEAGUE_AVG_SPRINT_SPEED = 27.0
LEAGUE_AVG_CHASE_RATE = 30.0

# Z-score weights for skill-change aggregation
HITTER_WEIGHTS = {
    "delta_xwoba": 3.0,
    "delta_barrel_pct": 2.0,
    "delta_hard_hit_pct": 1.5,
    "delta_sprint_speed": 1.0,
}
PITCHER_WEIGHTS = {
    "delta_xera": 3.0,           # inverted: lower is better
    "delta_whiff_pct": 2.0,
    "delta_k_minus_bb_pct": 2.0,  # combined K% and BB%
    "delta_chase_rate": 1.0,
}


def _league_avg_for(metric: str) -> float:
    return {
        "xwoba": LEAGUE_AVG_XWOBA,
        "barrel_pct": LEAGUE_AVG_BARREL_PCT,
        "hard_hit_pct": LEAGUE_AVG_HARD_HIT_PCT,
        "sprint_speed": LEAGUE_AVG_SPRINT_SPEED,
        "xera": LEAGUE_AVG_XERA,
        "whiff_pct": LEAGUE_AVG_WHIFF_PCT,
        "k_pct": LEAGUE_AVG_K_PCT,
        "bb_pct": LEAGUE_AVG_BB_PCT,
        "chase_rate": LEAGUE_AVG_CHASE_RATE,
    }.get(metric, 0.0)


def compute_metric_deltas(
    current: dict[str, Optional[float]],
    prior: Optional[dict[str, Optional[float]]],
    player_type: str,
) -> dict[str, Optional[float]]:
    """Compute current-season vs baseline deltas for one player.

    ``prior`` is the player's prior-season Statcast row (dict-like). If None,
    falls back to league averages and records ``baseline_source = 'league_avg'``.

    Returns a dict with ``delta_*`` keys appropriate to player_type plus
    ``baseline_source`` ("prior_season" | "league_avg").
    """
    metrics_for_type = {
        "hitter": ["xwoba", "barrel_pct", "hard_hit_pct", "sprint_speed"],
        "pitcher": ["xera", "whiff_pct", "k_pct", "bb_pct", "chase_rate"],
    }[player_type]

    if prior is not None and any(prior.get(m) is not None for m in metrics_for_type):
        baseline_source = "prior_season"
    else:
        baseline_source = "league_avg"

    out: dict[str, Optional[float]] = {"baseline_source": baseline_source}
    for m in metrics_for_type:
        cur_v = current.get(m)
        if cur_v is None:
            out[f"delta_{m}"] = None
            continue
        if baseline_source == "prior_season" and prior is not None and prior.get(m) is not None:
            base_v = prior[m]
        else:
            base_v = _league_avg_for(m)
        out[f"delta_{m}"] = cur_v - base_v
    return out


def compute_skill_change_zscore(
    deltas: dict[str, Optional[float]],
    pop_stats: dict[str, tuple[float, float]],
    player_type: str,
) -> Optional[float]:
    """Aggregate per-metric deltas into one weighted z-score.

    ``pop_stats`` maps metric_key -> (population_mean, population_sd).

    For pitchers, ``delta_xera`` is inverted (negative xERA delta = improving,
    which is good); ``delta_bb_pct`` is also inverted. Hitters: all metrics
    are "higher is better" so raw z-scores are used.
    """
    if player_type == "hitter":
        components = []
        for metric, weight in HITTER_WEIGHTS.items():
            if deltas.get(metric) is None or metric not in pop_stats:
                continue
            mean, sd = pop_stats[metric]
            if sd <= 0:
                continue
            z = (deltas[metric] - mean) / sd
            components.append((z, weight))
        if not components:
            return None
        total_w = sum(w for _, w in components)
        return sum(z * w for z, w in components) / total_w if total_w > 0 else None

    # Pitcher
    components: list[tuple[float, float]] = []
    if deltas.get("delta_xera") is not None and "delta_xera" in pop_stats:
        mean, sd = pop_stats["delta_xera"]
        if sd > 0:
            z = (deltas["delta_xera"] - mean) / sd
            components.append((-z, PITCHER_WEIGHTS["delta_xera"]))  # invert

    if deltas.get("delta_whiff_pct") is not None and "delta_whiff_pct" in pop_stats:
        mean, sd = pop_stats["delta_whiff_pct"]
        if sd > 0:
            z = (deltas["delta_whiff_pct"] - mean) / sd
            components.append((z, PITCHER_WEIGHTS["delta_whiff_pct"]))

    # K% - BB%: avg the K% z-score and the (inverted) BB% z-score
    k_z = None
    bb_z = None
    if deltas.get("delta_k_pct") is not None and "delta_k_pct" in pop_stats:
        mean, sd = pop_stats["delta_k_pct"]
        if sd > 0:
            k_z = (deltas["delta_k_pct"] - mean) / sd
    if deltas.get("delta_bb_pct") is not None and "delta_bb_pct" in pop_stats:
        mean, sd = pop_stats["delta_bb_pct"]
        if sd > 0:
            bb_z = -(deltas["delta_bb_pct"] - mean) / sd  # invert: lower BB is better
    pieces = [v for v in (k_z, bb_z) if v is not None]
    if pieces:
        components.append((sum(pieces) / len(pieces), PITCHER_WEIGHTS["delta_k_minus_bb_pct"]))

    if deltas.get("delta_chase_rate") is not None and "delta_chase_rate" in pop_stats:
        mean, sd = pop_stats["delta_chase_rate"]
        if sd > 0:
            z = (deltas["delta_chase_rate"] - mean) / sd
            components.append((z, PITCHER_WEIGHTS["delta_chase_rate"]))

    if not components:
        return None
    total_w = sum(w for _, w in components)
    return sum(z * w for z, w in components) / total_w if total_w > 0 else None


def compute_sustainability_score(
    current: dict[str, Optional[float]],
    player_type: str,
) -> float:
    """0-100 composite that surface stats are likely to hold up.

    Hitters: rewards positive xwOBA-wOBA gap, above-avg barrel%, above-avg
    hard-hit%. Pitchers: rewards xERA below ERA, above-avg whiff%, above-avg
    CSW%, below-avg BB%.

    Returns 0 when essential metrics are missing.
    """
    if player_type == "hitter":
        xwoba = current.get("xwoba")
        woba = current.get("woba")
        barrel = current.get("barrel_pct")
        hard_hit = current.get("hard_hit_pct")
        if xwoba is None or woba is None or barrel is None or hard_hit is None:
            return 0.0
        # gap_score: 50 base, +1 per +0.005 gap (capped 0..100)
        gap = xwoba - woba
        gap_score = 50 + (gap / 0.005) * 5
        gap_score = max(0.0, min(100.0, gap_score))
        # barrel ratio vs league avg (1.0 = league avg → 50)
        barrel_score = 50 + (barrel - LEAGUE_AVG_BARREL_PCT) * 5
        barrel_score = max(0.0, min(100.0, barrel_score))
        hard_hit_score = 50 + (hard_hit - LEAGUE_AVG_HARD_HIT_PCT) * 2.5
        hard_hit_score = max(0.0, min(100.0, hard_hit_score))
        return round((gap_score + barrel_score + hard_hit_score) / 3, 1)

    # Pitcher
    xera = current.get("xera")
    era = current.get("era")
    whiff = current.get("whiff_pct")
    csw = current.get("csw_pct")
    bb = current.get("bb_pct")
    if xera is None or era is None or whiff is None or csw is None or bb is None:
        return 0.0
    gap = era - xera  # positive when xera below era (good for pitcher)
    gap_score = 50 + (gap / 0.20) * 10
    gap_score = max(0.0, min(100.0, gap_score))
    whiff_score = 50 + (whiff - LEAGUE_AVG_WHIFF_PCT) * 4
    whiff_score = max(0.0, min(100.0, whiff_score))
    csw_score = 50 + (csw - LEAGUE_AVG_CSW_PCT) * 4
    csw_score = max(0.0, min(100.0, csw_score))
    bb_score = 50 + (LEAGUE_AVG_BB_PCT - bb) * 6  # lower BB is better
    bb_score = max(0.0, min(100.0, bb_score))
    return round((gap_score + whiff_score + csw_score + bb_score) / 4, 1)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/backend/analysis/test_skill_baselines.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/analysis/skill_baselines.py tests/backend/analysis/test_skill_baselines.py
git commit -m "feat(skill-baselines): add delta math + sustainability scoring"
```

---

## Task 5: Skill baselines — DB sync

**Files:**
- Modify: `backend/analysis/skill_baselines.py`
- Test: `tests/backend/analysis/test_skill_baselines.py` (add tests)

- [ ] **Step 1: Add the failing test for `compute_skill_baselines`**

Append to `tests/backend/analysis/test_skill_baselines.py`:

```python
from unittest.mock import patch, MagicMock


@patch("backend.analysis.skill_baselines.get_connection")
def test_compute_skill_baselines_writes_one_row_per_qualifying_player(mock_get_conn):
    conn = MagicMock()
    mock_get_conn.return_value = conn

    # Mock query returns: 1 hitter with current + prior data, qualifying PA
    # Statcast batting query (current season) → 1 row
    # Statcast batting query (prior season) → 1 row
    # Player count + PA query → 1 qualifying hitter
    def execute_side_effect(sql, params=()):
        cur = MagicMock()
        if "FROM statcast_batting" in sql and str(2025) in str(params):
            cur.fetchall.return_value = [
                {"mlb_id": 100, "xwoba": 0.330, "barrel_pct": 8.0,
                 "hard_hit_pct": 40.0, "sprint_speed": 27.5, "woba": 0.325}
            ]
        elif "FROM statcast_batting" in sql and str(2026) in str(params):
            cur.fetchall.return_value = [
                {"mlb_id": 100, "xwoba": 0.380, "barrel_pct": 12.0,
                 "hard_hit_pct": 45.0, "sprint_speed": 28.0, "woba": 0.385}
            ]
        elif "FROM statcast_pitching" in sql:
            cur.fetchall.return_value = []
        elif "FROM batting_stats" in sql:
            cur.fetchall.return_value = [{"mlb_id": 100, "plate_appearances": 80}]
        elif "FROM pitching_stats" in sql:
            cur.fetchall.return_value = []
        else:
            cur.fetchall.return_value = []
        return cur
    conn.execute.side_effect = execute_side_effect

    from backend.analysis.skill_baselines import compute_skill_baselines
    compute_skill_baselines(season=2026)

    # Look for an INSERT into statcast_baselines for our player
    insert_calls = [c for c in conn.execute.call_args_list
                    if "statcast_baselines" in str(c.args[0]) and "INSERT" in str(c.args[0])]
    assert len(insert_calls) >= 1
    inserted_args = insert_calls[0].args[1] if len(insert_calls[0].args) > 1 else ()
    assert 100 in inserted_args  # mlb_id present
    conn.commit.assert_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/backend/analysis/test_skill_baselines.py::test_compute_skill_baselines_writes_one_row_per_qualifying_player -v`
Expected: FAIL — `compute_skill_baselines` not defined.

- [ ] **Step 3: Implement `compute_skill_baselines`**

Append to `backend/analysis/skill_baselines.py`:

```python
from backend.database import get_connection

# Qualification thresholds
MIN_PA_HITTER = 50
MIN_IP_PITCHER = 20.0


def _population_stats(values: list[float]) -> tuple[float, float]:
    """Return (mean, sd) for a list of floats. SD is sample stdev."""
    n = len(values)
    if n < 2:
        return (0.0, 0.0)
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return (mean, math.sqrt(var))


def compute_skill_baselines(season: int) -> None:
    """Compute and persist per-player skill baselines for the current season.

    Writes to ``statcast_baselines``. Idempotent — re-running overwrites the
    row for each (mlb_id, season).
    """
    conn = get_connection()

    # Load current and prior season Statcast tables
    cur_bat = {r["mlb_id"]: dict(r) for r in conn.execute(
        "SELECT * FROM statcast_batting WHERE season = ?", (season,)
    ).fetchall()}
    prior_bat = {r["mlb_id"]: dict(r) for r in conn.execute(
        "SELECT * FROM statcast_batting WHERE season = ?", (season - 1,)
    ).fetchall()}
    cur_pit = {r["mlb_id"]: dict(r) for r in conn.execute(
        "SELECT * FROM statcast_pitching WHERE season = ?", (season,)
    ).fetchall()}
    prior_pit = {r["mlb_id"]: dict(r) for r in conn.execute(
        "SELECT * FROM statcast_pitching WHERE season = ?", (season - 1,)
    ).fetchall()}

    # Load qualification info
    pa_by_id = {r["mlb_id"]: r["plate_appearances"] for r in conn.execute(
        "SELECT mlb_id, plate_appearances FROM batting_stats WHERE season = ?", (season,)
    ).fetchall()}
    ip_by_id = {r["mlb_id"]: r["innings_pitched"] for r in conn.execute(
        "SELECT mlb_id, innings_pitched FROM pitching_stats WHERE season = ?", (season,)
    ).fetchall()}

    # First pass: compute deltas for everyone, accumulate populations for z-score normalization
    hitter_rows: list[tuple[int, dict, str]] = []
    pitcher_rows: list[tuple[int, dict, str]] = []
    hitter_population: dict[str, list[float]] = {k: [] for k in HITTER_WEIGHTS}
    pitcher_population: dict[str, list[float]] = {k: [] for k in PITCHER_WEIGHTS if k != "delta_k_minus_bb_pct"}
    pitcher_population.update({"delta_k_pct": [], "delta_bb_pct": []})

    for mid, cur in cur_bat.items():
        prior = prior_bat.get(mid)
        deltas = compute_metric_deltas(cur, prior, player_type="hitter")
        for k in HITTER_WEIGHTS:
            v = deltas.get(k)
            if v is not None:
                hitter_population[k].append(v)
        hitter_rows.append((mid, {**cur, **deltas}, deltas.get("baseline_source", "league_avg")))

    for mid, cur in cur_pit.items():
        prior = prior_pit.get(mid)
        deltas = compute_metric_deltas(cur, prior, player_type="pitcher")
        for k in ("delta_xera", "delta_whiff_pct", "delta_k_pct", "delta_bb_pct", "delta_chase_rate"):
            v = deltas.get(k)
            if v is not None:
                pitcher_population[k].append(v)
        pitcher_rows.append((mid, {**cur, **deltas}, deltas.get("baseline_source", "league_avg")))

    # Compute population stats once
    hitter_pop_stats = {k: _population_stats(v) for k, v in hitter_population.items()}
    pitcher_pop_stats = {k: _population_stats(v) for k, v in pitcher_population.items()}

    # Second pass: write rows
    for mid, payload, source in hitter_rows:
        pa = pa_by_id.get(mid, 0) or 0
        qualifies = 1 if pa >= MIN_PA_HITTER else 0
        z = compute_skill_change_zscore(payload, hitter_pop_stats, "hitter") if qualifies else None
        sustain = compute_sustainability_score(payload, "hitter") if qualifies else 0.0
        conn.execute(
            """INSERT INTO statcast_baselines
               (mlb_id, season, player_type,
                delta_xwoba, delta_barrel_pct, delta_hard_hit_pct, delta_sprint_speed,
                delta_xera, delta_whiff_pct, delta_k_pct, delta_bb_pct, delta_chase_rate,
                skill_change_zscore, sustainability_score, baseline_source, qualifies_pa_ip)
               VALUES (?, ?, ?,
                       ?, ?, ?, ?,
                       ?, ?, ?, ?, ?,
                       ?, ?, ?, ?)
               ON CONFLICT (mlb_id, season) DO UPDATE SET
                 player_type = EXCLUDED.player_type,
                 delta_xwoba = EXCLUDED.delta_xwoba,
                 delta_barrel_pct = EXCLUDED.delta_barrel_pct,
                 delta_hard_hit_pct = EXCLUDED.delta_hard_hit_pct,
                 delta_sprint_speed = EXCLUDED.delta_sprint_speed,
                 skill_change_zscore = EXCLUDED.skill_change_zscore,
                 sustainability_score = EXCLUDED.sustainability_score,
                 baseline_source = EXCLUDED.baseline_source,
                 qualifies_pa_ip = EXCLUDED.qualifies_pa_ip""",
            (
                mid, season, "hitter",
                payload.get("delta_xwoba"), payload.get("delta_barrel_pct"),
                payload.get("delta_hard_hit_pct"), payload.get("delta_sprint_speed"),
                None, None, None, None, None,
                z, sustain, source, qualifies,
            ),
        )

    for mid, payload, source in pitcher_rows:
        ip = ip_by_id.get(mid, 0.0) or 0.0
        qualifies = 1 if ip >= MIN_IP_PITCHER else 0
        z = compute_skill_change_zscore(payload, pitcher_pop_stats, "pitcher") if qualifies else None
        sustain = compute_sustainability_score(payload, "pitcher") if qualifies else 0.0
        conn.execute(
            """INSERT INTO statcast_baselines
               (mlb_id, season, player_type,
                delta_xwoba, delta_barrel_pct, delta_hard_hit_pct, delta_sprint_speed,
                delta_xera, delta_whiff_pct, delta_k_pct, delta_bb_pct, delta_chase_rate,
                skill_change_zscore, sustainability_score, baseline_source, qualifies_pa_ip)
               VALUES (?, ?, ?,
                       ?, ?, ?, ?,
                       ?, ?, ?, ?, ?,
                       ?, ?, ?, ?)
               ON CONFLICT (mlb_id, season) DO UPDATE SET
                 player_type = EXCLUDED.player_type,
                 delta_xera = EXCLUDED.delta_xera,
                 delta_whiff_pct = EXCLUDED.delta_whiff_pct,
                 delta_k_pct = EXCLUDED.delta_k_pct,
                 delta_bb_pct = EXCLUDED.delta_bb_pct,
                 delta_chase_rate = EXCLUDED.delta_chase_rate,
                 skill_change_zscore = EXCLUDED.skill_change_zscore,
                 sustainability_score = EXCLUDED.sustainability_score,
                 baseline_source = EXCLUDED.baseline_source,
                 qualifies_pa_ip = EXCLUDED.qualifies_pa_ip""",
            (
                mid, season, "pitcher",
                None, None, None, None,
                payload.get("delta_xera"), payload.get("delta_whiff_pct"),
                payload.get("delta_k_pct"), payload.get("delta_bb_pct"),
                payload.get("delta_chase_rate"),
                z, sustain, source, qualifies,
            ),
        )

    conn.commit()
    conn.close()
    logger.info(
        f"Skill baselines computed: {len(hitter_rows)} hitters, {len(pitcher_rows)} pitchers"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/backend/analysis/test_skill_baselines.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/analysis/skill_baselines.py tests/backend/analysis/test_skill_baselines.py
git commit -m "feat(skill-baselines): persist deltas + composite scores per season"
```

---

## Task 6: Refactor `_assign_faab_bids` into a parameterized helper

The Hot view also needs FAAB bids. Extract the existing helper so both engines share one implementation.

**Files:**
- Modify: `backend/analysis/waivers.py`
- Test: `tests/backend/analysis/test_waivers.py` (add a test)

- [ ] **Step 1: Add the failing test**

Append to `tests/backend/analysis/test_waivers.py`:

```python
class TestAssignFaabBids:
    def test_helper_uses_specified_metric_attribute(self):
        from backend.analysis.waivers import (
            assign_faab_bids,
            WaiverRecommendation,
        )

        recs = [
            WaiverRecommendation(
                add_player_id=1, add_player_name="A", add_player_position="OF",
                drop_player_id=10, drop_player_name="X", drop_player_position="OF",
                delta_expected_wins=0.50,
                suggested_faab_bid=0,
                category_impact={}, category_stat_delta={},
            ),
            WaiverRecommendation(
                add_player_id=2, add_player_name="B", add_player_position="OF",
                drop_player_id=11, drop_player_name="Y", drop_player_position="OF",
                delta_expected_wins=0.25,
                suggested_faab_bid=0,
                category_impact={}, category_stat_delta={},
            ),
        ]
        # By default the helper reads delta_expected_wins
        assign_faab_bids(recs, remaining_faab=100.0)
        assert recs[0].suggested_faab_bid > recs[1].suggested_faab_bid

        # Explicit attribute override
        recs2 = [WaiverRecommendation(
            add_player_id=3, add_player_name="C", add_player_position="OF",
            drop_player_id=12, drop_player_name="Z", drop_player_position="OF",
            delta_expected_wins=0.0,  # would be filtered out by default
            suggested_faab_bid=0,
            category_impact={}, category_stat_delta={},
        )]
        # Set a non-default attribute to use as the bid metric
        recs2[0].wins_added_if_rate_continues = 0.40
        assign_faab_bids(recs2, remaining_faab=100.0,
                         metric_attr="wins_added_if_rate_continues")
        assert recs2[0].suggested_faab_bid > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/backend/analysis/test_waivers.py::TestAssignFaabBids -v`
Expected: FAIL — `assign_faab_bids` not exported.

- [ ] **Step 3: Refactor the helper**

In `backend/analysis/waivers.py`, find the existing `_assign_faab_bids` function (around line 669) and replace it with:

```python
def assign_faab_bids(
    recommendations: list[WaiverRecommendation],
    remaining_faab: float,
    metric_attr: str = "delta_expected_wins",
) -> None:
    """Assign FAAB bid suggestions proportional to a delta-wins metric.

    By default uses ``delta_expected_wins``. Pass ``metric_attr="wins_added_if_rate_continues"``
    (or any attribute on ``WaiverRecommendation``) to use a different metric.

    Recommendations with metric value <= 0.01 are assigned a bid of 0.
    The top recommendation receives up to 40% of the remaining budget;
    others scale proportionally.
    """
    if not recommendations:
        return

    def _val(r: WaiverRecommendation) -> float:
        return getattr(r, metric_attr, 0.0) or 0.0

    positive = [r for r in recommendations if _val(r) > 0.01]
    if not positive:
        return

    top_value = max(_val(r) for r in positive)
    if top_value <= 0:
        return

    cap = max(1.0, remaining_faab * 0.4)
    for r in recommendations:
        v = _val(r)
        if v <= 0.01:
            r.suggested_faab_bid = 0
            continue
        r.suggested_faab_bid = max(1, round(cap * (v / top_value)))


# Keep the underscored alias so existing internal call sites don't break
_assign_faab_bids = assign_faab_bids
```

In the existing call site (around line 622 inside `compute_waiver_recommendations`), no change is needed because `_assign_faab_bids` still refers to the same function via the alias.

- [ ] **Step 4: Run tests to verify both old and new pass**

Run: `pytest tests/backend/analysis/test_waivers.py -v`
Expected: All tests PASS, including new `TestAssignFaabBids` and existing waiver tests.

Also verify dataclass `WaiverRecommendation` accepts dynamic attribute writes — Python dataclasses do unless `frozen=True`. The current decorator is `@dataclass`, no `frozen`. Confirmed by reading the existing definition.

If the dataclass test for `wins_added_if_rate_continues` fails because dataclass doesn't accept the attribute, edit `WaiverRecommendation` to add it as an optional field with default `None`:

```python
@dataclass
class WaiverRecommendation:
    add_player_id: int
    add_player_name: str
    add_player_position: str
    drop_player_id: Optional[int]
    drop_player_name: Optional[str]
    drop_player_position: Optional[str]
    delta_expected_wins: float
    suggested_faab_bid: int
    category_impact: dict[str, float]
    category_stat_delta: dict[str, float]
    wins_added_if_rate_continues: Optional[float] = None
```

- [ ] **Step 5: Commit**

```bash
git add backend/analysis/waivers.py tests/backend/analysis/test_waivers.py
git commit -m "refactor(waivers): parameterize assign_faab_bids by metric attr"
```

---

## Task 7: Breakouts engine — Hot view

**Files:**
- Create: `backend/analysis/breakouts.py`
- Test: `tests/backend/analysis/test_breakouts.py`

- [ ] **Step 1: Write the failing test**

Create `tests/backend/analysis/test_breakouts.py`:

```python
"""Tests for the breakout finder engine."""

import pytest

from backend.analysis.breakouts import (
    HotPlayer,
    BreakoutRecommendation,
    prorate_window_to_ros,
    sustainability_filter_passes,
    LEAGUE_AVG_BARREL_PCT,
    LEAGUE_AVG_HARD_HIT_PCT,
    LEAGUE_AVG_WHIFF_PCT,
)


class TestProrateWindowToRos:
    def test_hitter_pace_extrapolated_by_games_remaining(self):
        # 14d window, 12 games played, 90 games remaining in season
        window_stats = {
            "games": 12, "pa": 55, "ab": 48, "r": 12, "h": 17, "hr": 4,
            "rbi": 14, "sb": 2, "bb": 6, "k": 9, "hbp": 1, "sf": 0,
            "total_bases": 32, "obp": 0.420, "slg": 0.667,
        }
        result = prorate_window_to_ros(
            window_stats, player_type="hitter",
            games_in_window=12, games_remaining=90,
        )
        assert result["pa"] == pytest.approx(55 * 90 / 12, abs=1)  # ~412
        assert result["r"] == pytest.approx(12 * 90 / 12, abs=1)   # 90
        assert result["tb"] == pytest.approx(32 * 90 / 12, abs=1)
        # Rate stats use the window value directly
        assert result["obp"] == pytest.approx(0.420)

    def test_pitcher_pace_extrapolated_to_remaining_starts(self):
        # 14d window, 3 starts in window; assume 25 starts remaining
        window_stats = {
            "games": 3, "games_started": 3, "ip": 18.0, "k": 22, "bb": 4,
            "h_allowed": 13, "er": 5, "saves": 0, "holds": 0, "quality_starts": 2,
            "era": 2.50, "whip": 0.944,
        }
        result = prorate_window_to_ros(
            window_stats, player_type="pitcher",
            games_in_window=3, games_remaining=25,
        )
        assert result["ip"] == pytest.approx(18.0 * 25 / 3, abs=1)
        assert result["k"] == pytest.approx(22 * 25 / 3, abs=1)
        assert result["qs"] == pytest.approx(2 * 25 / 3, abs=1)
        assert result["era"] == pytest.approx(2.50)


class TestSustainabilityFilter:
    def test_hitter_passes_with_two_of_three_checks(self):
        # xwOBA gap OK + barrel% strong; sprint speed weak. Should pass (≥ 2 of 3)
        statcast = {
            "xwoba": 0.380, "woba": 0.385,    # gap = -0.005 (OK)
            "barrel_pct": 12.0,                # well above 7.0 * 0.85 = 5.95
            "hard_hit_pct": 30.0,              # below 35.0 * 0.95 = 33.25 (fails this leg)
            "sprint_speed": 25.0,              # below 27.0 (fails)
        }
        # checks: gap OK, barrel% OR hard_hit% OK (yes), sprint_speed OK? no
        # 2 of 3 → pass
        assert sustainability_filter_passes(statcast, player_type="hitter") is True

    def test_hitter_fails_when_two_checks_fail(self):
        statcast = {
            "xwoba": 0.300, "woba": 0.380,    # gap = -0.080 (fails)
            "barrel_pct": 4.0,                 # below 5.95 (fails)
            "hard_hit_pct": 30.0,              # below 33.25 (fails)
            "sprint_speed": 28.0,              # OK
        }
        assert sustainability_filter_passes(statcast, player_type="hitter") is False

    def test_pitcher_passes_with_two_of_three(self):
        statcast = {
            "xera": 3.20, "era": 3.50,    # xera <= era + 0.50 ✓
            "whiff_pct": 30.0,             # ≥ 25.0 * 0.95 = 23.75 ✓
            "csw_pct": 25.0,               # below 28.0 * 0.95 = 26.6 (this leg fails)
            "bb_pct": 11.0,                # > 8.5 * 1.20 = 10.2 ✗
        }
        # checks: xera-era ✓, whiff OR csw ✓ (whiff passes), bb_pct ✗
        # 2 of 3 → pass
        assert sustainability_filter_passes(statcast, player_type="pitcher") is True

    def test_returns_false_when_critical_data_missing(self):
        # Missing xwOBA (and woba) entirely → can't evaluate gap check
        statcast = {"barrel_pct": 12.0, "hard_hit_pct": 40.0, "sprint_speed": 28.0}
        # Without xwOBA gap, only 2 checks possible — need both to pass
        # barrel_pct OR hard_hit_pct ✓, sprint_speed ✓ → 2 of 2 → pass
        assert sustainability_filter_passes(statcast, player_type="hitter") is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/backend/analysis/test_breakouts.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement Hot-view primitives**

Create `backend/analysis/breakouts.py`:

```python
"""Breakout finder engine — Hot + Sustainable view and Stealth Breakouts view.

Both views share data plumbing but produce independent rankings:
- Hot view ranks free agents/rostered players by MCW-extrapolated wins added
  if the recent window's pace continues, filtered by Statcast sustainability.
- Stealth view ranks players by a composite skill-change z-score derived
  from `statcast_baselines`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from backend.analysis.skill_baselines import (
    LEAGUE_AVG_BARREL_PCT,
    LEAGUE_AVG_HARD_HIT_PCT,
    LEAGUE_AVG_WHIFF_PCT,
    LEAGUE_AVG_CSW_PCT,
    LEAGUE_AVG_BB_PCT,
)

logger = logging.getLogger(__name__)

# Sustainability hard-filter thresholds
HITTER_XWOBA_TOLERANCE = 0.020       # xwOBA >= wOBA - 0.020
HITTER_BARREL_THRESHOLD_RATIO = 0.85
HITTER_HARD_HIT_THRESHOLD_RATIO = 0.95
HITTER_SPRINT_SPEED_THRESHOLD = 27.0
PITCHER_XERA_TOLERANCE = 0.50         # xERA <= ERA + 0.50
PITCHER_WHIFF_THRESHOLD_RATIO = 0.95
PITCHER_CSW_THRESHOLD_RATIO = 0.95
PITCHER_BB_THRESHOLD_RATIO = 1.20


@dataclass
class HotPlayer:
    """A candidate for the Hot view, with pro-rated stats and metric badges."""
    mlb_id: int
    name: str
    eligible_positions: str
    player_type: str
    window_stats: dict
    prorated_stats: dict
    sustainability_badges: dict[str, str]
    sustainability_score: float


@dataclass
class BreakoutRecommendation:
    """One breakout-engine result row.

    Hot rows include drop_player_id and wins_added_if_rate_continues.
    Stealth rows leave those None and use skill_change_zscore + metric_deltas.
    """
    rank: int
    add_player: dict
    drop_player: Optional[dict] = None
    wins_added_if_rate_continues: Optional[float] = None
    suggested_faab_bid: int = 0
    sustainability_badges: dict = field(default_factory=dict)
    sustainability_score: Optional[float] = None
    window_stats: Optional[dict] = None
    skill_change_zscore: Optional[float] = None
    headline_delta: Optional[dict] = None
    metric_deltas: dict = field(default_factory=dict)
    current_vs_projection: dict = field(default_factory=dict)
    baseline_source: Optional[str] = None
    roster_status: Optional[str] = None  # "FA" | "team_<id>" | "my_team"


def prorate_window_to_ros(
    window_stats: dict,
    player_type: str,
    games_in_window: int,
    games_remaining: int,
) -> dict:
    """Pro-rate a window's stats to the rest-of-season pace.

    Counting stats scale by ``games_remaining / games_in_window``. Rate stats
    (OBP, ERA, WHIP, batting_avg, etc.) carry through unchanged.
    """
    if games_in_window <= 0 or games_remaining <= 0:
        return {}
    factor = games_remaining / games_in_window

    if player_type == "hitter":
        return {
            "pa": window_stats.get("pa", 0) * factor,
            "ab": window_stats.get("ab", 0) * factor,
            "r": window_stats.get("r", 0) * factor,
            "h": window_stats.get("h", 0) * factor,
            "hr": window_stats.get("hr", 0) * factor,
            "rbi": window_stats.get("rbi", 0) * factor,
            "sb": window_stats.get("sb", 0) * factor,
            "bb": window_stats.get("bb", 0) * factor,
            "k": window_stats.get("k", 0) * factor,
            "tb": window_stats.get("total_bases", 0) * factor,
            "obp": window_stats.get("obp", 0.0),
            "slg": window_stats.get("slg", 0.0),
        }

    # Pitcher
    return {
        "ip": window_stats.get("ip", 0.0) * factor,
        "k": window_stats.get("k", 0) * factor,
        "bb": window_stats.get("bb", 0) * factor,
        "qs": window_stats.get("quality_starts", 0) * factor,
        "saves": window_stats.get("saves", 0) * factor,
        "holds": window_stats.get("holds", 0) * factor,
        "svhd": (window_stats.get("saves", 0) + window_stats.get("holds", 0)) * factor,
        "era": window_stats.get("era", 0.0),
        "whip": window_stats.get("whip", 0.0),
    }


def _sustainability_check_results(statcast: dict, player_type: str) -> list[Optional[bool]]:
    """Run the three core checks. Each returns True/False; None when data is missing."""
    if player_type == "hitter":
        # Check 1: xwOBA-wOBA gap
        xwoba = statcast.get("xwoba")
        woba = statcast.get("woba")
        gap_check = (xwoba >= woba - HITTER_XWOBA_TOLERANCE) if (xwoba is not None and woba is not None) else None

        # Check 2: barrel% OR hard_hit%
        barrel = statcast.get("barrel_pct")
        hard_hit = statcast.get("hard_hit_pct")
        barrel_ok = barrel is not None and barrel >= LEAGUE_AVG_BARREL_PCT * HITTER_BARREL_THRESHOLD_RATIO
        hard_hit_ok = hard_hit is not None and hard_hit >= LEAGUE_AVG_HARD_HIT_PCT * HITTER_HARD_HIT_THRESHOLD_RATIO
        if barrel is None and hard_hit is None:
            quality_check = None
        else:
            quality_check = barrel_ok or hard_hit_ok

        # Check 3: sprint speed
        sprint = statcast.get("sprint_speed")
        sprint_check = sprint >= HITTER_SPRINT_SPEED_THRESHOLD if sprint is not None else None

        return [gap_check, quality_check, sprint_check]

    # Pitcher
    xera = statcast.get("xera")
    era = statcast.get("era")
    xera_check = (xera <= era + PITCHER_XERA_TOLERANCE) if (xera is not None and era is not None) else None

    whiff = statcast.get("whiff_pct")
    csw = statcast.get("csw_pct")
    whiff_ok = whiff is not None and whiff >= LEAGUE_AVG_WHIFF_PCT * PITCHER_WHIFF_THRESHOLD_RATIO
    csw_ok = csw is not None and csw >= LEAGUE_AVG_CSW_PCT * PITCHER_CSW_THRESHOLD_RATIO
    if whiff is None and csw is None:
        whiff_csw_check = None
    else:
        whiff_csw_check = whiff_ok or csw_ok

    bb = statcast.get("bb_pct")
    bb_check = bb <= LEAGUE_AVG_BB_PCT * PITCHER_BB_THRESHOLD_RATIO if bb is not None else None

    return [xera_check, whiff_csw_check, bb_check]


def sustainability_filter_passes(statcast: dict, player_type: str) -> bool:
    """≥ 2 of 3 core checks must pass. Missing checks are excluded from the count.

    If only 2 checks are evaluable, both must pass. If only 1, it must pass.
    If none, the player fails.
    """
    checks = _sustainability_check_results(statcast, player_type)
    evaluable = [c for c in checks if c is not None]
    if not evaluable:
        return False
    passed = sum(1 for c in evaluable if c)
    if len(evaluable) == 3:
        return passed >= 2
    # When fewer checks are evaluable, require all of them to pass
    return passed == len(evaluable)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/backend/analysis/test_breakouts.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/analysis/breakouts.py tests/backend/analysis/test_breakouts.py
git commit -m "feat(breakouts): add prorate + sustainability filter primitives"
```

---

## Task 8: Breakouts engine — Hot view orchestration

This task wires the primitives into the existing MCW pipeline (`build_team_totals`, `compute_expected_wins`) to compute `wins_added_if_rate_continues` for each candidate.

**Files:**
- Modify: `backend/analysis/breakouts.py`
- Test: `tests/backend/analysis/test_breakouts.py` (add tests)

- [ ] **Step 1: Add the failing tests**

Append to `tests/backend/analysis/test_breakouts.py`:

```python
from unittest.mock import patch
from backend.analysis.waivers import PlayerProjection


def _proj(mlb_id, name, ptype, **kw):
    defaults = dict(pa=600, r=80, tb=240, rbi=70, sb=10, obp=0.330,
                    ip=0.0, k=0, qs=0, era=0.0, whip=0.0, svhd=0,
                    eligible_positions="OF", overall_rank=100)
    defaults.update(kw)
    return PlayerProjection(
        mlb_id=mlb_id, name=name, position="OF", player_type=ptype,
        **defaults,
    )


def _pitcher_proj(mlb_id, name, **kw):
    defaults = dict(pa=0, r=0, tb=0, rbi=0, sb=0, obp=0.0,
                    ip=180.0, k=200, qs=15, era=3.50, whip=1.20, svhd=0,
                    eligible_positions="SP", overall_rank=100)
    defaults.update(kw)
    return PlayerProjection(
        mlb_id=mlb_id, name=name, position="SP", player_type="pitcher",
        **defaults,
    )


class TestComputeHotView:
    def test_returns_recommendation_when_fa_passes_filter(self):
        from backend.analysis.breakouts import compute_hot_view

        my_roster_ids = [1, 2]
        my_roster_slots = [
            {"mlb_id": 1, "lineup_slot_id": 0},
            {"mlb_id": 2, "lineup_slot_id": 0},
        ]
        # Hot FA with strong recent stats; existing weak hitter to drop
        projections = {
            1: _proj(1, "Strong"),
            2: _proj(2, "Weak", r=40, tb=120, rbi=30, sb=2, obp=0.290),
            99: _proj(99, "FA", r=0, tb=0, rbi=0, sb=0, obp=0.0),
        }
        # Other team baseline so my_totals are competitive
        other_team_slots = [{"mlb_id": 1001, "lineup_slot_id": 0}]
        projections[1001] = _proj(1001, "OtherTeam", r=70, tb=210, rbi=60, sb=8, obp=0.320)

        rolling_stats_by_id = {
            99: {"games": 12, "pa": 55, "ab": 48, "r": 14, "h": 18, "hr": 5,
                 "rbi": 16, "sb": 3, "bb": 6, "k": 8, "hbp": 1, "sf": 0,
                 "total_bases": 36, "obp": 0.450, "slg": 0.750}
        }
        statcast_by_id = {
            99: {"xwoba": 0.400, "woba": 0.430, "barrel_pct": 14.0,
                 "hard_hit_pct": 50.0, "sprint_speed": 28.5}
        }

        result = compute_hot_view(
            my_roster_ids=my_roster_ids,
            my_roster_slots=my_roster_slots,
            all_team_roster_slots=[other_team_slots],
            free_agent_ids=[99],
            projections=projections,
            rolling_stats_by_id=rolling_stats_by_id,
            statcast_by_id=statcast_by_id,
            games_in_window=12,
            games_remaining=120,
            remaining_faab=85.0,
        )

        recs = result["recommendations"]
        assert len(recs) >= 1
        assert recs[0].add_player["id"] == 99
        assert recs[0].wins_added_if_rate_continues is not None
        assert recs[0].sustainability_badges  # non-empty dict

    def test_filters_out_unsustainable_fa(self):
        from backend.analysis.breakouts import compute_hot_view

        my_roster_slots = [{"mlb_id": 1, "lineup_slot_id": 0}]
        projections = {
            1: _proj(1, "Mine"),
            99: _proj(99, "BadFA"),
            1001: _proj(1001, "Other"),
        }
        rolling_stats_by_id = {
            99: {"games": 10, "pa": 40, "ab": 36, "r": 8, "h": 15, "hr": 3,
                 "rbi": 10, "sb": 1, "bb": 4, "k": 6, "hbp": 0, "sf": 0,
                 "total_bases": 28, "obp": 0.475, "slg": 0.778}
        }
        # All sustainability checks fail
        statcast_by_id = {
            99: {"xwoba": 0.290, "woba": 0.420,    # gap fails
                 "barrel_pct": 4.0,                  # fails
                 "hard_hit_pct": 28.0,               # fails
                 "sprint_speed": 26.0}                # fails
        }

        result = compute_hot_view(
            my_roster_ids=[1], my_roster_slots=my_roster_slots,
            all_team_roster_slots=[[{"mlb_id": 1001, "lineup_slot_id": 0}]],
            free_agent_ids=[99],
            projections=projections,
            rolling_stats_by_id=rolling_stats_by_id,
            statcast_by_id=statcast_by_id,
            games_in_window=10, games_remaining=120, remaining_faab=85.0,
        )
        assert result["recommendations"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/backend/analysis/test_breakouts.py::TestComputeHotView -v`
Expected: FAIL — `compute_hot_view` not defined.

- [ ] **Step 3: Implement `compute_hot_view`**

Append to `backend/analysis/breakouts.py`:

```python
from backend.analysis.waivers import (
    PlayerProjection,
    TeamTotals,
    HITTER_BENCH_WEIGHT,
    IL_WEIGHT,
    IL_SLOT_THRESHOLD,
    ALL_CATS,
    INVERTED_CATS,
    build_team_totals,
    compute_expected_wins,
    assign_faab_bids,
    WaiverRecommendation,
)


def _badge_for_metric(value: Optional[float], population: list[float]) -> str:
    """Color-code a metric vs the current population's distribution."""
    if value is None or not population:
        return "gray"
    sorted_pop = sorted(population)
    n = len(sorted_pop)
    rank = sum(1 for v in sorted_pop if v < value)
    pct = rank / n
    if pct >= 0.60:
        return "green"
    if pct >= 0.40:
        return "yellow"
    return "red"


def _build_badges(statcast: dict, player_type: str,
                  population: dict[str, list[float]]) -> dict[str, str]:
    if player_type == "hitter":
        return {
            "xwoba_gap": _badge_for_metric(
                (statcast.get("xwoba") or 0) - (statcast.get("woba") or 0)
                if statcast.get("xwoba") is not None and statcast.get("woba") is not None
                else None,
                population.get("xwoba_gap", []),
            ),
            "barrel_pct": _badge_for_metric(statcast.get("barrel_pct"), population.get("barrel_pct", [])),
            "hard_hit_pct": _badge_for_metric(statcast.get("hard_hit_pct"), population.get("hard_hit_pct", [])),
            "sprint_speed": _badge_for_metric(statcast.get("sprint_speed"), population.get("sprint_speed", [])),
        }
    return {
        "xera_gap": _badge_for_metric(
            (statcast.get("era") or 0) - (statcast.get("xera") or 0)
            if statcast.get("xera") is not None and statcast.get("era") is not None
            else None,
            population.get("xera_gap", []),
        ),
        "whiff_pct": _badge_for_metric(statcast.get("whiff_pct"), population.get("whiff_pct", [])),
        "csw_pct": _badge_for_metric(statcast.get("csw_pct"), population.get("csw_pct", [])),
        "bb_pct": _badge_for_metric(statcast.get("bb_pct"), population.get("bb_pct", []), ),
    }


def _build_population_dist(statcast_by_id: dict[int, dict],
                           player_type: str) -> dict[str, list[float]]:
    """Build per-metric value lists for badge percentile computation."""
    pop: dict[str, list[float]] = {}
    if player_type == "hitter":
        keys = [("xwoba_gap", lambda s: (s.get("xwoba") - s.get("woba"))
                 if s.get("xwoba") is not None and s.get("woba") is not None else None),
                ("barrel_pct", lambda s: s.get("barrel_pct")),
                ("hard_hit_pct", lambda s: s.get("hard_hit_pct")),
                ("sprint_speed", lambda s: s.get("sprint_speed"))]
    else:
        keys = [("xera_gap", lambda s: (s.get("era") - s.get("xera"))
                 if s.get("xera") is not None and s.get("era") is not None else None),
                ("whiff_pct", lambda s: s.get("whiff_pct")),
                ("csw_pct", lambda s: s.get("csw_pct")),
                ("bb_pct", lambda s: s.get("bb_pct"))]
    for k, fn in keys:
        pop[k] = [v for v in (fn(s) for s in statcast_by_id.values()) if v is not None]
    return pop


def _build_proj_from_prorated(
    mlb_id: int,
    name: str,
    base_proj: PlayerProjection,
    prorated: dict,
    player_type: str,
) -> PlayerProjection:
    """Build a PlayerProjection that uses the prorated rolling-window pace."""
    return PlayerProjection(
        mlb_id=mlb_id, name=name,
        position=base_proj.position,
        player_type=player_type,
        eligible_positions=base_proj.eligible_positions,
        overall_rank=base_proj.overall_rank,
        pa=int(prorated.get("pa", 0)),
        r=int(prorated.get("r", 0)),
        tb=int(prorated.get("tb", 0)),
        rbi=int(prorated.get("rbi", 0)),
        sb=int(prorated.get("sb", 0)),
        obp=float(prorated.get("obp", 0.0)),
        ip=float(prorated.get("ip", 0.0)),
        k=int(prorated.get("k", 0)),
        qs=int(prorated.get("qs", 0)),
        era=float(prorated.get("era", 0.0)),
        whip=float(prorated.get("whip", 0.0)),
        svhd=int(prorated.get("svhd", 0)),
    )


def compute_hot_view(
    my_roster_ids: list[int],
    my_roster_slots: list[dict],
    all_team_roster_slots: list[list[dict]],
    free_agent_ids: list[int],
    projections: dict[int, PlayerProjection],
    rolling_stats_by_id: dict[int, dict],
    statcast_by_id: dict[int, dict],
    games_in_window: int,
    games_remaining: int,
    remaining_faab: float = 100.0,
) -> dict:
    """Hot + Sustainable view: rank candidates by wins added if their recent
    pace continues, filtered by sustainability checks.

    Inputs mirror the existing waiver engine plus rolling and Statcast data.
    Pre-baseline-season callers may pass empty dicts for either of the two
    new inputs, in which case no recommendations are returned.
    """
    # Build my baseline using existing projections (steady-state expectation)
    my_totals, _ = build_team_totals(my_roster_slots, projections)
    other_team_totals = []
    for slots in all_team_roster_slots:
        tt, _ = build_team_totals(slots, projections)
        other_team_totals.append(tt)

    my_cat_values = my_totals.category_values()
    other_cat_values = [t.category_values() for t in other_team_totals]
    baseline_wins, baseline_cat_probs = compute_expected_wins(my_cat_values, other_cat_values)

    droppable_ids = [
        s["mlb_id"] for s in my_roster_slots
        if s.get("lineup_slot_id", 0) < IL_SLOT_THRESHOLD
    ]

    # Build population distributions (split by player type for badging)
    hitter_statcast = {pid: s for pid, s in statcast_by_id.items()
                       if projections.get(pid) and projections[pid].player_type == "hitter"}
    pitcher_statcast = {pid: s for pid, s in statcast_by_id.items()
                        if projections.get(pid) and projections[pid].player_type == "pitcher"}
    hitter_pop = _build_population_dist(hitter_statcast, "hitter")
    pitcher_pop = _build_population_dist(pitcher_statcast, "pitcher")

    recommendations: list[BreakoutRecommendation] = []

    for fa_id in free_agent_ids:
        fa_proj = projections.get(fa_id)
        rolling = rolling_stats_by_id.get(fa_id)
        statcast = statcast_by_id.get(fa_id, {})
        if fa_proj is None or rolling is None:
            continue

        ptype = fa_proj.player_type
        if not sustainability_filter_passes(statcast, ptype):
            continue

        prorated = prorate_window_to_ros(rolling, ptype, games_in_window, games_remaining)
        if not prorated:
            continue

        # Synthesize a PlayerProjection from the prorated pace
        hot_proj = _build_proj_from_prorated(fa_id, fa_proj.name, fa_proj, prorated, ptype)

        best_drop_id: Optional[int] = None
        best_delta: float = float("-inf")
        for drop_id in droppable_ids:
            drop_proj = projections.get(drop_id)
            if drop_proj is None or drop_proj.player_type != ptype:
                continue
            trial_slots = [s for s in my_roster_slots if s["mlb_id"] != drop_id]
            trial_slots.append({"mlb_id": fa_id, "lineup_slot_id": 0})
            # Inject the hot projection for the FA only during this trial
            trial_projections = dict(projections)
            trial_projections[fa_id] = hot_proj
            trial_totals, _ = build_team_totals(trial_slots, trial_projections)
            trial_wins, _ = compute_expected_wins(
                trial_totals.category_values(), other_cat_values
            )
            delta = trial_wins - baseline_wins
            if delta > best_delta:
                best_delta = delta
                best_drop_id = drop_id

        if best_drop_id is None or best_delta <= 0.01:
            continue

        drop_proj = projections.get(best_drop_id)
        pop = hitter_pop if ptype == "hitter" else pitcher_pop
        badges = _build_badges(statcast, ptype, pop)
        from backend.analysis.skill_baselines import compute_sustainability_score
        sustain = compute_sustainability_score(statcast, ptype)

        recommendations.append(BreakoutRecommendation(
            rank=0,  # filled in after sort
            add_player={
                "id": fa_id, "name": fa_proj.name,
                "position": fa_proj.eligible_positions or fa_proj.position,
                "team": "",
                "roster_status": "FA",
            },
            drop_player={
                "id": best_drop_id, "name": drop_proj.name if drop_proj else "",
                "position": (drop_proj.eligible_positions or drop_proj.position)
                            if drop_proj else "",
            } if drop_proj else None,
            wins_added_if_rate_continues=round(best_delta, 4),
            sustainability_badges=badges,
            sustainability_score=sustain,
            window_stats=rolling,
        ))

    # Sort by wins added, with sustainability_score as tiebreaker
    recommendations.sort(
        key=lambda r: (
            -(r.wins_added_if_rate_continues or 0),
            -(r.sustainability_score or 0),
        )
    )
    for i, r in enumerate(recommendations):
        r.rank = i + 1

    # Build a lightweight stand-in compatible with assign_faab_bids() — it
    # operates on objects exposing .delta_expected_wins or a named attribute.
    # Wrap by setting wins_added_if_rate_continues on a WaiverRecommendation.
    waiver_recs = [
        WaiverRecommendation(
            add_player_id=r.add_player["id"],
            add_player_name=r.add_player["name"],
            add_player_position=r.add_player["position"],
            drop_player_id=r.drop_player["id"] if r.drop_player else None,
            drop_player_name=r.drop_player["name"] if r.drop_player else None,
            drop_player_position=r.drop_player["position"] if r.drop_player else None,
            delta_expected_wins=0.0,
            suggested_faab_bid=0,
            category_impact={}, category_stat_delta={},
            wins_added_if_rate_continues=r.wins_added_if_rate_continues,
        )
        for r in recommendations
    ]
    assign_faab_bids(waiver_recs, remaining_faab,
                     metric_attr="wins_added_if_rate_continues")
    for r, w in zip(recommendations, waiver_recs):
        r.suggested_faab_bid = w.suggested_faab_bid

    return {
        "baseline_expected_wins": round(baseline_wins, 3),
        "baseline_category_probs": {cat: round(v, 4) for cat, v in baseline_cat_probs.items()},
        "recommendations": recommendations,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/backend/analysis/test_breakouts.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/analysis/breakouts.py tests/backend/analysis/test_breakouts.py
git commit -m "feat(breakouts): wire up Hot view MCW + sustainability filter"
```

---

## Task 9: Breakouts engine — Stealth view

**Files:**
- Modify: `backend/analysis/breakouts.py`
- Test: `tests/backend/analysis/test_breakouts.py` (add tests)

- [ ] **Step 1: Add the failing tests**

Append to `tests/backend/analysis/test_breakouts.py`:

```python
class TestComputeStealthView:
    def test_ranks_by_skill_change_zscore_descending(self):
        from backend.analysis.breakouts import compute_stealth_view

        baselines = [
            {"mlb_id": 1, "player_type": "hitter",
             "skill_change_zscore": 1.2, "qualifies_pa_ip": 1,
             "delta_xwoba": 0.04, "delta_barrel_pct": 3.0,
             "delta_hard_hit_pct": 2.0, "delta_sprint_speed": 0.3,
             "baseline_source": "prior_season"},
            {"mlb_id": 2, "player_type": "hitter",
             "skill_change_zscore": 2.5, "qualifies_pa_ip": 1,
             "delta_xwoba": 0.06, "delta_barrel_pct": 5.5,
             "delta_hard_hit_pct": 4.0, "delta_sprint_speed": 0.5,
             "baseline_source": "prior_season"},
            {"mlb_id": 3, "player_type": "hitter",
             "skill_change_zscore": 0.5, "qualifies_pa_ip": 1,
             "delta_xwoba": 0.01, "delta_barrel_pct": 1.0,
             "delta_hard_hit_pct": 0.5, "delta_sprint_speed": 0.0,
             "baseline_source": "league_avg"},
        ]
        player_meta = {
            1: {"name": "A", "team": "BOS", "position": "OF"},
            2: {"name": "B", "team": "LAD", "position": "SS"},
            3: {"name": "C", "team": "SF", "position": "1B"},
        }
        roster_status_by_id = {1: "FA", 2: "FA", 3: "FA"}
        current_stats = {1: {"ops": 0.700}, 2: {"ops": 0.720}, 3: {"ops": 0.690}}
        proj_stats = {1: {"ops": 0.780}, 2: {"ops": 0.760}, 3: {"ops": 0.770}}

        result = compute_stealth_view(
            baselines=baselines, player_meta=player_meta,
            roster_status_by_id=roster_status_by_id,
            current_stats=current_stats, proj_stats=proj_stats,
            scope="FA", position_filter=None, player_type_filter=None,
        )
        recs = result["recommendations"]
        assert [r.add_player["id"] for r in recs] == [2, 1, 3]
        assert recs[0].skill_change_zscore == pytest.approx(2.5)
        assert recs[0].headline_delta is not None

    def test_filters_out_unqualified_players(self):
        from backend.analysis.breakouts import compute_stealth_view

        baselines = [
            {"mlb_id": 1, "player_type": "hitter",
             "skill_change_zscore": 3.0, "qualifies_pa_ip": 0,
             "delta_xwoba": 0.10, "delta_barrel_pct": 8.0,
             "delta_hard_hit_pct": 6.0, "delta_sprint_speed": 1.0,
             "baseline_source": "prior_season"},
        ]
        result = compute_stealth_view(
            baselines=baselines,
            player_meta={1: {"name": "A", "team": "X", "position": "OF"}},
            roster_status_by_id={1: "FA"},
            current_stats={1: {}}, proj_stats={1: {}},
            scope="FA", position_filter=None, player_type_filter=None,
        )
        assert result["recommendations"] == []

    def test_scope_filter_excludes_rostered_when_fa_only(self):
        from backend.analysis.breakouts import compute_stealth_view

        baselines = [
            {"mlb_id": 1, "player_type": "hitter",
             "skill_change_zscore": 2.0, "qualifies_pa_ip": 1,
             "delta_xwoba": 0.05, "delta_barrel_pct": 4.0,
             "delta_hard_hit_pct": 3.0, "delta_sprint_speed": 0.4,
             "baseline_source": "prior_season"},
        ]
        result = compute_stealth_view(
            baselines=baselines,
            player_meta={1: {"name": "A", "team": "X", "position": "OF"}},
            roster_status_by_id={1: "team_3"},
            current_stats={1: {}}, proj_stats={1: {}},
            scope="FA", position_filter=None, player_type_filter=None,
        )
        assert result["recommendations"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/backend/analysis/test_breakouts.py::TestComputeStealthView -v`
Expected: FAIL — `compute_stealth_view` not defined.

- [ ] **Step 3: Implement `compute_stealth_view`**

Append to `backend/analysis/breakouts.py`:

```python
def _format_headline_delta(baseline: dict) -> Optional[dict]:
    """Pick the largest single-metric jump as a headline."""
    candidates = []
    for k, label in [
        ("delta_xwoba", "xwOBA"),
        ("delta_barrel_pct", "barrel%"),
        ("delta_hard_hit_pct", "hard-hit%"),
        ("delta_sprint_speed", "sprint speed"),
        ("delta_xera", "xERA"),
        ("delta_whiff_pct", "whiff%"),
        ("delta_k_pct", "K%"),
        ("delta_bb_pct", "BB%"),
        ("delta_chase_rate", "chase%"),
    ]:
        v = baseline.get(k)
        if v is None:
            continue
        # Normalize for "magnitude of improvement" — invert xera and bb_pct
        magnitude = -v if k in ("delta_xera", "delta_bb_pct") else v
        candidates.append((magnitude, k, label, v))
    if not candidates:
        return None
    candidates.sort(key=lambda t: -t[0])
    _, key, label, raw_value = candidates[0]
    sign = "+" if raw_value > 0 else ""
    return {
        "metric": key,
        "label": f"{sign}{round(raw_value, 2)} {label}",
    }


def compute_stealth_view(
    baselines: list[dict],
    player_meta: dict[int, dict],
    roster_status_by_id: dict[int, str],
    current_stats: dict[int, dict],
    proj_stats: dict[int, dict],
    scope: str = "FA",
    position_filter: Optional[str] = None,
    player_type_filter: Optional[str] = None,
    limit: int = 50,
) -> dict:
    """Stealth Breakouts: rank players by skill-change z-score.

    Inputs:
      baselines: rows from ``statcast_baselines`` (dicts).
      player_meta: mlb_id -> {"name", "team", "position"}.
      roster_status_by_id: mlb_id -> "FA" | "team_<id>" | "my_team".
      current_stats / proj_stats: mlb_id -> sparse dict with surface stats
        for the "current vs projection" footnote.
      scope: "FA" | "rostered" | "all".
      position_filter: e.g. "OF", or None for all.
      player_type_filter: "hitter" | "pitcher" | None.
    """
    filtered: list[dict] = []
    for b in baselines:
        if not b.get("qualifies_pa_ip"):
            continue
        if b.get("skill_change_zscore") is None:
            continue
        mid = b["mlb_id"]
        rs = roster_status_by_id.get(mid, "FA")
        if scope == "FA" and rs != "FA":
            continue
        if scope == "rostered" and rs == "FA":
            continue
        if player_type_filter and b.get("player_type") != player_type_filter:
            continue
        meta = player_meta.get(mid, {})
        if position_filter and position_filter != "All":
            if position_filter not in (meta.get("position") or ""):
                continue
        filtered.append(b)

    filtered.sort(key=lambda b: -(b["skill_change_zscore"] or 0))
    filtered = filtered[:limit]

    recommendations: list[BreakoutRecommendation] = []
    for i, b in enumerate(filtered):
        mid = b["mlb_id"]
        meta = player_meta.get(mid, {})
        rs = roster_status_by_id.get(mid, "FA")
        ptype = b["player_type"]
        # Build metric_deltas with badges
        metric_deltas = {}
        for k in ("delta_xwoba", "delta_barrel_pct", "delta_hard_hit_pct",
                  "delta_sprint_speed", "delta_xera", "delta_whiff_pct",
                  "delta_k_pct", "delta_bb_pct", "delta_chase_rate"):
            v = b.get(k)
            if v is None:
                continue
            # Cheap badge: green for clearly-positive (or negative for inverted),
            # red for the opposite, yellow otherwise.
            inverted = k in ("delta_xera", "delta_bb_pct")
            sign_value = -v if inverted else v
            if sign_value > 0.5:
                badge = "green"
            elif sign_value > -0.5:
                badge = "yellow"
            else:
                badge = "red"
            metric_deltas[k] = {"value": round(v, 3), "badge": badge}

        cur = current_stats.get(mid, {})
        proj = proj_stats.get(mid, {})
        current_vs_projection = {
            k: {"current": cur.get(k), "projected": proj.get(k)}
            for k in cur.keys()
            if proj.get(k) is not None
        }

        recommendations.append(BreakoutRecommendation(
            rank=i + 1,
            add_player={
                "id": mid, "name": meta.get("name", ""),
                "team": meta.get("team", ""),
                "position": meta.get("position", ""),
                "roster_status": rs,
            },
            skill_change_zscore=round(b["skill_change_zscore"], 3),
            headline_delta=_format_headline_delta(b),
            metric_deltas=metric_deltas,
            current_vs_projection=current_vs_projection,
            baseline_source=b.get("baseline_source"),
        ))

    return {"recommendations": recommendations}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/backend/analysis/test_breakouts.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/analysis/breakouts.py tests/backend/analysis/test_breakouts.py
git commit -m "feat(breakouts): add Stealth view skill-change ranker"
```

---

## Task 10: FastAPI endpoint

**Files:**
- Modify: `backend/api/routes.py`
- Test: integration via `httpx.TestClient` (skip for v1 — verify manually)

- [ ] **Step 1: Add the endpoint**

Edit `backend/api/routes.py`. Below the existing waivers imports (around line 18-21), add:

```python
from backend.analysis.breakouts import (
    compute_hot_view,
    compute_stealth_view,
)
from backend.analysis.waivers import (
    load_projections_for_players,
    resolve_espn_names_to_mlbid,
)
```

(`load_projections_for_players` and `resolve_espn_names_to_mlbid` already exist; add to the import list if not already there.)

Add a request model and the endpoint at the bottom of the file (find the end of the existing routes and append):

```python
class BreakoutRequest(BaseModel):
    my_roster: list[dict]
    all_rosters: list[list[dict]]
    free_agents: list[dict]
    remaining_faab: float = 100.0
    season: int = 2026
    view: str  # "hot" | "stealth"
    window: int = 14
    scope: str = "FA"  # "FA" | "rostered" | "all"
    position: Optional[str] = None
    player_type: Optional[str] = None
    games_remaining: int = 130


@router.post("/breakouts/recommendations")
def post_breakouts_recommendations(req: BreakoutRequest):
    """Compute breakout recommendations.

    For ``view="hot"``: returns ranked free agents whose recent pace
    extrapolates to expected-wins improvement, filtered for sustainability.
    For ``view="stealth"``: returns ranked players by composite skill-change
    z-score from ``statcast_baselines``.
    """
    if req.view not in ("hot", "stealth"):
        raise HTTPException(400, "view must be 'hot' or 'stealth'")

    # Resolve ESPN player names to mlb_ids using the same flow as /api/waivers
    espn_names_for_resolution = (
        [{"name": p["name"], "player_type": p.get("player_type")} for p in req.free_agents]
        + [{"name": p["name"], "player_type": p.get("player_type")} for p in req.my_roster]
    )
    for team in req.all_rosters:
        for p in team:
            espn_names_for_resolution.append({"name": p["name"], "player_type": p.get("player_type")})
    name_to_mlbid = resolve_espn_names_to_mlbid(espn_names_for_resolution, season=req.season)

    def _to_mlb_ids(players: list[dict]) -> list[int]:
        return [name_to_mlbid[p["name"]] for p in players if p["name"] in name_to_mlbid]

    def _to_mlb_slots(players: list[dict]) -> list[dict]:
        return [
            {"mlb_id": name_to_mlbid[p["name"]], "lineup_slot_id": p.get("lineup_slot_id", 0)}
            for p in players if p["name"] in name_to_mlbid
        ]

    my_roster_ids = _to_mlb_ids(req.my_roster)
    my_roster_slots = _to_mlb_slots(req.my_roster)
    all_team_slots = [_to_mlb_slots(team) for team in req.all_rosters]
    free_agent_ids = _to_mlb_ids(req.free_agents)

    conn = get_connection()

    if req.view == "hot":
        all_ids = list(set(my_roster_ids + free_agent_ids
                            + [pid for slots in all_team_slots for s in slots for pid in [s["mlb_id"]]]))
        projections = load_projections_for_players(all_ids, req.season)

        # Pull rolling stats for the requested window, scoped to all_ids
        placeholders = ",".join(["?"] * len(all_ids)) if all_ids else "0"
        bat_rolling = {r["mlb_id"]: dict(r) for r in conn.execute(
            f"""SELECT * FROM rolling_batting_stats
                WHERE season = ? AND window_days = ?
                  AND mlb_id IN ({placeholders})""",
            (req.season, req.window, *all_ids),
        ).fetchall()} if all_ids else {}
        pit_rolling = {r["mlb_id"]: dict(r) for r in conn.execute(
            f"""SELECT * FROM rolling_pitching_stats
                WHERE season = ? AND window_days = ?
                  AND mlb_id IN ({placeholders})""",
            (req.season, req.window, *all_ids),
        ).fetchall()} if all_ids else {}
        rolling_stats_by_id = {**bat_rolling, **pit_rolling}

        bat_sc = {r["mlb_id"]: dict(r) for r in conn.execute(
            f"""SELECT * FROM statcast_batting WHERE season = ? AND mlb_id IN ({placeholders})""",
            (req.season, *all_ids),
        ).fetchall()} if all_ids else {}
        pit_sc = {r["mlb_id"]: dict(r) for r in conn.execute(
            f"""SELECT * FROM statcast_pitching WHERE season = ? AND mlb_id IN ({placeholders})""",
            (req.season, *all_ids),
        ).fetchall()} if all_ids else {}
        # Add ERA from pitching_stats so xera-vs-era check works
        for mid in pit_sc:
            row = conn.execute(
                "SELECT era FROM pitching_stats WHERE mlb_id = ? AND season = ?",
                (mid, req.season),
            ).fetchone()
            if row:
                pit_sc[mid]["era"] = row["era"]
        # Add wOBA from rolling_batting? We use the prior-stored wOBA (statcast_batting.woba)
        statcast_by_id = {**bat_sc, **pit_sc}

        # Estimate games-in-window from any player's rolling row (max games count)
        games_in_window_estimate = max(
            (s.get("games", 0) for s in rolling_stats_by_id.values()),
            default=req.window,
        )
        result = compute_hot_view(
            my_roster_ids=my_roster_ids,
            my_roster_slots=my_roster_slots,
            all_team_roster_slots=all_team_slots,
            free_agent_ids=free_agent_ids,
            projections=projections,
            rolling_stats_by_id=rolling_stats_by_id,
            statcast_by_id=statcast_by_id,
            games_in_window=games_in_window_estimate,
            games_remaining=req.games_remaining,
            remaining_faab=req.remaining_faab,
        )

        as_of = max(
            (s.get("as_of_date") for s in rolling_stats_by_id.values() if s.get("as_of_date")),
            default=None,
        )
        conn.close()
        return {
            "as_of_date": as_of,
            "view": "hot",
            "window": req.window,
            "baseline_expected_wins": result["baseline_expected_wins"],
            "baseline_category_probs": result["baseline_category_probs"],
            "recommendations": [
                {
                    "rank": r.rank,
                    "add_player": r.add_player,
                    "drop_player": r.drop_player,
                    "wins_added_if_rate_continues": r.wins_added_if_rate_continues,
                    "suggested_faab_bid": r.suggested_faab_bid,
                    "window_stats": r.window_stats,
                    "sustainability_badges": r.sustainability_badges,
                    "sustainability_score": r.sustainability_score,
                }
                for r in result["recommendations"]
            ],
        }

    # Stealth view
    baselines = [dict(r) for r in conn.execute(
        "SELECT * FROM statcast_baselines WHERE season = ?", (req.season,),
    ).fetchall()]

    # Build player_meta from players table for the candidate pool
    candidate_ids = [b["mlb_id"] for b in baselines]
    player_meta: dict[int, dict] = {}
    if candidate_ids:
        ph = ",".join(["?"] * len(candidate_ids))
        for r in conn.execute(
            f"SELECT mlb_id, full_name, primary_position, team FROM players WHERE mlb_id IN ({ph})",
            tuple(candidate_ids),
        ).fetchall():
            player_meta[r["mlb_id"]] = {
                "name": r["full_name"],
                "team": r["team"] or "",
                "position": r["primary_position"] or "",
            }

    # Roster status: my_roster, other rosters, otherwise FA
    roster_status_by_id: dict[int, str] = {pid: "my_team" for pid in my_roster_ids}
    for i, team in enumerate(all_team_slots):
        for s in team:
            roster_status_by_id.setdefault(s["mlb_id"], f"team_{i}")
    # Default fall-through is "FA" — handled inside compute_stealth_view

    # Current vs projection: surface stats — current pulled from season totals,
    # projected from rankings table
    current_stats: dict[int, dict] = {}
    proj_stats: dict[int, dict] = {}
    if candidate_ids:
        ph = ",".join(["?"] * len(candidate_ids))
        for r in conn.execute(
            f"""SELECT mlb_id, ops, era, whip
                FROM batting_stats LEFT JOIN pitching_stats USING (mlb_id, season)
                WHERE season = ? AND mlb_id IN ({ph})""",
            (req.season, *candidate_ids),
        ).fetchall():
            current_stats[r["mlb_id"]] = {
                "ops": r["ops"], "era": r["era"], "whip": r["whip"],
            }
        for r in conn.execute(
            f"""SELECT mlb_id, proj_obp, proj_era, proj_whip
                FROM rankings WHERE season = ? AND mlb_id IN ({ph})""",
            (req.season, *candidate_ids),
        ).fetchall():
            proj_stats[r["mlb_id"]] = {
                "ops": (r["proj_obp"] or 0) + 0,  # rough proxy; OPS not stored
                "era": r["proj_era"], "whip": r["proj_whip"],
            }

    result = compute_stealth_view(
        baselines=baselines,
        player_meta=player_meta,
        roster_status_by_id=roster_status_by_id,
        current_stats=current_stats,
        proj_stats=proj_stats,
        scope=req.scope,
        position_filter=req.position,
        player_type_filter=req.player_type,
    )
    conn.close()
    return {
        "view": "stealth",
        "recommendations": [
            {
                "rank": r.rank,
                "player": r.add_player,
                "skill_change_zscore": r.skill_change_zscore,
                "headline_delta": r.headline_delta,
                "metric_deltas": r.metric_deltas,
                "current_vs_projection": r.current_vs_projection,
                "baseline_source": r.baseline_source,
            }
            for r in result["recommendations"]
        ],
    }
```

- [ ] **Step 2: Verify the route registers**

Run the FastAPI server and confirm the endpoint exists:

```bash
cd /Users/jgibbons/code/fantasy-baseball-helper
uvicorn backend.api.main:app --reload --port 8000 &
sleep 2
curl -s http://localhost:8000/openapi.json | jq '.paths | keys[]' | grep breakouts
kill %1
```

Expected output: `"/api/breakouts/recommendations"` (or whichever prefix the existing router uses; if `/api` prefix isn't applied, the path will be `/breakouts/recommendations`).

- [ ] **Step 3: Commit**

```bash
git add backend/api/routes.py
git commit -m "feat(api): POST /breakouts/recommendations for hot + stealth views"
```

---

## Task 11: Next.js orchestrator route

**Files:**
- Create: `src/app/api/breakouts/recommendations/route.ts`

- [ ] **Step 1: Implement the orchestrator**

This route mirrors `src/app/api/waivers/recommendations/route.ts` — it fetches ESPN data, then forwards to the Python backend.

Create `src/app/api/breakouts/recommendations/route.ts`:

```typescript
import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { ESPNApi, ESPNRosterEntry } from '@/lib/espn-api'

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000'

const posMap: Record<number, string> = {
  1: 'SP', 2: 'C', 3: '1B', 4: '2B', 5: '3B',
  6: 'SS', 7: 'LF', 8: 'CF', 9: 'RF', 10: 'DH',
  11: 'RP',
}
const slotToPos: Record<number, string> = {
  0: 'C', 1: '1B', 2: '2B', 3: '3B', 4: 'SS',
  5: 'OF', 8: 'OF', 9: 'OF', 10: 'OF',
  11: 'DH', 14: 'SP', 15: 'RP',
}
const POS_ORDER = ['C', '1B', '2B', '3B', 'SS', 'OF', 'SP', 'RP', 'DH']

function eligiblePositionsFromSlots(eligibleSlots: number[] | undefined, fallbackId: number | undefined): string {
  if (eligibleSlots && eligibleSlots.length > 0) {
    const seen = new Set<string>()
    for (const s of eligibleSlots) {
      const pos = slotToPos[s]
      if (pos) seen.add(pos)
    }
    if (seen.size > 0) return POS_ORDER.filter((p) => seen.has(p)).join('/')
  }
  return posMap[fallbackId ?? 0] || 'UTIL'
}

function espnPlayerType(defaultPositionId: number | undefined): string {
  return defaultPositionId === 1 || defaultPositionId === 11 ? 'pitcher' : 'hitter'
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json()
    const {
      leagueId,
      teamId,
      season = '2026',
      view,           // "hot" | "stealth"
      window = 14,
      scope = 'FA',
      position,
      playerType,
      gamesRemaining = 130,
    } = body

    if (!leagueId || !teamId) {
      return NextResponse.json({ error: 'leagueId and teamId required' }, { status: 400 })
    }
    if (view !== 'hot' && view !== 'stealth') {
      return NextResponse.json({ error: 'view must be hot or stealth' }, { status: 400 })
    }

    const league = await prisma.league.findUnique({ where: { id: leagueId } })
    if (!league || !league.externalId) {
      return NextResponse.json({ error: 'League not found' }, { status: 404 })
    }

    const espn = await ESPNApi.fromLeagueId(leagueId)
    const seasonNum = parseInt(season, 10)

    const rosters = await espn.getRosters(seasonNum)
    const myTeam = rosters.teams.find((t: any) => String(t.id) === String(teamId))
    if (!myTeam) {
      return NextResponse.json({ error: 'Team not found in league' }, { status: 404 })
    }

    const myRoster = (myTeam.roster || []).map((p: ESPNRosterEntry) => ({
      name: p.fullName,
      lineup_slot_id: p.lineupSlotId,
      eligible_positions: eligiblePositionsFromSlots(p.eligibleSlots, p.defaultPositionId),
      player_type: espnPlayerType(p.defaultPositionId),
    }))

    const allRosters: any[] = rosters.teams
      .filter((t: any) => String(t.id) !== String(teamId))
      .map((t: any) => (t.roster || []).map((p: ESPNRosterEntry) => ({
        name: p.fullName,
        lineup_slot_id: p.lineupSlotId,
        player_type: espnPlayerType(p.defaultPositionId),
      })))

    const fas = await espn.getFreeAgents(seasonNum)
    const freeAgents = fas.map((p: any) => ({
      name: p.fullName,
      lineup_slot_id: 0,
      player_type: espnPlayerType(p.defaultPositionId),
    }))

    const remainingFaab = myTeam.faabRemaining ?? 100

    const backendBody = {
      my_roster: myRoster,
      all_rosters: allRosters,
      free_agents: freeAgents,
      remaining_faab: remainingFaab,
      season: seasonNum,
      view,
      window,
      scope,
      position,
      player_type: playerType,
      games_remaining: gamesRemaining,
    }

    const resp = await fetch(`${BACKEND_URL}/api/breakouts/recommendations`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(backendBody),
    })

    if (!resp.ok) {
      const text = await resp.text()
      return NextResponse.json({ error: `Backend error: ${text}` }, { status: resp.status })
    }
    const data = await resp.json()
    return NextResponse.json({
      ...data,
      remaining_faab: remainingFaab,
      my_roster_count: myRoster.length,
      free_agent_count: freeAgents.length,
    })
  } catch (err: any) {
    return NextResponse.json({ error: err.message || 'Unknown error' }, { status: 500 })
  }
}
```

- [ ] **Step 2: Verify the route compiles**

Run: `cd /Users/jgibbons/code/fantasy-baseball-helper && npx next build --no-lint` (or `npm run build`).
Expected: Build succeeds without TypeScript errors. If `getFreeAgents` doesn't exist on ESPNApi yet, the build will fail; in that case, follow the existing waivers route's pattern for fetching free agents (already implemented per the design spec) — verify by reading `src/lib/espn-api.ts` and `src/app/api/waivers/recommendations/route.ts`.

- [ ] **Step 3: Commit**

```bash
git add src/app/api/breakouts/recommendations/route.ts
git commit -m "feat(api): Next.js orchestrator for breakout recommendations"
```

---

## Task 12: Refactor `/waivers` page to introduce tab strip

**Files:**
- Modify: `src/app/waivers/page.tsx`
- Create: `src/app/waivers/_components/ProjectionsTab.tsx`

- [ ] **Step 1: Extract current page content into ProjectionsTab**

Read `src/app/waivers/page.tsx` end-to-end. Then:

1. Create `src/app/waivers/_components/ProjectionsTab.tsx` and move the bulk of the current `WaiversPage` body into it. Keep all state, fetching, and rendering logic — the refactor is purely structural.
2. The new `ProjectionsTab` should accept three props: `selectedLeague: string`, `selectedTeam: string`, `credentialsOk: boolean | null`.

Sketch:

```typescript
'use client'

import { useState, useEffect, useMemo, useRef } from 'react'
// ... copy other imports from page.tsx ...

interface Props {
  selectedLeague: string
  selectedTeam: string
  credentialsOk: boolean | null
}

export default function ProjectionsTab({ selectedLeague, selectedTeam, credentialsOk }: Props) {
  // Move all state from WaiversPage that relates to the recommendations table:
  // results, loading, error, posFilter, refreshing, refreshStatus,
  // excludeStreamSlot, includeCrossType, autoFetched ref, etc.
  // Move all useEffects and handlers (handleFetchRecommendations,
  // handleRefreshProjections, rosterBySlot useMemo, etc.).
  // Render the existing table, controls, and roster panel.
  return (/* the current JSX body of /waivers */)
}
```

2. Edit `src/app/waivers/page.tsx`. Replace the body with a tab-aware shell:

```typescript
'use client'

import { useState, useEffect } from 'react'
import { useSearchParams, useRouter, usePathname } from 'next/navigation'
import Link from 'next/link'
import ProjectionsTab from './_components/ProjectionsTab'
import HotTab from './_components/HotTab'
import StealthTab from './_components/StealthTab'

type TabKey = 'projections' | 'hot' | 'stealth'

const STORAGE_KEY = 'waiver_settings'

interface League { id: string; name: string; platform: string; season: string; externalId?: string }
interface Team { id: string; externalId: string; name: string; ownerName?: string }

function loadSettings(): { leagueId: string; teamId: string } | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const s = JSON.parse(raw)
    if (s.leagueId && s.teamId) return { leagueId: s.leagueId, teamId: s.teamId }
    return null
  } catch { return null }
}

function saveSettings(leagueId: string, teamId: string) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ leagueId, teamId }))
}

export default function WaiversPage() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()
  const tab = (searchParams.get('tab') as TabKey) || 'projections'

  const [leagues, setLeagues] = useState<League[]>([])
  const [teams, setTeams] = useState<Team[]>([])
  const [selectedLeague, setSelectedLeague] = useState<string>('')
  const [selectedTeam, setSelectedTeam] = useState<string>('')
  const [credentialsOk, setCredentialsOk] = useState<boolean | null>(null)

  useEffect(() => {
    fetch('/api/leagues')
      .then((r) => r.ok ? r.json() : [])
      .then((data) => {
        setLeagues(data)
        const saved = loadSettings()
        if (saved) {
          setSelectedLeague(saved.leagueId)
          setSelectedTeam(saved.teamId)
        }
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (!selectedLeague) return
    fetch(`/api/leagues/${selectedLeague}/teams`)
      .then((r) => r.ok ? r.json() : { teams: [] })
      .then((data) => setTeams(data.teams || []))
      .catch(() => {})
  }, [selectedLeague])

  useEffect(() => {
    if (!selectedLeague) { setCredentialsOk(null); return }
    fetch(`/api/leagues/${selectedLeague}/credentials`)
      .then((r) => r.ok ? r.json() : { has_credentials: false })
      .then((data) => setCredentialsOk(data.has_credentials === true))
      .catch(() => setCredentialsOk(false))
  }, [selectedLeague])

  function setTab(t: TabKey) {
    const sp = new URLSearchParams(searchParams.toString())
    sp.set('tab', t)
    router.replace(`${pathname}?${sp.toString()}`)
  }

  function setLeagueTeam(leagueId: string, teamId: string) {
    setSelectedLeague(leagueId)
    setSelectedTeam(teamId)
    if (leagueId && teamId) saveSettings(leagueId, teamId)
  }

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      <header className="border-b border-gray-800 px-6 py-4 flex items-center gap-4">
        <h1 className="text-xl font-semibold">Waiver Wire</h1>
        <Link href="/" className="text-sm text-gray-400 hover:text-gray-200">← Home</Link>
      </header>

      <div className="px-6 py-3 border-b border-gray-800 flex flex-col sm:flex-row gap-3 sm:items-center">
        {/* League/Team selectors — kept here so all tabs share one config */}
        <select
          className="bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm"
          value={selectedLeague}
          onChange={(e) => setLeagueTeam(e.target.value, '')}
        >
          <option value="">— League —</option>
          {leagues.map((l) => (
            <option key={l.id} value={l.id}>{l.name} ({l.season})</option>
          ))}
        </select>
        <select
          className="bg-gray-900 border border-gray-700 rounded px-2 py-1 text-sm"
          value={selectedTeam}
          onChange={(e) => setLeagueTeam(selectedLeague, e.target.value)}
          disabled={!selectedLeague}
        >
          <option value="">— Team —</option>
          {teams.map((t) => (
            <option key={t.id} value={t.id}>{t.name}</option>
          ))}
        </select>
        {credentialsOk === false && (
          <span className="text-xs text-amber-400">No ESPN credentials saved for this league</span>
        )}
      </div>

      <nav className="px-6 border-b border-gray-800 flex gap-1">
        {(['projections', 'hot', 'stealth'] as TabKey[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm border-b-2 transition-colors ${
              tab === t
                ? 'border-emerald-500 text-emerald-300'
                : 'border-transparent text-gray-400 hover:text-gray-200'
            }`}
          >
            {t === 'projections' && 'Projections-Based'}
            {t === 'hot' && 'Hot + Sustainable'}
            {t === 'stealth' && 'Stealth Breakouts'}
          </button>
        ))}
      </nav>

      <div className="p-6">
        {tab === 'projections' && (
          <ProjectionsTab
            selectedLeague={selectedLeague}
            selectedTeam={selectedTeam}
            credentialsOk={credentialsOk}
          />
        )}
        {tab === 'hot' && (
          <HotTab
            selectedLeague={selectedLeague}
            selectedTeam={selectedTeam}
            credentialsOk={credentialsOk}
          />
        )}
        {tab === 'stealth' && (
          <StealthTab
            selectedLeague={selectedLeague}
            selectedTeam={selectedTeam}
            credentialsOk={credentialsOk}
          />
        )}
      </div>
    </div>
  )
}
```

3. Stub-create the two new tabs so the page compiles. Create empty placeholders:

```typescript
// src/app/waivers/_components/HotTab.tsx
'use client'
interface Props { selectedLeague: string; selectedTeam: string; credentialsOk: boolean | null }
export default function HotTab(_: Props) {
  return <div className="text-gray-400 text-sm">Hot + Sustainable view — coming up next.</div>
}

// src/app/waivers/_components/StealthTab.tsx
'use client'
interface Props { selectedLeague: string; selectedTeam: string; credentialsOk: boolean | null }
export default function StealthTab(_: Props) {
  return <div className="text-gray-400 text-sm">Stealth Breakouts view — coming up next.</div>
}
```

- [ ] **Step 2: Verify the build still works and the existing tab still renders**

Run: `npm run build` and `npm run dev`. Open `http://localhost:3000/waivers` and confirm:
- Default landing shows the tab strip with "Projections-Based" highlighted
- Existing recommendations table still renders identically when league/team are configured
- `?tab=hot` and `?tab=stealth` show the placeholder messages

- [ ] **Step 3: Commit**

```bash
git add src/app/waivers/page.tsx src/app/waivers/_components/
git commit -m "refactor(waivers): split into tabs (Projections / Hot / Stealth)"
```

---

## Task 13: Implement HotTab UI

**Files:**
- Modify: `src/app/waivers/_components/HotTab.tsx`

- [ ] **Step 1: Build out the Hot tab UI**

Replace `src/app/waivers/_components/HotTab.tsx` with a working component:

```typescript
'use client'

import { useState, useEffect } from 'react'

interface Props {
  selectedLeague: string
  selectedTeam: string
  credentialsOk: boolean | null
}

interface PlayerRef { id: number; name: string; position: string; team?: string; roster_status?: string }

interface HotRecommendation {
  rank: number
  add_player: PlayerRef
  drop_player: PlayerRef | null
  wins_added_if_rate_continues: number
  suggested_faab_bid: number
  window_stats: Record<string, number>
  sustainability_badges: Record<string, 'green' | 'yellow' | 'red' | 'gray'>
  sustainability_score: number
}

interface HotResults {
  as_of_date: string | null
  view: 'hot'
  window: number
  baseline_expected_wins: number
  recommendations: HotRecommendation[]
  remaining_faab: number
}

const badgeColor: Record<string, string> = {
  green: 'bg-emerald-500/20 text-emerald-300',
  yellow: 'bg-amber-500/20 text-amber-300',
  red: 'bg-red-500/20 text-red-300',
  gray: 'bg-gray-500/20 text-gray-400',
}

const POSITIONS = ['All', 'C', '1B', '2B', '3B', 'SS', 'OF', 'DH', 'SP', 'RP']

export default function HotTab({ selectedLeague, selectedTeam, credentialsOk }: Props) {
  const [windowDays, setWindowDays] = useState<number>(14)
  const [scope, setScope] = useState<'FA' | 'rostered' | 'all'>('FA')
  const [posFilter, setPosFilter] = useState<string>('All')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [results, setResults] = useState<HotResults | null>(null)

  async function fetchRecommendations() {
    if (!selectedLeague || !selectedTeam) return
    setLoading(true); setError(null)
    try {
      const resp = await fetch('/api/breakouts/recommendations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          leagueId: selectedLeague,
          teamId: selectedTeam,
          view: 'hot',
          window: windowDays,
          scope,
          position: posFilter === 'All' ? undefined : posFilter,
        }),
      })
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}))
        throw new Error(data.error || `Error ${resp.status}`)
      }
      setResults(await resp.json())
    } catch (e: any) {
      setError(e.message || 'Failed')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (selectedLeague && selectedTeam && credentialsOk) {
      fetchRecommendations()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedLeague, selectedTeam, credentialsOk, windowDays, scope, posFilter])

  if (!selectedLeague || !selectedTeam) {
    return <div className="text-gray-400 text-sm">Select a league and team above.</div>
  }
  if (credentialsOk === false) {
    return <div className="text-amber-400 text-sm">No ESPN credentials saved for this league.</div>
  }

  return (
    <div>
      <div className="flex flex-wrap gap-3 items-center mb-4">
        <label className="text-sm text-gray-400">
          Window:
          <select
            value={windowDays}
            onChange={(e) => setWindowDays(parseInt(e.target.value, 10))}
            className="ml-2 bg-gray-900 border border-gray-700 rounded px-2 py-1"
          >
            <option value={7}>7 days</option>
            <option value={14}>14 days</option>
            <option value={30}>30 days</option>
          </select>
        </label>
        <label className="text-sm text-gray-400">
          Scope:
          <select
            value={scope}
            onChange={(e) => setScope(e.target.value as any)}
            className="ml-2 bg-gray-900 border border-gray-700 rounded px-2 py-1"
          >
            <option value="FA">Free Agents</option>
            <option value="rostered">Rostered</option>
            <option value="all">All</option>
          </select>
        </label>
        <label className="text-sm text-gray-400">
          Position:
          <select
            value={posFilter}
            onChange={(e) => setPosFilter(e.target.value)}
            className="ml-2 bg-gray-900 border border-gray-700 rounded px-2 py-1"
          >
            {POSITIONS.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </label>
        {results?.as_of_date && (
          <span className="text-xs text-gray-500 ml-auto">Data as of {results.as_of_date}</span>
        )}
      </div>

      {loading && <div className="text-gray-400 text-sm">Loading...</div>}
      {error && <div className="text-red-400 text-sm">{error}</div>}

      {results && (
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="text-gray-400 border-b border-gray-800">
              <tr>
                <th className="text-left p-2">#</th>
                <th className="text-left p-2">Add</th>
                <th className="text-left p-2">Drop</th>
                <th className="text-right p-2">Wins+</th>
                <th className="text-left p-2">Window</th>
                <th className="text-left p-2">Badges</th>
                <th className="text-right p-2">Bid</th>
              </tr>
            </thead>
            <tbody>
              {results.recommendations.map((r) => (
                <tr key={r.rank} className="border-b border-gray-900 hover:bg-gray-900/50">
                  <td className="p-2 text-gray-500">{r.rank}</td>
                  <td className="p-2">
                    <div className="font-medium">{r.add_player.name}</div>
                    <div className="text-xs text-gray-500">{r.add_player.position}</div>
                  </td>
                  <td className="p-2 text-gray-400">
                    {r.drop_player ? r.drop_player.name : '—'}
                  </td>
                  <td className="p-2 text-right text-emerald-400">
                    +{r.wins_added_if_rate_continues.toFixed(2)}
                  </td>
                  <td className="p-2 text-xs text-gray-400">
                    {r.window_stats?.pa
                      ? `${r.window_stats.pa} PA, .${(r.window_stats.obp * 1000 | 0).toString().padStart(3, '0')} OBP`
                      : r.window_stats?.ip
                        ? `${r.window_stats.ip} IP, ${r.window_stats.era?.toFixed(2)} ERA`
                        : ''}
                  </td>
                  <td className="p-2">
                    <div className="flex flex-wrap gap-1">
                      {Object.entries(r.sustainability_badges).map(([metric, color]) => (
                        <span
                          key={metric}
                          className={`px-1.5 py-0.5 rounded text-xs ${badgeColor[color]}`}
                          title={`${metric}: ${color}`}
                        >
                          {metric.replace('_', ' ')}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="p-2 text-right text-amber-300">
                    ${r.suggested_faab_bid}
                  </td>
                </tr>
              ))}
              {results.recommendations.length === 0 && (
                <tr><td colSpan={7} className="p-4 text-center text-gray-500">No qualifying breakouts in this window.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Manual smoke test**

With backend running and rolling stats synced, open `/waivers?tab=hot`. Verify:
- Window dropdown changes the result set
- Scope filter changes scope
- Each row shows badges, FAAB bid, window stats

- [ ] **Step 3: Commit**

```bash
git add src/app/waivers/_components/HotTab.tsx
git commit -m "feat(waivers): Hot + Sustainable tab UI"
```

---

## Task 14: Implement StealthTab UI

**Files:**
- Modify: `src/app/waivers/_components/StealthTab.tsx`

- [ ] **Step 1: Build out the Stealth tab UI**

Replace `src/app/waivers/_components/StealthTab.tsx`:

```typescript
'use client'

import { useState, useEffect } from 'react'

interface Props {
  selectedLeague: string
  selectedTeam: string
  credentialsOk: boolean | null
}

interface PlayerRef { id: number; name: string; team?: string; position: string; roster_status?: string }

interface MetricDelta { value: number; badge: 'green' | 'yellow' | 'red' | 'gray' }

interface StealthRecommendation {
  rank: number
  player: PlayerRef
  skill_change_zscore: number
  headline_delta: { metric: string; label: string } | null
  metric_deltas: Record<string, MetricDelta>
  current_vs_projection: Record<string, { current: number | null; projected: number | null }>
  baseline_source: string | null
}

interface StealthResults {
  view: 'stealth'
  recommendations: StealthRecommendation[]
}

const badgeColor: Record<string, string> = {
  green: 'bg-emerald-500/20 text-emerald-300',
  yellow: 'bg-amber-500/20 text-amber-300',
  red: 'bg-red-500/20 text-red-300',
  gray: 'bg-gray-500/20 text-gray-400',
}

const POSITIONS = ['All', 'C', '1B', '2B', '3B', 'SS', 'OF', 'DH', 'SP', 'RP']

export default function StealthTab({ selectedLeague, selectedTeam, credentialsOk }: Props) {
  const [scope, setScope] = useState<'FA' | 'rostered' | 'all'>('FA')
  const [posFilter, setPosFilter] = useState<string>('All')
  const [playerType, setPlayerType] = useState<'' | 'hitter' | 'pitcher'>('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [results, setResults] = useState<StealthResults | null>(null)

  async function fetchRecommendations() {
    if (!selectedLeague || !selectedTeam) return
    setLoading(true); setError(null)
    try {
      const resp = await fetch('/api/breakouts/recommendations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          leagueId: selectedLeague,
          teamId: selectedTeam,
          view: 'stealth',
          scope,
          position: posFilter === 'All' ? undefined : posFilter,
          playerType: playerType || undefined,
        }),
      })
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}))
        throw new Error(data.error || `Error ${resp.status}`)
      }
      setResults(await resp.json())
    } catch (e: any) {
      setError(e.message || 'Failed')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (selectedLeague && selectedTeam && credentialsOk) {
      fetchRecommendations()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedLeague, selectedTeam, credentialsOk, scope, posFilter, playerType])

  if (!selectedLeague || !selectedTeam) {
    return <div className="text-gray-400 text-sm">Select a league and team above.</div>
  }
  if (credentialsOk === false) {
    return <div className="text-amber-400 text-sm">No ESPN credentials saved for this league.</div>
  }

  return (
    <div>
      <div className="flex flex-wrap gap-3 items-center mb-4">
        <label className="text-sm text-gray-400">
          Scope:
          <select
            value={scope}
            onChange={(e) => setScope(e.target.value as any)}
            className="ml-2 bg-gray-900 border border-gray-700 rounded px-2 py-1"
          >
            <option value="FA">Free Agents</option>
            <option value="rostered">Rostered</option>
            <option value="all">All</option>
          </select>
        </label>
        <label className="text-sm text-gray-400">
          Position:
          <select
            value={posFilter}
            onChange={(e) => setPosFilter(e.target.value)}
            className="ml-2 bg-gray-900 border border-gray-700 rounded px-2 py-1"
          >
            {POSITIONS.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </label>
        <label className="text-sm text-gray-400">
          Type:
          <select
            value={playerType}
            onChange={(e) => setPlayerType(e.target.value as any)}
            className="ml-2 bg-gray-900 border border-gray-700 rounded px-2 py-1"
          >
            <option value="">All</option>
            <option value="hitter">Hitters</option>
            <option value="pitcher">Pitchers</option>
          </select>
        </label>
      </div>

      {loading && <div className="text-gray-400 text-sm">Loading...</div>}
      {error && <div className="text-red-400 text-sm">{error}</div>}

      {results && (
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="text-gray-400 border-b border-gray-800">
              <tr>
                <th className="text-left p-2">#</th>
                <th className="text-left p-2">Player</th>
                <th className="text-right p-2">Z</th>
                <th className="text-left p-2">Headline</th>
                <th className="text-left p-2">Metric Deltas</th>
                <th className="text-left p-2">Baseline</th>
              </tr>
            </thead>
            <tbody>
              {results.recommendations.map((r) => (
                <tr key={r.rank} className="border-b border-gray-900 hover:bg-gray-900/50">
                  <td className="p-2 text-gray-500">{r.rank}</td>
                  <td className="p-2">
                    <div className="font-medium">{r.player.name}</div>
                    <div className="text-xs text-gray-500">
                      {r.player.team} · {r.player.position} · {r.player.roster_status}
                    </div>
                  </td>
                  <td className="p-2 text-right text-emerald-300">
                    {r.skill_change_zscore.toFixed(2)}
                  </td>
                  <td className="p-2 text-emerald-400">{r.headline_delta?.label}</td>
                  <td className="p-2">
                    <div className="flex flex-wrap gap-1">
                      {Object.entries(r.metric_deltas).map(([k, m]) => (
                        <span
                          key={k}
                          className={`px-1.5 py-0.5 rounded text-xs ${badgeColor[m.badge]}`}
                          title={`${k}: ${m.value}`}
                        >
                          {k.replace('delta_', '')}: {m.value > 0 ? '+' : ''}{m.value}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="p-2 text-xs text-gray-500">{r.baseline_source}</td>
                </tr>
              ))}
              {results.recommendations.length === 0 && (
                <tr><td colSpan={6} className="p-4 text-center text-gray-500">No qualifying stealth breakouts.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Manual smoke test**

Open `/waivers?tab=stealth` with backend running and `statcast_baselines` populated. Verify:
- Top recommendation shows a clear headline delta
- Filters update the result set
- Roster status appears next to the player

- [ ] **Step 3: Commit**

```bash
git add src/app/waivers/_components/StealthTab.tsx
git commit -m "feat(waivers): Stealth Breakouts tab UI"
```

---

## Task 15: Daily sync orchestrator script + cron documentation

**Files:**
- Create: `backend/scripts/daily_breakout_sync.py`
- Modify: `backend/scripts/__init__.py` (if it doesn't exist as a package, create empty file)
- Modify: `README.md` (add a "Daily breakout sync" section, or create one inline if README isn't present)

- [ ] **Step 1: Verify the scripts package init exists**

Run: `ls backend/scripts/__init__.py 2>/dev/null || touch backend/scripts/__init__.py`

- [ ] **Step 2: Create the orchestrator script**

Create `backend/scripts/daily_breakout_sync.py`:

```python
"""Daily breakout-finder sync orchestrator.

Run this at 03:00 ET daily, before the 04:00 ET ESPN waiver run, to refresh:
  1. rolling_batting_stats / rolling_pitching_stats (7/14/30 day windows)
  2. statcast_batting / statcast_pitching (current season)
  3. statcast_baselines (deltas + composites)

Each step is idempotent. Failures in one step don't block the others.

Usage:
    python -m backend.scripts.daily_breakout_sync --season 2026
"""

from __future__ import annotations

import argparse
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--skip-rolling", action="store_true")
    parser.add_argument("--skip-statcast", action="store_true")
    parser.add_argument("--skip-baselines", action="store_true")
    args = parser.parse_args()

    failures = 0

    if not args.skip_rolling:
        try:
            from backend.data.rolling_stats import sync_rolling_stats
            logger.info("Step 1/3: rolling stats")
            sync_rolling_stats(season=args.season)
        except Exception as e:
            logger.error(f"Rolling stats sync failed: {e}", exc_info=True)
            failures += 1

    if not args.skip_statcast:
        try:
            from backend.data.statcast import sync_statcast_data
            logger.info("Step 2/3: current-season Statcast")
            sync_statcast_data(season=args.season)
        except Exception as e:
            logger.error(f"Statcast sync failed: {e}", exc_info=True)
            failures += 1

    if not args.skip_baselines:
        try:
            from backend.analysis.skill_baselines import compute_skill_baselines
            logger.info("Step 3/3: skill baselines")
            compute_skill_baselines(season=args.season)
        except Exception as e:
            logger.error(f"Skill baselines compute failed: {e}", exc_info=True)
            failures += 1

    if failures:
        logger.error(f"{failures} step(s) failed")
        return 1
    logger.info("Daily breakout sync complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Smoke-test the script with skip flags**

Run: `python -m backend.scripts.daily_breakout_sync --season 2026 --skip-rolling --skip-statcast --skip-baselines`
Expected: Logs "Daily breakout sync complete" and exits 0.

Then run the full thing during a season (or manually verify each step works):
```bash
python -m backend.scripts.daily_breakout_sync --season 2026
```
Expected: Logs lines for each of the 3 steps; rows land in the new tables.

- [ ] **Step 4: Document the cron entry**

Find the existing README or docs file that describes operational tasks. If none exists, create `docs/superpowers/specs/2026-05-05-breakout-finder-design.md` is the design doc, but ops belongs in code-adjacent docs. Add the schedule notes to the existing project README. If there's no README, create `docs/operations.md` with:

```markdown
# Operations

## Daily Breakout Sync

Schedule: **03:00 ET daily** (before 04:00 ET ESPN waivers run).

```cron
0 3 * * * cd /path/to/fantasy-baseball-helper && python -m backend.scripts.daily_breakout_sync --season 2026 >> logs/breakout-sync.log 2>&1
```

The script runs three idempotent steps. Failures in one step don't block the
others; check `logs/breakout-sync.log` for any error trace. Re-running the
script in the same day overwrites existing rows.
```

If a README already documents cron, append the entry there instead of creating a new doc.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/daily_breakout_sync.py backend/scripts/__init__.py docs/operations.md
git commit -m "feat(ops): daily breakout sync orchestrator + cron docs"
```

---

## Self-Review Notes (post-plan)

After completing all tasks:

1. **Run the full backend test suite** — `pytest tests/backend/ -v` — all green.
2. **Run the frontend type-check** — `npm run build` — no errors.
3. **Manual end-to-end** during an active season:
   - Open `/waivers?tab=hot` — at least one recommendation, sustainability badges visible, FAAB bids assigned.
   - Open `/waivers?tab=stealth` — top recommendation has a clear headline delta and at least one green badge.
   - Switching window (7 → 14 → 30) on Hot tab visibly changes the result set.
   - Sanity-check: Hot view's top pick should not have all-red sustainability badges; Stealth view's top pick should not already have eye-popping season stats.
4. **Confirm cron runs** the morning after deployment — check `logs/breakout-sync.log` and verify `as_of_date` in the rolling tables advances daily.
