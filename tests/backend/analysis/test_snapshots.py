"""Tests for board snapshots — the mechanism that makes the 2027 retrospective
possible without reconstructing anything."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest

from backend.analysis import snapshots as snap


@pytest.fixture
def conn():
    """An in-memory database with the two source tables the snapshots copy."""
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(f"""
        CREATE TABLE rankings (
            {snap._column_definitions(snap._RANKING_COLUMNS,
                                      snap._INTEGER_COLUMNS, snap._TEXT_COLUMNS)}
        )
    """)
    connection.execute(f"""
        CREATE TABLE projections (
            {snap._column_definitions(snap._PROJECTION_COLUMNS,
                                      snap._INTEGER_COLUMNS, snap._TEXT_COLUMNS)}
        )
    """)
    for i in range(1, 6):
        connection.execute(
            "INSERT INTO rankings (mlb_id, season, overall_rank, total_zscore, "
            "player_type) VALUES (?, ?, ?, ?, ?)",
            (i, 2026, i, 10.0 - i, "hitter"))
        connection.execute(
            "INSERT INTO projections (mlb_id, source, season, player_type, proj_pa) "
            "VALUES (?, ?, ?, ?, ?)",
            (i, "atc", 2026, "hitter", 600))
    connection.commit()
    yield connection
    connection.close()


class TestCreateSnapshot:
    def test_copies_the_current_board(self, conn):
        result = snap.create_snapshot("preseason-2026", 2026, conn=conn)
        assert result["created"] is True
        assert result["row_counts"] == {"rankings": 5, "projections": 5}

    def test_is_idempotent(self, conn):
        snap.create_snapshot("preseason-2026", 2026, conn=conn)
        again = snap.create_snapshot("preseason-2026", 2026, conn=conn)
        assert again["created"] is False
        assert len(snap.load_snapshot("preseason-2026", conn=conn)) == 5

    def test_snapshot_survives_the_source_being_overwritten(self, conn):
        """The whole point: the board is preserved when the refresh lands."""
        snap.create_snapshot("preseason-2026", 2026, conn=conn)
        conn.execute("UPDATE rankings SET total_zscore = 0, proj_pa = 45")
        conn.commit()

        preserved = snap.load_snapshot("preseason-2026", conn=conn)
        assert [row["total_zscore"] for row in preserved] == [9.0, 8.0, 7.0, 6.0, 5.0]

    def test_only_the_requested_season_is_copied(self, conn):
        conn.execute(
            "INSERT INTO rankings (mlb_id, season, overall_rank, total_zscore) "
            "VALUES (?, ?, ?, ?)", (99, 2025, 1, 5.0))
        conn.commit()
        result = snap.create_snapshot("s", 2026, conn=conn)
        assert result["row_counts"]["rankings"] == 5

    def test_rows_come_back_in_rank_order(self, conn):
        snap.create_snapshot("s", 2026, conn=conn)
        ranks = [row["overall_rank"] for row in snap.load_snapshot("s", conn=conn)]
        assert ranks == sorted(ranks)


class TestLabels:
    def test_auto_labels_are_dated_and_recognisable(self):
        label = snap.auto_label(date(2026, 8, 15))
        assert label == "auto-2026-08-15"
        assert snap.is_auto(label)

    def test_named_labels_are_not_auto(self):
        assert not snap.is_auto("preseason-2027")


class TestListing:
    def test_lists_newest_first_with_counts(self, conn):
        snap.create_snapshot("first", 2026, conn=conn)
        snap.create_snapshot("second", 2026, note="later", conn=conn)
        listed = snap.list_snapshots(conn=conn)
        assert {s["snapshot_label"] for s in listed} == {"first", "second"}
        assert listed[0]["row_counts"]["rankings"] == 5

    def test_missing_snapshot_loads_as_empty(self, conn):
        assert snap.load_snapshot("nope", conn=conn) == []


class TestPruning:
    def _dated_snapshot(self, conn, label, days_ago, kind="auto"):
        snap.create_snapshot(label, 2026, kind=kind, conn=conn)
        taken = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
        conn.execute("UPDATE snapshot_manifest SET taken_at = ? "
                     "WHERE snapshot_label = ?", (taken, label))
        conn.commit()

    def test_old_automatic_snapshots_are_removed(self, conn):
        self._dated_snapshot(conn, "auto-old", days_ago=500)
        removed = snap.prune_auto_snapshots(older_than_days=400, conn=conn)
        assert removed == ["auto-old"]
        assert snap.load_snapshot("auto-old", conn=conn) == []

    def test_recent_automatic_snapshots_are_kept(self, conn):
        self._dated_snapshot(conn, "auto-recent", days_ago=10)
        assert snap.prune_auto_snapshots(older_than_days=400, conn=conn) == []

    def test_named_snapshots_are_never_pruned(self, conn):
        """A preseason label has to survive until the next retrospective."""
        self._dated_snapshot(conn, "preseason-2020", days_ago=2000, kind="manual")
        assert snap.prune_auto_snapshots(older_than_days=400, conn=conn) == []
        assert len(snap.load_snapshot("preseason-2020", conn=conn)) == 5

    def test_a_full_season_survives_the_default_window(self, conn):
        """400 days keeps a February board alive through the following winter."""
        self._dated_snapshot(conn, "auto-lastfeb", days_ago=380)
        assert snap.prune_auto_snapshots(conn=conn) == []


class TestSchema:
    def test_key_columns_keep_their_types(self):
        definitions = snap._column_definitions(
            snap._RANKING_COLUMNS, snap._INTEGER_COLUMNS, snap._TEXT_COLUMNS)
        assert "mlb_id INTEGER" in definitions
        assert "season INTEGER" in definitions
        assert "player_type TEXT" in definitions
        assert "total_zscore REAL" in definitions

    def test_projection_source_column_is_text(self):
        definitions = snap._column_definitions(
            snap._PROJECTION_COLUMNS, snap._INTEGER_COLUMNS, snap._TEXT_COLUMNS)
        assert "source TEXT" in definitions
