"""Pretty-print benchmark results."""

from __future__ import annotations

import math

from .player_pool import ALL_CAT_KEYS, CAT_LABELS


def print_report(
    results: list[dict],
    num_sims: int,
    sims_per_slot: int,
    num_teams: int,
    seed: int | None,
    config_label: str = "",
) -> None:
    """Print formatted benchmark report from a list of per-simulation evaluation dicts."""
    if not results:
        print("No results to report.")
        return

    wins = [r["expected_wins"] for r in results]
    mean_wins = sum(wins) / len(wins)
    variance = sum((w - mean_wins) ** 2 for w in wins) / len(wins)
    std_wins = math.sqrt(variance)

    # Per-slot averages
    slot_wins: dict[int, list[float]] = {}
    for r in results:
        slot = r["my_slot"]
        if slot not in slot_wins:
            slot_wins[slot] = []
        slot_wins[slot].append(r["expected_wins"])

    # Category win rates
    cat_rates: dict[str, list[float]] = {k: [] for k in ALL_CAT_KEYS}
    for r in results:
        for cat_key, prob in r["cat_win_probs"].items():
            cat_rates[cat_key].append(prob)

    # Draft composition
    hitter_counts = [r["hitter_count"] for r in results]
    pitcher_counts = [r["pitcher_count"] for r in results]
    first_pitcher_rounds = [r["first_pitcher_round"] for r in results if r["first_pitcher_round"] is not None]

    # Print
    seed_str = f", seed={seed}" if seed is not None else ""
    label = f" [{config_label}]" if config_label else ""
    print(f"\nDraft Model Benchmark ({num_sims} sims, {sims_per_slot}/slot{seed_str}){label}")
    print("=" * 60)
    print(f"Expected Weekly Wins:  {mean_wins:.2f} +/- {std_wins:.2f}")

    print(f"\nPer Slot:")
    line1_slots = []
    line2_slots = []
    for slot in range(num_teams):
        sw = slot_wins.get(slot, [])
        avg = sum(sw) / len(sw) if sw else 0.0
        entry = f"  {slot + 1}: {avg:.2f}"
        if slot < 5:
            line1_slots.append(entry)
        else:
            line2_slots.append(entry)
    print("".join(line1_slots))
    print("".join(line2_slots))

    print(f"\nCategory Win Rates:")
    cats_line1 = []
    cats_line2 = []
    for i, cat_key in enumerate(ALL_CAT_KEYS):
        rates = cat_rates[cat_key]
        avg = sum(rates) / len(rates) if rates else 0.0
        label_str = CAT_LABELS.get(cat_key, cat_key)
        entry = f"  {label_str}: .{int(avg * 100):02d}"
        if i < 5:
            cats_line1.append(entry)
        else:
            cats_line2.append(entry)
    print("".join(cats_line1))
    print("".join(cats_line2))

    bench_pitcher_counts = [r.get("bench_pitcher_count", 0) for r in results]

    avg_hitters = sum(hitter_counts) / len(hitter_counts) if hitter_counts else 0
    avg_pitchers = sum(pitcher_counts) / len(pitcher_counts) if pitcher_counts else 0
    avg_first_p = sum(first_pitcher_rounds) / len(first_pitcher_rounds) if first_pitcher_rounds else 0
    avg_bench_p = sum(bench_pitcher_counts) / len(bench_pitcher_counts) if bench_pitcher_counts else 0

    print(f"\nDraft Composition (avg):")
    print(f"  Hitters: {avg_hitters:.1f}   Pitchers: {avg_pitchers:.1f}   Bench P: {avg_bench_p:.1f}")
    if first_pitcher_rounds:
        print(f"  First pitcher picked at: round {avg_first_p:.1f}")


def print_comparison(
    results_a: list[dict],
    results_b: list[dict],
    label_a: str,
    label_b: str,
) -> None:
    """Print side-by-side comparison of two benchmark runs."""
    wins_a = [r["expected_wins"] for r in results_a]
    wins_b = [r["expected_wins"] for r in results_b]
    mean_a = sum(wins_a) / len(wins_a) if wins_a else 0
    mean_b = sum(wins_b) / len(wins_b) if wins_b else 0

    print(f"\n{'Comparison':^60}")
    print("=" * 60)
    print(f"  {label_a:30s}: {mean_a:.3f} wins/week")
    print(f"  {label_b:30s}: {mean_b:.3f} wins/week")
    delta = mean_b - mean_a
    direction = "+" if delta >= 0 else ""
    print(f"  {'Delta':30s}: {direction}{delta:.3f} wins/week")

    # Per-category comparison
    cat_a: dict[str, float] = {k: 0.0 for k in ALL_CAT_KEYS}
    cat_b: dict[str, float] = {k: 0.0 for k in ALL_CAT_KEYS}
    for r in results_a:
        for k, v in r["cat_win_probs"].items():
            cat_a[k] += v
    for r in results_b:
        for k, v in r["cat_win_probs"].items():
            cat_b[k] += v
    n_a = len(results_a) or 1
    n_b = len(results_b) or 1

    print(f"\nPer-Category Delta:")
    for cat_key in ALL_CAT_KEYS:
        avg_a = cat_a[cat_key] / n_a
        avg_b = cat_b[cat_key] / n_b
        d = avg_b - avg_a
        sign = "+" if d >= 0 else ""
        label_str = CAT_LABELS.get(cat_key, cat_key)
        print(f"  {label_str:6s}: {avg_a:.3f} -> {avg_b:.3f} ({sign}{d:.3f})")
