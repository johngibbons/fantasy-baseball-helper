"""Ex-post SGP: value what players actually did, on the draft board's scale.

The idea: feed realized 2026 stats through the same valuation engine that
produced the draft board, so "what a player was worth" and "what we thought a
player was worth" are the same unit (standings gain points) and can be
subtracted. No new valuation math is introduced — backend/analysis/zscores.py
does the work; this module only reshapes actuals into the rows it expects.

Two things must be handled or the comparison is meaningless:

1. The playing-time discount must be OFF for ex-post values. FULL_CREDIT_PA
   discounts *uncertainty about future* playing time. Once the season has
   happened there is no uncertainty — a short season is already fully expressed
   in the raw counting totals. Applying it again would double-count and
   systematically under-value injured players, who are exactly the population
   the retrospective needs to measure.

2. Both boards must be valued over the same player pool. Replacement levels,
   league OBP/ERA/WHIP, and the rate-stat marginal denominators are all
   pool-relative, so a preseason board covering 1,300 players and an ex-post
   board covering everyone who took a plate appearance are not on the same
   scale. Callers align the pool (see backend/scripts/retro_expost.py) and
   zero-fill anyone who never played.

Pure functions only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

# MLB regular season bounds; mirrors SEASON_START/SEASON_END in
# src/app/api/performance/route.ts so August and September runs agree.
SEASON_START = date(2026, 3, 25)
SEASON_END = date(2026, 9, 27)

EXPOST_SOURCE = "actual"


def season_elapsed_fraction(
    as_of: date,
    start: date = SEASON_START,
    end: date = SEASON_END,
) -> float:
    """Fraction of the regular season completed, clamped to [0, 1]."""
    season_days = (end - start).days
    if season_days <= 0:
        return 0.0
    elapsed = (as_of - start).days
    elapsed = max(0, min(season_days, elapsed))
    return elapsed / season_days


@dataclass(frozen=True)
class PlayerIdentity:
    """The player columns the valuation engine reads alongside the stats."""

    mlb_id: int
    full_name: str
    primary_position: str
    team: str | None = None
    eligible_positions: str | None = None


def _num(value, default=0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def batting_actuals_to_row(identity: PlayerIdentity, stats: dict | None) -> dict:
    """Shape a batting_stats row like a hitter projection row.

    `stats` of None means the player never appeared — a real outcome for a
    drafted player, and one that must stay in the pool at zero rather than
    being dropped, or replacement level would be computed over survivors only.
    """
    stats = stats or {}
    return {
        "mlb_id": identity.mlb_id,
        "full_name": identity.full_name,
        "primary_position": identity.primary_position,
        "team": identity.team,
        "eligible_positions": identity.eligible_positions,
        "proj_pa": _num(stats.get("plate_appearances")),
        "proj_runs": _num(stats.get("runs")),
        "proj_total_bases": _num(stats.get("total_bases")),
        "proj_rbi": _num(stats.get("rbi")),
        "proj_stolen_bases": _num(stats.get("stolen_bases")),
        "proj_obp": _num(stats.get("obp")),
        # Components: the engine derives pool league OBP from these, so they
        # must be the realized ones rather than a projection's.
        "proj_hits": _num(stats.get("hits")),
        "proj_walks": _num(stats.get("walks")),
        "proj_hbp": _num(stats.get("hit_by_pitch")),
        "proj_sac_flies": _num(stats.get("sac_flies")),
        "proj_at_bats": _num(stats.get("at_bats")),
    }


def pitching_actuals_to_row(identity: PlayerIdentity, stats: dict | None) -> dict:
    """Shape a pitching_stats row like a pitcher projection row."""
    stats = stats or {}
    return {
        "mlb_id": identity.mlb_id,
        "full_name": identity.full_name,
        "primary_position": identity.primary_position,
        "team": identity.team,
        "proj_ip": _num(stats.get("innings_pitched")),
        "proj_pitcher_strikeouts": _num(stats.get("strikeouts")),
        "proj_quality_starts": _num(stats.get("quality_starts")),
        "proj_era": _num(stats.get("era")),
        "proj_whip": _num(stats.get("whip")),
        "proj_saves": _num(stats.get("saves")),
        "proj_holds": _num(stats.get("holds")),
        # Components for pool league ERA/WHIP.
        "proj_hits_allowed": _num(stats.get("hits_allowed")),
        "proj_walks_allowed": _num(stats.get("walks_allowed")),
        "proj_earned_runs": _num(stats.get("earned_runs")),
    }


def align_pool(rows: list[dict], universe: set[int],
               identities: dict[int, PlayerIdentity],
               builder) -> list[dict]:
    """Restrict rows to `universe` and zero-fill every missing member.

    Guarantees the returned pool is exactly `universe`, which is what makes two
    boards comparable. `builder` is batting_actuals_to_row or
    pitching_actuals_to_row.
    """
    by_id = {row["mlb_id"]: row for row in rows if row["mlb_id"] in universe}
    for mlb_id in universe:
        if mlb_id not in by_id:
            identity = identities.get(mlb_id)
            if identity is None:
                continue
            by_id[mlb_id] = builder(identity, None)
    return [by_id[mlb_id] for mlb_id in sorted(by_id)]


def attrition_report(
    preseason_rows: list[dict],
    expost_rows: list[dict],
    volume_key: str,
) -> list[dict]:
    """Projected vs. realized playing time, the retrospective's likeliest
    single explanatory variable for valuation error."""
    projected = {r["mlb_id"]: _num(r.get(volume_key)) for r in preseason_rows}
    actual = {r["mlb_id"]: _num(r.get(volume_key)) for r in expost_rows}
    names = {r["mlb_id"]: r.get("full_name") for r in preseason_rows}

    out = []
    for mlb_id, proj in projected.items():
        act = actual.get(mlb_id, 0.0)
        out.append({
            "mlb_id": mlb_id,
            "name": names.get(mlb_id),
            "projected": round(proj, 1),
            "actual": round(act, 1),
            "delta": round(act - proj, 1),
            "ratio": round(act / proj, 3) if proj > 0 else None,
            "never_played": act == 0,
        })
    out.sort(key=lambda r: r["delta"])
    return out
