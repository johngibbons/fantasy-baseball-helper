"""Preserve the board before it is overwritten.

The 2026 retrospective had to reconstruct its own baseline from committed CSVs,
because `projections` is unique on (mlb_id, source, season, player_type) and
`rankings` on (mlb_id, season): every refresh overwrites in place. By the time
anyone asked how the draft board did, the board was gone — replaced by
rest-of-season values, with Skubal showing 45 projected innings.

This module keeps copies. Two kinds:

  auto-YYYY-MM-DD   taken automatically before any refresh overwrites the
                    tables, idempotent per day, pruned after a season or so.
                    A write-ahead journal, not an archive.
  named labels      taken deliberately (`preseason-2027` on draft day) and
                    never pruned.

Snapshots are columnar copies of the source tables rather than JSON blobs
because the analysis reads them as tables. The cost is small: roughly 1,400
ranking rows per snapshot.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone

from backend.database import get_connection

logger = logging.getLogger(__name__)

AUTO_PREFIX = "auto-"
DEFAULT_PRUNE_AFTER_DAYS = 400  # long enough that a full season survives

# Columns copied verbatim from the source tables.
_RANKING_COLUMNS = (
    "mlb_id, season, overall_rank, position_rank, total_zscore, "
    "zscore_r, zscore_tb, zscore_rbi, zscore_sb, zscore_obp, "
    "zscore_k, zscore_qs, zscore_era, zscore_whip, zscore_svhd, "
    "proj_pa, proj_r, proj_tb, proj_rbi, proj_sb, proj_obp, "
    "proj_ip, proj_k, proj_qs, proj_era, proj_whip, proj_svhd, "
    "espn_adp, adp_diff, fangraphs_adp, player_type"
)
_PROJECTION_COLUMNS = (
    "mlb_id, source, season, player_type, "
    "proj_pa, proj_runs, proj_hits, proj_doubles, proj_triples, "
    "proj_home_runs, proj_rbi, proj_stolen_bases, proj_walks, "
    "proj_strikeouts, proj_hbp, proj_sac_flies, proj_at_bats, proj_obp, "
    "proj_total_bases, proj_ip, proj_pitcher_strikeouts, "
    "proj_quality_starts, proj_era, proj_whip, proj_saves, proj_holds, "
    "proj_wins, proj_hits_allowed, proj_walks_allowed, proj_earned_runs"
)


def _column_definitions(columns: str, integer: set[str], text: set[str]) -> str:
    """Type each copied column: everything is REAL unless named otherwise."""
    definitions = []
    for column in (c.strip() for c in columns.split(",")):
        if column in integer:
            sql_type = "INTEGER"
        elif column in text:
            sql_type = "TEXT"
        else:
            sql_type = "REAL"
        definitions.append(f"{column} {sql_type}")
    return ",\n            ".join(definitions)


_INTEGER_COLUMNS = {
    "mlb_id", "season", "overall_rank", "position_rank",
    "proj_pa", "proj_r", "proj_tb", "proj_rbi", "proj_sb",
    "proj_k", "proj_qs", "proj_svhd", "proj_runs", "proj_hits",
    "proj_doubles", "proj_triples", "proj_home_runs", "proj_stolen_bases",
    "proj_walks", "proj_strikeouts", "proj_hbp", "proj_sac_flies",
    "proj_at_bats", "proj_total_bases", "proj_pitcher_strikeouts",
    "proj_quality_starts", "proj_saves", "proj_holds", "proj_wins",
    "proj_hits_allowed", "proj_walks_allowed", "proj_earned_runs",
}
_TEXT_COLUMNS = {"player_type", "source"}


def ensure_snapshot_tables(conn) -> None:
    """Create the snapshot tables if absent.

    Follows the self-healing pattern used by _ensure_draft_state_table in
    routes.py, so production needs no migration step.
    """
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS ranking_snapshots (
            snapshot_label TEXT NOT NULL,
            taken_at TEXT NOT NULL,
            {_column_definitions(_RANKING_COLUMNS, _INTEGER_COLUMNS, _TEXT_COLUMNS)},
            UNIQUE(snapshot_label, mlb_id, season)
        )
    """)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS projection_snapshots (
            snapshot_label TEXT NOT NULL,
            taken_at TEXT NOT NULL,
            {_column_definitions(_PROJECTION_COLUMNS, _INTEGER_COLUMNS, _TEXT_COLUMNS)},
            UNIQUE(snapshot_label, mlb_id, source, season, player_type)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS snapshot_manifest (
            snapshot_label TEXT PRIMARY KEY,
            season INTEGER NOT NULL,
            taken_at TEXT NOT NULL,
            kind TEXT NOT NULL,
            note TEXT,
            row_counts TEXT
        )
    """)
    conn.commit()


def is_auto(label: str) -> bool:
    return label.startswith(AUTO_PREFIX)


def auto_label(when: date | None = None) -> str:
    return f"{AUTO_PREFIX}{(when or date.today()).isoformat()}"


def snapshot_exists(conn, label: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM snapshot_manifest WHERE snapshot_label = ?", (label,)
    ).fetchone()
    return row is not None


def create_snapshot(label: str, season: int, *, kind: str = "manual",
                    note: str | None = None, conn=None) -> dict:
    """Copy the current rankings and projections under `label`.

    Idempotent: an existing label is left untouched and reported back, so the
    pre-refresh hook can fire on every refresh without piling up duplicates.
    """
    own_connection = conn is None
    conn = conn or get_connection()
    try:
        ensure_snapshot_tables(conn)
        if snapshot_exists(conn, label):
            return {"snapshot_label": label, "created": False,
                    "reason": "already exists"}

        taken_at = datetime.now(timezone.utc).isoformat()
        conn.execute(
            f"""INSERT INTO ranking_snapshots (snapshot_label, taken_at, {_RANKING_COLUMNS})
                SELECT ?, ?, {_RANKING_COLUMNS} FROM rankings WHERE season = ?""",
            (label, taken_at, season),
        )
        conn.execute(
            f"""INSERT INTO projection_snapshots (snapshot_label, taken_at, {_PROJECTION_COLUMNS})
                SELECT ?, ?, {_PROJECTION_COLUMNS} FROM projections WHERE season = ?""",
            (label, taken_at, season),
        )
        counts = {
            "rankings": conn.execute(
                "SELECT COUNT(*) c FROM ranking_snapshots WHERE snapshot_label = ?",
                (label,)).fetchone()["c"],
            "projections": conn.execute(
                "SELECT COUNT(*) c FROM projection_snapshots WHERE snapshot_label = ?",
                (label,)).fetchone()["c"],
        }
        conn.execute(
            """INSERT INTO snapshot_manifest
               (snapshot_label, season, taken_at, kind, note, row_counts)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (label, season, taken_at, kind, note, json.dumps(counts)),
        )
        conn.commit()
        logger.info(f"Snapshot {label}: {counts['rankings']} rankings, "
                    f"{counts['projections']} projections")
        return {"snapshot_label": label, "created": True, "season": season,
                "taken_at": taken_at, "row_counts": counts}
    finally:
        if own_connection:
            conn.close()


def snapshot_before_refresh(season: int, note: str | None = None) -> dict | None:
    """Take today's automatic snapshot, if it has not been taken already.

    Callers must treat failure as non-fatal — losing a snapshot is worse than
    a failed refresh, but not worse than no refresh at all.
    """
    return create_snapshot(auto_label(), season, kind="auto", note=note)


def list_snapshots(conn=None) -> list[dict]:
    own_connection = conn is None
    conn = conn or get_connection()
    try:
        ensure_snapshot_tables(conn)
        rows = conn.execute(
            """SELECT snapshot_label, season, taken_at, kind, note, row_counts
               FROM snapshot_manifest ORDER BY taken_at DESC"""
        ).fetchall()
        return [
            {**dict(row),
             "row_counts": json.loads(row["row_counts"] or "{}")}
            for row in rows
        ]
    finally:
        if own_connection:
            conn.close()


def load_snapshot(label: str, conn=None) -> list[dict]:
    """The ranking rows preserved under `label`, best-first."""
    own_connection = conn is None
    conn = conn or get_connection()
    try:
        ensure_snapshot_tables(conn)
        rows = conn.execute(
            """SELECT * FROM ranking_snapshots WHERE snapshot_label = ?
               ORDER BY overall_rank""",
            (label,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        if own_connection:
            conn.close()


def prune_auto_snapshots(older_than_days: int = DEFAULT_PRUNE_AFTER_DAYS,
                         today: date | None = None, conn=None) -> list[str]:
    """Drop automatic snapshots past their useful life.

    Named labels are never pruned: a `preseason-2027` snapshot has to survive
    until the 2027 retrospective, which is the whole point.
    """
    own_connection = conn is None
    conn = conn or get_connection()
    try:
        ensure_snapshot_tables(conn)
        today = today or date.today()
        removed = []
        for row in conn.execute(
            "SELECT snapshot_label, taken_at FROM snapshot_manifest WHERE kind = 'auto'"
        ).fetchall():
            label = row["snapshot_label"]
            if not is_auto(label):
                continue
            try:
                taken = datetime.fromisoformat(row["taken_at"]).date()
            except (TypeError, ValueError):
                continue
            if (today - taken).days > older_than_days:
                removed.append(label)

        for label in removed:
            conn.execute("DELETE FROM ranking_snapshots WHERE snapshot_label = ?",
                         (label,))
            conn.execute("DELETE FROM projection_snapshots WHERE snapshot_label = ?",
                         (label,))
            conn.execute("DELETE FROM snapshot_manifest WHERE snapshot_label = ?",
                         (label,))
        conn.commit()
        return removed
    finally:
        if own_connection:
            conn.close()
