"""Sweep SP/RP composition targets to find optimal pitcher split.

Usage:
    python3 sweep_composition.py --seed 42
    python3 sweep_composition.py --sims 500 --seed 42   # higher-confidence run
"""

from __future__ import annotations

import argparse
import math
import random
import sys
import time

from backend.simulation.config import SimConfig
from backend.simulation.draft_engine import simulate_draft
from backend.simulation.evaluate import evaluate_draft
from backend.simulation.player_pool import load_players, ALL_CAT_KEYS, CAT_LABELS
from backend.simulation.report import print_report

# (label, TARGET_SP, TARGET_RP)
CONFIGS: list[tuple[str, int | None, int | None]] = [
    ("unconstrained", None, None),
    ("5SP-4RP", 5, 4),
    ("4SP-5RP", 4, 5),
    ("5SP-5RP", 5, 5),
    ("6SP-4RP", 6, 4),
    ("4SP-6RP", 4, 6),
    ("6SP-5RP", 6, 5),
    ("7SP-4RP", 7, 4),
    ("5SP-6RP", 5, 6),
    ("7SP-5RP", 7, 5),
    ("6SP-6RP", 6, 6),
    ("8SP-4RP", 8, 4),
]


def run_config(
    label: str,
    target_sp: int | None,
    target_rp: int | None,
    players: list,
    num_sims: int,
    seed: int | None,
    num_teams: int,
) -> list[dict]:
    config = SimConfig(TARGET_SP=target_sp, TARGET_RP=target_rp)
    sims_per_slot = num_sims // num_teams
    results: list[dict] = []
    rng = random.Random(seed)

    for slot in range(num_teams):
        for _ in range(sims_per_slot):
            draft = simulate_draft(players, slot, config, rng)
            ev = evaluate_draft(draft, num_teams)
            ev["my_slot"] = slot
            results.append(ev)

    return results


def run_sweep(num_sims: int, seed: int | None) -> None:
    players = load_players()
    if not players:
        print("ERROR: No players found in database. Run data sync first.")
        sys.exit(1)

    num_teams = 10
    sims_per_slot = num_sims // num_teams

    all_results: list[tuple[str, int | None, int | None, list[dict], float]] = []

    for label, target_sp, target_rp in CONFIGS:
        t0 = time.time()
        results = run_config(label, target_sp, target_rp, players, num_sims, seed, num_teams)
        elapsed = time.time() - t0

        print_report(results, num_sims, sims_per_slot, num_teams, seed, config_label=label)
        print(f"  ({elapsed:.1f}s)")
        all_results.append((label, target_sp, target_rp, results, elapsed))

    # Summary table
    print("\n" + "=" * 88)
    print(f"{'COMPOSITION SWEEP SUMMARY':^88}")
    print("=" * 88)
    print(f"  {'Config':<15} {'Wins/Wk':>8} {'StdDev':>7} {'SP':>5} {'RP':>5} {'Hitters':>8} {'Bench P':>8}")
    print("-" * 88)

    ranked: list[tuple[str, float, float, float, float, float, float, list[dict]]] = []

    for label, target_sp, target_rp, results, _ in all_results:
        wins = [r["expected_wins"] for r in results]
        mean_wins = sum(wins) / len(wins)
        variance = sum((w - mean_wins) ** 2 for w in wins) / len(wins)
        std_wins = math.sqrt(variance)

        sp = [r.get("sp_count", 0) for r in results]
        rp = [r.get("rp_count", 0) for r in results]
        hitters = [r["hitter_count"] for r in results]
        bench_p = [r.get("bench_pitcher_count", 0) for r in results]

        avg_sp = sum(sp) / len(sp)
        avg_rp = sum(rp) / len(rp)
        avg_hitters = sum(hitters) / len(hitters)
        avg_bench_p = sum(bench_p) / len(bench_p)

        ranked.append((label, mean_wins, std_wins, avg_sp, avg_rp, avg_hitters, avg_bench_p, results))

    # Sort by wins descending
    ranked.sort(key=lambda x: x[1], reverse=True)

    for label, mean_wins, std_wins, avg_sp, avg_rp, avg_hitters, avg_bench_p, _ in ranked:
        print(f"  {label:<15} {mean_wins:>8.3f} {std_wins:>7.3f} {avg_sp:>5.1f} {avg_rp:>5.1f} {avg_hitters:>8.1f} {avg_bench_p:>8.1f}")

    print("-" * 88)
    best = ranked[0]
    print(f"  Best: {best[0]} -> {best[1]:.3f} wins/week")

    # Per-category win rates for top 3
    print(f"\n{'PER-CATEGORY WIN RATES (Top 3 Configs)':^88}")
    print("=" * 88)

    # Header
    cat_header = "  " + f"{'Config':<15}"
    for cat_key in ALL_CAT_KEYS:
        cat_label = CAT_LABELS.get(cat_key, cat_key)
        cat_header += f" {cat_label:>6}"
    print(cat_header)
    print("-" * 88)

    for label, mean_wins, _, _, _, _, _, results in ranked[:3]:
        cat_avgs: dict[str, float] = {}
        for cat_key in ALL_CAT_KEYS:
            vals = [r["cat_win_probs"][cat_key] for r in results]
            cat_avgs[cat_key] = sum(vals) / len(vals)

        line = f"  {label:<15}"
        for cat_key in ALL_CAT_KEYS:
            line += f"  .{int(cat_avgs[cat_key] * 100):02d} "
        line += f"  ({mean_wins:.3f})"
        print(line)

    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Sweep SP/RP composition targets")
    parser.add_argument("--sims", type=int, default=200, help="Total sims (distributed across slots)")
    parser.add_argument("--seed", type=int, default=None, help="RNG seed for reproducibility")
    args = parser.parse_args()

    run_sweep(args.sims, args.seed)


if __name__ == "__main__":
    main()
