"""Phase 4: the value-at-pick curve across every season.

Usage:
    .venv/bin/python -m backend.scripts.history_value_curve

Requires Phases 0-2. Emits value_curve_analysis.json.

Answers whether `expectedValueAtRound` in src/app/keepers/page.tsx -- which
assumes round R is worth the player ranked R x 10, and which every keeper
surplus the app shows depends on -- is stable enough across seasons to be
replaced with a fitted empirical curve.

The curve used throughout excludes keepers, for the same reason Phase 3
excludes them: keepers occupy the rounds they cost, so a curve including them
partly describes the players being measured against it.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

from backend.analysis.history.boards import (
    ALL_CATS,
    PITCHER_POSITIONS,
    full_pool,
    load_identities,
    season_board,
    value_map,
)
from backend.analysis.history.keeper_backtest import pick_index_for_round
from backend.analysis.history.value_curve import (
    concentration,
    fit_shapes,
    pooled_curve,
    rank_linear_prediction,
    season_correlations,
    stability,
)
from backend.analysis.retro.keeper_eval import NUM_TEAMS, value_at_pick_curve
from backend.analysis.zscores import _compute_sgp_denominators
from backend.database import get_connection

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HISTORY_DIR = REPO_ROOT / "backend" / "data" / "fixtures" / "league_history"
ROSTER_CACHE = HISTORY_DIR / "_rosters"


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def _load(path: Path):
    return json.loads(path.read_text()) if path.exists() else None


def roster_positions(season: int) -> dict[int, str]:
    positions: dict[int, str] = {}
    for delta in (0, -1, 1):
        cache = ROSTER_CACHE / f"players_{season + delta}.json"
        if cache.exists():
            for person in json.loads(cache.read_text()):
                positions.setdefault(person["mlb_id"],
                                     person.get("primary_position") or "")
    return positions


def analyse_season(conn, season: int, denominators: dict[str, float]) -> dict | None:
    draft = _load(HISTORY_DIR / f"drafts_{season}.json")
    resolution = _load(HISTORY_DIR / f"resolution_{season}.json")
    keepers_payload = _load(HISTORY_DIR / f"keepers_{season}.json")
    if not draft or not resolution:
        return None

    ids = {r["name"]: r["mlb_id"] for r in resolution["resolutions"]
           if r["mlb_id"] is not None}
    positions = roster_positions(season)
    picks = [dict(p, mlb_id=ids.get(p["player_name"])) for p in draft["picks"]]
    resolved = [p for p in picks if p["mlb_id"] is not None]
    universe = {p["mlb_id"] for p in resolved}
    if not universe:
        return None

    # The board is built over the FULL pool of players who could have been
    # rostered, not just the 250 drafted. Replacement level and the value of
    # "the player ranked Nth" are both meaningless over the narrow pool: rank
    # 250 there is the worst player alive, where on the app's ~1,350-player
    # board it is a mid-tier regular.
    pool_hitters, pool_pitchers = full_pool(conn, season, universe)
    identities = load_identities(conn, pool_hitters | pool_pitchers)
    hitter_board, pitcher_board = season_board(
        conn, season, pool_hitters, pool_pitchers, identities, denominators)
    realized = value_map(hitter_board, pitcher_board)

    keeper_ids = set()
    if keepers_payload:
        keeper_ids = {ids.get(k["player_name"]) for k in keepers_payload["keepers"]}
        keeper_ids.discard(None)

    def is_keeper(pick: dict) -> bool:
        return (pick["mlb_id"] in keeper_ids
                or "keeper" in (pick.get("notes") or "").lower())

    open_picks = [p for p in resolved if not is_keeper(p)]
    rows, by_round_values = [], {}
    for pick in open_picks:
        index = pick_index_for_round(pick.get("round"))
        if index is None:
            continue
        value = realized.get(pick["mlb_id"], 0.0)
        rows.append({"pick_index": index, "board_value": 0.0,
                     "realized_value": value})
        by_round_values.setdefault(pick["round"], []).append(value)

    curve = value_at_pick_curve(rows)

    # Spread of individual picks inside a round -- the noise the curve sits in.
    within_sd = {r: statistics.stdev(v) for r, v in by_round_values.items()
                 if len(v) > 1}

    # The app's assumption, evaluated on this season's realized board.
    sorted_board = sorted(realized.values(), reverse=True)
    assumption = []
    for entry in curve:
        predicted = rank_linear_prediction(entry["round"], sorted_board)
        if predicted is None:
            continue
        assumption.append({
            "round": entry["round"],
            "rank_linear": round(predicted, 3),
            "actual": entry["mean_realized_value"],
            "error": round(predicted - entry["mean_realized_value"], 3),
        })

    return {
        "season": season,
        "picks": len(resolved),
        "non_keeper_picks": len(open_picks),
        "pool": len(pool_hitters) + len(pool_pitchers),
        "pool_hitters": len(pool_hitters),
        "pool_pitchers": len(pool_pitchers),
        "drafted": len(universe),
        "curve": curve,
        "within_round_sd": {str(k): round(v, 3) for k, v in sorted(within_sd.items())},
        "rank_linear_vs_actual": assumption,
        "concentration": concentration(list(realized.values()), NUM_TEAMS * 25),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seasons", type=int, nargs="*", default=None)
    args = parser.parse_args()

    report = _load(HISTORY_DIR / "resolution_report.json")
    seasons = args.seasons or report["included_seasons"]

    conn = get_connection()
    denominators = {k: round(v, 6)
                    for k, v in _compute_sgp_denominators(ALL_CATS).items()}

    per_season = []
    for season in seasons:
        result = analyse_season(conn, season, denominators)
        if result is None:
            continue
        per_season.append(result)
        print(f"  {season}  pool {result['pool']:>4} "
              f"({result['pool_hitters']}H/{result['pool_pitchers']}P), "
              f"{result['non_keeper_picks']:>3} non-keeper picks")
    conn.close()

    curves = {r["season"]: r["curve"] for r in per_season}
    within = {}
    for result in per_season:
        for round_str, sd in result["within_round_sd"].items():
            within.setdefault(int(round_str), []).append(sd)
    mean_within = {r: sum(v) / len(v) for r, v in within.items()}

    pooled = pooled_curve(curves)
    stability_summary = stability(curves, mean_within)
    correlations = season_correlations(curves)
    shapes = fit_shapes([r["round"] for r in pooled], [r["mean"] for r in pooled])

    # How wrong the rank-linear assumption is, pooled over every season.
    errors_by_round: dict[int, list[float]] = {}
    for result in per_season:
        for row in result["rank_linear_vs_actual"]:
            errors_by_round.setdefault(row["round"], []).append(row["error"])
    assumption_error = [{
        "round": r,
        "seasons": len(v),
        "mean_error": round(sum(v) / len(v), 3),
        "sd": round(statistics.stdev(v), 3) if len(v) > 1 else None,
    } for r, v in sorted(errors_by_round.items()) if len(v) >= 5]

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seasons": [r["season"] for r in per_season],
        "sgp_denominators": denominators,
        "method": {
            "curve": "mean realized SGP per round, EXCLUDING keepers",
            "rank_linear": "expectedValueAtRound's assumption (value of the "
                           "player ranked round x 10) evaluated on the same "
                           "season's REALIZED board -- a test of the shape, "
                           "not a measurement of the app's projected values",
            "pool": "each season's own resolved draftees",
        },
        "pooled_curve": pooled,
        "stability": stability_summary,
        "season_correlations": correlations,
        "shape_fits": shapes,
        "rank_linear_error_by_round": assumption_error,
        "by_season": per_season,
    }
    _write_json(HISTORY_DIR / "value_curve_analysis.json", payload)

    print(f"\nPooled curve over {len(per_season)} seasons "
          f"({len(pooled)} rounds with >=5 seasons)\n")
    print(f"  {'rd':>3} {'mean':>7} {'sd':>6} {'min':>7} {'max':>7} "
          f"{'rank-linear err':>16}")
    err = {e["round"]: e for e in assumption_error}
    for row in pooled:
        e = err.get(row["round"], {})
        print(f"  {row['round']:>3} {row['mean']:>7.2f} "
              f"{row['sd_across_seasons']:>6.2f} {row['min']:>7.2f} "
              f"{row['max']:>7.2f} {e.get('mean_error', float('nan')):>16.2f}")

    print(f"\nStability:")
    print(f"  between-season sd, mean over rounds: "
          f"{stability_summary['mean_between_season_sd']:.2f} SGP "
          f"(worst round {stability_summary['worst_round']}: "
          f"{stability_summary['max_between_season_sd']:.2f})")
    if "mean_within_round_sd" in stability_summary:
        print(f"  within-round sd, mean over rounds:  "
              f"{stability_summary['mean_within_round_sd']:.2f} SGP")
        print(f"  ratio between/within: "
              f"{stability_summary['between_over_within']:.2f}"
              f"  ({'stable' if stability_summary['between_over_within'] < 1 else 'unstable'})")
    print(f"  season-pair shape correlation: mean "
          f"{correlations['mean_spearman']:+.2f} "
          f"(range {correlations['min_spearman']:+.2f} to "
          f"{correlations['max_spearman']:+.2f})")

    if "fits" in shapes:
        print(f"\nShape fits (RMSE against the pooled curve):")
        for name, fit in sorted(shapes["fits"].items(), key=lambda kv: kv[1]["rmse"]):
            print(f"  {name:>12}  {fit['rmse']:.3f}"
                  + (f"   {fit['formula']}" if "formula" in fit else ""))
        print(f"  best: {shapes['best']}, spread {shapes['rmse_spread']:.3f}"
              f" -> shapes {'are' if shapes['shapes_separable'] else 'are NOT'}"
              f" separable")

    print(f"\nWritten to {HISTORY_DIR / 'value_curve_analysis.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
