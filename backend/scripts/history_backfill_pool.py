"""Phase 4 prerequisite: realized stats for the FULL player pool, not just draftees.

Usage:
    .venv/bin/python -m backend.scripts.history_backfill_pool
    .venv/bin/python -m backend.scripts.history_backfill_pool --seasons 2019

Phase 2 backfilled only the ~250 players the league drafted each season. That
is the right pool for judging a keeper against its round, but it is the wrong
pool for two of Phase 4's questions, because **replacement level is computed
over whatever pool it is given**:

- `expectedValueAtRound` asks for the value of the player ranked round x 10.
  Over a 250-player pool, round 25 asks for the 250th-best player -- the very
  worst in the pool. Over the ~1,350-player board the app actually builds, it
  asks for a mid-tier player. Testing the assumption against the narrow pool
  measures the pool, not the assumption.
- "Only 139 of 1,358 players cleared replacement while the league rosters 250"
  is meaningless over a pool of exactly the 250 rostered players, where
  replacement sits near the bottom by construction.

So this fetches every player who recorded a season line, via the bulk stats
endpoint -- two calls per season rather than ~2,000 -- and derives quality
starts from game logs for the ~370 pitchers per season who started a game.
Relievers have no starts and therefore no quality starts, so they need no
game-log call at all.

Without the QS derivation every starter would carry a zero in one of four
scored pitcher categories, which would drag pitcher replacement level down and
make every drafted pitcher look better than he was.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

from backend.analysis.performance import _HITTER_UPSERT, _PITCHER_UPSERT
from backend.data.mlb_api import count_quality_starts, parse_innings_pitched
from backend.database import get_connection

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HISTORY_DIR = REPO_ROOT / "backend" / "data" / "fixtures" / "league_history"
BASE_URL = "https://statsapi.mlb.com/api/v1"

PITCHER_POSITIONS = {"P", "SP", "RP"}


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def _num(value, default=0):
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value, default=0) -> int:
    return int(_num(value, default))


def fetch_season_stats(season: int, group: str) -> list[dict]:
    """Every player's season line for one stat group, in one request."""
    resp = httpx.get(f"{BASE_URL}/stats", params={
        "stats": "season", "group": group, "season": season,
        "sportId": 1, "limit": 5000, "playerPool": "All"}, timeout=120)
    resp.raise_for_status()
    stats = resp.json().get("stats", [])
    return stats[0].get("splits", []) if stats else []


async def derive_quality_starts(mlb_ids: list[int], season: int,
                                concurrency: int = 10) -> dict[int, int]:
    """Quality starts per pitcher, from game logs.

    Only called for pitchers with at least one start; a reliever's quality
    starts are zero by definition.
    """
    from backend.data.mlb_api import get_pitching_game_log

    results: dict[int, int] = {}
    semaphore = asyncio.Semaphore(concurrency)

    async def one(mlb_id: int) -> None:
        async with semaphore:
            try:
                log = await get_pitching_game_log(mlb_id, season)
                results[mlb_id] = count_quality_starts(log)
            except Exception:
                # Left absent rather than zeroed: a zero here is
                # indistinguishable from a pitcher who genuinely had none.
                pass

    await asyncio.gather(*(one(i) for i in mlb_ids))
    return results


def upsert_players(conn, splits: list[dict]) -> int:
    """Make sure every player in the pool exists in `players`.

    Historical players are inserted with is_active = 0 so they never reach the
    live draft board, which filters on that column.
    """
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    added = 0
    for split in splits:
        person = split.get("player") or {}
        mlb_id = person.get("id")
        if not mlb_id:
            continue
        position = (split.get("position") or {}).get("abbreviation", "") or ""
        cursor = conn.execute(
            """INSERT OR IGNORE INTO players
               (mlb_id, full_name, first_name, last_name, primary_position,
                player_type, is_active, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 0, ?)""",
            (mlb_id, person.get("fullName", ""), person.get("firstName", ""),
             person.get("lastName", ""), position,
             "pitcher" if position in PITCHER_POSITIONS else "hitter", now))
        added += cursor.rowcount or 0
    return added


def store_hitters(conn, season: int, splits: list[dict]) -> int:
    rows = 0
    for split in splits:
        mlb_id = (split.get("player") or {}).get("id")
        if not mlb_id:
            continue
        s = split["stat"]
        conn.execute(_HITTER_UPSERT, (
            mlb_id, season, _int(s.get("gamesPlayed")),
            _int(s.get("plateAppearances")), _int(s.get("atBats")),
            _int(s.get("runs")), _int(s.get("hits")), _int(s.get("doubles")),
            _int(s.get("triples")), _int(s.get("homeRuns")), _int(s.get("rbi")),
            _int(s.get("stolenBases")), _int(s.get("caughtStealing")),
            _int(s.get("baseOnBalls")), _int(s.get("strikeOuts")),
            _int(s.get("hitByPitch")), _int(s.get("sacFlies")),
            _num(s.get("avg")), _num(s.get("obp")), _num(s.get("slg")),
            _num(s.get("ops")), _int(s.get("totalBases")),
        ))
        rows += 1
    return rows


def store_pitchers(conn, season: int, splits: list[dict],
                   quality_starts: dict[int, int]) -> int:
    rows = 0
    for split in splits:
        mlb_id = (split.get("player") or {}).get("id")
        if not mlb_id:
            continue
        s = split["stat"]
        conn.execute(_PITCHER_UPSERT, (
            mlb_id, season, _int(s.get("gamesPlayed")),
            _int(s.get("gamesStarted")), _int(s.get("wins")),
            _int(s.get("losses")), _num(s.get("era")), _num(s.get("whip")),
            parse_innings_pitched(s.get("inningsPitched")),
            _int(s.get("hits")), _int(s.get("runs")), _int(s.get("earnedRuns")),
            _int(s.get("baseOnBalls")), _int(s.get("strikeOuts")),
            _int(s.get("homeRuns")), _int(s.get("saves")), _int(s.get("holds")),
            quality_starts.get(mlb_id, 0),
        ))
        rows += 1
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seasons", type=int, nargs="*", default=None)
    parser.add_argument("--concurrency", type=int, default=10)
    args = parser.parse_args()

    report = json.loads((HISTORY_DIR / "resolution_report.json").read_text())
    seasons = args.seasons or report["included_seasons"]

    conn = get_connection()
    coverage: dict[int, dict] = {}

    for season in seasons:
        hitting = fetch_season_stats(season, "hitting")
        pitching = fetch_season_stats(season, "pitching")
        if not hitting and not pitching:
            print(f"  {season}  no season lines returned, skipping")
            continue

        added = upsert_players(conn, hitting) + upsert_players(conn, pitching)

        starters = [(s["player"]["id"]) for s in pitching
                    if _int(s["stat"].get("gamesStarted")) > 0
                    and (s.get("player") or {}).get("id")]
        print(f"  {season}  {len(hitting)} hitters, {len(pitching)} pitchers, "
              f"deriving QS for {len(starters)} starters...", flush=True)
        quality_starts = asyncio.run(
            derive_quality_starts(starters, season, args.concurrency))
        missing_qs = len(starters) - len(quality_starts)

        h_rows = store_hitters(conn, season, hitting)
        p_rows = store_pitchers(conn, season, pitching, quality_starts)
        conn.commit()

        coverage[season] = {
            "hitters": h_rows, "pitchers": p_rows,
            "players_added": added,
            "starters": len(starters),
            "quality_starts_derived": len(quality_starts),
            "quality_starts_missing": missing_qs,
        }
        note = f", {missing_qs} QS FAILED" if missing_qs else ""
        print(f"    stored {h_rows} hitting, {p_rows} pitching, "
              f"{added} new players{note}")

    conn.close()
    _write_json(HISTORY_DIR / "pool_coverage.json", {
        "backfilled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": f"{BASE_URL}/stats?stats=season&playerPool=All",
        "by_season": {str(s): c for s, c in sorted(coverage.items())},
    })
    total_missing = sum(c["quality_starts_missing"] for c in coverage.values())
    print(f"\nQuality-start derivations that failed: {total_missing}")
    if total_missing:
        print("  Re-run those seasons: a starter missing QS carries a zero in "
              "one of four scored categories.")
    return 1 if total_missing else 0


if __name__ == "__main__":
    sys.exit(main())
