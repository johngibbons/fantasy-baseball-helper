from __future__ import annotations

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
               r.player_type, r.espn_adp,
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
        players.append(
            Player(
                mlb_id=row["mlb_id"],
                full_name=row["full_name"],
                primary_position=row["primary_position"] or "",
                player_type=row["player_type"],
                overall_rank=row["overall_rank"] or 9999,
                total_zscore=row["total_zscore"] or 0.0,
                espn_adp=row["espn_adp"],
                eligible_positions=row["eligible_positions"],
                zscores=zscores,
            )
        )

    conn.close()
    return players
