"""Phase 6 guard: a regenerated projection must never see its own season.

The plan calls this out as the trap that ruins everything, and the reason it is
dangerous is that it does not look like a bug. Regenerating 2022 projections
from 2022 statistics produces a spectacular backtest, and every intermediate
artifact looks entirely normal — good correlations, sensible-looking players,
nothing to catch a reviewer's eye. So it is tested rather than reviewed.

The test is deliberately **behavioural**, not a check on SQL strings: generate
projections for a season with later seasons present in the database, generate
them again with those seasons deleted, and require the two to be identical. Any
path by which future data reaches the projection changes the answer, including
paths added later that no string-matching test would know to look for.
"""

from __future__ import annotations

import sqlite3

import pytest

from backend import database
from backend.data.projections import generate_projections_from_stats

TARGET_SEASON = 2020
PRIOR_SEASONS = (2017, 2018, 2019)
FUTURE_SEASONS = (2020, 2021, 2022)


def _seed_player(conn, mlb_id: int, name: str, player_type: str,
                 position: str, is_active: int, seasons) -> None:
    conn.execute(
        """INSERT INTO players (mlb_id, full_name, first_name, last_name,
               primary_position, player_type, is_active, birth_date, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, '2026-01-01')""",
        (mlb_id, name, name.split()[0], name.split()[-1], position,
         player_type, is_active, "1995-05-05"))

    for season in seasons:
        # Values vary by season so that reading the wrong season is visible.
        scale = 1 + (season - 2017)
        if player_type == "hitter":
            conn.execute(
                """INSERT INTO batting_stats (mlb_id, season, games,
                       plate_appearances, at_bats, runs, hits, doubles, triples,
                       home_runs, rbi, stolen_bases, caught_stealing, walks,
                       strikeouts, hit_by_pitch, sac_flies, batting_average,
                       obp, slg, ops, total_bases)
                   VALUES (?, ?, 150, ?, ?, ?, ?, 25, 2, ?, ?, ?, 3, ?, ?, 4, 4,
                           0.270, 0.340, 0.450, 0.790, ?)""",
                (mlb_id, season, 600 * scale, 540 * scale, 80 * scale,
                 145 * scale, 20 * scale, 75 * scale, 10 * scale, 55 * scale,
                 120 * scale, 240 * scale))
        else:
            conn.execute(
                """INSERT INTO pitching_stats (mlb_id, season, games,
                       games_started, wins, losses, era, whip, innings_pitched,
                       hits_allowed, runs_allowed, earned_runs, walks_allowed,
                       strikeouts, home_runs_allowed, saves, holds,
                       quality_starts)
                   VALUES (?, ?, 30, 30, ?, 8, 3.50, 1.15, ?, ?, ?, ?, ?, ?,
                           18, 0, 0, ?)""",
                (mlb_id, season, 12 * scale, 180.0 * scale, 160 * scale,
                 75 * scale, 70 * scale, 50 * scale, 200 * scale, 18 * scale))


@pytest.fixture()
def seeded_db(tmp_path, monkeypatch):
    """A throwaway database, seeded on demand with the seasons a test wants."""

    def build(seasons, is_active: int = 1):
        path = tmp_path / f"scoping_{'_'.join(map(str, seasons))}_{is_active}.db"
        monkeypatch.setattr(database, "_SQLITE_PATH", path)
        database.init_db()
        conn = database.get_connection()
        _seed_player(conn, 1001, "Testy Hitter", "hitter", "OF", is_active, seasons)
        _seed_player(conn, 1002, "Testy Pitcher", "pitcher", "SP", is_active, seasons)
        conn.commit()
        conn.close()
        return path

    return build


def _projections(path) -> list[tuple]:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT mlb_id, player_type, proj_pa, proj_runs, proj_total_bases,
                  proj_rbi, proj_stolen_bases, proj_ip, proj_pitcher_strikeouts,
                  proj_quality_starts
           FROM projections WHERE season = ? ORDER BY mlb_id""",
        (TARGET_SEASON,)).fetchall()
    conn.close()
    return [tuple(r) for r in rows]


def test_future_seasons_do_not_change_the_projection(seeded_db):
    """The load-bearing test.

    Same target season, same prior stats; the only difference is whether the
    database also holds the target season and the two after it. If any of that
    reaches the projection, these two runs disagree.
    """
    prior_only = seeded_db(PRIOR_SEASONS)
    generate_projections_from_stats(TARGET_SEASON)
    scoped = _projections(prior_only)

    with_future = seeded_db(PRIOR_SEASONS + FUTURE_SEASONS)
    generate_projections_from_stats(TARGET_SEASON)
    contaminated = _projections(with_future)

    assert scoped, "no projections were generated at all — the test is not testing"
    assert scoped == contaminated, (
        "projections for {season} changed when {future} were present in the "
        "database: the generator is reading its own season or later".format(
            season=TARGET_SEASON, future=list(FUTURE_SEASONS)))


def test_a_projection_is_actually_produced(seeded_db):
    """Guards the guard: a test that silently produces nothing always passes."""
    path = seeded_db(PRIOR_SEASONS)
    generate_projections_from_stats(TARGET_SEASON)
    rows = _projections(path)

    assert len(rows) == 2
    assert {r[1] for r in rows} == {"hitter", "pitcher"}
    assert all(any(v for v in r[2:]) for r in rows)


def test_retired_players_are_not_silently_dropped(seeded_db):
    """Selection on today's roster is lookahead of a subtler kind.

    A 2018 backtest run over only players still active in 2026 is a backtest
    over players who turned out to have long careers. That is the same
    survivorship bias Phase 1 fought when it stopped resolving old names
    against a current-roster table, and it biases every result optimistically.
    """
    path = seeded_db(PRIOR_SEASONS, is_active=0)
    generate_projections_from_stats(TARGET_SEASON, active_only=False)
    rows = _projections(path)

    assert len(rows) == 2, (
        "players inactive today produced no projection for a historical "
        "season — the backtest would silently exclude everyone who retired"
    )
