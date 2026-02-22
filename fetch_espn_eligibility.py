"""Fetch ESPN fantasy position eligibility and regenerate CSV.

Pulls current position eligibility from ESPN's public fantasy API,
cross-references with our player database, and writes the CSV that
import_position_eligibility() consumes.

Usage:
    python3 fetch_espn_eligibility.py              # write CSV only
    python3 fetch_espn_eligibility.py --import      # write CSV and import to DB
    python3 fetch_espn_eligibility.py --diff        # show changes vs current CSV
"""

from __future__ import annotations

import argparse
import csv
import json
import unicodedata
import urllib.request
from pathlib import Path

from backend.database import get_connection

OUTPUT_PATH = Path("backend/projection_data/position_eligibility_2026.csv")

# ESPN eligibleSlots ID -> position abbreviation
# Only real positions, not meta-slots (MI, CI, UTIL, P, BE, IL)
SLOT_TO_POS: dict[int, str] = {
    0: "C", 1: "1B", 2: "2B", 3: "3B", 4: "SS",
    5: "OF", 8: "OF", 9: "OF", 10: "OF",
    11: "DH", 14: "SP", 15: "RP",
}

# Position display order (primary positions first, DH last)
POS_ORDER = ["C", "1B", "2B", "3B", "SS", "OF", "SP", "RP", "DH"]

# ESPN proTeamId -> standard abbreviation
TEAM_MAP: dict[int, str] = {
    0: "FA", 1: "BAL", 2: "BOS", 3: "LAA", 4: "CWS", 5: "CLE",
    6: "DET", 7: "KC", 8: "MIL", 9: "MIN", 10: "NYY", 11: "ATH",
    12: "SEA", 13: "TEX", 14: "TOR", 15: "ATL", 16: "CHC", 17: "CIN",
    18: "HOU", 19: "LAD", 20: "WSH", 21: "NYM", 22: "PHI", 23: "PIT",
    24: "STL", 25: "SD", 26: "SF", 27: "COL", 28: "MIA", 29: "ARI", 30: "TB",
}

ESPN_API_URL = (
    "https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb/seasons/2026"
    "/players?scoringPeriodId=0&view=players_wl"
)


def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    ).lower()


def fetch_espn_players() -> list[dict]:
    """Fetch all active players from ESPN fantasy API, paginating via x-fantasy-filter."""
    all_players: list[dict] = []
    batch_size = 250
    offset = 0

    while True:
        filter_header = json.dumps({
            "filterActive": {"value": True},
            "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
            "limit": batch_size,
            "offset": offset,
        })

        req = urllib.request.Request(ESPN_API_URL)
        req.add_header("x-fantasy-filter", filter_header)
        req.add_header("Accept", "application/json")

        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())

        if not data:
            break

        all_players.extend(data)

        # Stop when ownership drops to 0 (remaining players are irrelevant)
        last_ownership = data[-1].get("ownership", {}).get("percentOwned", 0)
        if last_ownership == 0 or len(data) < batch_size:
            break

        offset += batch_size
        print(f"  fetched {len(all_players)} players (last ownership: {last_ownership:.1f}%)...")

    return all_players


def positions_from_slots(eligible_slots: list[int]) -> list[str]:
    """Convert ESPN eligibleSlots IDs to ordered position abbreviations."""
    seen: set[str] = set()
    for slot in eligible_slots:
        pos = SLOT_TO_POS.get(slot)
        if pos:
            seen.add(pos)
    # Sort by POS_ORDER
    return [p for p in POS_ORDER if p in seen]


def load_current_csv() -> dict[str, str]:
    """Load existing CSV into {player_name: eligible_positions} map."""
    result: dict[str, str] = {}
    if not OUTPUT_PATH.exists():
        return result
    with open(OUTPUT_PATH) as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("player_name", "").strip()
            positions = row.get("eligible_positions", "").strip()
            if name and positions:
                result[name] = positions
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch ESPN position eligibility")
    parser.add_argument("--import", dest="do_import", action="store_true",
                        help="Also import to database after writing CSV")
    parser.add_argument("--diff", action="store_true",
                        help="Show changes vs current CSV")
    args = parser.parse_args()

    # 1. Fetch from ESPN
    print("Fetching players from ESPN fantasy API...")
    espn_players = fetch_espn_players()
    print(f"  total: {len(espn_players)} players")

    # 2. Build DB name lookup
    conn = get_connection()
    db_rows = conn.execute("SELECT mlb_id, full_name FROM players WHERE is_active = 1").fetchall()

    name_to_row: dict[str, tuple[int, str]] = {}
    stripped_to_row: dict[str, tuple[int, str]] = {}
    for r in db_rows:
        name_to_row[r["full_name"].lower()] = (r["mlb_id"], r["full_name"])
        stripped_to_row[_strip_accents(r["full_name"])] = (r["mlb_id"], r["full_name"])

    # 3. Match ESPN players to our DB and extract positions
    rows: list[tuple[str, str, str]] = []  # (name, team, positions)
    matched_ids: set[int] = set()
    unmatched: list[tuple[str, float]] = []

    for ep in espn_players:
        espn_name = ep["fullName"]
        team_id = ep["proTeamId"]
        team = TEAM_MAP.get(team_id, "???")

        if team == "FA":
            continue

        # Match by name
        match = name_to_row.get(espn_name.lower())
        if not match:
            match = stripped_to_row.get(_strip_accents(espn_name))

        if not match:
            ownership = ep.get("ownership", {}).get("percentOwned", 0)
            if ownership > 1.0:
                unmatched.append((espn_name, ownership))
            continue

        mlb_id, db_name = match
        if mlb_id in matched_ids:
            continue  # skip duplicates
        matched_ids.add(mlb_id)

        positions = positions_from_slots(ep["eligibleSlots"])
        if not positions:
            continue

        rows.append((db_name, team, "/".join(positions)))

    # Sort by team then name for readability
    rows.sort(key=lambda r: (r[1], r[0]))

    # 4. Load old CSV before overwriting (for diff)
    old_csv = load_current_csv() if args.diff else {}

    # 5. Write CSV
    with open(OUTPUT_PATH, "w", newline="") as f:
        f.write("player_name,team,eligible_positions\n")
        for name, team, positions in rows:
            # Quote names containing commas or special chars
            if "," in name:
                name = f'"{name}"'
            f.write(f"{name},{team},{positions}\n")

    print(f"\nWrote {len(rows)} players to {OUTPUT_PATH}")

    # 6. Show unmatched
    if unmatched:
        unmatched.sort(key=lambda x: -x[1])
        print(f"\nUnmatched players with >1% ownership ({len(unmatched)}):")
        for name, own in unmatched[:25]:
            print(f"  {name:30s} ({own:.1f}%)")

    # 7. Diff mode
    if args.diff:
        old = old_csv
        print(f"\nChanges vs previous CSV:")
        changes = 0
        for name, team, positions in rows:
            old_pos = old.get(name)
            if old_pos and old_pos != positions:
                print(f"  CHANGED: {name:30s} {old_pos:15s} -> {positions}")
                changes += 1
        new_names = {r[0] for r in rows}
        for old_name in old:
            if old_name not in new_names:
                print(f"  REMOVED: {old_name:30s} {old[old_name]}")
                changes += 1
        for name, team, positions in rows:
            if name not in old:
                print(f"  ADDED:   {name:30s} {positions}")
                changes += 1
        if changes == 0:
            print("  (no changes)")

    # 8. Optional DB import
    if args.do_import:
        from backend.data.projections import import_position_eligibility
        count = import_position_eligibility(str(OUTPUT_PATH))
        print(f"\nImported eligibility for {count} players to database")

    conn.close()


if __name__ == "__main__":
    main()
