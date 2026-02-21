from __future__ import annotations

from .player_pool import Player, ROSTER_SLOTS, POSITION_TO_SLOTS


class RosterState:
    """Tracks remaining roster slot capacity for one team."""

    def __init__(self) -> None:
        self.capacity: dict[str, int] = dict(ROSTER_SLOTS)

    def can_add(self, player: Player) -> bool:
        for slot in self._eligible_slots_ordered(player):
            if self.capacity.get(slot, 0) > 0:
                return True
        return False

    def add_player(self, player: Player) -> str | None:
        """Greedy assign to most-constrained (first) eligible slot. Returns slot name or None."""
        for slot in self._eligible_slots_ordered(player):
            if self.capacity.get(slot, 0) > 0:
                self.capacity[slot] -= 1
                return slot
        return None

    def has_starting_need(self, player: Player) -> bool:
        """Returns True if player fills a non-bench slot."""
        for slot in self._eligible_slots_ordered(player):
            if slot != "BE" and self.capacity.get(slot, 0) > 0:
                return True
        return False

    def _eligible_slots_ordered(self, player: Player) -> list[str]:
        """Get eligible slots in POSITION_TO_SLOTS order (most restrictive first)."""
        positions = player.get_positions()
        seen: set[str] = set()
        ordered: list[str] = []
        for pos in positions:
            slots = POSITION_TO_SLOTS.get(pos, [])
            for s in slots:
                if s not in seen:
                    seen.add(s)
                    ordered.append(s)
        return ordered
