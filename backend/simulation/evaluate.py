"""Post-draft team evaluation: expected weekly category wins."""

from __future__ import annotations

from .player_pool import ALL_CAT_KEYS
from .scoring_model import compute_rank, win_prob_from_rank
from .draft_engine import DraftResult


def evaluate_draft(result: DraftResult, num_teams: int) -> dict:
    """Evaluate a completed draft. Returns per-category win rates and total expected weekly wins.

    Unlike the draft-time model, evaluation counts ALL 10 categories (no punt skipping).
    """
    my_totals = result.all_team_totals[result.my_slot]

    cat_win_probs: dict[str, float] = {}
    for cat_key in ALL_CAT_KEYS:
        other_vals = [
            result.all_team_totals[t][cat_key]
            for t in range(num_teams)
            if t != result.my_slot
        ]
        other_vals.sort(reverse=True)
        rank = compute_rank(my_totals[cat_key], other_vals)
        cat_win_probs[cat_key] = win_prob_from_rank(rank, num_teams)

    expected_wins = sum(cat_win_probs.values())

    # Count hitters vs pitchers
    hitter_count = sum(1 for p in result.my_players if p.player_type == "hitter")
    pitcher_count = sum(1 for p in result.my_players if p.player_type == "pitcher")

    # First pitcher pick round
    first_pitcher_round = None
    for i, p in enumerate(result.my_players):
        if p.player_type == "pitcher":
            first_pitcher_round = i + 1  # 1-indexed
            break

    return {
        "expected_wins": expected_wins,
        "cat_win_probs": cat_win_probs,
        "hitter_count": hitter_count,
        "pitcher_count": pitcher_count,
        "first_pitcher_round": first_pitcher_round,
        "bench_pitcher_count": result.bench_pitcher_count,
        "sp_count": result.sp_count,
        "rp_count": result.rp_count,
    }
