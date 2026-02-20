#!/usr/bin/env python3
"""Optimize draft scoring model coefficients using Bayesian optimization (Optuna TPE).

Uses the draft simulator as a black-box objective function and searches
for coefficients that maximize expected weekly category wins.

Usage:
    python3 optimize_model.py                         # Default: 100 trials, 100 sims/trial
    python3 optimize_model.py --trials 200            # More thorough search
    python3 optimize_model.py --sims-per-trial 200    # More stable per-trial estimates
    python3 optimize_model.py --validate 500          # Run 500 validation sims on best params
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, "backend")

import optuna
from optuna.samplers import TPESampler

from simulation.config import SimConfig
from simulation.player_pool import load_players, Player
from simulation.draft_engine import simulate_draft
from simulation.evaluate import evaluate_draft
from simulation.report import print_report, print_comparison


# ── Objective function ──

def run_sims(
    players: list[Player],
    config: SimConfig,
    n_sims_per_slot: int,
    seed: int,
) -> list[dict]:
    """Run simulations across all 10 slots, return evaluation results."""
    rng = random.Random(seed)
    num_teams = config.NUM_TEAMS
    results: list[dict] = []

    for slot in range(num_teams):
        for _ in range(n_sims_per_slot):
            sim_seed = rng.randint(0, 2**31)
            sim_rng = random.Random(sim_seed)
            draft_result = simulate_draft(players, slot, config, sim_rng)
            evaluation = evaluate_draft(draft_result, num_teams)
            evaluation["my_slot"] = slot
            results.append(evaluation)

    return results


def objective(
    trial: optuna.Trial,
    players: list[Player],
    n_sims_per_slot: int,
    seed: int,
) -> float:
    """Optuna objective: suggest params, run sims, return expected weekly wins."""

    config = SimConfig(
        MCW_WEIGHT=trial.suggest_float("MCW_WEIGHT", 4.0, 24.0),
        VONA_WEIGHT_MCW=trial.suggest_float("VONA_WEIGHT_MCW", 0.0, 4.0),
        VONA_WEIGHT_BPA=trial.suggest_float("VONA_WEIGHT_BPA", 0.0, 2.0),
        URGENCY_WEIGHT_MCW=trial.suggest_float("URGENCY_WEIGHT_MCW", 0.0, 2.0),
        URGENCY_WEIGHT_BPA=trial.suggest_float("URGENCY_WEIGHT_BPA", 0.0, 1.0),
        AVAILABILITY_DISCOUNT=trial.suggest_float("AVAILABILITY_DISCOUNT", 0.0, 1.0),
        BENCH_PENALTY_RATE=trial.suggest_float("BENCH_PENALTY_RATE", 0.2, 1.0),
        CONFIDENCE_START=trial.suggest_int("CONFIDENCE_START", 0, 60),
        CONFIDENCE_END=trial.suggest_int("CONFIDENCE_END", 40, 160),
    )

    results = run_sims(players, config, n_sims_per_slot, seed)
    wins = [r["expected_wins"] for r in results]
    mean_wins = sum(wins) / len(wins)

    # Log category win rates for analysis
    for cat_key in ["zscore_r", "zscore_tb", "zscore_rbi", "zscore_sb", "zscore_obp",
                     "zscore_k", "zscore_qs", "zscore_era", "zscore_whip", "zscore_svhd"]:
        cat_rates = [r["cat_win_probs"][cat_key] for r in results]
        trial.set_user_attr(f"cat_{cat_key}", sum(cat_rates) / len(cat_rates))

    hitters = [r["hitter_count"] for r in results]
    pitchers = [r["pitcher_count"] for r in results]
    trial.set_user_attr("avg_hitters", sum(hitters) / len(hitters))
    trial.set_user_attr("avg_pitchers", sum(pitchers) / len(pitchers))

    return mean_wins


# ── Main ──

def main() -> None:
    parser = argparse.ArgumentParser(description="Optimize draft model coefficients")
    parser.add_argument("--trials", type=int, default=100,
                        help="Number of optimization trials (default 100)")
    parser.add_argument("--sims-per-trial", type=int, default=10,
                        help="Simulations per slot per trial (default 10, total = 10 slots * N)")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed for reproducibility")
    parser.add_argument("--validate", type=int, default=0,
                        help="Run N validation sims on best params (0 to skip)")
    parser.add_argument("--db", type=str, default=None,
                        help="Path to SQLite database")
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--study-name", type=str, default="draft-model-opt",
                        help="Optuna study name (for resuming)")
    parser.add_argument("--storage", type=str, default=None,
                        help="Optuna storage URL (e.g. sqlite:///optuna.db) for persistence")
    args = parser.parse_args()

    # Load player data
    print("Loading player data...")
    players = load_players(db_path=args.db, season=args.season)
    print(f"  {len(players)} players loaded")

    total_per_trial = 10 * args.sims_per_trial
    print(f"\nOptimization: {args.trials} trials, {total_per_trial} sims/trial "
          f"({args.sims_per_trial}/slot), seed={args.seed}")
    print(f"Total simulations: ~{args.trials * total_per_trial:,}")

    # Run baseline first
    print("\n--- Baseline (current defaults) ---")
    baseline_config = SimConfig()
    t0 = time.time()
    baseline_results = run_sims(players, baseline_config, args.sims_per_trial, args.seed)
    baseline_wins = [r["expected_wins"] for r in baseline_results]
    baseline_mean = sum(baseline_wins) / len(baseline_wins)
    t1 = time.time()
    print(f"  Expected weekly wins: {baseline_mean:.3f}  ({t1 - t0:.1f}s)")

    # Create Optuna study
    storage = args.storage
    sampler = TPESampler(seed=args.seed, n_startup_trials=20)
    study = optuna.create_study(
        study_name=args.study_name,
        storage=storage,
        direction="maximize",
        sampler=sampler,
        load_if_exists=True,
    )

    # Suppress Optuna's per-trial logging — we do our own
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    # Run optimization
    print(f"\n--- Optimizing ({args.trials} trials) ---")
    trial_count = 0
    t_start = time.time()

    def callback(study: optuna.Study, trial: optuna.trial.FrozenTrial) -> None:
        nonlocal trial_count
        trial_count += 1
        elapsed = time.time() - t_start
        best = study.best_value
        improvement = best - baseline_mean
        sign = "+" if improvement >= 0 else ""
        avg_per_trial = elapsed / trial_count
        remaining = (args.trials - trial_count) * avg_per_trial

        print(f"\r  Trial {trial_count}/{args.trials}  "
              f"this={trial.value:.3f}  best={best:.3f} ({sign}{improvement:.3f})  "
              f"[{elapsed:.0f}s elapsed, ~{remaining:.0f}s remaining]   ",
              end="", flush=True)

    study.optimize(
        lambda trial: objective(trial, players, args.sims_per_trial, args.seed),
        n_trials=args.trials,
        callbacks=[callback],
    )
    print()

    t_end = time.time()
    print(f"\nOptimization completed in {t_end - t_start:.0f}s")

    # Report best parameters
    best = study.best_trial
    print(f"\n{'Best Parameters':=^60}")
    print(f"Expected Weekly Wins: {best.value:.3f} "
          f"(baseline: {baseline_mean:.3f}, delta: {best.value - baseline_mean:+.3f})")
    print()

    defaults = SimConfig()
    param_names = [
        "MCW_WEIGHT", "VONA_WEIGHT_MCW", "VONA_WEIGHT_BPA",
        "URGENCY_WEIGHT_MCW", "URGENCY_WEIGHT_BPA",
        "AVAILABILITY_DISCOUNT", "BENCH_PENALTY_RATE",
        "CONFIDENCE_START", "CONFIDENCE_END",
    ]
    print(f"  {'Parameter':<25s} {'Default':>10s} {'Optimized':>10s} {'Change':>10s}")
    print(f"  {'-'*25} {'-'*10} {'-'*10} {'-'*10}")
    for name in param_names:
        default_val = getattr(defaults, name)
        opt_val = best.params[name]
        delta = opt_val - default_val
        sign = "+" if delta >= 0 else ""
        print(f"  {name:<25s} {default_val:>10.2f} {opt_val:>10.2f} {sign}{delta:>9.2f}")

    # Category win rates from best trial
    print(f"\nCategory Win Rates (best trial):")
    cat_labels = {
        "zscore_r": "R", "zscore_tb": "TB", "zscore_rbi": "RBI",
        "zscore_sb": "SB", "zscore_obp": "OBP", "zscore_k": "K",
        "zscore_qs": "QS", "zscore_era": "ERA", "zscore_whip": "WHIP",
        "zscore_svhd": "SVHD",
    }
    for key, label in cat_labels.items():
        rate = best.user_attrs.get(f"cat_{key}", 0)
        print(f"  {label:6s}: .{int(rate * 100):02d}", end="")
    print()

    # Print as CLI flags for easy testing
    print(f"\n--- Replay command ---")
    flags = []
    flag_map = {
        "MCW_WEIGHT": "--mcw-weight",
        "VONA_WEIGHT_MCW": "--vona-weight-mcw",
        "VONA_WEIGHT_BPA": "--vona-weight-bpa",
        "URGENCY_WEIGHT_MCW": "--urgency-weight-mcw",
        "URGENCY_WEIGHT_BPA": "--urgency-weight-bpa",
        "AVAILABILITY_DISCOUNT": "--availability-discount",
        "BENCH_PENALTY_RATE": "--bench-penalty-rate",
        "CONFIDENCE_START": "--confidence-start",
        "CONFIDENCE_END": "--confidence-end",
    }
    for param, flag in flag_map.items():
        val = best.params[param]
        if isinstance(val, float):
            flags.append(f"{flag} {val:.4f}")
        else:
            flags.append(f"{flag} {val}")

    print(f"python3 simulate_draft.py -n 500 --seed 42 --compare \\")
    print(f"  {' '.join(flags)}")

    # Top 5 trials
    print(f"\n--- Top 5 Trials ---")
    top_trials = sorted(study.trials, key=lambda t: t.value if t.value is not None else -999, reverse=True)[:5]
    for i, t in enumerate(top_trials):
        if t.value is None:
            continue
        print(f"  #{i+1}: {t.value:.3f} wins/week  "
              f"MCW={t.params['MCW_WEIGHT']:.1f} "
              f"VONA_MCW={t.params['VONA_WEIGHT_MCW']:.2f} "
              f"AVAIL={t.params['AVAILABILITY_DISCOUNT']:.2f} "
              f"BENCH={t.params['BENCH_PENALTY_RATE']:.2f}")

    # Parameter importance
    try:
        importance = optuna.importance.get_param_importances(study)
        print(f"\n--- Parameter Importance ---")
        for name, imp in sorted(importance.items(), key=lambda x: x[1], reverse=True):
            bar = "#" * int(imp * 40)
            print(f"  {name:<25s} {imp:.3f}  {bar}")
    except Exception:
        pass  # importance calculation can fail with few trials

    # Validation run
    if args.validate > 0:
        print(f"\n--- Validation ({args.validate} sims) ---")
        opt_config = defaults.with_overrides(**{
            k: v for k, v in best.params.items()
        })

        sims_per_slot = max(1, args.validate // 10)

        print(f"Running defaults ({sims_per_slot * 10} sims)...")
        val_baseline = run_sims(players, defaults, sims_per_slot, args.seed + 1000)

        print(f"Running optimized ({sims_per_slot * 10} sims)...")
        val_optimized = run_sims(players, opt_config, sims_per_slot, args.seed + 1000)

        print_report(val_baseline, sims_per_slot * 10, sims_per_slot, 10, args.seed + 1000, "defaults")
        print_report(val_optimized, sims_per_slot * 10, sims_per_slot, 10, args.seed + 1000, "optimized")
        print_comparison(val_baseline, val_optimized, "defaults", "optimized")

    # Save results to JSON
    output_path = Path("optimization_results.json")
    output = {
        "baseline_wins": baseline_mean,
        "best_wins": best.value,
        "delta": best.value - baseline_mean,
        "best_params": best.params,
        "best_category_rates": {
            k: best.user_attrs.get(f"cat_{k}", 0)
            for k in cat_labels
        },
        "top_5": [
            {"wins": t.value, "params": t.params}
            for t in top_trials[:5] if t.value is not None
        ],
        "total_trials": len(study.trials),
        "seed": args.seed,
    }
    output_path.write_text(json.dumps(output, indent=2))
    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    main()
