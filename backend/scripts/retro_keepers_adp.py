"""Layer C: ADP calibration, the value-at-pick curve, and keeper outcomes.

Usage:
    python3 -m backend.scripts.retro_keepers_adp --season 2026

Requires draft_decisions.json from retro_draft.py. Emits:
  adp_calibration.json    — residual spread by ADP band; which sigma model fits
  value_at_pick_curve.json — what each round actually returned
  keeper_analysis.json    — was each keeper worth its round cost
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from backend.analysis.retro.adp_model import (
    compare_sigma_models,
    compute_residuals,
    fit_linear_sigma,
    manager_bias,
    sigma_by_bucket,
    sigma_summary,
)
from backend.analysis.retro.keeper_eval import (
    compare_curve_to_assumption,
    evaluate_keepers,
    keeper_accuracy,
    value_at_pick_curve,
)
from backend.analysis.zscores import PITCHER_CATEGORY_NORMALIZER

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# ESPN team id -> manager, mirroring TEAM_MANAGER in src/lib/draft-history.ts.
TEAM_MANAGER = {
    1: "Jess Barron", 2: "Russell Berry", 3: "Tim Riker", 4: "Harris Cook",
    5: "Jason McComb", 6: "Matt Wayne", 7: "David Rotatori",
    8: "John Gibbons", 9: "Eric Mercado", 10: "Bryan Lewis",
}


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def value_map(board: dict, normalizer: float) -> dict[int, float]:
    values = {r["mlb_id"]: float(r["total_zscore"]) for r in board["hitters"]}
    for row in board["pitchers"]:
        values[row["mlb_id"]] = float(row["total_zscore"]) * normalizer
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--dir", type=Path, default=None)
    args = parser.parse_args()

    out_dir = args.dir or (REPO_ROOT / "backend" / "data" / "fixtures"
                           / f"retro_{args.season}")
    decisions = json.loads((out_dir / "draft_decisions.json").read_text())
    state = json.loads((out_dir / f"draft_state_{args.season}.json").read_text())
    adp_payload = json.loads(
        (out_dir / f"adp_draftday_{args.season}.json").read_text())
    preseason = json.loads((out_dir / "preseason_board.json").read_text())
    paced = out_dir / "expost_values_paced.json"
    expost = json.loads((paced if paced.exists()
                         else out_dir / "expost_values.json").read_text())

    adp = {int(k): v for k, v in adp_payload["adp_by_mlb_id"].items()}
    header = {
        "as_of": expost["as_of"],
        "season": args.season,
        "season_elapsed_fraction": expost["season_elapsed_fraction"],
    }

    # ── ADP calibration ──
    keeper_adps = [adp[k] for k in state["keeperMlbIds"] if k in adp]
    residuals = compute_residuals(decisions["picks"], adp, keeper_adps)
    buckets = sigma_by_bucket(residuals)
    summary = sigma_summary(residuals)
    sigma_models = compare_sigma_models(buckets)
    linear_fit = fit_linear_sigma(buckets)
    managers = manager_bias(residuals, TEAM_MANAGER)

    _write_json(out_dir / "adp_calibration.json", {
        **header,
        "keepers_with_adp": len(keeper_adps),
        "summary": summary,
        "by_adp_bucket": buckets,
        "sigma_model_comparison": sigma_models,
        "linear_sigma_fit": linear_fit,
        "manager_bias": managers,
        "residuals": [
            {"mlb_id": r.mlb_id, "name": r.name, "team_id": r.team_id,
             "pick": r.pick_number, "adp": r.adp,
             "effective_adp": round(r.effective_adp, 1),
             "residual": round(r.residual, 1)}
            for r in residuals
        ],
    })

    # ── Value at pick ──
    curve = value_at_pick_curve(decisions["picks"])
    board_sorted = sorted(
        preseason["hitters"] + preseason["pitchers"],
        key=lambda r: -float(r["total_zscore"]))
    assumption = compare_curve_to_assumption(curve, board_sorted)
    _write_json(out_dir / "value_at_pick_curve.json", {
        **header,
        "note": ("Assumed value is expectedValueAtRound in "
                 "src/app/keepers/page.tsx: the player ranked round x 10."),
        "curve": curve,
        "vs_assumption": assumption,
    })

    # ── Keepers ──
    board_value = value_map(preseason, PITCHER_CATEGORY_NORMALIZER)
    realized_value = value_map(expost, 1.0)
    names = {r["mlb_id"]: r.get("full_name")
             for r in preseason["hitters"] + preseason["pitchers"]}
    outcomes = evaluate_keepers(state["leagueKeepers"], board_value,
                                realized_value, curve, names)
    accuracy = keeper_accuracy(outcomes)
    _write_json(out_dir / "keeper_analysis.json", {
        **header, "accuracy": accuracy, "keepers": outcomes,
    })

    # ── Console summary ──
    print(f"\nLayer C — ADP and keepers ({summary['n']} picks with draft-day ADP)\n")
    print("Residual (actual pick - predicted pick):")
    print(f"  raw ADP            mean={summary['raw']['mean']:+7.2f}  "
          f"sigma={summary['raw']['sigma']:6.2f}")
    print(f"  keeper-adjusted    mean={summary['keeper_adjusted']['mean']:+7.2f}  "
          f"sigma={summary['keeper_adjusted']['sigma']:6.2f}")

    print("\nSpread by ADP band (tests whether sigma is constant):")
    print(f"  {'band':>10} {'n':>4} {'mean adp':>9} {'measured':>9} "
          f"{'flat 18':>8} {'var (ts)':>9} {'var (py)':>9}")
    for row in sigma_models["per_bucket"]:
        bucket = next(b for b in buckets if b["adp_bucket"] == row["adp_bucket"])
        print(f"  {row['adp_bucket']:>10} {bucket['n']:>4} "
              f"{bucket['mean_adp']:>9.1f} {row['measured_sigma']:>9.2f} "
              f"{row['flat_18']:>8.1f} {row['variable_ts']:>9.2f} "
              f"{row['variable_py']:>9.2f}")
    mae = sigma_models["mean_abs_error"]
    print("  mean abs error: " + "  ".join(
        f"{model}={value:.2f}" for model, value in mae.items())
        + f"   -> {sigma_models['best']} fits best")
    if linear_fit:
        print(f"  best linear fit: sigma = {linear_fit['intercept']:.2f} "
              f"+ {linear_fit['slope']:.4f} * adp")

    print("\nManager reach/wait (negative = drafts earlier than the field expects):")
    for row in sorted(managers, key=lambda m: m["mean_residual"]):
        print(f"  {row['manager'] or row['team_id']:<16} n={row['picks']:>3}  "
              f"mean={row['mean_residual']:+7.2f}  sigma={row['sigma']:6.2f}")

    print("\nValue at pick — assumed vs actual (SGP):")
    print(f"  {'round':>6} {'assumed':>9} {'board':>9} {'realized':>9} {'error':>9}")
    for row in assumption[:12]:
        print(f"  {row['round']:>6} {row['assumed_value']:>9.2f} "
              f"{row['actual_board_value']:>9.2f} "
              f"{row['actual_realized_value']:>9.2f} "
              f"{row['assumption_error_vs_board']:>+9.2f}")

    print(f"\nKeepers: {accuracy['n']} evaluated, "
          f"{accuracy['kept_and_worth_it']} beat their round's return")
    print(f"  sign agreement board vs reality: {accuracy['sign_agreement']:.0%}")
    print("  best:", ", ".join(
        f"{o['name']} ({o['realized_surplus']:+.1f})" for o in outcomes[:3]))
    print("  worst:", ", ".join(
        f"{o['name']} ({o['realized_surplus']:+.1f})" for o in outcomes[-3:]))
    print(f"\nArtifacts written to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
