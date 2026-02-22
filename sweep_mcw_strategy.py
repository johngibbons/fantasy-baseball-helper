"""Sweep MCW strategy weights (lock/target) to find optimal configuration.

Tests whether discounting MCW for locked categories and boosting MCW for
target categories improves draft outcomes.

Usage:
    python3 sweep_mcw_strategy.py --seed 42
    python3 sweep_mcw_strategy.py --sims 500 --seed 42
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

# Sweep configurations: (lock_weight, target_weight, label)
SWEEP_CONFIGS = [
    (1.0, 1.0, "baseline"),
    (0.5, 1.0, "lock=0.5 only"),
    (1.0, 1.25, "target=1.25 only"),
    (0.5, 1.25, "lock=0.5, target=1.25"),
    (0.25, 1.5, "lock=0.25, target=1.5"),
    (0.0, 1.25, "lock=0, target=1.25"),
]


def run_sweep(num_sims: int, seed: int | None) -> None:
    players = load_players()
    if not players:
        print("ERROR: No players found in database. Run data sync first.")
        sys.exit(1)

    num_teams = 10
    sims_per_slot = num_sims // num_teams

    all_sweep_results: list[tuple[str, float, float, list[dict]]] = []

    for lock_w, target_w, label in SWEEP_CONFIGS:
        config = SimConfig(
            LOCK_MCW_WEIGHT=lock_w,
            TARGET_MCW_WEIGHT=target_w,
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
        config_label = f"lock={lock_w:.2f}, target={target_w:.2f}"
        print_report(results, num_sims, sims_per_slot, num_teams, seed, config_label=config_label)
        print(f"  ({elapsed:.1f}s)")
        all_sweep_results.append((label, lock_w, target_w, results))

    # Summary comparison table
    print("\n" + "=" * 80)
    print(f"{'MCW STRATEGY WEIGHT SWEEP':^80}")
    print("=" * 80)
    print(f"  {'Config':<38}  {'Wins/Wk':>8}  {'StdDev':>7}  {'Min Cat':>8}  {'Max Cat':>8}")
    print("-" * 80)

    best_label = None
    best_wins = float("-inf")

    for label, lock_w, target_w, results in all_sweep_results:
        wins = [r["expected_wins"] for r in results]
        mean_wins = sum(wins) / len(wins)
        variance = sum((w - mean_wins) ** 2 for w in wins) / len(wins)
        std_wins = variance ** 0.5

        # Find weakest and strongest average category win rates
        cat_avgs: dict[str, float] = {}
        for cat_key in results[0]["cat_win_probs"]:
            cat_vals = [r["cat_win_probs"][cat_key] for r in results]
            cat_avgs[cat_key] = sum(cat_vals) / len(cat_vals)

        min_cat = min(cat_avgs.values())
        max_cat = max(cat_avgs.values())

        if mean_wins > best_wins:
            best_wins = mean_wins
            best_label = label

        print(f"  {label:<38}  {mean_wins:>8.3f}  {std_wins:>7.3f}  {min_cat:>8.2f}  {max_cat:>8.2f}")

    print("-" * 80)
    print(f"  Best: {best_label} -> {best_wins:.3f} wins/week")
    print()

    # Detailed category breakdown for top 3 configs
    all_sweep_results.sort(key=lambda x: sum(r["expected_wins"] for r in x[3]) / len(x[3]), reverse=True)
    print("Per-category win rates (top 3 configs):")
    print(f"  {'Config':<38}  {'R':>5} {'TB':>5} {'RBI':>5} {'SB':>5} {'OBP':>5} {'K':>5} {'QS':>5} {'ERA':>5} {'WHIP':>5} {'SVHD':>5}")
    print("-" * 100)
    cat_order = ["zscore_r", "zscore_tb", "zscore_rbi", "zscore_sb", "zscore_obp",
                 "zscore_k", "zscore_qs", "zscore_era", "zscore_whip", "zscore_svhd"]
    for label, lock_w, target_w, results in all_sweep_results[:3]:
        cats = []
        for cat_key in cat_order:
            cat_vals = [r["cat_win_probs"][cat_key] for r in results]
            cats.append(f"{sum(cat_vals) / len(cat_vals):>5.2f}")
        print(f"  {label:<38}  {' '.join(cats)}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Sweep MCW strategy weights")
    parser.add_argument("--sims", type=int, default=200, help="Total sims (distributed across slots)")
    parser.add_argument("--seed", type=int, default=None, help="RNG seed for reproducibility")
    args = parser.parse_args()

    run_sweep(args.sims, args.seed)


if __name__ == "__main__":
    main()
