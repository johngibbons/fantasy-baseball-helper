"""Does per-pool calibration shrinkage produce better drafts?

Usage:
    .venv/bin/python sweep_shrinkage.py --sims 200 --seed 42

The multi-season backtest measured that the board over-disperses, markedly
more for pitchers (0.699-0.722, below 1 in every season) than for hitters
(0.759-0.885, above 1 in two). `ValuationConfig.hitter_shrinkage` /
`pitcher_shrinkage` correct it, and ship switched off.

Calibration evidence is not the same as draft evidence. Shrinkage never
reorders a pool -- the transform is monotonic -- so what it changes is how
hitters interleave with pitchers, and the size of the value *differences* that
VONA and urgency are built from. A board can be better calibrated and draft
worse. The variable-sigma question is the cautionary tale in both directions:
rejected on simulation in 2026, and the re-run reversed it.

Two comparisons matter here beyond "is it better than off":

  **uniform vs per-pool** tests the central claim. If one shrinkage constant
  applied to both pools does as well as two, "per-pool" is decoration.

  **the mixed pair** (trend-model hitters against THE BAT X pitchers) is the
  mistake this analysis nearly shipped. Its ratio is an artifact of comparing
  two forecasters rather than a calibration, and it moves 13 pitchers out of
  the top 100 where the properly-paired constants move 3. Included so the
  simulator can say whether that distinction shows up in drafts.

Note the simulator normally reads the precomputed `rankings` table, which no
config can influence. Boards are therefore computed in memory here and fed
through `load_players_from_rows`, with ADP joined from `rankings` because the
opponent model needs it and the valuation path does not produce it.
"""

from __future__ import annotations

import argparse
import random
import sqlite3
import statistics
import sys
import time
from pathlib import Path

from backend.analysis.zscores import ValuationConfig, calculate_all_zscores
from backend.simulation.config import SimConfig
from backend.simulation.draft_engine import simulate_draft
from backend.simulation.evaluate import compute_streaming_zscores, evaluate_draft
from backend.simulation.player_pool import load_players_from_rows

DB = Path(__file__).parent / "backend" / "fantasy_baseball.db"

# (label, hitter_shrinkage, pitcher_shrinkage)
CANDIDATES = [
    ("off (shipped)", 1.0, 1.0),
    ("per-pool 0.759H / 0.722P (recommended)", 0.759, 0.722),
    ("uniform 0.74 both pools", 0.74, 0.74),
    ("pitchers only 1.0H / 0.722P", 1.0, 0.722),
    ("mixed sources 0.88H / 0.72P (the trap)", 0.88, 0.72),
]


def adp_lookup(season: int) -> dict[int, tuple]:
    """ADP per player, which the valuation path does not produce."""
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT mlb_id, espn_adp, fangraphs_adp FROM rankings WHERE season = ?",
        (season,)).fetchall()
    conn.close()
    return {r["mlb_id"]: (r["espn_adp"], r["fangraphs_adp"]) for r in rows}


def board_rows(season: int, hitter: float, pitcher: float,
               adp: dict[int, tuple]) -> list[dict]:
    results = calculate_all_zscores(
        season=season, source="atc", save_to_db=False,
        config=ValuationConfig(hitter_shrinkage=hitter, pitcher_shrinkage=pitcher))
    rows = []
    for row in results:
        espn, nfbc = adp.get(row["mlb_id"], (None, None))
        rows.append({**row, "espn_adp": espn, "fangraphs_adp": nfbc})
    return rows


def run(num_sims: int, seed: int | None, season: int) -> None:
    adp = adp_lookup(season)
    if not adp:
        print(f"ERROR: no rankings rows for {season}; run the sync first.")
        sys.exit(1)

    num_teams = 10
    sims_per_slot = max(1, num_sims // num_teams)
    config = SimConfig()

    results: list[tuple[str, list[float]]] = []
    for label, hitter, pitcher in CANDIDATES:
        players = load_players_from_rows(board_rows(season, hitter, pitcher, adp))
        streaming = compute_streaming_zscores(players, config)
        wins: list[float] = []
        started = time.time()
        # Identical seeds across candidates, so the comparison is draft-by-draft.
        for slot in range(num_teams):
            for sim in range(sims_per_slot):
                rng = random.Random(
                    None if seed is None else seed + slot * 1000 + sim)
                draft = simulate_draft(players, slot, config, rng)
                wins.append(evaluate_draft(draft, num_teams, config=config,
                                           streaming_zscores=streaming)
                            ["expected_wins"])
        results.append((label, wins))
        print(f"  {label:40} mean={statistics.mean(wins):6.3f} "
              f"({time.time() - started:5.1f}s)", flush=True)

    baseline = results[0][1]
    print(f"\n{len(baseline)} drafts per candidate, seed={seed}, season={season}\n")
    print(f"  {'candidate':40} {'wins':>7} {'se':>6} {'vs off':>9} {'paired se':>10}")
    for label, wins in results:
        mean = statistics.mean(wins)
        se = statistics.stdev(wins) / (len(wins) ** 0.5) if len(wins) > 1 else 0.0
        verdict = paired = ""
        if label != results[0][0]:
            diffs = [a - b for a, b in zip(wins, baseline)]
            delta = statistics.mean(diffs)
            dse = (statistics.stdev(diffs) / (len(diffs) ** 0.5)
                   if len(diffs) > 1 and any(diffs) else 0.0)
            verdict = f"{delta:+.3f}" + (" *" if dse and abs(delta) > 1.96 * dse
                                         else "  ns")
            paired = f"{dse:.4f}" if dse else "-"
        print(f"  {label:40} {mean:>7.3f} {se:>6.3f} {verdict:>9} {paired:>10}")
    print("\n  * = outside a 95% paired interval; ns = inside it, i.e. no effect.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sims", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--season", type=int, default=2026)
    args = parser.parse_args()
    run(args.sims, args.seed, args.season)
    return 0


if __name__ == "__main__":
    sys.exit(main())
