"""Phase 5 prerequisite: resolve ESPN/Yahoo ranking names to mlb_ids.

Usage:
    .venv/bin/python -m backend.scripts.history_resolve_rankings

Phase 1 resolved draft and keeper names. The ranking sheets -- the league's
preseason market view, and the list it actually drafted from -- were extracted
but left as raw strings. Phase 5 cannot compare the board against the market
until they carry ids.

Emits rankings_resolution_YYYY.json per season and a combined report.

Two differences from Phase 1 worth knowing:

**A ranking sheet is a market, not a roster.** It lists players who never
appeared that season -- prospects ranked on hype, and veterans who got hurt in
March. Those *should* fail against the season roster and resolve from a
neighbouring season instead, exactly as Phase 1 handles drafted players who
missed a year. The floor is therefore advisory here rather than an
include/exclude gate: an unresolved ranking row costs one row of a market
comparison, where an unresolved draft pick would bias a whole season.

**The sheets carry a team column**, which Phase 1's sources did not. It is not
used for matching yet -- the season roster cache holds no team -- but it is
preserved so a later pass can use it to break the same-name ties that position
alone cannot (the two Will Smiths played for different clubs).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from backend.analysis.history.resolve import (
    DEFAULT_FLOOR,
    Candidate,
    resolution_report,
    resolve_season,
)
from backend.scripts.history_resolve import fetch_season_roster

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HISTORY_DIR = REPO_ROOT / "backend" / "data" / "fixtures" / "league_history"


# Resolution degrades with rank depth, so a single rate over a 2,250-row sheet
# says almost nothing. These bands separate "the part of the market the league
# actually drafts from" (top 300) from the deep tail, which is prospects and
# retirees who never appeared in MLB and *should* fail to resolve.
RANK_BANDS = [(1, 300), (301, 600), (601, 1000), (1001, 1500), (1501, 10000)]


def rank_band_coverage(rows: list[dict]) -> list[dict]:
    """Resolution rate by rank band, for sheets that run deeper than a top 300."""
    bands = []
    for low, high in RANK_BANDS:
        in_band = [r for r in rows if r["rank"] and low <= r["rank"] <= high]
        if not in_band:
            continue
        resolved = sum(1 for r in in_band if r["mlb_id"] is not None)
        bands.append({
            "from": low,
            "to": min(high, max(r["rank"] for r in in_band)),
            "rows": len(in_band),
            "resolved": resolved,
            "match_rate": round(resolved / len(in_band), 4),
        })
    return bands


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def _candidates(rows: list[dict]) -> list[Candidate]:
    return [Candidate(mlb_id=p["mlb_id"], full_name=p["full_name"],
                      primary_position=p.get("primary_position"),
                      birth_date=p.get("birth_date"))
            for p in rows]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--floor", type=float, default=DEFAULT_FLOOR)
    parser.add_argument("--seasons", type=int, nargs="*", default=None)
    args = parser.parse_args()

    # Four-digit season only: a looser glob also matches this script's own
    # rankings_resolution_YYYY.json output, which has a similar enough shape to
    # be re-processed silently on a second run.
    paths = sorted(HISTORY_DIR.glob("rankings_[0-9][0-9][0-9][0-9].json"))
    header = {
        "resolved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "floor": args.floor,
    }
    report: dict[int, dict] = {}

    for path in paths:
        payload = json.loads(path.read_text())
        season = payload["season"]
        if args.seasons and season not in args.seasons:
            continue

        roster = _candidates(fetch_season_roster(season))
        neighbours = [_candidates(fetch_season_roster(season + d)) for d in (-1, 1)]

        per_sheet, summaries = [], []
        for source in payload["sources"]:
            rows = source["rankings"]
            names = sorted({r["player_name"] for r in rows})
            hints = {}
            for row in rows:
                if row.get("position"):
                    hints.setdefault(row["player_name"], row["position"])

            resolutions = resolve_season(names, roster, hints, neighbours)
            summary = resolution_report(resolutions, args.floor)
            summaries.append((source["sheet"], summary))
            band_note = ""

            by_name = {r.name: r for r in resolutions}
            resolved_rows = [{
                    "rank": row["rank"],
                    "player_name": row["player_name"],
                    "mlb_team": row["mlb_team"],
                    "position": row["position"],
                    "status": row["status"],
                    "mlb_id": by_name[row["player_name"]].mlb_id,
                    "match_confidence": round(
                        by_name[row["player_name"]].confidence, 3),
                    "match_method": by_name[row["player_name"]].method,
                } for row in rows]

            per_sheet.append({
                "sheet": source["sheet"],
                "snapshot_date": source["snapshot_date"],
                "summary": {k: v for k, v in summary.items() if k != "unresolved"},
                "by_rank_band": rank_band_coverage(resolved_rows),
                "rankings": resolved_rows,
            })
            bands = rank_band_coverage(resolved_rows)
            top = next((b for b in bands if b["from"] == 1), None)
            band_note = (f"   top-300: {top['match_rate']:.1%}"
                         if top and len(bands) > 1 else "")
            print(f"  {season} {source['sheet']:22} "
                  f"{summary['resolved']:>4}/{summary['names']:<4} "
                  f"{summary['match_rate']:>7.1%}{band_note}")

        _write_json(HISTORY_DIR / f"rankings_resolution_{season}.json", {
            **header, "season": season, "sources": per_sheet,
        })
        report[season] = {
            "sheets": [{"sheet": sheet["sheet"],
                        "by_rank_band": sheet["by_rank_band"],
                        **{k: v for k, v in sheet["summary"].items()}}
                       for sheet in per_sheet],
            "unresolved": sorted({n for _, summary in summaries
                                  for n in summary["unresolved"]}),
        }

    total = sum(sheet["names"] for r in report.values() for sheet in r["sheets"])
    resolved = sum(sheet["resolved"] for r in report.values() for sheet in r["sheets"])
    _write_json(HISTORY_DIR / "rankings_resolution_report.json", {
        **header,
        "total_names": total,
        "total_resolved": resolved,
        "match_rate": round(resolved / total, 4) if total else None,
        "below_floor": sorted(
            f"{season}:{sheet['sheet']}"
            for season, r in report.items() for sheet in r["sheets"]
            if sheet["match_rate"] < args.floor),
        "by_season": {str(s): r for s, r in sorted(report.items())},
    })

    print(f"\n{resolved}/{total} distinct ranking names resolved "
          f"({resolved / total:.1%})" if total else "nothing to resolve")
    return 0


if __name__ == "__main__":
    sys.exit(main())
