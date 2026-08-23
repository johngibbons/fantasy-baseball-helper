"""Regenerate KEEPER_HISTORY in src/lib/draft-history.ts from the workbook.

Usage:
    .venv/bin/python -m backend.scripts.generate_keeper_history          # write
    .venv/bin/python -m backend.scripts.generate_keeper_history --check  # diff only

The hand-curated array had drifted badly from the league's own record: 29 field
disagreements, seven seasons attributed to a manager who had not joined the
league yet, and 22 invented 2026 rows that were the 2025 rows copied forward.
Where the league's keeper doctrine could adjudicate, the workbook obeyed it 12
times and the curated file zero (see history_crosscheck.py). It was also
missing about half the multi-season keepers outright.

Generating it removes the drift as a category rather than fixing this instance.

Two things this does that hand-maintenance could not:

**Groups by mlb_id, not by name.** The workbook spells the same player several
ways across seventeen seasons -- "Vlad Guerrero Jr", "Vlad Guerrero JR",
"Vladimir Guerrero Jr." -- so name-grouping silently splits one keeper run into
three. Phase 1 already resolved every name to an id; this reuses it.

**Canonicalizes manager names.** "Dave"/"David Rotatori", "Chris"/"Christopher
Herbst", the 2023 sheet's "Eric Mercardo" typo, and "Tim Riker (Brian Martin)"
from the handover season all collapse to one spelling, and every merge is
printed so it can be reviewed rather than trusted.

Only players kept in two or more seasons are emitted, because that is what the
Keeper History panel displays (`entries.length >= 2`).
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from backend.analysis.history.resolve import first_names_compatible
from backend.data.name_matching import normalize_name

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HISTORY_DIR = REPO_ROOT / "backend" / "data" / "fixtures" / "league_history"
TARGET = REPO_ROOT / "src" / "lib" / "draft-history.ts"

# Manager spellings this close are treated as the same person, resolved to
# whichever spelling the workbook uses most often. Names that share a surname
# additionally merge on a compatible first name, which is what catches
# Chris/Christopher and Dave/David -- pairs that sit just below any ratio
# loose enough to be safe between genuinely different people.
MANAGER_SIMILARITY = 0.82

_PAREN_RE = re.compile(r"\s*\([^)]*\)\s*$")
_ARRAY_RE = re.compile(
    r"(export const KEEPER_HISTORY: KeeperHistory\[\] = \[\n).*?(\n\]\n)",
    re.S)


def canonical_managers(names: Counter) -> tuple[dict[str, str], list[tuple[str, str]]]:
    """Map every manager spelling to one canonical form.

    The most frequent spelling wins, which is what makes a single-season typo
    lose to the fifteen seasons that spell it correctly.
    """
    stripped = Counter()
    for name, count in names.items():
        stripped[_PAREN_RE.sub("", name).strip()] += count

    def same_person(a: str, b: str) -> bool:
        first_a, _, last_a = normalize_name(a).partition(" ")
        first_b, _, last_b = normalize_name(b).partition(" ")
        if last_a and last_a == last_b:
            return first_names_compatible(first_a, first_b)
        return difflib.SequenceMatcher(
            None, normalize_name(a), normalize_name(b)
        ).ratio() >= MANAGER_SIMILARITY

    ordered = [name for name, _ in stripped.most_common()]
    mapping: dict[str, str] = {}
    canon: list[str] = []
    for name in ordered:
        match = next((c for c in canon if same_person(name, c)), None)
        if match is None:
            canon.append(name)
            mapping[name] = name
        else:
            mapping[name] = match

    full = {}
    merges = []
    for name in names:
        base = _PAREN_RE.sub("", name).strip()
        resolved = mapping.get(base, base)
        full[name] = resolved
        if resolved != name:
            merges.append((name, resolved))
    return full, sorted(set(merges))


def collect() -> tuple[list[dict], dict]:
    """Keeper runs per player, newest season last."""
    by_id: dict[int, list[dict]] = defaultdict(list)
    display: dict[int, str] = {}
    manager_counts: Counter = Counter()

    for path in sorted(HISTORY_DIR.glob("keepers_*.json")):
        payload = json.loads(path.read_text())
        season = payload["season"]
        resolution_path = HISTORY_DIR / f"resolution_{season}.json"
        if not resolution_path.exists():
            continue
        resolved = {r["name"]: r
                    for r in json.loads(resolution_path.read_text())["resolutions"]}

        for keeper in payload["keepers"]:
            entry = resolved.get(keeper["player_name"])
            if not entry or entry["mlb_id"] is None or keeper["round_cost"] is None:
                continue
            mlb_id = entry["mlb_id"]
            manager_counts[keeper["manager"]] += 1
            # MLB's own spelling, not the workbook's; later seasons win so the
            # name shown is the one the player currently goes by.
            display[mlb_id] = entry["matched_name"] or keeper["player_name"]
            by_id[mlb_id].append({
                "season": season,
                "manager": keeper["manager"],
                "round_cost": keeper["round_cost"],
                "seasons_kept": keeper["seasons_kept"],
            })

    managers, merges = canonical_managers(manager_counts)

    players = []
    for mlb_id, runs in by_id.items():
        if len(runs) < 2:
            continue
        runs.sort(key=lambda r: r["season"])
        entries = []
        for run in runs:
            # 2015 and 2016 predate the Seasons Kept column, and a run that
            # began before 2015 cannot be reconstructed -- deriving it from
            # position in the chain would invent a number for a field nothing
            # reads. Emitted as null instead.
            entries.append({
                "year": run["season"],
                "manager": managers[run["manager"]],
                "roundCost": run["round_cost"],
                "seasonsKept": run["seasons_kept"],
            })
        players.append({
            "mlb_id": mlb_id,
            "playerName": display[mlb_id],
            "entries": entries,
        })

    players.sort(key=lambda p: (-len(p["entries"]), p["playerName"]))
    return players, {"manager_merges": merges,
                     "managers": sorted(set(managers.values()))}


def render(players: list[dict]) -> str:
    """The TypeScript array body, matching the file's existing style."""
    lines: list[str] = []
    lines.append("  // Generated by backend/scripts/generate_keeper_history.py")
    lines.append("  // from backend/data/fixtures/league_history/keepers_*.json.")
    lines.append("  // Do not edit by hand -- regenerate instead. Players kept in")
    lines.append("  // two or more seasons only, which is what the panel displays.")

    current = None
    for player in players:
        length = len(player["entries"])
        if length != current:
            current = length
            lines.append("")
            lines.append(f"  // ── {length}-season keepers ──")
        lines.append("  {")
        name = player["playerName"].replace("\\", "\\\\").replace("'", "\\'")
        lines.append(f"    playerName: '{name}',")
        lines.append("    entries: [")
        for entry in player["entries"]:
            manager = entry["manager"].replace("\\", "\\\\").replace("'", "\\'")
            lines.append(
                f"      {{ year: {entry['year']}, manager: '{manager}', "
                f"roundCost: {entry['roundCost']}, "
                f"seasonsKept: "
                f"{'null' if entry['seasonsKept'] is None else entry['seasonsKept']}"
                f" }},")
        lines.append("    ],")
        lines.append("  },")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="report what would change without writing")
    args = parser.parse_args()

    players, meta = collect()
    if not players:
        raise SystemExit("no multi-season keepers found — run Phases 0 and 1 first")

    source = TARGET.read_text()
    match = _ARRAY_RE.search(source)
    if not match:
        raise SystemExit(f"could not locate the KEEPER_HISTORY array in {TARGET}")

    previous = match.group(0)
    updated = _ARRAY_RE.sub(
        lambda m: m.group(1) + render(players) + m.group(2), source, count=1)

    old_players = set(re.findall(r"playerName: '([^']+)'", previous))
    new_players = {p["playerName"] for p in players}

    print(f"\nKEEPER_HISTORY: {len(players)} multi-season keepers, "
          f"{sum(len(p['entries']) for p in players)} entries")
    print(f"  was {len(old_players)} players -> now {len(new_players)}")
    added = sorted(new_players - old_players)
    dropped = sorted(old_players - new_players)
    print(f"  added   ({len(added)}): {', '.join(added[:8])}"
          f"{' ...' if len(added) > 8 else ''}")
    print(f"  dropped ({len(dropped)}): {', '.join(dropped[:8])}"
          f"{' ...' if len(dropped) > 8 else ''}")

    if meta["manager_merges"]:
        print("\n  manager spellings merged:")
        for was, now in meta["manager_merges"]:
            print(f"    {was!r} -> {now!r}")
    print(f"  managers: {', '.join(meta['managers'])}")

    if args.check:
        print("\n--check: nothing written")
        return 1 if updated != source else 0

    TARGET.write_text(updated)
    print(f"\nWrote {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
