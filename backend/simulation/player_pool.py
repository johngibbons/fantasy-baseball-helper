from __future__ import annotations

import bisect
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set

# Category keys in the same order as the TypeScript ALL_CATS
HITTING_CAT_KEYS = ["zscore_r", "zscore_tb", "zscore_rbi", "zscore_sb", "zscore_obp"]
PITCHING_CAT_KEYS = ["zscore_k", "zscore_qs", "zscore_era", "zscore_whip", "zscore_svhd"]
ALL_CAT_KEYS = HITTING_CAT_KEYS + PITCHING_CAT_KEYS

CAT_LABELS = {
    "zscore_r": "R", "zscore_tb": "TB", "zscore_rbi": "RBI",
    "zscore_sb": "SB", "zscore_obp": "OBP", "zscore_k": "K",
    "zscore_qs": "QS", "zscore_era": "ERA", "zscore_whip": "WHIP",
    "zscore_svhd": "SVHD",
}

# Roster slot config — matches page.tsx:46-47
ROSTER_SLOTS: dict[str, int] = {
    "C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3,
    "UTIL": 2, "SP": 3, "RP": 2, "P": 2, "BE": 8,
}

TOTAL_ROSTER_SIZE = sum(ROSTER_SLOTS.values())
STARTER_SLOT_COUNT = sum(v for k, v in ROSTER_SLOTS.items() if k != "BE")

# Bench players contribute ~25% of projected stats (injury coverage, rest days, streaming)
BENCH_CONTRIBUTION = 0.25

# Maps positions to eligible roster slots (most restrictive first) — matches page.tsx:50-57
POSITION_TO_SLOTS: dict[str, list[str]] = {
    "C": ["C", "UTIL", "BE"],
    "1B": ["1B", "UTIL", "BE"],
    "2B": ["2B", "UTIL", "BE"],
    "3B": ["3B", "UTIL", "BE"],
    "SS": ["SS", "UTIL", "BE"],
    "OF": ["OF", "UTIL", "BE"],
    "LF": ["OF", "UTIL", "BE"],
    "CF": ["OF", "UTIL", "BE"],
    "RF": ["OF", "UTIL", "BE"],
    "DH": ["UTIL", "BE"],
    "SP": ["SP", "P", "BE"],
    "RP": ["RP", "P", "BE"],
    "TWP": ["UTIL", "SP", "P", "BE"],
}


ESPN_ADP_WEIGHT = 0.65
NFBC_ADP_WEIGHT = 0.35


def blend_adp(espn_adp: Optional[float], nfbc_adp: Optional[float]) -> Optional[float]:
    """Blend ESPN and NFBC ADP (65/35 split). Falls back to whichever is available."""
    if espn_adp is not None and nfbc_adp is not None:
        return ESPN_ADP_WEIGHT * espn_adp + NFBC_ADP_WEIGHT * nfbc_adp
    return espn_adp if espn_adp is not None else nfbc_adp


@dataclass
class Player:
    mlb_id: int
    full_name: str
    primary_position: str
    player_type: str  # 'hitter' or 'pitcher'
    overall_rank: int
    total_zscore: float
    espn_adp: Optional[float]
    eligible_positions: Optional[str]
    zscores: dict[str, float]  # cat_key -> z-score value
    nfbc_adp: Optional[float] = None
    blended_adp: Optional[float] = None

    def pitcher_role(self) -> str:
        if self.zscores.get("zscore_qs", 0) != 0:
            return "SP"
        if self.zscores.get("zscore_svhd", 0) != 0:
            return "RP"
        return "SP"

    def get_positions(self) -> list[str]:
        if self.eligible_positions:
            return self.eligible_positions.split("/")
        if self.player_type == "pitcher":
            return [self.pitcher_role()]
        return [self.primary_position]

    def get_eligible_slots(self) -> list[str]:
        positions = self.get_positions()
        slot_set: set[str] = set()
        for pos in positions:
            slots = POSITION_TO_SLOTS.get(pos)
            if slots:
                for s in slots:
                    slot_set.add(s)
        return list(slot_set)

    def cat_keys(self) -> list[str]:
        return PITCHING_CAT_KEYS if self.player_type == "pitcher" else HITTING_CAT_KEYS


# H2H category weights baked into stored z-scores (from analysis/zscores.py)
_H2H_WEIGHTS = {
    "zscore_r": 0.92, "zscore_tb": 0.95, "zscore_rbi": 0.96, "zscore_sb": 1.15, "zscore_obp": 1.02,
    "zscore_k": 1.02, "zscore_qs": 0.98, "zscore_era": 0.95, "zscore_whip": 0.97, "zscore_svhd": 1.14,
}


def rescale_h2h_weights(players: list[Player], scale: float) -> None:
    """Adjust H2H correlation weights on loaded z-scores.

    scale=1.0 keeps current weights (no-op). scale=0.0 removes them entirely.
    scale=0.5 halves the adjustment (weight halfway between 1.0 and current).
    Modifies players in place and recalculates total_zscore.
    """
    if scale == 1.0:
        return
    for p in players:
        cats = PITCHING_CAT_KEYS if p.player_type == "pitcher" else HITTING_CAT_KEYS
        total = 0.0
        for cat in cats:
            old_weight = _H2H_WEIGHTS[cat]
            new_weight = 1.0 + (old_weight - 1.0) * scale
            p.zscores[cat] = p.zscores[cat] * new_weight / old_weight
            total += p.zscores[cat]
        p.total_zscore = total


@dataclass
class KeeperEntry:
    mlb_id: int
    team_idx: int      # 0-based draft position (not ESPN team ID)
    round_cost: int    # 1-based round


def load_keepers(db_path: Optional[str] = None, season: int = 2026) -> list[KeeperEntry]:
    """Load keepers from draft_state.state_json -> leagueKeepers.

    Converts ESPN team IDs to 0-based draft positions using the stored draftOrder.
    """
    if db_path is None:
        db_path = str(Path(__file__).parent.parent / "fantasy_baseball.db")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT state_json FROM draft_state WHERE season = ?", (season,)
    ).fetchone()
    conn.close()

    if not row:
        return []

    state = json.loads(row["state_json"])
    league_keepers = state.get("leagueKeepers", [])
    draft_order = state.get("draftOrder", [])

    if not league_keepers or not draft_order:
        return []

    # Map ESPN team ID -> 0-based draft position
    team_id_to_idx = {tid: idx for idx, tid in enumerate(draft_order)}

    entries: list[KeeperEntry] = []
    for k in league_keepers:
        team_id = k["teamId"]
        idx = team_id_to_idx.get(team_id)
        if idx is None:
            continue
        entries.append(KeeperEntry(
            mlb_id=k["mlb_id"],
            team_idx=idx,
            round_cost=k["roundCost"],
        ))
    return entries


def keeper_pick_index(team_idx: int, round_cost: int, num_teams: int) -> int:
    """Compute the pick index for a keeper in a snake draft.

    team_idx: 0-based draft position
    round_cost: 1-based round number
    """
    round_0 = round_cost - 1
    if round_0 % 2 == 0:
        return round_0 * num_teams + team_idx
    else:
        return round_0 * num_teams + (num_teams - 1 - team_idx)


def build_keeper_adp_list(keepers: list[KeeperEntry], player_by_id: dict[int, Player]) -> list[float]:
    """Build sorted list of keeper ADPs for count_kept_below_adp lookups."""
    adps: list[float] = []
    for k in keepers:
        p = player_by_id.get(k.mlb_id)
        if p and p.blended_adp is not None:
            adps.append(p.blended_adp)
    adps.sort()
    return adps


def count_kept_below_adp(adp: float, keeper_adps_sorted: list[float]) -> int:
    """Count how many kept players have ADP <= adp (binary search)."""
    return bisect.bisect_right(keeper_adps_sorted, adp)


def load_players(db_path: Optional[str] = None, season: int = 2026) -> list[Player]:
    if db_path is None:
        db_path = str(Path(__file__).parent.parent / "fantasy_baseball.db")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT r.mlb_id, r.overall_rank, r.total_zscore,
               r.zscore_r, r.zscore_tb, r.zscore_rbi, r.zscore_sb, r.zscore_obp,
               r.zscore_k, r.zscore_qs, r.zscore_era, r.zscore_whip, r.zscore_svhd,
               r.player_type, r.espn_adp, r.fangraphs_adp,
               p.full_name, p.primary_position, p.eligible_positions
        FROM rankings r
        JOIN players p ON r.mlb_id = p.mlb_id
        WHERE r.season = ?
        ORDER BY r.overall_rank
        """,
        (season,),
    )

    players: list[Player] = []
    for row in cursor.fetchall():
        zscores = {key: row[key] or 0.0 for key in ALL_CAT_KEYS}
        espn = row["espn_adp"]
        nfbc = row["fangraphs_adp"]
        players.append(
            Player(
                mlb_id=row["mlb_id"],
                full_name=row["full_name"],
                primary_position=row["primary_position"] or "",
                player_type=row["player_type"],
                overall_rank=row["overall_rank"] or 9999,
                total_zscore=row["total_zscore"] or 0.0,
                espn_adp=espn,
                eligible_positions=row["eligible_positions"],
                zscores=zscores,
                nfbc_adp=nfbc,
                blended_adp=blend_adp(espn, nfbc),
            )
        )

    conn.close()
    return players
