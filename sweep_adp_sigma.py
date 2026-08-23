"""Re-open the variable-ADP-sigma question with the measured coefficients.

Usage:
    .venv/bin/python sweep_adp_sigma.py --sims 200 --seed 42
    .venv/bin/python sweep_adp_sigma.py --sims 1000 --seed 42   # tighter

SCORING_IMPROVEMENTS.md section 6 tested `sigma = 10 + 0.1 * ADP` against the
fixed 18 and rejected it: 8.77 wins against 8.89 over 200 sims. That rejection
stands on its own terms, but it tested one formula, and the multi-season
backtest since measured the actual residual spread:

    2026 alone:   sigma = 6.55  + 0.158 * ADP
    2017-2025:    sigma = 11.13 + 0.161 * ADP

Two independent measurements agreeing on a slope of ~0.16 -- roughly **sixty
percent steeper** than the 0.1 that was tested. At ADP 150 the shipped formula
says 25 picks of spread where the data says 35. So the rejected experiment used
a model of ADP noise now known to be wrong, and the question deserves re-asking
with the right coefficients rather than the flag simply being flipped.

What this measures is deliberately *not* the same thing the backtest measured.
The backtest showed the availability model is miscalibrated. This asks whether
fixing that calibration produces better drafts, which is a different question
and can perfectly well come back negative: a draft engine can be robust to a
badly calibrated input, and sigma feeds only availability weighting and the
opponent model.
"""

from __future__ import annotations

import argparse
import random
import statistics
import sys
import time

from backend.simulation.config import SimConfig
from backend.simulation.draft_engine import simulate_draft
from backend.simulation.evaluate import compute_streaming_zscores, evaluate_draft
from backend.simulation.player_pool import load_players

# (label, USE_VARIABLE_SIGMA, intercept, slope)
CANDIDATES = [
    ("fixed 18 (shipped)", False, 0.0, 0.0),
    ("10 + 0.100*adp (rejected in SI section 6)", True, 10.0, 0.1),
    ("11.13 + 0.161*adp (measured 2017-2025)", True, 11.13, 0.161),
    ("6.55 + 0.158*adp (measured 2026)", True, 6.55, 0.158),
]


def run(num_sims: int, seed: int | None) -> None:
    players = load_players()
    if not players:
        print("ERROR: No players found in database. Run data sync first.")
        sys.exit(1)

    num_teams = 10
    sims_per_slot = max(1, num_sims // num_teams)
    num_teams_arg = num_teams

    results: list[tuple[str, list[float]]] = []
    for label, use_variable, intercept, slope in CANDIDATES:
        config = SimConfig(
            USE_VARIABLE_SIGMA=use_variable,
            **({"ADP_SIGMA_INTERCEPT": intercept, "ADP_SIGMA_SLOPE": slope}
               if use_variable else {}),
        )
        streaming = compute_streaming_zscores(players, config)
        wins: list[float] = []
        started = time.time()
        # Every candidate sees the identical sequence of drafts: same seed, same
        # slot order. Without that, the difference between two candidates is
        # swamped by which drafts each happened to get.
        for slot in range(num_teams):
            for sim in range(sims_per_slot):
                rng = random.Random(
                    None if seed is None else seed + slot * 1000 + sim)
                draft = simulate_draft(players, slot, config, rng)
                evaluation = evaluate_draft(draft, num_teams_arg, config=config,
                                            streaming_zscores=streaming)
                wins.append(evaluation["expected_wins"])
        results.append((label, wins))
        print(f"  {label:44} mean={statistics.mean(wins):6.3f} "
              f"({time.time() - started:5.1f}s)")

    print(f"\n{len(results[0][1])} drafts per candidate, seed={seed}\n")
    print(f"  {'candidate':44} {'wins':>7} {'sd':>6} {'se':>6} {'vs shipped':>11}")
    baseline = statistics.mean(results[0][1])
    for label, wins in results:
        mean = statistics.mean(wins)
        sd = statistics.stdev(wins) if len(wins) > 1 else 0.0
        se = sd / (len(wins) ** 0.5)
        # Paired difference: same seeds, so compare draft by draft.
        paired = [a - b for a, b in zip(wins, results[0][1])]
        delta_se = (statistics.stdev(paired) / (len(paired) ** 0.5)
                    if len(paired) > 1 and any(paired) else 0.0)
        verdict = ""
        if label != results[0][0]:
            delta = mean - baseline
            verdict = f"{delta:+.3f}"
            if delta_se:
                verdict += (" *" if abs(delta) > 1.96 * delta_se else "  ns")
        print(f"  {label:44} {mean:>7.3f} {sd:>6.3f} {se:>6.3f} {verdict:>11}")

    print("\n  * = outside a 95% paired interval; ns = inside it, i.e. no effect.")
    print("  Paired on seed, so the comparison is draft-by-draft rather than "
          "mean-vs-mean.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sims", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    run(args.sims, args.seed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
