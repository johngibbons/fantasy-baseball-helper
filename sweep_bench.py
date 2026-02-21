"""Sweep PITCHER_BENCH_CONTRIBUTION to find optimal bench pitcher config.

Usage:
    python3 sweep_bench.py --seed 42
    python3 sweep_bench.py --sims 500 --seed 42   # higher-confidence run
"""

from __future__ import annotations

import argparse
import random
import sys
import time

from backend.simulation.config import SimConfig
from backend.simulation.draft_engine import simulate_draft
from backend.simulation.evaluate import evaluate_draft
from backend.simulation.player_pool import load_players
from backend.simulation.report import print_report

SWEEP_VALUES = [0.25, 0.35, 0.45, 0.55, 0.65]
HITTER_BENCH_CONTRIBUTION = 0.20


def run_sweep(num_sims: int, seed: int | None) -> None:
    players = load_players()
    if not players:
        print("ERROR: No players found in database. Run data sync first.")
        sys.exit(1)

    num_teams = 10
    sims_per_slot = num_sims // num_teams

    all_sweep_results: list[tuple[float, list[dict]]] = []

    for pitcher_bc in SWEEP_VALUES:
        config = SimConfig(
            PITCHER_BENCH_CONTRIBUTION=pitcher_bc,
            HITTER_BENCH_CONTRIBUTION=HITTER_BENCH_CONTRIBUTION,
        )

        results: list[dict] = []
        rng = random.Random(seed)
        t0 = time.time()

        for slot in range(num_teams):
            for _ in range(sims_per_slot):
                draft = simulate_draft(players, slot, config, rng)
                ev = evaluate_draft(draft, num_teams)
                ev["my_slot"] = slot
                results.append(ev)

        elapsed = time.time() - t0
        label = f"P_BC={pitcher_bc:.2f}, H_BC={HITTER_BENCH_CONTRIBUTION:.2f}"
        print_report(results, num_sims, sims_per_slot, num_teams, seed, config_label=label)
        print(f"  ({elapsed:.1f}s)")
        all_sweep_results.append((pitcher_bc, results))

    # Summary comparison table
    print("\n" + "=" * 72)
    print(f"{'SWEEP SUMMARY':^72}")
    print("=" * 72)
    print(f"  {'P_BC':>6}  {'Wins/Wk':>8}  {'StdDev':>7}  {'Bench P':>8}  {'Pitchers':>9}  {'Hitters':>8}")
    print("-" * 72)

    best_val = None
    best_wins = float("-inf")

    for pitcher_bc, results in all_sweep_results:
        wins = [r["expected_wins"] for r in results]
        mean_wins = sum(wins) / len(wins)
        variance = sum((w - mean_wins) ** 2 for w in wins) / len(wins)
        std_wins = variance ** 0.5

        bench_p = [r.get("bench_pitcher_count", 0) for r in results]
        avg_bench_p = sum(bench_p) / len(bench_p) if bench_p else 0

        pitchers = [r["pitcher_count"] for r in results]
        avg_pitchers = sum(pitchers) / len(pitchers) if pitchers else 0

        hitters = [r["hitter_count"] for r in results]
        avg_hitters = sum(hitters) / len(hitters) if hitters else 0

        marker = ""
        if mean_wins > best_wins:
            best_wins = mean_wins
            best_val = pitcher_bc

        print(f"  {pitcher_bc:>6.2f}  {mean_wins:>8.3f}  {std_wins:>7.3f}  {avg_bench_p:>8.1f}  {avg_pitchers:>9.1f}  {avg_hitters:>8.1f}")

    print("-" * 72)
    print(f"  Best: P_BC={best_val:.2f} -> {best_wins:.3f} wins/week")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Sweep bench pitcher contribution rates")
    parser.add_argument("--sims", type=int, default=200, help="Total sims (distributed across slots)")
    parser.add_argument("--seed", type=int, default=None, help="RNG seed for reproducibility")
    args = parser.parse_args()

    run_sweep(args.sims, args.seed)


if __name__ == "__main__":
    main()
