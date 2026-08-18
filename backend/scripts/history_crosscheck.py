"""Phase 1 cross-check: the workbook against src/lib/draft-history.ts.

Usage:
    .venv/bin/python -m backend.scripts.history_crosscheck

`KEEPER_HISTORY` in src/lib/draft-history.ts is hand-curated and drives what
the app shows on the keepers page. The workbook is the league's own record.
Where they disagree one of them is wrong, and the app is the one users see, so
the disagreements are worth having written down.

Emits keeper_history_crosscheck.json: every curated entry the workbook does not
carry, every field-level disagreement, and a `doctrine_check` column saying
which side obeys the league's own keeper rule (cost drops five rounds per extra
season, floored at round 1). That last column is what makes the report
actionable rather than a list of differences.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from backend.data.name_matching import normalize_name

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HISTORY_DIR = REPO_ROOT / "backend" / "data" / "fixtures" / "league_history"
DRAFT_HISTORY_TS = REPO_ROOT / "src" / "lib" / "draft-history.ts"

_ENTRY_RE = re.compile(
    r"\{\s*year:\s*(\d+),\s*manager:\s*'([^']+)',\s*"
    r"roundCost:\s*(\d+),\s*seasonsKept:\s*(\d+)")
_PLAYER_RE = re.compile(r"playerName:\s*'([^']+)',\s*entries:\s*\[(.*?)\]", re.S)


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def parse_curated(source: str) -> list[dict]:
    """Pull KEEPER_HISTORY out of the TypeScript file."""
    start = source.index("KEEPER_HISTORY")
    entries = []
    for player in _PLAYER_RE.finditer(source[start:]):
        name = player.group(1)
        for entry in _ENTRY_RE.finditer(player.group(2)):
            entries.append({
                "player_name": name,
                "season": int(entry.group(1)),
                "manager": entry.group(2),
                "round_cost": int(entry.group(3)),
                "seasons_kept": int(entry.group(4)),
            })
    return entries


def load_workbook_keepers() -> dict[tuple[str, int], dict]:
    keepers: dict[tuple[str, int], dict] = {}
    for path in sorted(HISTORY_DIR.glob("keepers_*.json")):
        payload = json.loads(path.read_text())
        for keeper in payload["keepers"]:
            key = (normalize_name(keeper["player_name"]), payload["season"])
            keepers[key] = dict(keeper, season=payload["season"])
    return keepers


def obeys_doctrine(round_cost: int, seasons_kept: int,
                   previous: dict | None) -> bool | None:
    """Does this round cost follow from the previous season's under the rule?

    The league's doctrine: each season beyond the first costs five rounds
    earlier than the season before, floored at round 1. Checked against the
    *previous season's recorded cost* rather than the original draft round,
    which is how the sheet itself computes it.
    """
    if previous is None or seasons_kept <= 1:
        return None
    expected = max(1, previous["round_cost"] - 5)
    return round_cost == expected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    curated = parse_curated(DRAFT_HISTORY_TS.read_text())
    workbook = load_workbook_keepers()

    # Index curated entries per player so the doctrine check can look back.
    curated_by_player: dict[str, dict[int, dict]] = {}
    for entry in curated:
        curated_by_player.setdefault(
            normalize_name(entry["player_name"]), {})[entry["season"]] = entry

    absent, disagreements = [], []
    for entry in curated:
        key = (normalize_name(entry["player_name"]), entry["season"])
        sheet = workbook.get(key)
        if sheet is None:
            absent.append({
                "player_name": entry["player_name"],
                "season": entry["season"],
                "curated": {k: entry[k] for k in
                            ("manager", "round_cost", "seasons_kept")},
                "note": "curated entry has no matching row in the workbook's "
                        "keeper sheet for that season",
            })
            continue

        fields = {}
        if sheet["round_cost"] != entry["round_cost"]:
            fields["round_cost"] = {"workbook": sheet["round_cost"],
                                    "curated": entry["round_cost"]}
        if (sheet["seasons_kept"] is not None
                and sheet["seasons_kept"] != entry["seasons_kept"]):
            fields["seasons_kept"] = {"workbook": sheet["seasons_kept"],
                                      "curated": entry["seasons_kept"]}
        if normalize_name(sheet["manager"]) != normalize_name(entry["manager"]):
            fields["manager"] = {"workbook": sheet["manager"],
                                 "curated": entry["manager"]}
        if not fields:
            continue

        player_key = normalize_name(entry["player_name"])
        prior_sheet = workbook.get((player_key, entry["season"] - 1))
        prior_curated = curated_by_player.get(player_key, {}).get(
            entry["season"] - 1)
        disagreements.append({
            "player_name": entry["player_name"],
            "season": entry["season"],
            "fields": fields,
            "doctrine_check": {
                "workbook": obeys_doctrine(sheet["round_cost"],
                                           sheet["seasons_kept"] or 1,
                                           prior_sheet),
                "curated": obeys_doctrine(entry["round_cost"],
                                          entry["seasons_kept"],
                                          prior_curated),
            },
        })

    # Which side wins on the doctrine, where the doctrine can adjudicate.
    verdicts = {"workbook": 0, "curated": 0, "both": 0, "neither": 0}
    for row in disagreements:
        check = row["doctrine_check"]
        if check["workbook"] is None and check["curated"] is None:
            continue
        if check["workbook"] and not check["curated"]:
            verdicts["workbook"] += 1
        elif check["curated"] and not check["workbook"]:
            verdicts["curated"] += 1
        elif check["workbook"] and check["curated"]:
            verdicts["both"] += 1
        else:
            verdicts["neither"] += 1

    payload = {
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "curated_entries": len(curated),
        "workbook_keeper_rows": len(workbook),
        "absent_from_workbook": absent,
        "disagreements": disagreements,
        "doctrine_verdicts": verdicts,
    }
    out = args.out or (HISTORY_DIR / "keeper_history_crosscheck.json")
    _write_json(out, payload)

    print(f"\nKEEPER_HISTORY cross-check")
    print(f"  curated entries:            {len(curated)}")
    print(f"  absent from the workbook:   {len(absent)}")
    print(f"  field disagreements:        {len(disagreements)}")
    print(f"\n  where the keeper doctrine can adjudicate:")
    for side, count in verdicts.items():
        print(f"    {side:>9} obeys it: {count}")

    by_season: dict[int, int] = {}
    for row in absent:
        by_season[row["season"]] = by_season.get(row["season"], 0) + 1
    if by_season:
        print("\n  absent entries by season: " + ", ".join(
            f"{s}: {n}" for s, n in sorted(by_season.items())))
    print(f"\nWritten to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
