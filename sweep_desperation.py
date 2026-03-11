"""Sweep desperation/balance parameters to fix pitching starvation.

Tests improvements that address the model's tendency to over-draft hitters
and under-draft pitchers, leading to dead-last K/QS categories.

Features tested:
1. Stronger desperation bonus (higher weight, wider threshold, uncapped)
2. Multi-category desperation multiplier (compound bonus for SPs helping K+QS+ERA+WHIP)
3. Category floor penalty (penalize picks that ignore dead categories)
4. Composition steering (TARGET_SP, MAX_HITTERS)
5. Best combinations

Usage:
    python3 sweep_desperation.py --seed 42
    python3 sweep_desperation.py --sims 500 --seed 42
    python3 sweep_desperation.py --sims 500 --seed 42 --keepers
"""

from __future__ import annotations

import argparse
import random
import sys
import time

from backend.simulation.config import SimConfig
from backend.simulation.draft_engine import simulate_draft
from backend.simulation.evaluate import evaluate_draft
from backend.simulation.player_pool import load_players, load_keepers
from backend.simulation.report import print_report

CAT_ORDER = [
    "zscore_r", "zscore_tb", "zscore_rbi", "zscore_sb", "zscore_obp",
    "zscore_k", "zscore_qs", "zscore_era", "zscore_whip", "zscore_svhd",
]
CAT_LABELS = ["R", "TB", "RBI", "SB", "OBP", "K", "QS", "ERA", "WHIP", "SVHD"]
PITCH_CATS = {"zscore_k", "zscore_qs", "zscore_era", "zscore_whip", "zscore_svhd"}

# ── Sweep configurations ──

SWEEP_CONFIGS: list[tuple[str, dict]] = [
    # Current best (unlimited desperation — the baseline to beat)
    ("current_best", dict(
        DESPERATION_WEIGHT=6.0, DESPERATION_THRESHOLD=0.35,
        DESPERATION_CAP=0.0, DESPERATION_MULTI_CAT=0.5,
    )),

    # --- Hard cap on total desperation bonus ---
    ("max=10", dict(
        DESPERATION_WEIGHT=6.0, DESPERATION_THRESHOLD=0.35,
        DESPERATION_CAP=0.0, DESPERATION_MULTI_CAT=0.5, DESPERATION_MAX=10.0,
    )),
    ("max=15", dict(
        DESPERATION_WEIGHT=6.0, DESPERATION_THRESHOLD=0.35,
        DESPERATION_CAP=0.0, DESPERATION_MULTI_CAT=0.5, DESPERATION_MAX=15.0,
    )),
    ("max=20", dict(
        DESPERATION_WEIGHT=6.0, DESPERATION_THRESHOLD=0.35,
        DESPERATION_CAP=0.0, DESPERATION_MULTI_CAT=0.5, DESPERATION_MAX=20.0,
    )),
    ("max=30", dict(
        DESPERATION_WEIGHT=6.0, DESPERATION_THRESHOLD=0.35,
        DESPERATION_CAP=0.0, DESPERATION_MULTI_CAT=0.5, DESPERATION_MAX=30.0,
    )),
    ("max=50", dict(
        DESPERATION_WEIGHT=6.0, DESPERATION_THRESHOLD=0.35,
        DESPERATION_CAP=0.0, DESPERATION_MULTI_CAT=0.5, DESPERATION_MAX=50.0,
    )),

    # --- Z-score cap per category (instead of total cap) ---
    ("zcap=1.0", dict(
        DESPERATION_WEIGHT=6.0, DESPERATION_THRESHOLD=0.35,
        DESPERATION_CAP=1.0, DESPERATION_MULTI_CAT=0.5,
    )),
    ("zcap=1.5", dict(
        DESPERATION_WEIGHT=6.0, DESPERATION_THRESHOLD=0.35,
        DESPERATION_CAP=1.5, DESPERATION_MULTI_CAT=0.5,
    )),
    ("zcap=2.0", dict(
        DESPERATION_WEIGHT=6.0, DESPERATION_THRESHOLD=0.35,
        DESPERATION_CAP=2.0, DESPERATION_MULTI_CAT=0.5,
    )),

    # --- Lower multi-cat (reduce the 3x multiplier) ---
    ("multi=0.25", dict(
        DESPERATION_WEIGHT=6.0, DESPERATION_THRESHOLD=0.35,
        DESPERATION_CAP=0.0, DESPERATION_MULTI_CAT=0.25,
    )),
    ("multi=0", dict(
        DESPERATION_WEIGHT=6.0, DESPERATION_THRESHOLD=0.35,
        DESPERATION_CAP=0.0, DESPERATION_MULTI_CAT=0.0,
    )),

    # --- Lower weight (keep multi-cat) ---
    ("wt=3", dict(
        DESPERATION_WEIGHT=3.0, DESPERATION_THRESHOLD=0.35,
        DESPERATION_CAP=0.0, DESPERATION_MULTI_CAT=0.5,
    )),
    ("wt=2", dict(
        DESPERATION_WEIGHT=2.0, DESPERATION_THRESHOLD=0.35,
        DESPERATION_CAP=0.0, DESPERATION_MULTI_CAT=0.5,
    )),

    # --- Best combos: hard cap + z-cap ---
    ("max=15,zcap=1.5", dict(
        DESPERATION_WEIGHT=6.0, DESPERATION_THRESHOLD=0.35,
        DESPERATION_CAP=1.5, DESPERATION_MULTI_CAT=0.5, DESPERATION_MAX=15.0,
    )),
    ("max=20,zcap=2.0", dict(
        DESPERATION_WEIGHT=6.0, DESPERATION_THRESHOLD=0.35,
        DESPERATION_CAP=2.0, DESPERATION_MULTI_CAT=0.5, DESPERATION_MAX=20.0,
    )),

    # --- Hard cap + lower multi ---
    ("max=15,multi=0.25", dict(
        DESPERATION_WEIGHT=6.0, DESPERATION_THRESHOLD=0.35,
        DESPERATION_CAP=0.0, DESPERATION_MULTI_CAT=0.25, DESPERATION_MAX=15.0,
    )),
    ("max=20,multi=0.25", dict(
        DESPERATION_WEIGHT=6.0, DESPERATION_THRESHOLD=0.35,
        DESPERATION_CAP=0.0, DESPERATION_MULTI_CAT=0.25, DESPERATION_MAX=20.0,
    )),
]


def run_config(
    label: str,
    overrides: dict,
    players: list,
    num_sims: int,
    seed: int | None,
    keepers=None,
) -> tuple[str, list[dict]]:
    config = SimConfig(**overrides)
    num_teams = config.NUM_TEAMS
    sims_per_slot = num_sims // num_teams

    results: list[dict] = []
    rng = random.Random(seed)

    for slot in range(num_teams):
        for _ in range(sims_per_slot):
            sim_seed = rng.randint(0, 2**31)
            sim_rng = random.Random(sim_seed)
            draft = simulate_draft(players, slot, config, sim_rng, keepers=keepers)
            ev = evaluate_draft(draft, num_teams)
            ev["my_slot"] = slot
            results.append(ev)

    return label, results


def analyze_results(results: list[dict]) -> dict:
    """Compute summary stats from simulation results."""
    wins = [r["expected_wins"] for r in results]
    mean_wins = sum(wins) / len(wins)
    variance = sum((w - mean_wins) ** 2 for w in wins) / len(wins)
    std_wins = variance ** 0.5

    cat_avgs: dict[str, float] = {}
    for cat_key in CAT_ORDER:
        cat_vals = [r["cat_win_probs"][cat_key] for r in results]
        cat_avgs[cat_key] = sum(cat_vals) / len(cat_vals)

    pitch_avg = sum(cat_avgs[c] for c in PITCH_CATS) / len(PITCH_CATS)
    hit_avg = sum(cat_avgs[c] for c in CAT_ORDER if c not in PITCH_CATS) / len([c for c in CAT_ORDER if c not in PITCH_CATS])
    min_cat = min(cat_avgs.values())
    min_cat_name = CAT_LABELS[CAT_ORDER.index(min(cat_avgs, key=cat_avgs.get))]

    hitter_counts = [r["hitter_count"] for r in results]
    pitcher_counts = [r["pitcher_count"] for r in results]
    sp_counts = [r.get("sp_count", 0) for r in results]

    return {
        "mean_wins": mean_wins,
        "std_wins": std_wins,
        "cat_avgs": cat_avgs,
        "pitch_avg": pitch_avg,
        "hit_avg": hit_avg,
        "min_cat": min_cat,
        "min_cat_name": min_cat_name,
        "avg_hitters": sum(hitter_counts) / len(hitter_counts),
        "avg_sp": sum(sp_counts) / len(sp_counts),
    }


def run_sweep(num_sims: int, seed: int | None, use_keepers: bool) -> None:
    players = load_players()
    if not players:
        print("ERROR: No players found. Run data sync first.")
        sys.exit(1)

    keepers = load_keepers() if use_keepers else None

    print(f"Loaded {len(players)} players" + (f", {len(keepers)} keepers" if keepers else ""))
    print(f"Running {len(SWEEP_CONFIGS)} configs x {num_sims} sims each (seed={seed})")
    print()

    all_results: list[tuple[str, list[dict], dict]] = []

    for i, (label, overrides) in enumerate(SWEEP_CONFIGS):
        t0 = time.time()
        print(f"[{i+1}/{len(SWEEP_CONFIGS)}] {label}...", end="", flush=True)
        _, results = run_config(label, overrides, players, num_sims, seed, keepers)
        stats = analyze_results(results)
        elapsed = time.time() - t0
        print(f" {stats['mean_wins']:.3f} wins/wk ({elapsed:.1f}s)")
        all_results.append((label, results, stats))

    # ── Summary table ──
    print()
    print("=" * 130)
    print(f"{'DESPERATION / BALANCE SWEEP':^130}")
    print("=" * 130)
    header = (
        f"  {'Config':<42} {'Wins':>6} {'Std':>5} {'HitWR':>6} {'PitWR':>6} "
        f"{'MinCat':>7} {'AvgH':>5} {'AvgSP':>5}  "
        + " ".join(f"{l:>5}" for l in CAT_LABELS)
    )
    print(header)
    print("-" * 130)

    # Sort by mean wins descending
    all_results.sort(key=lambda x: x[2]["mean_wins"], reverse=True)
    baseline_stats = next(s for l, _, s in all_results if l in ("baseline", "current_best"))

    for label, results, stats in all_results:
        delta = stats["mean_wins"] - baseline_stats["mean_wins"]
        delta_str = f"{'+'if delta>=0 else ''}{delta:.3f}"
        cat_strs = " ".join(f"{stats['cat_avgs'][c]:>5.2f}" for c in CAT_ORDER)
        marker = " ***" if label == "baseline" else ""
        print(
            f"  {label:<42} {stats['mean_wins']:>6.3f} {stats['std_wins']:>5.2f} "
            f"{stats['hit_avg']:>6.3f} {stats['pitch_avg']:>6.3f} "
            f"{stats['min_cat']:>5.2f}{stats['min_cat_name']:>2s} "
            f"{stats['avg_hitters']:>5.1f} {stats['avg_sp']:>5.1f}  "
            f"{cat_strs} ({delta_str}){marker}"
        )

    print("-" * 130)
    best = all_results[0]
    print(f"\n  Best: {best[0]} -> {best[2]['mean_wins']:.3f} wins/week")

    # ── Detailed comparison: baseline vs top 3 ──
    print(f"\n{'Per-Category Deltas vs Baseline (top 5)':^80}")
    print("-" * 80)
    print(f"  {'Config':<42} " + " ".join(f"{l:>6}" for l in CAT_LABELS))
    print("-" * 80)
    for label, results, stats in all_results[:5]:
        deltas = []
        for c in CAT_ORDER:
            d = stats["cat_avgs"][c] - baseline_stats["cat_avgs"][c]
            deltas.append(f"{'+' if d>=0 else ''}{d:.3f}")
        print(f"  {label:<42} " + " ".join(f"{d:>6}" for d in deltas))
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Sweep desperation/balance parameters")
    parser.add_argument("--sims", type=int, default=200, help="Sims per config (distributed across slots)")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed")
    parser.add_argument("--keepers", action="store_true", help="Include keepers in simulation")
    args = parser.parse_args()
    run_sweep(args.sims, args.seed, args.keepers)


if __name__ == "__main__":
    main()
