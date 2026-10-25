"""Does a better-calibrated availability model produce better drafts?

Usage:
    .venv/bin/python sweep_adp_sigma.py --sims 200 --seed 42
    .venv/bin/python sweep_adp_sigma.py --sims 200 --modes default   # skip window VONA

The availability model's sigma is miscalibrated, and that much is settled on
real data: against the 2026 draft the board's old `6 + adp/250 * 6` was twice
too confident in the 50-100 band and three to four times from pick 100 on,
and the multi-season backtest measured the spread as

    2026 alone:   sigma = 6.55  + 0.158 * ADP
    2017-2025:    sigma = 11.13 + 0.161 * ADP

This asks the different question of whether fixing it changes the drafts.

The first version of this sweep let USE_VARIABLE_SIGMA switch the simulated
opponents' noise as well (flat 18 -> 10 + 0.1 * adp), so every variable
candidate was scored in a different league from the baseline. That shared
change, not the coefficients, is the likeliest source of the +0.1 wins it
reported: the three variable candidates sat within one standard error of
each other. Opponent noise now has its own setting (OPP_USE_VARIABLE_SIGMA),
and here it is held fixed within each league while only our model varies.

Two leagues: today's simulated one (flat 18), and one whose opponents stray
from ADP by the measured amount. Two scoring modes: the simulator's default,
and window VONA, which is what the live board uses.

Result, 2026-10-24: no candidate differs from the old board formula outside a
95% paired interval, in any league or mode. The variable sigma shipped on
calibration grounds; see SCORING_IMPROVEMENTS.md section 6.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from backend.simulation.config import SimConfig

# Our availability model: (label, USE_VARIABLE_SIGMA, intercept, slope)
CANDIDATES = [
    ("old board: 6 + 0.024*adp", True, 6.0, 0.024),
    ("flat 18 (simulator default)", False, 0.0, 0.0),
    ("measured 2026: 6.55 + 0.158*adp", True, 6.55, 0.158),
    ("measured 2017-25: 11.13 + 0.161*adp", True, 11.13, 0.161),
]
BASELINE = CANDIDATES[0][0]

# The simulated league: how far opponents stray from ADP.
LEAGUES = {
    "flat 18": {"OPP_USE_VARIABLE_SIGMA": False},
    "measured spread": {"OPP_USE_VARIABLE_SIGMA": True,
                        "OPP_ADP_SIGMA_INTERCEPT": 11.13,
                        "OPP_ADP_SIGMA_SLOPE": 0.161},
}
MODES = {"default": {"USE_WINDOW_VONA": False},
         "window VONA": {"USE_WINDOW_VONA": True}}
NUM_TEAMS = 10

_players = None


def _load():
    global _players
    from backend.simulation.player_pool import load_players
    _players = load_players()


def config_for(mode: str, league: str, candidate: tuple) -> SimConfig:
    _, use_variable, intercept, slope = candidate
    ours = ({"USE_VARIABLE_SIGMA": True, "ADP_SIGMA_INTERCEPT": intercept,
             "ADP_SIGMA_SLOPE": slope} if use_variable
            else {"USE_VARIABLE_SIGMA": False})
    return SimConfig(**MODES[mode], **LEAGUES[league], **ours)


def run_one(job: tuple) -> tuple:
    from backend.simulation.draft_engine import simulate_draft
    from backend.simulation.evaluate import compute_streaming_zscores, evaluate_draft

    mode, league, candidate, slot, sim, seed = job
    config = config_for(mode, league, candidate)
    streaming = compute_streaming_zscores(_players, config)
    # Same seed and slot for every candidate, so they are compared draft by draft.
    rng = random.Random(seed + slot * 1000 + sim)
    draft = simulate_draft(_players, slot, config, rng)
    wins = evaluate_draft(draft, NUM_TEAMS, config=config,
                          streaming_zscores=streaming)["expected_wins"]
    return mode, league, candidate[0], slot, sim, wins


def summarize(results: dict, mode: str, league: str) -> list[dict]:
    keyed = results[(mode, league)]
    base = keyed[BASELINE]
    keys = sorted(base)
    rows = []
    for label, _, _, _ in CANDIDATES:
        wins = [keyed[label][k] for k in keys]
        paired = [keyed[label][k] - base[k] for k in keys]
        delta = statistics.mean(paired)
        se = statistics.stdev(paired) / len(paired) ** 0.5 if any(paired) else 0.0
        rows.append({
            "candidate": label, "n": len(wins),
            "mean_wins": round(statistics.mean(wins), 4),
            "delta_vs_old_board": round(delta, 4),
            "delta_se": round(se, 4),
            "significant": bool(se and abs(delta) > 1.96 * se),
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sims", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--modes", nargs="+", default=list(MODES), choices=list(MODES))
    parser.add_argument("--out", type=Path, default=None,
                        help="Optional JSON file for the summary")
    args = parser.parse_args()

    sims_per_slot = max(1, args.sims // NUM_TEAMS)
    jobs = [(mode, league, candidate, slot, sim, args.seed)
            for mode in args.modes for league in LEAGUES
            for candidate in CANDIDATES
            for slot in range(NUM_TEAMS) for sim in range(sims_per_slot)]
    print(f"{len(jobs)} drafts on {args.workers} workers...")

    results: dict = {}
    started = time.time()
    with ProcessPoolExecutor(args.workers, initializer=_load) as pool:
        for mode, league, label, slot, sim, wins in pool.map(run_one, jobs, chunksize=4):
            results.setdefault((mode, league), {}).setdefault(label, {})[(slot, sim)] = wins
    print(f"done in {time.time() - started:.0f}s\n")

    summary = {}
    for mode in args.modes:
        for league in LEAGUES:
            rows = summarize(results, mode, league)
            summary[f"{mode} | {league}"] = rows
            print(f"{mode} scoring, {league} league "
                  f"({rows[0]['n']} drafts, paired on seed)")
            for row in rows:
                verdict = ("" if row["candidate"] == BASELINE else
                           f"{row['delta_vs_old_board']:+.3f} ± {1.96 * row['delta_se']:.3f}"
                           f"{' *' if row['significant'] else ''}")
                print(f"  {row['candidate']:38} {row['mean_wins']:7.3f}  {verdict}")
            print()
    print("Deltas are against the old board formula, with 95% paired intervals; "
          "* = outside it.")
    if args.out:
        args.out.write_text(json.dumps(summary, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
