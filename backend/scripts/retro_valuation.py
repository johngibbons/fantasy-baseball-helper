"""Layer A: how well did the valuation model predict realized value?

Usage:
    python3 -m backend.scripts.retro_valuation --season 2026

Requires the boards built by retro_expost.py. Emits:
  valuation_accuracy.json     — rank correlation, calibration, top-N, segments
  component_attribution.json  — exact per-category error decomposition
  ablations.json              — one assumption changed at a time, scored
                                against the fixed realized objective

The ablations rebuild the preseason board from the same February projection
rows, so every variant differs from the baseline in exactly one knob.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from backend.analysis.retro.attribution import (
    HITTER_CATEGORIES,
    PITCHER_CATEGORIES,
    attribute,
    run_ablations,
    streaming_bonus_check,
)
from backend.analysis.retro.valuation import (
    accuracy_summary,
    bootstrap_spearman_ci,
    paired_series,
    segment_bias,
)
from backend.analysis.zscores import (
    H2H_CATEGORY_WEIGHTS,
    PITCHER_CATEGORY_NORMALIZER,
    ValuationConfig,
    compute_hitter_sgp,
    compute_pitcher_sgp,
)
from backend.database import get_connection
from backend.scripts.retro_expost import (
    ALL_CATS,
    load_projection_rows,
    slim,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def _scaled_weights(scale: float) -> dict[str, float]:
    """Interpolate between equal weights (scale 0) and the shipped H2H
    correlation weights (scale 1); scale > 1 exaggerates them."""
    return {cat: 1.0 + (weight - 1.0) * scale
            for cat, weight in H2H_CATEGORY_WEIGHTS.items()}


def build_variants(hitter_rows, pitcher_rows, denoms) -> dict[str, dict]:
    """Preseason boards, each differing from the baseline in exactly one knob.

    Note which knobs can move which pool. The playing-time discount and the
    category weights touch both; the streaming bonus is starters-only; the
    pitcher normalizer changes nothing *within* a pool — it only rescales
    pitchers against hitters, so it is evaluated on the combined board instead
    (see build_combined_variants).
    """
    def cfg(**overrides):
        return ValuationConfig(sgp_denominators=denoms, **overrides)

    variants: dict[str, ValuationConfig] = {}

    # Category correlation weights: the comment block in zscores.py calls the
    # correlations behind these "approximate". Scale 0 = equal weights.
    for scale in (0.0, 0.5, 1.5):
        variants[f"category_weights_scale_{scale}"] = cfg(
            category_weights=_scaled_weights(scale))

    # The discount as a whole, then the thresholds with it left on. Keeping
    # these separate matters: turning the discount off changes both pools,
    # while moving FULL_CREDIT_PA only changes hitters.
    variants["no_playing_time_discount"] = cfg(apply_playing_time_discount=False)
    for pa in (300, 650):
        variants[f"full_credit_pa_{pa}"] = cfg(full_credit_pa=pa)
    for ip in (100, 180):
        variants[f"full_credit_ip_sp_{ip}"] = cfg(full_credit_ip_sp=ip)

    variants["streaming_bonus_0.0"] = cfg(streaming_bonus=0.0)
    variants["streaming_bonus_1.4"] = cfg(streaming_bonus=1.4)

    # Replacement level off entirely — the null hypothesis for position scarcity.
    variants["no_replacement"] = cfg(apply_replacement=False)

    boards = {}
    for label, config in variants.items():
        boards[label] = {
            "hitters": compute_hitter_sgp(hitter_rows, config=config),
            "pitchers": compute_pitcher_sgp(pitcher_rows, config=config),
        }
    return boards


def combined_board(hitters: list[dict], pitchers: list[dict],
                   normalizer: float) -> list[dict]:
    """One cross-position board, applying the pitcher category normalizer.

    Mirrors what calculate_all_zscores does after the two pools are valued:
    pitchers contribute to four categories against hitters' five, so their
    totals are scaled before the pools are ranked against each other. Within a
    pool the normalizer is a no-op, which is why it can only be measured here.
    """
    out = [dict(r) for r in hitters]
    for pitcher in pitchers:
        scaled = dict(pitcher)
        scaled["total_zscore"] = round(
            float(pitcher["total_zscore"]) * normalizer, 3)
        out.append(scaled)
    out.sort(key=lambda r: -r["total_zscore"])
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--source", default="thebatx")
    parser.add_argument("--dir", type=Path, default=None)
    args = parser.parse_args()

    out_dir = args.dir or (REPO_ROOT / "backend" / "data" / "fixtures"
                           / f"retro_{args.season}")
    preseason = json.loads((out_dir / "preseason_board.json").read_text())
    raw_expost = json.loads((out_dir / "expost_values.json").read_text())

    # Levels are compared on the pace-adjusted board. Counting-stat SGP scales
    # with playing time while rate-stat SGP does not, so a mid-season board
    # would otherwise show over-dispersion that is only the calendar. At season
    # end the two boards coincide.
    paced_path = out_dir / "expost_values_paced.json"
    expost = json.loads(paced_path.read_text()) if paced_path.exists() else raw_expost

    if preseason["sgp_denominators"] != expost["sgp_denominators"]:
        raise SystemExit("Boards were built with different SGP denominators; "
                         "they are not on the same scale.")
    denoms = preseason["sgp_denominators"]

    header = {
        "as_of": expost["as_of"],
        "season": expost["season"],
        "season_elapsed_fraction": expost["season_elapsed_fraction"],
        "preseason_source": preseason["preseason_source"],
        "sgp_denominators": denoms,
        "expost_board": "pace_adjusted" if paced_path.exists() else "raw",
    }

    # ── Accuracy ──
    accuracy = {
        "hitters": accuracy_summary(preseason["hitters"], expost["hitters"]),
        "pitchers": accuracy_summary(preseason["pitchers"], expost["pitchers"]),
    }
    # Keep the uncorrected numbers visible so the correction is auditable.
    accuracy["partial_season_uncorrected"] = {
        pool: {k: v for k, v in accuracy_summary(
            preseason[pool], raw_expost[pool]).items()
            if k in ("spearman", "ols_slope", "r_squared")}
        for pool in ("hitters", "pitchers")
    }

    def volume_bucket(row, key, edges):
        volume = row.get(key) or 0
        for edge, label in edges:
            if volume < edge:
                return label
        return edges[-1][1]

    accuracy["hitter_segments"] = {
        "by_slot": segment_bias(preseason["hitters"], expost["hitters"],
                                lambda r: r.get("primary_position")),
        "by_projected_pa": segment_bias(
            preseason["hitters"], expost["hitters"],
            lambda r: volume_bucket(r, "proj_pa", [
                (200, "0-199 PA"), (400, "200-399 PA"), (550, "400-549 PA"),
                (10_000, "550+ PA")])),
    }
    accuracy["pitcher_segments"] = {
        "by_projected_ip": segment_bias(
            preseason["pitchers"], expost["pitchers"],
            lambda r: volume_bucket(r, "proj_ip", [
                (60, "0-59 IP"), (120, "60-119 IP"), (170, "120-169 IP"),
                (10_000, "170+ IP")])),
    }
    _write_json(out_dir / "valuation_accuracy.json", {**header, **accuracy})

    # ── Attribution ──
    attribution = {
        "hitters": attribute(preseason["hitters"], expost["hitters"],
                             HITTER_CATEGORIES),
        "pitchers": attribute(preseason["pitchers"], expost["pitchers"],
                              PITCHER_CATEGORIES),
        "streaming_bonus": streaming_bonus_check(preseason["pitchers"],
                                                 expost["pitchers"]),
    }
    _write_json(out_dir / "component_attribution.json", {**header, **attribution})

    # ── Ablations ──
    conn = get_connection()
    hitter_rows = load_projection_rows(conn, args.season, args.source, "hitter")
    pitcher_rows = load_projection_rows(conn, args.season, args.source, "pitcher")
    conn.close()

    variant_boards = build_variants(hitter_rows, pitcher_rows, denoms)

    ablations = {}
    for pool in ("hitters", "pitchers"):
        _, projected, realized = paired_series(preseason[pool], expost[pool])
        ablations[pool] = {
            "baseline_spearman_ci": list(bootstrap_spearman_ci(projected, realized)),
            "results": run_ablations(
                preseason[pool], expost[pool],
                {label: slim(board[pool]) for label, board in variant_boards.items()},
            ),
        }

    # The pitcher normalizer only affects hitters-vs-pitchers ordering, so it is
    # measured on the combined board rather than within either pool.
    baseline_combined = combined_board(preseason["hitters"], preseason["pitchers"],
                                       PITCHER_CATEGORY_NORMALIZER)
    realized_combined = combined_board(expost["hitters"], expost["pitchers"], 1.0)
    normalizer_variants = {
        f"pitcher_normalizer_{n}": combined_board(
            preseason["hitters"], preseason["pitchers"], n)
        for n in (1.0, 1.1, 1.4, 1.6)
    }
    ablations["combined"] = {
        "note": ("Cross-position board. The realized side needs no normalizer — "
                 "it is the objective, not a ranking to be corrected."),
        "shipped_normalizer": PITCHER_CATEGORY_NORMALIZER,
        "results": run_ablations(baseline_combined, realized_combined,
                                 normalizer_variants),
    }
    _write_json(out_dir / "ablations.json", {**header, **ablations})

    # ── Console summary ──
    print(f"\nLayer A — valuation accuracy ({header['preseason_source']} preseason "
          f"vs. realized, {header['season_elapsed_fraction']:.0%} of season)\n")
    for pool in ("hitters", "pitchers"):
        summary = accuracy[pool]
        ci = summary["spearman_ci"]
        print(f"{pool.upper()}  n={summary['n']}")
        print(f"  Spearman      {summary['spearman']:.3f}  "
              f"(95% CI {ci[0]:.3f}–{ci[1]:.3f})")
        print(f"  Kendall tau   {summary['kendall_tau']:.3f}")
        print(f"  OLS slope     {summary['ols_slope']:.3f}   R²={summary['r_squared']:.3f}")
        precision = summary["top_n_precision"]
        print("  Top-N hit rate " + "  ".join(
            f"@{n}={precision[n]:.0%}" for n in ("25", "50", "100", "200")
            if precision.get(n) is not None))
        print()

    print("Per-category mean error (realized − projected SGP):")
    for pool, categories in (("hitters", HITTER_CATEGORIES),
                             ("pitchers", PITCHER_CATEGORIES)):
        means = attribution[pool]["mean_delta_by_category"]
        print(f"  {pool:9} " + "  ".join(
            f"{cat.replace('zscore_', '').upper()}={means[cat]:+.3f}"
            for cat in categories))
    print()

    print("Ablations — paired bootstrap on Δρ; 'ns' = interval contains zero:")
    for pool in ("hitters", "pitchers", "combined"):
        base = next(r for r in ablations[pool]["results"] if r["label"] == "baseline")
        print(f"  {pool} (baseline ρ={base['spearman']:.4f}):")
        for result in ablations[pool]["results"]:
            if result["label"] == "baseline" or result["delta_spearman"] is None:
                continue
            lo, hi = result["delta_spearman_ci"]
            flag = "ns" if result["inside_noise"] else "  "
            ci = f"[{lo:+.4f},{hi:+.4f}]" if lo is not None else "[n/a]"
            print(f"    {flag} {result['label']:<30} "
                  f"Δρ={result['delta_spearman']:+.4f} {ci:>20}  "
                  f"Δtop100={result['delta_top_100']:+.3f}")
    print(f"\nArtifacts written to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
