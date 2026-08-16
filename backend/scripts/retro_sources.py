"""Layer D: score each projection source against realized value.

Usage:
    python3 -m backend.scripts.retro_sources --season 2026

Emits projection_source_accuracy.json: rank correlation with realized SGP for
each source and for blends, plus the rate-versus-playing-time split that says
whether swapping sources is worth anything at all.

Every source is valued over the same intersection of players with the same
pinned SGP denominators, so the only thing varying is the projection.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from backend.analysis.retro.sources import (
    blend_values,
    common_player_ids,
    coverage_report,
    rate_accuracy,
    volume_accuracy,
)
from backend.analysis.retro.valuation import (
    bootstrap_delta_spearman_ci,
    paired_series,
    ranked_ids,
    spearman,
    top_n_precision,
)
from backend.analysis.zscores import (
    ValuationConfig,
    compute_hitter_sgp,
    compute_pitcher_sgp,
)
from backend.database import get_connection
from backend.scripts.retro_expost import load_projection_rows

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Sources carrying full-season 2026 projections. 'atc' is excluded: it holds
# rest-of-season values now, so it cannot be compared to a preseason board.
SOURCES = ("thebatx", "steamer", "zips", "trend", "statcast_adjusted")

MIN_PA_FOR_RATE = 200
MIN_IP_FOR_RATE = 40


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def score(values: dict[int, float], realized: list[dict]) -> dict:
    """Rank accuracy of one value map against the realized board."""
    board = [{"mlb_id": mlb_id, "total_zscore": value}
             for mlb_id, value in values.items()]
    realized_subset = [r for r in realized if r["mlb_id"] in values]
    ids, projected, actual = paired_series(board, realized_subset)
    if len(ids) < 2:
        return {"n": len(ids)}
    return {
        "n": len(ids),
        "spearman": spearman(projected, actual),
        "top_25": top_n_precision(ranked_ids(board), ranked_ids(realized_subset), 25),
        "top_100": top_n_precision(ranked_ids(board), ranked_ids(realized_subset), 100),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--dir", type=Path, default=None)
    args = parser.parse_args()

    out_dir = args.dir or (REPO_ROOT / "backend" / "data" / "fixtures"
                           / f"retro_{args.season}")
    preseason = json.loads((out_dir / "preseason_board.json").read_text())
    paced = out_dir / "expost_values_paced.json"
    expost = json.loads((paced if paced.exists()
                         else out_dir / "expost_values.json").read_text())
    denoms = preseason["sgp_denominators"]

    conn = get_connection()
    hitters = {s: load_projection_rows(conn, args.season, s, "hitter")
               for s in SOURCES}
    pitchers = {s: load_projection_rows(conn, args.season, s, "pitcher")
                for s in SOURCES}
    conn.close()

    hitters = {s: rows for s, rows in hitters.items() if rows}
    pitchers = {s: rows for s, rows in pitchers.items() if rows}

    results = {}
    for pool_name, rows_by_source, compute, volume_key, rate_key, min_volume in (
        ("hitters", hitters, compute_hitter_sgp, "proj_pa", "proj_obp", MIN_PA_FOR_RATE),
        ("pitchers", pitchers, compute_pitcher_sgp, "proj_ip", "proj_era", MIN_IP_FOR_RATE),
    ):
        realized_board = expost[pool_name]
        realized_ids = {r["mlb_id"] for r in realized_board}
        common = common_player_ids(rows_by_source) & realized_ids
        if len(common) < 20:
            results[pool_name] = {"error": f"only {len(common)} shared players"}
            continue

        config = ValuationConfig(sgp_denominators=denoms)
        value_maps = {}
        for source, rows in rows_by_source.items():
            restricted = [r for r in rows if r["mlb_id"] in common]
            valued = compute(restricted, config=config)
            value_maps[source] = {r["mlb_id"]: float(r["total_zscore"])
                                  for r in valued}

        # The realized board already carries raw stat columns under the same
        # names the projection rows use, so it doubles as the actuals here.
        actual_rows = realized_board
        if not any(r.get(rate_key) for r in actual_rows):
            raise SystemExit(
                f"Realized board has no {rate_key}; regenerate the boards with "
                f"retro_expost.py so the rate split has something to compare."
            )

        per_source = {}
        for source in value_maps:
            restricted = [r for r in rows_by_source[source]
                          if r["mlb_id"] in common]
            per_source[source] = {
                "value_accuracy": score(value_maps[source], realized_board),
                "volume_accuracy": volume_accuracy(
                    restricted, actual_rows, volume_key),
                "rate_accuracy": rate_accuracy(
                    restricted, actual_rows, rate_key, volume_key, min_volume),
            }

        blends = {
            "blend_all": score(blend_values(value_maps), realized_board),
            "blend_fangraphs": score(
                blend_values({s: v for s, v in value_maps.items()
                              if s in ("thebatx", "steamer", "zips")}),
                realized_board),
        }

        # One season of ~600 players cannot separate sources a few thousandths
        # apart. Compare each against the leader with a paired bootstrap so the
        # ranking is not read as more precise than it is.
        candidates = {**value_maps,
                      "blend_all": blend_values(value_maps)}
        best_source = max(
            per_source,
            key=lambda s: per_source[s]["value_accuracy"].get("spearman") or -1)
        realized_by_id = {r["mlb_id"]: float(r["total_zscore"])
                          for r in realized_board}
        leader = candidates[best_source]
        significance = {}
        for source, values in candidates.items():
            if source == best_source:
                continue
            shared = sorted(set(values) & set(leader) & set(realized_by_id))
            lo, hi = bootstrap_delta_spearman_ci(
                [values[i] for i in shared],
                [leader[i] for i in shared],
                [realized_by_id[i] for i in shared],
            )
            significance[source] = {
                "vs": best_source,
                "delta_spearman_ci": [lo, hi],
                "distinguishable": (None if lo is None
                                    else not (lo <= 0 <= hi)),
            }

        results[pool_name] = {
            "common_players": len(common),
            "coverage": coverage_report(rows_by_source, common),
            "sources": per_source,
            "blends": blends,
            "best_source": best_source,
            "significance_vs_best": significance,
        }

    header = {
        "as_of": expost["as_of"],
        "season": args.season,
        "season_elapsed_fraction": expost["season_elapsed_fraction"],
        "sgp_denominators": denoms,
        "note": ("All sources valued over the same player intersection with the "
                 "same denominators. 'atc' is excluded — it now holds "
                 "rest-of-season values, not preseason ones."),
    }
    _write_json(out_dir / "projection_source_accuracy.json", {**header, **results})

    # ── Console summary ──
    print(f"\nLayer D — projection sources vs realized value "
          f"({header['season_elapsed_fraction']:.0%} of season)\n")
    for pool_name in ("hitters", "pitchers"):
        pool = results.get(pool_name, {})
        if "error" in pool:
            print(f"{pool_name.upper()}: {pool['error']}")
            continue
        print(f"{pool_name.upper()}  (scored over {pool['common_players']} "
              f"players every source covers)")
        print(f"  {'source':<20} {'covers':>7} {'rho':>7} {'top25':>7} "
              f"{'vol r':>7} {'rate r':>7}")
        rows = []
        for source, value in pool["sources"].items():
            coverage = next(c["projected_players"] for c in pool["coverage"]
                            if c["source"] == source)
            rows.append((value["value_accuracy"].get("spearman") or 0, source,
                         coverage, value))
        for _, source, coverage, value in sorted(rows, reverse=True):
            accuracy = value["value_accuracy"]
            volume = value["volume_accuracy"].get("correlation")
            rate = value["rate_accuracy"].get("correlation")
            print(f"  {source:<20} {coverage:>7} "
                  f"{accuracy.get('spearman', 0):>7.3f} "
                  f"{accuracy.get('top_25') or 0:>7.2f} "
                  f"{(volume if volume is not None else 0):>7.3f} "
                  f"{(rate if rate is not None else 0):>7.3f}")
        for label, value in pool["blends"].items():
            print(f"  {label:<20} {'-':>7} {value.get('spearman', 0):>7.3f} "
                  f"{value.get('top_25') or 0:>7.2f}")
        best = pool["best_source"]
        indistinguishable = [s for s, v in pool["significance_vs_best"].items()
                             if v["distinguishable"] is False]
        print(f"  best: {best}; indistinguishable from it: "
              f"{', '.join(indistinguishable) or 'none'}")
        print()

    print(f"Artifacts written to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
