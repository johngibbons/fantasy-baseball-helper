#!/usr/bin/env python3
"""
Compute the complete 2026 fantasy baseball draft order for a 10-team snake draft
with keeper forfeitures, traded picks, and the 25-player roster cap.

Rules:
- Every manager ends up with exactly 25 players (keepers + draft picks = 25)
- A manager can only keep at rounds where they have a surviving pick (after 25-cap)
- If a keeper's declared round is beyond the cap, it slides to the latest available slot
- Managers short on picks get supplemental round picks after round 25
"""

import csv
import re
from collections import defaultdict

ROSTER_SIZE = 25
NUM_ROUNDS = 25

MANAGERS = {
    1: "Jason McComb",
    2: "Eric Mercado",
    3: "Chris Herbst",
    4: "John Gibbons",
    5: "Tim Riker",
    6: "Bryan Lewis",
    7: "Harris Cook",
    8: "Matt Wayne",
    9: "Jess Barron",
    10: "David Rotatori",
}

NAME_TO_POS = {v: k for k, v in MANAGERS.items()}

PICK_TRADES = [
    ("Eric Mercado",   "Chris Herbst", 4),
    ("David Rotatori", "Chris Herbst", 6),
    ("Harris Cook",    "Chris Herbst", 5),
    ("Matt Wayne",     "Chris Herbst", 8),
    ("Bryan Lewis",    "Chris Herbst", 11),
    ("Matt Wayne",     "Chris Herbst", 16),
    ("Harris Cook",    "Chris Herbst", 10),
    ("Jason McComb",   "Chris Herbst", 14),
    ("Chris Herbst",   "Jason McComb", 15),
    ("Chris Herbst",   "Jason McComb", 16),
]

# Keepers: (manager, declared_round, player, year_label)
KEEPERS = [
    ("Chris Herbst",    20, "Jackson Merrill", "2nd yr"),
    ("Chris Herbst",    23, "Eury Perez",      "1st yr"),
    ("Chris Herbst",    24, "Drake Baldwin",    "1st yr"),
    ("Chris Herbst",    25, "Roman Anthony",    "1st yr"),
    ("Jess Barron",      1, "Shohei Ohtani",   "2nd yr"),
    ("Jess Barron",      9, "Ketel Marte",     "3rd yr"),
    ("Jess Barron",     24, "Cade Smith",       "1st yr"),
    ("Jess Barron",     25, "Geraldo Perdomo",  "1st yr"),
    ("David Rotatori",  12, "Hunter Brown",     "2nd yr"),
    ("David Rotatori",  20, "Mason Miller",     "2nd yr"),
    ("David Rotatori",  24, "Trevor Rogers",    "1st yr"),
    ("David Rotatori",  25, "Kyle Bradish",     "1st yr"),
]


def get_round_order(round_num):
    if round_num % 2 == 1:
        return list(range(1, 11))
    else:
        return list(range(10, 0, -1))


def compute_all_pick_slots():
    """
    Build every manager's pick slots in chronological draft order.
    Returns dict: manager -> [(round, snake_pos, trade_note)]
    """
    lost_picks = {}
    for from_mgr, to_mgr, rnd in PICK_TRADES:
        lost_picks[(from_mgr, rnd)] = to_mgr

    manager_slots = defaultdict(list)

    for rnd in range(1, NUM_ROUNDS + 1):
        for pos in get_round_order(rnd):
            mgr = MANAGERS[pos]

            if (mgr, rnd) in lost_picks:
                receiver = lost_picks[(mgr, rnd)]
                manager_slots[receiver].append((rnd, pos, f"(traded from {mgr})"))
            else:
                manager_slots[mgr].append((rnd, pos, ""))

    return manager_slots


def assign_keepers_with_cap(manager_slots):
    """
    Apply the 25-player cap and assign keepers to valid rounds.

    For each manager:
    1. List all pick slots chronologically
    2. If total > 25, only the first 25 survive
    3. Keepers must be assigned to surviving slots
    4. If a keeper's declared round is beyond the cap, it slides to the
       latest available surviving slot

    Returns:
        final_slots: dict manager -> [(round, snake_pos, slot_type, notes)]
            where slot_type is 'draft', 'keeper', or 'forfeited'
        supplemental_needs: dict manager -> int (extra picks needed)
        keeper_adjustments: list of (manager, player, original_round, actual_round)
    """
    # Group keepers by manager
    mgr_keepers = defaultdict(list)
    for mgr, rnd, player, yr in KEEPERS:
        mgr_keepers[mgr].append((rnd, player, yr))

    # Sort each manager's keepers by declared round (ascending)
    for mgr in mgr_keepers:
        mgr_keepers[mgr].sort(key=lambda x: x[0])

    final_slots = {}
    supplemental_needs = {}
    keeper_adjustments = []

    for mgr in MANAGERS.values():
        slots = manager_slots[mgr]  # already in chronological order
        keepers = mgr_keepers.get(mgr, [])
        num_keepers = len(keepers)
        total = len(slots)

        # Determine which slots survive the 25-cap
        surviving = slots[:ROSTER_SIZE]
        forfeited = slots[ROSTER_SIZE:]

        # Build set of rounds that survive
        surviving_rounds = set()
        for rnd, pos, note in surviving:
            surviving_rounds.add(rnd)

        # Check each keeper: is its declared round in the surviving set?
        # If not, we need to reassign it.
        valid_keepers = []   # (round, player, yr, original_round) — keepers at valid rounds
        invalid_keepers = []  # (round, player, yr) — keepers that need reassignment

        for rnd, player, yr in keepers:
            if rnd in surviving_rounds:
                valid_keepers.append((rnd, player, yr, rnd))
            else:
                invalid_keepers.append((rnd, player, yr))

        # For invalid keepers, assign to latest surviving slots not already
        # used by valid keepers, working backward from the last surviving slot.
        used_keeper_rounds = set(k[0] for k in valid_keepers)

        # Available rounds for reassignment: surviving rounds not used by valid keepers
        # We need to find specific slots (not just rounds) since a manager may have
        # multiple slots in the same round. Work backward through surviving slots.
        available_for_reassign = []
        for rnd, pos, note in reversed(surviving):
            if rnd not in used_keeper_rounds:
                available_for_reassign.append((rnd, pos, note))

        # Assign invalid keepers to the latest available slots
        # Sort invalid keepers by declared round descending (latest keeper gets latest slot)
        invalid_keepers.sort(key=lambda x: x[0], reverse=True)

        reassigned = []
        used_slots = set()
        for orig_rnd, player, yr in invalid_keepers:
            for i, (arnd, apos, anote) in enumerate(available_for_reassign):
                slot_key = (arnd, apos)
                if slot_key not in used_slots:
                    used_slots.add(slot_key)
                    reassigned.append((arnd, player, yr, orig_rnd))
                    used_keeper_rounds.add(arnd)
                    keeper_adjustments.append((mgr, player, orig_rnd, arnd))
                    break

        all_keepers = valid_keepers + reassigned
        keeper_round_set = set()
        keeper_slot_keys = set()
        for k in all_keepers:
            keeper_round_set.add(k[0])

        # Build a lookup: round -> keeper info
        keeper_by_round = {}
        for rnd, player, yr, orig_rnd in all_keepers:
            keeper_by_round[rnd] = (player, yr, orig_rnd)

        # Now build final slot list for this manager
        result = []
        keeper_assigned = set()

        for rnd, pos, note in slots[:ROSTER_SIZE]:
            if rnd in keeper_by_round and rnd not in keeper_assigned:
                player, yr, orig_rnd = keeper_by_round[rnd]
                keeper_assigned.add(rnd)
                adj_note = f"KEEPER: {player} ({yr})"
                if orig_rnd != rnd:
                    adj_note += f" [moved from Rd {orig_rnd}]"
                result.append((rnd, pos, "keeper", adj_note))
            else:
                result.append((rnd, pos, "draft", note))

        final_slots[mgr] = result

        # Supplemental needs
        current_total = len(result)
        if current_total < ROSTER_SIZE:
            supplemental_needs[mgr] = ROSTER_SIZE - current_total
        else:
            supplemental_needs[mgr] = 0

    return final_slots, supplemental_needs, keeper_adjustments


def build_draft_order(final_slots, supplemental_needs):
    """Build the ordered draft board from final slot assignments + supplemental rounds."""

    # Build a lookup: for each (round, snake_pos), what happens?
    # Possible: draft pick by manager, keeper by manager, or empty (forfeited/not assigned)
    round_events = defaultdict(list)  # round -> [(snake_pos, manager, slot_type, notes)]

    for mgr, slots in final_slots.items():
        for rnd, pos, stype, notes in slots:
            round_events[rnd].append((pos, mgr, stype, notes))

    # Sort each round's events by snake position order
    for rnd in round_events:
        base_order = get_round_order(rnd)
        pos_order = {p: i for i, p in enumerate(base_order)}
        round_events[rnd].sort(key=lambda x: pos_order.get(x[0], 99))

    results = []
    overall_pick = 0

    for rnd in range(1, NUM_ROUNDS + 1):
        events = round_events.get(rnd, [])
        pick_in_round = 0

        for pos, mgr, stype, notes in events:
            pick_in_round += 1
            if stype == "keeper":
                results.append({
                    "overall_pick": "KEEPER",
                    "round": rnd,
                    "pick_in_round": pick_in_round,
                    "manager": mgr,
                    "notes": notes,
                })
            else:
                overall_pick += 1
                results.append({
                    "overall_pick": overall_pick,
                    "round": rnd,
                    "pick_in_round": pick_in_round,
                    "manager": mgr,
                    "notes": notes,
                })

    # Supplemental rounds
    total_supp = sum(supplemental_needs.values())
    if total_supp > 0:
        supp_remaining = dict(supplemental_needs)
        supp_round = NUM_ROUNDS + 1

        while sum(supp_remaining.values()) > 0:
            base_order = get_round_order(supp_round)
            pick_in_round = 0

            for pos in base_order:
                mgr = MANAGERS[pos]
                if supp_remaining.get(mgr, 0) > 0:
                    pick_in_round += 1
                    overall_pick += 1
                    supp_remaining[mgr] -= 1
                    results.append({
                        "overall_pick": overall_pick,
                        "round": supp_round,
                        "pick_in_round": pick_in_round,
                        "manager": mgr,
                        "notes": "(supplemental)",
                    })

            supp_round += 1

    return results


def print_draft_board(results):
    current_round = 0

    print("\n" + "=" * 95)
    print("2026 FANTASY BASEBALL DRAFT ORDER")
    print("10-Team Snake Draft, 25 Rounds + Supplemental")
    print("25-player cap enforced: excess picks forfeited, keepers slide to latest available round")
    print("=" * 95)

    for r in results:
        if r["round"] != current_round:
            current_round = r["round"]
            if current_round <= NUM_ROUNDS:
                direction = "\u2192" if current_round % 2 == 1 else "\u2190"
                print(f"\n--- ROUND {current_round} ({direction}) ---")
            else:
                direction = "\u2192" if current_round % 2 == 1 else "\u2190"
                print(f"\n--- SUPPLEMENTAL ROUND {current_round - NUM_ROUNDS} ({direction}) ---")

        pick_label = f"#{r['overall_pick']:>3}" if r["overall_pick"] != "KEEPER" else " KEP"
        notes = f"  {r['notes']}" if r['notes'] else ""
        print(f"  {r['round']:>2}.{r['pick_in_round']:>2}  Pick {pick_label}  {r['manager']:<20}{notes}")


def print_summary(results):
    pick_counts = defaultdict(lambda: {"draft": 0, "keepers": 0, "supp": 0, "total": 0})

    for r in results:
        mgr = r["manager"]
        if r["overall_pick"] == "KEEPER":
            pick_counts[mgr]["keepers"] += 1
        else:
            pick_counts[mgr]["draft"] += 1
            if "(supplemental)" in r.get("notes", ""):
                pick_counts[mgr]["supp"] += 1
        pick_counts[mgr]["total"] += 1

    print("\n===== MANAGER PICK SUMMARY =====")
    print(f"{'Manager':<20} {'Draft':>6} {'Supp':>5} {'Keep':>5} {'Total':>6}")
    print("-" * 50)
    for pos in range(1, 11):
        mgr = MANAGERS[pos]
        c = pick_counts[mgr]
        supp_str = f"+{c['supp']}" if c['supp'] > 0 else ""
        print(f"{mgr:<20} {c['draft']:>6} {supp_str:>5} {c['keepers']:>5} {c['total']:>6}")

    td = sum(c["draft"] for c in pick_counts.values())
    tk = sum(c["keepers"] for c in pick_counts.values())
    tt = sum(c["total"] for c in pick_counts.values())
    print("-" * 50)
    print(f"{'TOTAL':<20} {td:>6} {'':>5} {tk:>5} {tt:>6}")


def print_keeper_adjustments(adjustments):
    if not adjustments:
        return
    print("\n===== KEEPER ROUND ADJUSTMENTS (due to 25-cap) =====")
    for mgr, player, orig_rnd, actual_rnd in adjustments:
        print(f"  {mgr}: {player} — declared Rd {orig_rnd} → moved to Rd {actual_rnd}")


def print_forfeited_picks(manager_slots, final_slots):
    print("\n===== FORFEITED PICKS (excess beyond 25-cap) =====")
    for pos in range(1, 11):
        mgr = MANAGERS[pos]
        orig_count = len(manager_slots[mgr])
        final_count = len(final_slots[mgr])

        if orig_count > ROSTER_SIZE:
            forfeited = manager_slots[mgr][ROSTER_SIZE:]
            picks_str = ", ".join(
                f"Rd {r}" + (f" {n}" if n else "")
                for r, p, n in forfeited
            )
            print(f"  {mgr}: forfeits {len(forfeited)} picks — {picks_str}")


def print_manager_detail(mgr_name, final_slots):
    print(f"\n===== {mgr_name.upper()} — FINAL PICK INVENTORY =====")
    slots = final_slots[mgr_name]
    draft_count = 0
    keeper_count = 0
    last_draft_round = 0
    for rnd, pos, stype, notes in slots:
        if stype == "keeper":
            keeper_count += 1
            print(f"  Round {rnd:>2}  KEEPER  {notes}")
        else:
            draft_count += 1
            note_str = f"  {notes}" if notes else ""
            print(f"  Round {rnd:>2}  Draft pick #{draft_count}{note_str}")
            last_draft_round = rnd
    print(f"\n  Total: {draft_count} draft + {keeper_count} keepers = {draft_count + keeper_count}")
    print(f"  Last draft pick: Round {last_draft_round}")


def write_csv(results, filename):
    with open(filename, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            "overall_pick", "round", "pick_in_round", "manager", "notes"
        ])
        writer.writeheader()
        writer.writerows(results)
    print(f"\nCSV written to {filename}")


def write_sheet_format_csv(results, keeper_adjustments, filename):
    """Write draft order CSV matching the 2025 Draft Google Sheets tab format."""

    INITIALS = {
        "Jason McComb": "JM", "Eric Mercado": "EM", "Chris Herbst": "CH",
        "John Gibbons": "JG", "Tim Riker": "TR", "Bryan Lewis": "BL",
        "Harris Cook": "HC", "Matt Wayne": "MW", "Jess Barron": "JB",
        "David Rotatori": "DR",
    }

    # Count picks and keepers per manager for sidebar
    mgr_totals = defaultdict(lambda: {"total": 0, "keepers": 0})
    for r in results:
        mgr = r["manager"]
        mgr_totals[mgr]["total"] += 1
        if r["overall_pick"] == "KEEPER":
            mgr_totals[mgr]["keepers"] += 1

    # Sidebar managers in draft position order
    sidebar_mgrs = [MANAGERS[i] for i in range(1, 11)]

    rows = []

    # Header row
    rows.append(["", "#", "Owner", "Player", "Position", "MLB Team", "Notes",
                 "", "", "", "", "", ""])

    current_round = 0
    sequential_pick = 0
    sidebar_idx = 0
    first_round2_pick = True
    in_supplemental = False

    for r in results:
        rnd = r["round"]

        # Round header when round changes
        if rnd != current_round:
            current_round = rnd
            emit_header = False

            if rnd <= NUM_ROUNDS:
                round_label = f"Round {rnd}"
                emit_header = True
            elif not in_supplemental:
                round_label = "Supplemental"
                in_supplemental = True
                emit_header = True

            if emit_header:
                if rnd == 1:
                    rows.append([round_label, "", "", "", "", "", "", "", "",
                                 "# of draft picks", "Selections Remaining",
                                 "", ""])
                else:
                    rows.append([round_label, "", "", "", "", "", "", "", "",
                                 "", "", "", ""])
            sidebar_idx = 0

        # Pick data
        sequential_pick += 1
        mgr = r["manager"]
        player_name = ""
        notes = ""

        if r["overall_pick"] == "KEEPER":
            # Extract player name from "KEEPER: Player Name (Xth yr) [moved...]"
            keeper_text = r["notes"]
            if "KEEPER: " in keeper_text:
                rest = keeper_text.replace("KEEPER: ", "")
                paren_idx = rest.find(" (")
                player_name = rest[:paren_idx] if paren_idx >= 0 else rest

            match = re.search(r'\[moved from Rd (\d+)\]', keeper_text)
            if match:
                notes = f"Keeper (from Rd {match.group(1)})"
            else:
                notes = "Keeper"
        else:
            raw_notes = r.get("notes", "")
            match = re.search(r'\(traded from (.+?)\)', raw_notes)
            if match:
                initials = INITIALS.get(match.group(1), match.group(1))
                notes = f"Trade with {initials}"

        row = ["", sequential_pick, mgr, player_name, "", "", notes,
               "", "", "", "", "", ""]

        # Sidebar for Round 1 picks
        if rnd == 1 and sidebar_idx < len(sidebar_mgrs):
            s_mgr = sidebar_mgrs[sidebar_idx]
            s_total = mgr_totals[s_mgr]["total"]
            s_remaining = s_total - mgr_totals[s_mgr]["keepers"]
            row[8] = s_mgr
            row[9] = s_total
            row[10] = s_remaining
            sidebar_idx += 1

        # Total row on first pick of Round 2
        if rnd == 2 and first_round2_pick:
            total_picks = sum(t["total"] for t in mgr_totals.values())
            total_keepers = sum(t["keepers"] for t in mgr_totals.values())
            total_remaining = total_picks - total_keepers
            row[8] = "total"
            row[9] = total_picks
            row[10] = total_remaining
            row[11] = total_keepers
            row[12] = "# of players drafted"
            first_round2_pick = False

        rows.append(row)

    with open(filename, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerows(rows)

    print(f"\nSheet-format CSV written to {filename}")


def main():
    manager_slots = compute_all_pick_slots()
    final_slots, supplemental_needs, keeper_adjustments = assign_keepers_with_cap(manager_slots)
    results = build_draft_order(final_slots, supplemental_needs)

    print_draft_board(results)
    print_summary(results)
    print_keeper_adjustments(keeper_adjustments)
    print_forfeited_picks(manager_slots, final_slots)
    print_manager_detail("Chris Herbst", final_slots)

    csv_path = "/Users/jgibbons/code/fantasy-baseball-helper/2026_draft_order.csv"
    write_sheet_format_csv(results, keeper_adjustments, csv_path)


if __name__ == "__main__":
    main()
