"""Phase 1: resolve league-history player names to MLB ids.

Usage:
    .venv/bin/python -m backend.scripts.history_resolve
    .venv/bin/python -m backend.scripts.history_resolve --floor 0.95

Reads the Phase 0 fixtures, resolves every draft and keeper name against the
MLB roster *for that season*, caches newly discovered people into the `players`
table so the network work happens once, and writes:

  resolution_YYYY.json  — every name with its mlb_id, method and confidence
  resolution_report.json — per-season match rate and the include/exclude call

Seasons below the floor are marked excluded. They are not deleted: the report
records why, and the downstream phases read the flag. A season resolved at 70%
is not 70% of a season, it is a season missing its retired players, and the
players who retired are disproportionately the ones whose keeper decisions went
badly.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

from backend.analysis.history.resolve import (
    DEFAULT_FLOOR,
    Candidate,
    resolution_report,
    resolve_season,
)
from backend.database import get_connection

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HISTORY_DIR = REPO_ROOT / "backend" / "data" / "fixtures" / "league_history"
ROSTER_CACHE = HISTORY_DIR / "_rosters"
BASE_URL = "https://statsapi.mlb.com/api/v1"

PITCHER_POSITIONS = {"P", "SP", "RP"}


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def fetch_season_roster(season: int, refresh: bool = False) -> list[dict]:
    """Every player who appeared on an MLB roster in `season`.

    Cached to disk because it is ~1,300 rows per season across seventeen
    seasons and never changes for a completed season.
    """
    cache = ROSTER_CACHE / f"players_{season}.json"
    if cache.exists() and not refresh:
        return json.loads(cache.read_text())

    resp = httpx.get(f"{BASE_URL}/sports/1/players",
                     params={"season": season}, timeout=90)
    resp.raise_for_status()
    people = resp.json().get("people", [])
    slim = [{
        "mlb_id": p.get("id"),
        "full_name": p.get("fullName", ""),
        "first_name": p.get("firstName", ""),
        "last_name": p.get("lastName", ""),
        "primary_position": p.get("primaryPosition", {}).get("abbreviation", ""),
        "birth_date": p.get("birthDate", ""),
        "active": bool(p.get("active")),
    } for p in people if p.get("id") and p.get("fullName")]
    _write_json(cache, slim)
    return slim


def season_names(season: int) -> tuple[list[str], dict[str, list[str]], dict[str, str]]:
    """Distinct player names for a season, where each came from, and the
    position the workbook recorded — used only to break same-name ties."""
    sources: dict[str, list[str]] = {}
    positions: dict[str, str] = {}

    draft_path = HISTORY_DIR / f"drafts_{season}.json"
    if draft_path.exists():
        for pick in json.loads(draft_path.read_text())["picks"]:
            sources.setdefault(pick["player_name"], []).append("draft")
            if pick.get("position"):
                positions.setdefault(pick["player_name"], pick["position"])

    keeper_path = HISTORY_DIR / f"keepers_{season}.json"
    if keeper_path.exists():
        payload = json.loads(keeper_path.read_text())
        for keeper in payload["keepers"]:
            sources.setdefault(keeper["player_name"], []).append("keeper")
        for pick in payload.get("pick_slots", []):
            sources.setdefault(pick["player_name"], []).append("keeper_slot")
            if pick.get("position"):
                positions.setdefault(pick["player_name"], pick["position"])

    return sorted(sources), sources, positions


def cache_players(conn, roster: list[dict], mlb_ids: set[int]) -> int:
    """Insert any resolved player the `players` table does not already hold.

    Historical players are stored with is_active = 0 so they never leak into
    the live draft board, which filters on that column.
    """
    if not mlb_ids:
        return 0
    existing = {
        r[0] for r in conn.execute(
            "SELECT mlb_id FROM players WHERE mlb_id IN "
            f"({','.join('?' * len(mlb_ids))})", tuple(mlb_ids)).fetchall()
    }
    by_id = {p["mlb_id"]: p for p in roster}
    added = 0
    for mlb_id in sorted(mlb_ids - existing):
        person = by_id.get(mlb_id)
        if person is None:
            continue
        position = person.get("primary_position") or ""
        conn.execute(
            """INSERT OR IGNORE INTO players
               (mlb_id, full_name, first_name, last_name, primary_position,
                player_type, is_active, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 0, ?)""",
            (mlb_id, person["full_name"], person.get("first_name", ""),
             person.get("last_name", ""), position,
             "pitcher" if position in PITCHER_POSITIONS else "hitter",
             datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )
        added += 1
    conn.commit()
    return added


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--floor", type=float, default=DEFAULT_FLOOR,
                        help=f"minimum match rate to include a season "
                             f"(default {DEFAULT_FLOOR})")
    parser.add_argument("--refresh-rosters", action="store_true")
    parser.add_argument("--seasons", type=int, nargs="*", default=None)
    args = parser.parse_args()

    manifest = json.loads((HISTORY_DIR / "manifest.json").read_text())
    seasons = args.seasons or sorted(
        set(manifest["draft_seasons"]) | set(manifest["keeper_seasons"]))

    conn = get_connection()
    header = {
        "resolved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "floor": args.floor,
        "source": f"{BASE_URL}/sports/1/players",
    }
    report: dict[int, dict] = {}
    total_added = 0

    for season in seasons:
        names, sources, positions = season_names(season)
        if not names:
            continue
        roster_rows = fetch_season_roster(season, args.refresh_rosters)

        def to_candidates(rows: list[dict]) -> list[Candidate]:
            return [Candidate(mlb_id=p["mlb_id"], full_name=p["full_name"],
                              primary_position=p.get("primary_position"),
                              birth_date=p.get("birth_date"))
                    for p in rows]

        roster = to_candidates(roster_rows)
        neighbour_rows = [fetch_season_roster(season + delta, args.refresh_rosters)
                          for delta in (-1, 1)]
        resolutions = resolve_season(names, roster, positions,
                                     [to_candidates(r) for r in neighbour_rows])
        roster_rows = roster_rows + [p for rows in neighbour_rows for p in rows]
        summary = resolution_report(resolutions, args.floor)
        summary["roster_size"] = len(roster)
        report[season] = summary

        total_added += cache_players(
            conn, roster_rows,
            {r.mlb_id for r in resolutions if r.mlb_id is not None})

        _write_json(HISTORY_DIR / f"resolution_{season}.json", {
            **header,
            "season": season,
            "summary": {k: v for k, v in summary.items() if k != "unresolved"},
            "resolutions": [
                {**r.as_dict(), "sources": sorted(set(sources[r.name]))}
                for r in resolutions
            ],
        })
        print(f"  {season}  {summary['resolved']:>4}/{summary['names']:<4} "
              f"{summary['match_rate']:>7.1%}  "
              f"{'include' if summary['included'] else 'EXCLUDE'}")

    conn.close()

    included = sorted(s for s, r in report.items() if r["included"])
    excluded = sorted(s for s, r in report.items() if not r["included"])
    _write_json(HISTORY_DIR / "resolution_report.json", {
        **header,
        "included_seasons": included,
        "excluded_seasons": excluded,
        "by_season": {str(s): r for s, r in sorted(report.items())},
    })

    print(f"\nCached {total_added} previously unknown players into `players`.")
    print(f"Included: {included}")
    print(f"Excluded: {excluded}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
