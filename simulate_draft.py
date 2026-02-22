#!/usr/bin/env python3
"""Draft Model Benchmark Simulator — CLI entry point.

Usage:
    python3 simulate_draft.py                         # Default: 500 sims
    python simulate_draft.py -n 50                    # Quick test
    python simulate_draft.py --seed 42                # Reproducible
    python simulate_draft.py --mcw-weight 15 --compare  # A/B test
    python simulate_draft.py --slot 3                 # Single slot
"""

from __future__ import annotations

import argparse
import random
import sys
import time

sys.path.insert(0, "backend")

from simulation.config import SimConfig
from simulation.player_pool import load_players, rescale_h2h_weights
from simulation.draft_engine import simulate_draft
from simulation.evaluate import evaluate_draft
from simulation.report import print_report, print_comparison


def run_benchmark(
    players: list,
    config: SimConfig,
    num_sims: int,
    sims_per_slot: int,
    seed: int | None,
    slots: list[int] | None = None,
    config_label: str = "",
) -> list[dict]:
    """Run batch simulations and return list of evaluation results."""
    rng = random.Random(seed)
    num_teams = config.NUM_TEAMS

    if slots is None:
        slots = list(range(num_teams))

    results: list[dict] = []
    total = sims_per_slot * len(slots)
    done = 0

    for slot in slots:
        for _ in range(sims_per_slot):
            # Each sim gets a deterministic sub-seed from the master RNG
            sim_seed = rng.randint(0, 2**31)
            sim_rng = random.Random(sim_seed)

            draft_result = simulate_draft(players, slot, config, sim_rng)
            evaluation = evaluate_draft(draft_result, num_teams)
            evaluation["my_slot"] = slot
            results.append(evaluation)

            done += 1
            if done % 10 == 0 or done == total:
                pct = done / total * 100
                print(f"\r  Simulating... {done}/{total} ({pct:.0f}%)", end="", flush=True)

    print()  # newline after progress
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Draft Model Benchmark Simulator")

    parser.add_argument("-n", "--num-sims", type=int, default=500,
                        help="Total simulations (distributed across slots, default 500)")
    parser.add_argument("--seed", type=int, default=None,
                        help="Random seed for reproducibility")
    parser.add_argument("--slot", type=int, default=None,
                        help="Single draft slot to test (1-indexed)")
    parser.add_argument("--db", type=str, default=None,
                        help="Path to SQLite database")
    parser.add_argument("--season", type=int, default=2026,
                        help="Season to load rankings for (default 2026)")
    parser.add_argument("--compare", action="store_true",
                        help="Run twice: custom params vs defaults, show delta")

    # Tunable coefficients
    parser.add_argument("--mcw-weight", type=float, default=None)
    parser.add_argument("--vona-weight-mcw", type=float, default=None)
    parser.add_argument("--vona-weight-bpa", type=float, default=None)
    parser.add_argument("--urgency-weight-mcw", type=float, default=None)
    parser.add_argument("--urgency-weight-bpa", type=float, default=None)
    parser.add_argument("--availability-discount", type=float, default=None)
    parser.add_argument("--bench-penalty-rate", type=float, default=None)
    parser.add_argument("--adp-sigma", type=float, default=None)
    parser.add_argument("--confidence-start", type=int, default=None)
    parser.add_argument("--confidence-end", type=int, default=None)
    parser.add_argument("--lock-mcw-weight", type=float, default=None)
    parser.add_argument("--target-mcw-weight", type=float, default=None)
    parser.add_argument("--h2h-weight-scale", type=float, default=None,
                        help="Scale H2H correlation weights (1.0=current, 0.0=removed, 0.5=halved)")
    parser.add_argument("--scale-bpa-urgency", action="store_true",
                        help="Scale BPA urgency weight by draft progress (reduces early-round urgency)")
    parser.add_argument("--slot-scarcity", action="store_true",
                        help="Use slot scarcity gradient for roster fit instead of binary")
    parser.add_argument("--variable-sigma", action="store_true",
                        help="Use ADP-dependent sigma (10 + 0.1*ADP) instead of fixed 18")
    parser.add_argument("--window-vona", action="store_true",
                        help="Use window VONA (availability-weighted replacement)")
    parser.add_argument("--no-surplus-value", action="store_true",
                        help="Disable surplus value (VORP) in BPA formula (on by default)")
    parser.add_argument("--no-restrict-norm-pool", action="store_true",
                        help="Disable normalization pool restriction (use full player pool)")

    args = parser.parse_args()

    # Load player data
    print("Loading player data...")
    players = load_players(db_path=args.db, season=args.season)
    if args.h2h_weight_scale is not None:
        rescale_h2h_weights(players, args.h2h_weight_scale)
    print(f"  Loaded {len(players)} players ({sum(1 for p in players if p.player_type == 'hitter')} hitters, "
          f"{sum(1 for p in players if p.player_type == 'pitcher')} pitchers)")

    # Build config with overrides
    overrides: dict = {}
    flag_map = {
        "mcw_weight": "MCW_WEIGHT",
        "vona_weight_mcw": "VONA_WEIGHT_MCW",
        "vona_weight_bpa": "VONA_WEIGHT_BPA",
        "urgency_weight_mcw": "URGENCY_WEIGHT_MCW",
        "urgency_weight_bpa": "URGENCY_WEIGHT_BPA",
        "availability_discount": "AVAILABILITY_DISCOUNT",
        "bench_penalty_rate": "BENCH_PENALTY_RATE",
        "adp_sigma": "ADP_SIGMA",
        "confidence_start": "CONFIDENCE_START",
        "confidence_end": "CONFIDENCE_END",
        "lock_mcw_weight": "LOCK_MCW_WEIGHT",
        "target_mcw_weight": "TARGET_MCW_WEIGHT",
    }
    for arg_name, config_name in flag_map.items():
        val = getattr(args, arg_name)
        if val is not None:
            overrides[config_name] = val
    if args.scale_bpa_urgency:
        overrides["SCALE_BPA_URGENCY"] = True
    if args.slot_scarcity:
        overrides["USE_SLOT_SCARCITY"] = True
    if args.variable_sigma:
        overrides["USE_VARIABLE_SIGMA"] = True
    if args.window_vona:
        overrides["USE_WINDOW_VONA"] = True
    if args.no_surplus_value:
        overrides["USE_SURPLUS_VALUE"] = False
    if args.no_restrict_norm_pool:
        overrides["RESTRICT_NORM_POOL"] = False
    if args.h2h_weight_scale is not None:
        overrides["H2H_WEIGHT_SCALE"] = args.h2h_weight_scale

    default_config = SimConfig()

    # Determine slots and sims_per_slot
    num_teams = default_config.NUM_TEAMS
    if args.slot is not None:
        slots = [args.slot - 1]  # convert to 0-indexed
        sims_per_slot = args.num_sims
    else:
        slots = list(range(num_teams))
        sims_per_slot = max(1, args.num_sims // num_teams)

    total_sims = sims_per_slot * len(slots)

    # Separate non-SimConfig overrides from the label dict
    config_overrides = {k: v for k, v in overrides.items() if k != "H2H_WEIGHT_SCALE"}

    if args.compare and overrides:
        # A/B comparison mode
        custom_config = default_config.with_overrides(**config_overrides)
        override_desc = ", ".join(f"{k}={v}" for k, v in overrides.items())

        print(f"\n--- Running DEFAULTS ({total_sims} sims) ---")
        t0 = time.time()
        results_default = run_benchmark(
            players, default_config, total_sims, sims_per_slot,
            seed=args.seed, slots=slots, config_label="defaults",
        )
        t1 = time.time()
        print_report(results_default, total_sims, sims_per_slot, num_teams, args.seed, "defaults")
        print(f"  ({t1 - t0:.1f}s)")

        print(f"\n--- Running CUSTOM: {override_desc} ({total_sims} sims) ---")
        t0 = time.time()
        results_custom = run_benchmark(
            players, custom_config, total_sims, sims_per_slot,
            seed=args.seed, slots=slots, config_label=override_desc,
        )
        t1 = time.time()
        print_report(results_custom, total_sims, sims_per_slot, num_teams, args.seed, override_desc)
        print(f"  ({t1 - t0:.1f}s)")

        print_comparison(results_default, results_custom, "defaults", override_desc)

    else:
        config = default_config.with_overrides(**config_overrides) if config_overrides else default_config
        label = ", ".join(f"{k}={v}" for k, v in overrides.items()) if overrides else "defaults"

        print(f"\nRunning {total_sims} simulations ({sims_per_slot} per slot)...")
        t0 = time.time()
        results = run_benchmark(
            players, config, total_sims, sims_per_slot,
            seed=args.seed, slots=slots, config_label=label,
        )
        t1 = time.time()
        print_report(results, total_sims, sims_per_slot, num_teams, args.seed, label)
        print(f"\nCompleted in {t1 - t0:.1f}s")


if __name__ == "__main__":
    main()
