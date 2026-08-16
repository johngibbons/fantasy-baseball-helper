"""Parse and resolve the draft-day ESPN ADP export to mlb_ids.

Why this exists: `rankings.espn_adp` is refreshed from ESPN's live API all
season (import_espn_adp in backend/data/projections.py), so it holds *current*
ADP, not what the board showed on draft day. Skubal was 5.8 in the March export
and 9.6 in production today. The CSV snapshot at repo root is the only surviving
record of draft-day ADP, and it is keyed by name — hence this module.

Pure functions only; the DB read and file IO live in
backend/scripts/retro_snapshot.py.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from io import StringIO

from backend.data.name_matching import normalize_name

# ESPN writes pitchers as SP/RP/P. Anything else implies the player is in the
# hitter pool — including two-way players like Ohtani ("DH/SP"), who are
# hitter-first in the valuation engine (see the two-way merge in zscores.py).
_PITCHER_POSITIONS = {"SP", "RP", "P"}


@dataclass(frozen=True)
class AdpEntry:
    """One row of the ESPN ADP export."""

    name: str
    team: str
    positions: tuple[str, ...]
    pos_rank: str
    adp: float
    row_index: int

    @property
    def is_pitcher(self) -> bool:
        """True when every listed position is a pitching slot."""
        if not self.positions:
            return False
        return all(p in _PITCHER_POSITIONS for p in self.positions)


@dataclass(frozen=True)
class PlayerRow:
    """Minimal player record for matching (from the players + rankings join)."""

    mlb_id: int
    full_name: str
    player_type: str | None = None
    overall_rank: int | None = None
    is_active: bool = True


@dataclass
class AdpResolution:
    """Result of matching ADP rows against the player table."""

    matched: dict[int, float] = field(default_factory=dict)
    details: list[dict] = field(default_factory=list)
    unmatched: list[dict] = field(default_factory=list)
    ambiguous: list[dict] = field(default_factory=list)


def parse_adp_csv(text: str) -> list[AdpEntry]:
    """Parse the ESPN ADP export.

    Expected header: ,Player,Team,Elig. Pos.,Pos. Rank,ADP,,,
    Rows lacking a player name or a numeric ADP are skipped.
    """
    entries: list[AdpEntry] = []
    reader = csv.DictReader(StringIO(text))
    for i, row in enumerate(reader):
        name = (row.get("Player") or "").strip()
        raw_adp = (row.get("ADP") or "").strip()
        if not name or not raw_adp:
            continue
        try:
            adp = float(raw_adp)
        except ValueError:
            continue
        positions = tuple(
            p.strip().upper()
            for p in (row.get("Elig. Pos.") or "").split("/")
            if p.strip()
        )
        entries.append(AdpEntry(
            name=name,
            team=(row.get("Team") or "").strip(),
            positions=positions,
            pos_rank=(row.get("Pos. Rank") or "").strip(),
            adp=adp,
            row_index=i,
        ))
    return entries


def coverage_summary(
    entries: list[AdpEntry],
    resolution: AdpResolution,
    adp_cutoff: float,
) -> dict:
    """Report match coverage, separating rows that could plausibly be drafted.

    ESPN pads its export with a filler ADP (~259.9) for everyone it does not
    expect to be drafted, so a raw unmatched count is dominated by prospects
    and free agents nobody could have taken. Coverage below `adp_cutoff`
    (= the number of picks in the draft) is the number that actually matters.
    """
    in_range = [e for e in entries if e.adp < adp_cutoff]
    unmatched_in_range = [
        u for u in resolution.unmatched if u["adp"] < adp_cutoff
    ]
    return {
        "adp_cutoff": adp_cutoff,
        "entries_in_range": len(in_range),
        "unmatched_in_range": len(unmatched_in_range),
        "unmatched_in_range_names": [u["name"] for u in unmatched_in_range],
        "ambiguous_in_range": sum(
            1 for a in resolution.ambiguous if a["adp"] < adp_cutoff
        ),
    }


def _candidate_sort_key(p: PlayerRow) -> tuple:
    """Best candidate first: ranked players, then better rank, then active.

    Mirrors the collision rule in resolve_keepers (routes.py) — a player who
    carries a ranking for the season is the one the board was talking about.
    mlb_id is the final tiebreak purely for determinism across runs.
    """
    return (
        p.overall_rank is None,
        p.overall_rank if p.overall_rank is not None else 10**9,
        not p.is_active,
        p.mlb_id,
    )


def resolve_adp_entries(
    entries: list[AdpEntry],
    players: list[PlayerRow],
) -> AdpResolution:
    """Match ADP rows to mlb_ids by normalized name, disambiguated by type+rank.

    Never silently drops a row: everything lands in exactly one of
    `details` (matched), `unmatched`, and collisions are additionally recorded
    in `ambiguous` so the data-quality cost is visible in the artifact.
    """
    by_name: dict[str, list[PlayerRow]] = {}
    for p in players:
        by_name.setdefault(normalize_name(p.full_name), []).append(p)

    result = AdpResolution()
    for entry in entries:
        norm = normalize_name(entry.name)
        candidates = by_name.get(norm, [])
        if not candidates:
            result.unmatched.append({
                "name": entry.name,
                "team": entry.team,
                "positions": list(entry.positions),
                "adp": entry.adp,
                "reason": "no_name_match",
            })
            continue

        # Narrow by hitter/pitcher when the ADP row tells us which pool it is.
        wanted_type = "pitcher" if entry.is_pitcher else "hitter"
        typed = [c for c in candidates if c.player_type == wanted_type]
        pool = typed or candidates

        pool = sorted(pool, key=_candidate_sort_key)
        best = pool[0]

        if len(pool) > 1:
            result.ambiguous.append({
                "name": entry.name,
                "adp": entry.adp,
                "chosen_mlb_id": best.mlb_id,
                "candidates": [
                    {"mlb_id": c.mlb_id, "player_type": c.player_type,
                     "overall_rank": c.overall_rank}
                    for c in pool
                ],
                "narrowed_by_type": bool(typed),
            })

        # A later duplicate name would otherwise overwrite an earlier, better
        # ADP; keep the first (lower ADP = earlier in the export).
        if best.mlb_id in result.matched:
            result.unmatched.append({
                "name": entry.name,
                "team": entry.team,
                "positions": list(entry.positions),
                "adp": entry.adp,
                "reason": "duplicate_mlb_id",
                "mlb_id": best.mlb_id,
            })
            continue

        result.matched[best.mlb_id] = entry.adp
        result.details.append({
            "mlb_id": best.mlb_id,
            "name": entry.name,
            "db_name": best.full_name,
            "team": entry.team,
            "positions": list(entry.positions),
            "pos_rank": entry.pos_rank,
            "adp": entry.adp,
        })

    return result
