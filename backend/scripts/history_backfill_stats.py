"""Phase 2: backfill realized stats for every season in the backtest.

Usage:
    .venv/bin/python -m backend.scripts.history_backfill_stats
    .venv/bin/python -m backend.scripts.history_backfill_stats --seasons 2018 2019

`batting_stats` and `pitching_stats` ship with 2024-2026 only. Everything the
multi-season backtest measures — keeper outcomes, the value-at-pick curve — is
computed from realized production, so those tables have to cover every season
first.

Quality starts are derived from game logs (`include_quality_starts=True`)
rather than read from the season endpoint, which does not expose them. Skipping
that step leaves every pitcher with a zero in one of four scored categories,
which is the bug that put no starter in the 2026 ex-post top five.

Player type comes from the season's own roster, so a player who converted (or
Ohtani, who is both) is classified as of that season rather than today.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from backend.analysis.performance import refresh_actuals_for_players
from backend.database import get_connection

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HISTORY_DIR = REPO_ROOT / "backend" / "data" / "fixtures" / "league_history"
ROSTER_CACHE = HISTORY_DIR / "_rosters"

PITCHER_POSITIONS = {"P", "SP", "RP"}
TWO_WAY = "TWP"


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def roster_positions(season: int) -> dict[int, str]:
    """mlb_id -> primary position, from the cached season roster."""
    positions: dict[int, str] = {}
    for delta in (0, -1, 1):
        cache = ROSTER_CACHE / f"players_{season + delta}.json"
        if not cache.exists():
            continue
        for person in json.loads(cache.read_text()):
            positions.setdefault(person["mlb_id"], person.get("primary_position") or "")
    return positions


def season_targets(season: int) -> list[tuple[int, str]]:
    """(mlb_id, player_type) for every resolved player in a season.

    A two-way player yields two targets, because his hitting and his pitching
    are valued on separate boards.
    """
    path = HISTORY_DIR / f"resolution_{season}.json"
    if not path.exists():
        return []
    positions = roster_positions(season)

    targets: set[tuple[int, str]] = set()
    for entry in json.loads(path.read_text())["resolutions"]:
        mlb_id = entry["mlb_id"]
        if mlb_id is None:
            continue
        position = positions.get(mlb_id, "")
        if position == TWO_WAY:
            targets.add((mlb_id, "hitter"))
            targets.add((mlb_id, "pitcher"))
        elif position in PITCHER_POSITIONS:
            targets.add((mlb_id, "pitcher"))
        else:
            targets.add((mlb_id, "hitter"))
    return sorted(targets)


def coverage(conn, season: int, targets: list[tuple[int, str]]) -> dict:
    """How many targets ended up with a stat row, split by type."""
    wanted_h = {i for i, t in targets if t == "hitter"}
    wanted_p = {i for i, t in targets if t == "pitcher"}
    have_h = {r[0] for r in conn.execute(
        "SELECT mlb_id FROM batting_stats WHERE season = ?", (season,)).fetchall()}
    have_p = {r[0] for r in conn.execute(
        "SELECT mlb_id FROM pitching_stats WHERE season = ?", (season,)).fetchall()}
    with_qs = conn.execute(
        "SELECT COUNT(*) FROM pitching_stats WHERE season = ? "
        "AND quality_starts IS NOT NULL", (season,)).fetchone()[0]
    return {
        "hitter_targets": len(wanted_h),
        "hitters_with_stats": len(wanted_h & have_h),
        "pitcher_targets": len(wanted_p),
        "pitchers_with_stats": len(wanted_p & have_p),
        "pitching_rows_with_quality_starts": with_qs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seasons", type=int, nargs="*", default=None)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--skip-existing", action="store_true",
                        help="skip a season that already has stat rows")
    args = parser.parse_args()

    report = json.loads((HISTORY_DIR / "resolution_report.json").read_text())
    seasons = args.seasons or report["included_seasons"]

    # Phase 3 values each season's players on the PREVIOUS season too, to build
    # a decision-time baseline. Seasons with no draft sheet of their own (2015,
    # 2021) are never in `included_seasons`, so without this their stats are
    # never fetched and the baseline silently reads as zero for everyone.
    by_season: dict[int, set[tuple[int, str]]] = {}
    for season in seasons:
        targets = season_targets(season)
        by_season.setdefault(season, set()).update(targets)
        by_season.setdefault(season - 1, set()).update(targets)

    conn = get_connection()
    results: dict[int, dict] = {}

    for season in sorted(by_season):
        targets = sorted(by_season[season])
        if not targets:
            print(f"  {season}  no resolved players, skipping")
            continue

        existing = conn.execute(
            "SELECT COUNT(*) FROM batting_stats WHERE season = ?",
            (season,)).fetchone()[0]
        if existing and args.skip_existing:
            print(f"  {season}  already has {existing} batting rows, skipping")
            results[season] = coverage(conn, season, targets)
            continue

        print(f"  {season}  fetching {len(targets)} player-seasons...", flush=True)
        state = asyncio.run(refresh_actuals_for_players(
            targets, season, concurrency=args.concurrency,
            include_quality_starts=True))

        # A failed fetch and a genuine no-show both end up as an absent row,
        # and the ex-post board zero-fills absent rows. Conflating them would
        # quietly value a real season at nothing, so failures are surfaced.
        if state["errors"]:
            print(f"    WARNING {state['errors']} fetches failed "
                  f"(e.g. {state.get('failed_ids', [])[:5]}) — re-run this "
                  f"season before trusting its numbers")

        conn.close()
        conn = get_connection()
        stats = coverage(conn, season, targets)
        stats["fetch_errors"] = state["errors"]
        stats["no_stats"] = state.get("no_stats", 0)
        results[season] = stats
        print(f"    {stats['hitters_with_stats']}/{stats['hitter_targets']} hitters, "
              f"{stats['pitchers_with_stats']}/{stats['pitcher_targets']} pitchers, "
              f"{state.get('no_stats', 0)} never played, "
              f"{state['errors']} errors")

    conn.close()
    _write_json(HISTORY_DIR / "stats_coverage.json", {
        "backfilled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "by_season": {str(s): r for s, r in sorted(results.items())},
    })
    total_errors = sum(r.get("fetch_errors", 0) for r in results.values())
    print(f"\nTotal fetch errors: {total_errors}")
    return 1 if total_errors else 0


if __name__ == "__main__":
    sys.exit(main())
