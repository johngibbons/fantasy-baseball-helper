"""Position-aware greedy lineup optimizer for daily-lineup fantasy leagues.

Assigns hitters to active roster slots (C, 1B, 2B, 3B, SS, OF×3, UTIL×2)
or bench using a two-phase algorithm:

  Phase 1 — positional slots: Players are sorted by fewest dedicated positional
    slots first (most constrained), then by overall_rank. Each player is
    assigned to their first available positional (non-UTIL) slot. DH-only
    players skip Phase 1 entirely.

  Phase 2 — UTIL: Players unplaced in Phase 1, plus all DH-only players, are
    sorted by overall_rank and assigned to UTIL in order. Any remaining
    players go to bench (BE).

This ensures the C-only player beats a C/1B player for the C slot (Phase 1
constraint sort), while also ensuring a high-rank flexible player can claim
UTIL ahead of a low-rank single-position player whose primary slot is full.

Pitchers don't need optimization — in daily-lineup leagues all non-IL
pitchers contribute at full weight regardless of ESPN bench/active slot.
"""

from __future__ import annotations

from dataclasses import dataclass


HITTER_ACTIVE_SLOTS: dict[str, int] = {
    "C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "UTIL": 2,
}

POSITION_TO_ACTIVE_SLOTS: dict[str, list[str]] = {
    "C":  ["C", "UTIL"],
    "1B": ["1B", "UTIL"],
    "2B": ["2B", "UTIL"],
    "3B": ["3B", "UTIL"],
    "SS": ["SS", "UTIL"],
    "OF": ["OF", "UTIL"],
    "LF": ["OF", "UTIL"],
    "CF": ["OF", "UTIL"],
    "RF": ["OF", "UTIL"],
    "DH": ["UTIL"],
}


@dataclass
class HitterSlotAssignment:
    mlb_id: int
    slot: str        # "C", "1B", ..., "UTIL", "BE"
    is_starter: bool  # True if assigned to an active slot


def _eligible_active_slots(eligible_positions: str) -> list[str]:
    """Return ordered list of active slots a player can fill.

    Positional slots (non-UTIL) are listed first in the order they appear
    from POSITION_TO_ACTIVE_SLOTS; UTIL is appended last.  This ensures
    multi-position players (e.g. SS/2B) try both positional slots before
    falling back to UTIL.
    """
    if not eligible_positions:
        return ["UTIL"]
    positions = eligible_positions.split("/")
    seen: set[str] = set()
    positional: list[str] = []
    has_util = False
    for pos in positions:
        for s in POSITION_TO_ACTIVE_SLOTS.get(pos, []):
            if s == "UTIL":
                has_util = True
            elif s not in seen:
                seen.add(s)
                positional.append(s)
    slots = positional + (["UTIL"] if has_util else [])
    return slots if slots else ["UTIL"]


def optimize_hitter_lineup(
    hitters: list[dict],
) -> list[HitterSlotAssignment]:
    """Assign hitters to active slots or bench using two-phase optimization.

    Phase 1 — positional slots:
      Sort players with at least one positional slot by
      (positional_slot_count ASC, overall_rank ASC).  Assign each to their
      first available positional slot.  Unplaced players carry over to Phase 2.
      DH-only players skip Phase 1.

    Phase 2 — UTIL:
      Combine Phase-1 carry-overs with DH-only players.  Sort by overall_rank
      ASC and assign to UTIL.  Any remaining players → bench (BE).
    """
    if not hitters:
        return []

    capacity = dict(HITTER_ACTIVE_SLOTS)

    enriched: list[tuple[dict, list[str]]] = [
        (h, _eligible_active_slots(h.get("eligible_positions", "") or ""))
        for h in hitters
    ]

    # Split into positional players and DH-only
    positional: list[tuple[dict, list[str]]] = [
        (h, slots) for h, slots in enriched
        if any(s != "UTIL" for s in slots)
    ]
    dh_only: list[tuple[dict, list[str]]] = [
        (h, slots) for h, slots in enriched
        if all(s == "UTIL" for s in slots)
    ]

    # Phase 1: assign to positional slots
    positional.sort(
        key=lambda x: (
            len([s for s in x[1] if s != "UTIL"]),
            x[0].get("overall_rank", 9999),
        )
    )

    slot_assignments: dict[int, tuple[str, bool]] = {}
    phase2_pool: list[tuple[dict, list[str]]] = []

    for h, slots in positional:
        positional_slots = [s for s in slots if s != "UTIL"]
        placed = False
        for slot in positional_slots:
            if capacity.get(slot, 0) > 0:
                capacity[slot] -= 1
                slot_assignments[h["mlb_id"]] = (slot, True)
                placed = True
                break
        if not placed:
            phase2_pool.append((h, slots))

    # Phase 2: assign carry-overs + DH-only to UTIL in rank order
    phase2_all = phase2_pool + dh_only
    phase2_all.sort(key=lambda x: x[0].get("overall_rank", 9999))

    for h, _slots in phase2_all:
        if capacity.get("UTIL", 0) > 0:
            capacity["UTIL"] -= 1
            slot_assignments[h["mlb_id"]] = ("UTIL", True)
        else:
            slot_assignments[h["mlb_id"]] = ("BE", False)

    # Return assignments in original hitter order
    return [
        HitterSlotAssignment(
            mlb_id=h["mlb_id"],
            slot=slot_assignments[h["mlb_id"]][0],
            is_starter=slot_assignments[h["mlb_id"]][1],
        )
        for h, _ in enriched
    ]
