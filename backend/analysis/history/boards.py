"""Building realized-value boards for a historical season.

Shared by the keeper backtest (Phase 3) and the value-curve analysis
(Phase 4), which must value players identically or their numbers cannot be
compared. Every season runs through the same SGP engine that builds the live
draft board, with two deliberate differences documented in
backend/analysis/retro/expost.py: the playing-time discount is off, because
realized volume is a fact rather than a risk, and the streaming bonus is zero,
because the truth metric is pure production.

The one thing callers must get right is the **pool**. Replacement level, league
OBP/ERA/WHIP and the rate-stat denominators are all computed over whatever pool
is passed in, so two boards are comparable only over the same universe. A board
over 250 drafted players and a board over 1,300 rostered players put replacement
level in completely different places and their values must never be compared.
"""

from __future__ import annotations

from backend.analysis.retro.expost import (
    PlayerIdentity,
    align_pool,
    batting_actuals_to_row,
    pitching_actuals_to_row,
)
from backend.analysis.zscores import (
    PITCHER_CATEGORY_NORMALIZER,
    ValuationConfig,
    compute_hitter_sgp,
    compute_pitcher_sgp,
)

ALL_CATS = ["R", "TB", "RBI", "SB", "OBP", "K", "QS", "ERA", "WHIP", "SVHD"]
PITCHER_POSITIONS = {"P", "SP", "RP"}


def load_identities(conn, mlb_ids: set[int]) -> dict[int, PlayerIdentity]:
    """The player columns the valuation engine reads alongside the stats."""
    if not mlb_ids:
        return {}
    marks = ",".join("?" * len(mlb_ids))
    rows = conn.execute(
        f"""SELECT mlb_id, full_name, primary_position, team, eligible_positions
            FROM players WHERE mlb_id IN ({marks})""", tuple(mlb_ids)).fetchall()
    return {r["mlb_id"]: PlayerIdentity(
        mlb_id=r["mlb_id"], full_name=r["full_name"],
        primary_position=r["primary_position"], team=r["team"],
        eligible_positions=r["eligible_positions"]) for r in rows}


def load_actuals(conn, season: int, table: str) -> dict[int, dict]:
    return {r["mlb_id"]: dict(r) for r in conn.execute(
        f"SELECT * FROM {table} WHERE season = ?", (season,)).fetchall()}


def stat_coverage(conn, season: int, universe: set[int]) -> float:
    """Share of `universe` with a batting or pitching row in `season`."""
    if not universe:
        return 0.0
    marks = ",".join("?" * len(universe))
    found = {r[0] for r in conn.execute(
        f"SELECT mlb_id FROM batting_stats WHERE season = ? "
        f"AND mlb_id IN ({marks})", (season, *universe)).fetchall()}
    found |= {r[0] for r in conn.execute(
        f"SELECT mlb_id FROM pitching_stats WHERE season = ? "
        f"AND mlb_id IN ({marks})", (season, *universe)).fetchall()}
    return len(found & universe) / len(universe)


def full_pool(conn, season: int, extra: set[int] | None = None
              ) -> tuple[set[int], set[int]]:
    """Hitter and pitcher pools over everyone who recorded a season line.

    This is the pool the app's own board approximates — every player who could
    plausibly have been rostered — as opposed to the ~250 the league actually
    drafted. The distinction decides where replacement level sits, so any
    question phrased "how many players cleared replacement" or "what is the
    player ranked Nth worth" has to be asked over this pool, not the drafted one.

    The only filter is the pitcher/hitter split by primary position. Pitchers
    take plate appearances, and leaving them in the hitter pool would drag the
    pool's league OBP down and rescale every hitter's rate categories. No
    playing-time threshold is applied: position players number ~630 a season,
    close to the ~660 the shipped board carries, so a threshold would be a knob
    without a purpose.

    `extra` adds players who recorded no line at all — drafted players who
    missed the whole season. They belong in the pool at zero, not absent.
    """
    batting = {r[0] for r in conn.execute(
        "SELECT mlb_id FROM batting_stats WHERE season = ?", (season,)).fetchall()}
    pitching = {r[0] for r in conn.execute(
        "SELECT mlb_id FROM pitching_stats WHERE season = ?", (season,)).fetchall()}
    everyone = batting | pitching | (extra or set())
    if not everyone:
        return set(), set()

    marks = ",".join("?" * len(everyone))
    positions = {r[0]: (r[1] or "") for r in conn.execute(
        f"SELECT mlb_id, primary_position FROM players WHERE mlb_id IN ({marks})",
        tuple(everyone)).fetchall()}

    hitters = {i for i in everyone
               if positions.get(i, "") not in PITCHER_POSITIONS}
    # A pitcher is anyone classified as one who actually pitched, plus any
    # drafted pitcher who did not appear at all.
    pitchers = (everyone - hitters) & (pitching | (extra or set()))
    return hitters, pitchers


def season_board(conn, season: int, hitters: set[int], pitchers: set[int],
                 identities: dict[int, PlayerIdentity],
                 denominators: dict[str, float]) -> tuple[list[dict], list[dict]]:
    """Valued hitter and pitcher boards for one season's realized stats.

    Players who never appeared stay in the pool at zero rather than being
    dropped, which is what keeps a draft's busts inside its averages.
    """
    batting = load_actuals(conn, season, "batting_stats")
    pitching = load_actuals(conn, season, "pitching_stats")

    hitter_rows = align_pool(
        [batting_actuals_to_row(identities[i], batting.get(i))
         for i in sorted(hitters) if i in identities],
        hitters, identities, batting_actuals_to_row)
    pitcher_rows = align_pool(
        [pitching_actuals_to_row(identities[i], pitching.get(i))
         for i in sorted(pitchers) if i in identities],
        pitchers, identities, pitching_actuals_to_row)

    config = ValuationConfig(
        sgp_denominators=denominators,
        apply_playing_time_discount=False,
        streaming_bonus=0.0,
    )
    return (compute_hitter_sgp(hitter_rows, config=config),
            compute_pitcher_sgp(pitcher_rows, config=config))


def value_map(hitter_board: list[dict], pitcher_board: list[dict]
              ) -> dict[int, float]:
    """mlb_id -> SGP, with pitchers rescaled onto the hitters' scale.

    Mirrors `value_map` in backend/scripts/retro_keepers_adp.py; the two pools
    are valued separately and only the normalizer makes them one board.
    """
    values = {row["mlb_id"]: float(row["total_zscore"]) for row in hitter_board}
    for row in pitcher_board:
        values[row["mlb_id"]] = (float(row["total_zscore"])
                                 * PITCHER_CATEGORY_NORMALIZER)
    return values


def value_board(conn, season: int, hitters: set[int], pitchers: set[int],
                identities: dict[int, PlayerIdentity],
                denominators: dict[str, float]) -> dict[int, float]:
    """`season_board` collapsed to one mlb_id -> SGP mapping."""
    return value_map(*season_board(conn, season, hitters, pitchers,
                                   identities, denominators))
