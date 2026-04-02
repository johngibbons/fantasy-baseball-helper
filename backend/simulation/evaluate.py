"""Post-draft team evaluation: expected weekly category wins."""

from __future__ import annotations

from .config import SimConfig
from .player_pool import Player, ALL_CAT_KEYS, PITCHING_CAT_KEYS
from .scoring_model import compute_rank, win_prob_from_rank
from .draft_engine import DraftResult


def compute_streaming_zscores(players: list[Player], config: SimConfig) -> dict[str, float]:
    """Compute z-score bonus from one streaming slot over a full season.

    Finds replacement-level SPs near STREAMING_SP_THRESHOLD in the player pool,
    averages their per-category z-scores, then scales by the ratio of streaming
    starts (STREAMS_PER_WEEK × STREAMING_WEEKS) to a replacement SP's projected
    starts (STREAMING_REPL_SP_STARTS).

    Z-scores scale linearly for both counting stats (raw_count / sgp_denom) and
    rate stats ((league_avg - rate) × IP / avg_team_IP / sgp_denom) because
    streaming SPs have the same per-start profile as replacement SPs.

    Returns dict mapping cat_key → z-score (hitting cats are 0.0, SVHD is 0.0).
    """
    threshold = config.STREAMING_SP_THRESHOLD
    repl_sps = [
        p for p in players
        if p.player_type == "pitcher" and p.pitcher_role() == "SP"
        and threshold - 50 <= p.overall_rank <= threshold + 50
    ]
    result: dict[str, float] = {k: 0.0 for k in ALL_CAT_KEYS}
    if not repl_sps:
        return result

    # Average z-scores of replacement-level SPs
    for cat in PITCHING_CAT_KEYS:
        vals = [p.zscores.get(cat, 0.0) for p in repl_sps]
        result[cat] = sum(vals) / len(vals)

    # Scale: streaming adds many more starts than one replacement SP projects
    streaming_starts = config.STREAMS_PER_WEEK * config.STREAMING_WEEKS
    scale = streaming_starts / config.STREAMING_REPL_SP_STARTS

    for cat in PITCHING_CAT_KEYS:
        if cat == "zscore_svhd":
            result[cat] = 0.0  # Streamers don't earn saves/holds
        else:
            result[cat] *= scale

    return result


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
