"""Phase 6: does the valuation engine over-disperse in every season?

Usage:
    .venv/bin/python -m backend.scripts.history_valuation
    .venv/bin/python -m backend.scripts.history_valuation --seasons 2024 2025

Requires Phases 0-2 and the full-pool backfill. Emits valuation_calibration.json.

The 2026 retrospective's largest measured effect was that the draft board
spreads players about 25% further apart than reality: regressing realized value
on projected value gave a calibration slope of 0.759 for hitters and 0.722 for
pitchers. It rested on one season. This runs the same regression on thirteen.

**What this measures, stated plainly, because it is easy to over-read.** No
archived preseason projections exist before 2026, so the projections here are
regenerated with `generate_projections_from_stats` -- the app's own weighted,
age-adjusted three-season average. In 2026 that model scored 0.639 rank
correlation for hitters against THE BAT X's 0.741. So a slope computed here is
**the trend model's calibration, not THE BAT X's**, and is not a clean
replication of the 2026 number. It is still worth having: it starts to separate
"the projections over-disperse" from "the SGP conversion over-disperses",
because if the slope is well below 1 for a completely different projection
source, the dispersion is coming from the valuation engine rather than from any
one forecaster.

Lookahead is the trap that ruins this phase, and it is guarded rather than
reviewed -- see tests/backend/analysis/test_projection_scoping.py. Projections
are generated with `active_only=False` so the player universe is not restricted
to today's roster, which would be survivorship bias of the same kind.

Seasons start at 2013: projecting season S reads S-1 through S-3, and the
full-pool stat backfill starts at 2010.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from backend.analysis.history.boards import (
    ALL_CATS,
    PITCHER_POSITIONS,
    load_identities,
    season_board,
)
from backend.analysis.retro.valuation import accuracy_summary
from backend.analysis.zscores import (
    ValuationConfig,
    _compute_sgp_denominators,
    compute_hitter_sgp,
    compute_pitcher_sgp,
)
from backend.data.projections import generate_projections_from_stats
from backend.database import get_connection

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HISTORY_DIR = REPO_ROOT / "backend" / "data" / "fixtures" / "league_history"

# Projecting season S reads S-1..S-3; the full-pool backfill begins at 2010.
FIRST_SEASON = 2013
# 2026 is excluded by default. Its `trend` projections are already in the table
# and feed the Layer D source comparison in RETROSPECTIVE_2026.md; regenerating
# them here (with a different player universe) would silently invalidate that
# artifact. 2026 is covered by the retrospective directly.
LAST_SEASON = 2025
SOURCE = "trend"

HITTER_COLS = """p.mlb_id, p.full_name, p.primary_position, p.team,
    p.eligible_positions, pr.proj_pa, pr.proj_runs, pr.proj_total_bases,
    pr.proj_rbi, pr.proj_stolen_bases, pr.proj_obp, pr.proj_hits, pr.proj_walks,
    pr.proj_hbp, pr.proj_sac_flies, pr.proj_at_bats"""
PITCHER_COLS = """p.mlb_id, p.full_name, p.primary_position, p.team,
    pr.proj_ip, pr.proj_pitcher_strikeouts, pr.proj_quality_starts, pr.proj_era,
    pr.proj_whip, pr.proj_saves, pr.proj_holds, pr.proj_hits_allowed,
    pr.proj_walks_allowed, pr.proj_earned_runs"""


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def load_projection_rows(conn, season: int, player_type: str) -> list[dict]:
    cols = HITTER_COLS if player_type == "hitter" else PITCHER_COLS
    return [dict(r) for r in conn.execute(
        f"""SELECT {cols} FROM projections pr JOIN players p ON pr.mlb_id = p.mlb_id
            WHERE pr.season = ? AND pr.source = ? AND pr.player_type = ?""",
        (season, SOURCE, player_type)).fetchall()]


def analyse_season(conn, season: int, denominators: dict[str, float],
                   regenerate: bool) -> dict | None:
    if regenerate:
        # active_only=False: restricting to today's roster would project a
        # historical season over only the players who turned out to last.
        generate_projections_from_stats(season, active_only=False)
        conn.close()
        conn = get_connection()

    hitters = load_projection_rows(conn, season, "hitter")
    pitchers = load_projection_rows(conn, season, "pitcher")
    if len(hitters) < 50 or len(pitchers) < 50:
        return None, conn

    # The pool is exactly the players the projection covers, so the preseason
    # and realized boards are built over an identical universe -- replacement
    # level and the rate-stat denominators are pool-relative.
    hitter_ids = {r["mlb_id"] for r in hitters}
    pitcher_ids = {r["mlb_id"] for r in pitchers}
    identities = load_identities(conn, hitter_ids | pitcher_ids)

    preseason_cfg = ValuationConfig(sgp_denominators=denominators)
    preseason_h = compute_hitter_sgp(hitters, config=preseason_cfg)
    preseason_p = compute_pitcher_sgp(pitchers, config=preseason_cfg)

    realized_h, realized_p = season_board(
        conn, season, hitter_ids, pitcher_ids, identities, denominators)

    return {
        "season": season,
        "pool": {"hitters": len(preseason_h), "pitchers": len(preseason_p)},
        "hitters": accuracy_summary(preseason_h, realized_h),
        "pitchers": accuracy_summary(preseason_p, realized_p),
    }, conn


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seasons", type=int, nargs="*", default=None)
    parser.add_argument("--no-regenerate", action="store_true",
                        help="reuse trend projections already in the table")
    args = parser.parse_args()

    report = json.loads((HISTORY_DIR / "resolution_report.json").read_text())
    seasons = args.seasons or [s for s in report["included_seasons"]
                               if FIRST_SEASON <= s <= LAST_SEASON]

    conn = get_connection()
    denominators = {k: round(v, 6)
                    for k, v in _compute_sgp_denominators(ALL_CATS).items()}

    per_season = []
    for season in seasons:
        print(f"  {season}  generating and valuing...", flush=True)
        result, conn = analyse_season(conn, season, denominators,
                                      not args.no_regenerate)
        if result is None:
            print(f"    too few projections, skipped")
            continue
        per_season.append(result)
        print(f"    hitters n={result['hitters']['n']:<5} "
              f"slope={result['hitters']['ols_slope']:.3f} "
              f"rho={result['hitters']['spearman']:.3f}   "
              f"pitchers n={result['pitchers']['n']:<5} "
              f"slope={result['pitchers']['ols_slope']:.3f} "
              f"rho={result['pitchers']['spearman']:.3f}")
    conn.close()

    if not per_season:
        raise SystemExit("no season produced a board")

    # 2020 was 60 games. Counting stats collapse, the sample per player is a
    # third of normal, and every calibration number moves several standard
    # deviations. Reported separately rather than dropped.
    SHORT_SEASON = 2020

    def summarise(pool: str, exclude_short: bool = False) -> dict:
        rows = [r for r in per_season
                if not (exclude_short and r["season"] == SHORT_SEASON)]
        slopes = [r[pool]["ols_slope"] for r in rows
                  if r[pool].get("ols_slope") is not None]
        rhos = [r[pool]["spearman"] for r in rows
                if r[pool].get("spearman") is not None]
        return {
            "seasons": len(slopes),
            "mean_slope": round(sum(slopes) / len(slopes), 4) if slopes else None,
            "min_slope": round(min(slopes), 4) if slopes else None,
            "max_slope": round(max(slopes), 4) if slopes else None,
            "seasons_below_one": sum(1 for s in slopes if s < 1),
            "mean_spearman": round(sum(rhos) / len(rhos), 4) if rhos else None,
        }

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seasons": [r["season"] for r in per_season],
        "projection_source": SOURCE,
        "caveat": (
            "These are the TREND model's calibration slopes, not THE BAT X's. "
            "No archived preseason projections exist before 2026, so "
            "projections are regenerated from the app's own three-season "
            "weighted average, which scored 0.639 rank correlation for hitters "
            "in 2026 against THE BAT X's 0.741. Not a clean replication of the "
            "2026 slope of 0.759/0.722 and must never be reported as one."),
        "hitters": summarise("hitters"),
        "pitchers": summarise("pitchers"),
        "hitters_excluding_2020": summarise("hitters", exclude_short=True),
        "pitchers_excluding_2020": summarise("pitchers", exclude_short=True),
        "by_season": per_season,
    }
    _write_json(HISTORY_DIR / "valuation_calibration.json", payload)

    print(f"\nCalibration slope (realized regressed on projected; "
          f"<1 means the board over-disperses)\n")
    print(f"  {'season':>7} {'H slope':>9} {'H rho':>7} {'P slope':>9} {'P rho':>7}")
    for r in per_season:
        print(f"  {r['season']:>7} {r['hitters']['ols_slope']:>9.3f} "
              f"{r['hitters']['spearman']:>7.3f} "
              f"{r['pitchers']['ols_slope']:>9.3f} "
              f"{r['pitchers']['spearman']:>7.3f}")
    for pool in ("hitters", "pitchers"):
        for key, label in ((pool, "all seasons"),
                           (f"{pool}_excluding_2020", "excluding 2020")):
            s = payload[key]
            print(f"\n  {pool:9} ({label:14}): mean slope {s['mean_slope']:.3f} "
                  f"(range {s['min_slope']:.3f}-{s['max_slope']:.3f}), "
                  f"{s['seasons_below_one']}/{s['seasons']} below 1, "
                  f"mean rho {s['mean_spearman']:.3f}")
    print(f"\n  2026 (THE BAT X, different model): hitters 0.759, pitchers 0.722")
    print(f"\nWritten to {HISTORY_DIR / 'valuation_calibration.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
