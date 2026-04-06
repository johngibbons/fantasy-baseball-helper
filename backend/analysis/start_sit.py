"""Start/Sit optimization engine for H2H fantasy baseball starting pitchers.

Combines PitcherList per-start quality ratings with current matchup category
state to recommend whether to start or sit each SP today.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

# Expected counting-stat swing per day (across all SP starts on a typical roster)
DAILY_SWING = {
    "K": 6.0,
    "QS": 1.5,
    "SVHD": 1.0,
    "R": 4.0,
    "TB": 8.0,
    "RBI": 4.0,
    "SB": 0.5,
}

# Rate-stat gap thresholds for "big" vs "close" classification
RATE_THRESHOLDS = {
    "ERA": 0.30,
    "WHIP": 0.08,
    "OBP": 0.008,
}

# Categories where a lower value is better
LOWER_IS_BETTER = {"ERA", "WHIP"}

# Minimum IP to trust rate-stat classification (below this → force "close")
MIN_IP_FOR_BIG = 15.0

# Pitching categories affected by an SP start decision
SP_AFFECTED_CATS = {"K", "QS", "ERA", "WHIP"}

# Decision matrix: (tier, column) → recommendation
# Columns: "ratio_protect", "k_chase", "default"
_DECISION_MATRIX: dict[str, dict[str, str]] = {
    "strong_start": {
        "ratio_protect": "start",
        "k_chase": "strong_start",
        "ratio_punt": "strong_start",
        "default": "strong_start",
    },
    "start": {
        "ratio_protect": "risky_start",
        "k_chase": "start",
        "ratio_punt": "start",
        "default": "start",
    },
    "maybe": {
        "ratio_protect": "sit",
        "k_chase": "risky_start",
        "ratio_punt": "start",
        "default": "sit",
    },
    "sit": {
        "ratio_protect": "sit",
        "k_chase": "sit",
        "ratio_punt": "risky_start",
        "default": "sit",
    },
}


# ── Core classification functions ─────────────────────────────────────────────


def classify_category(
    cat: str,
    yours: float,
    theirs: float,
    days_remaining: int,
    team_ip: float = 50.0,
) -> str:
    """Classify a single matchup category as winning_big/winning_close/losing_close/losing_big.

    Args:
        cat: Category name (e.g., "K", "ERA", "OBP").
        yours: Your team's current value for this category.
        theirs: Opponent's current value.
        days_remaining: Days left in the matchup period (including today).
        team_ip: Your team's total IP so far this week (used for rate-stat override).

    Returns:
        One of "winning_big", "winning_close", "losing_close", "losing_big".
    """
    # Determine direction: am I winning this category?
    if cat in LOWER_IS_BETTER:
        winning = yours < theirs
    else:
        winning = yours > theirs

    abs_gap = abs(yours - theirs)

    if abs_gap == 0:
        return "tied"

    # Determine size: big or close
    if cat in RATE_THRESHOLDS:
        threshold = RATE_THRESHOLDS[cat]
        # Low-IP override: force "close" if not enough innings to trust rate stats
        if cat in LOWER_IS_BETTER and team_ip < MIN_IP_FOR_BIG:
            is_big = False
        else:
            is_big = abs_gap >= threshold
    elif cat in DAILY_SWING:
        gap_in_days = abs_gap / DAILY_SWING[cat]
        is_big = gap_in_days > days_remaining * 0.8
    else:
        # Unknown category — default to close
        is_big = False

    if winning:
        return "winning_big" if is_big else "winning_close"
    else:
        return "losing_big" if is_big else "losing_close"


def compute_ratio_exposure(total_starts_remaining: int) -> float:
    """Compute how much ratio exposure remains this week.

    Normalized: 5+ starts = 1.0 (full exposure), 1 start = 0.2 (low exposure).
    High exposure means sitting today won't protect ratios — future starts will
    put them at risk anyway.

    Args:
        total_starts_remaining: Total SP starts left this matchup period
            (including today).

    Returns:
        Float in [0.0, 1.0].
    """
    return min(1.0, total_starts_remaining / 5.0)


def decide_recommendation(
    pitcherlist_tier: str,
    cat_states: dict[str, str],
    ratio_exposure: float,
) -> str:
    """Apply the decision matrix to produce a start/sit recommendation.

    Args:
        pitcherlist_tier: One of "strong_start", "start", "maybe", "sit".
        cat_states: Dict mapping K/QS/ERA/WHIP → state string.
        ratio_exposure: Float [0, 1] from compute_ratio_exposure().

    Returns:
        One of "strong_start", "start", "risky_start", "sit", "safe_sit".
    """
    # All SP-affected cats winning_big → safe sit (protect every lead)
    sp_cats = {c: cat_states.get(c, "losing_close") for c in SP_AFFECTED_CATS}
    if all(s == "winning_big" for s in sp_cats.values()):
        return "safe_sit"

    # Ratio punt: ERA/WHIP already lost — no downside to starting, go for K/QS
    era_whip_losing_big = all(
        sp_cats.get(c) in ("losing_big", "tied") for c in ("ERA", "WHIP")
    ) and any(
        sp_cats.get(c) == "losing_big" for c in ("ERA", "WHIP")
    )
    if era_whip_losing_big:
        column = "ratio_punt"
        tier_row = _DECISION_MATRIX.get(pitcherlist_tier, _DECISION_MATRIX["sit"])
        return tier_row[column]

    # Identify conflict flags
    era_whip_close = any(
        sp_cats.get(c) == "winning_close" for c in ("ERA", "WHIP")
    )
    k_qs_losing_close = any(
        sp_cats.get(c) == "losing_close" for c in ("K", "QS")
    )

    # Determine which decision matrix column to use
    if era_whip_close and k_qs_losing_close:
        # Conflict: ERA/WHIP close AND K/QS losing close
        if ratio_exposure >= 0.8:
            column = "k_chase"
        else:
            column = "ratio_protect"
    elif era_whip_close:
        if ratio_exposure >= 0.8:
            # Can't protect ratios anyway — too many starts left
            column = "default"
        else:
            # Low or middle exposure → protect the rate stat lead
            column = "ratio_protect"
    elif k_qs_losing_close:
        column = "k_chase"
    else:
        column = "default"

    tier_row = _DECISION_MATRIX.get(pitcherlist_tier, _DECISION_MATRIX["sit"])
    return tier_row[column]


def generate_rationale(
    pitcherlist_raw: str,
    opponent: str,
    recommendation: str,
    pitcherlist_tier: str,
    cats: dict[str, str],
    ratio_exposure: float,
    starts_remaining: int,
) -> str:
    """Generate a human-readable rationale string for the recommendation.

    Args:
        pitcherlist_raw: Raw PitcherList label, e.g. "Start-8" or "Maybe-3".
        opponent: Opponent team abbreviation, e.g. "CIN".
        recommendation: Our recommendation string.
        pitcherlist_tier: Mapped tier, e.g. "strong_start", "start", "maybe", "sit".
        cats: Dict of K/QS/ERA/WHIP → state string.
        ratio_exposure: Float [0, 1].
        starts_remaining: Total SP starts remaining this week (including today).

    Returns:
        Human-readable rationale string.
    """
    if recommendation == "safe_sit":
        return "Winning all pitching categories comfortably. Safe to sit and protect leads."

    # Ratio punt: ERA/WHIP already lost — start for counting stats
    era_whip_losing_big = all(
        cats.get(c) in ("losing_big", "tied") for c in ("ERA", "WHIP")
    ) and any(
        cats.get(c) == "losing_big" for c in ("ERA", "WHIP")
    )
    if era_whip_losing_big:
        return f"{pitcherlist_raw} vs {opponent}. ERA/WHIP already lost — start for K/QS upside."

    # Sit-tier pitchers always sit regardless of matchup context — say so clearly
    if pitcherlist_tier == "sit":
        return f"{pitcherlist_raw} vs {opponent}. PitcherList ranks too low to justify starting."

    era_whip_close = any(
        cats.get(c) == "winning_close" for c in ("ERA", "WHIP")
    )
    k_qs_losing_close = any(
        cats.get(c) == "losing_close" for c in ("K", "QS")
    )

    parts: list[str] = [f"{pitcherlist_raw} vs {opponent}."]

    if era_whip_close and ratio_exposure >= 0.8:
        parts.append(
            f"ERA/WHIP close but {starts_remaining} start{'s' if starts_remaining != 1 else ''}"
            f" left this week — can't protect ratios anyway."
        )
    elif era_whip_close and ratio_exposure <= 0.4:
        parts.append("ERA/WHIP close and last start of the week. Protect the ratio lead.")
    elif era_whip_close:
        parts.append(
            "ERA/WHIP close — future starts add ratio risk."
        )

    if k_qs_losing_close:
        parts.append("Chasing Ks/QS upside.")

    if recommendation == "risky_start":
        parts.append("Borderline — league-dependent call.")

    return " ".join(parts)


# ── Main entry point ──────────────────────────────────────────────────────────


def compute_start_sit_recommendations(
    roster_pitcher_names: list[str],
    matchup_categories: dict[str, dict[str, float]],
    team_ip: float,
    days_remaining: int,
    opponent_name: str,
    today_date: str,
    matchup_end_date: str,
    all_rostered_names: list[str] | None = None,
    streaming_target_date: str | None = None,
    streaming_end_date: str | None = None,
) -> dict:
    """Compute start/sit recommendations for today's SP starters.

    Args:
        roster_pitcher_names: List of SP names on the user's roster.
        matchup_categories: Dict of cat → {"yours": float, "theirs": float}
            for all 10 categories.
        team_ip: User's team IP accumulated so far this week.
        days_remaining: Days remaining in matchup period (including today).
        opponent_name: Opponent team name.
        today_date: ISO date string, e.g. "2026-03-25".
        matchup_end_date: ISO date string of last day of matchup period.
        streaming_target_date: ISO date for first day to show streamers (tomorrow).
        streaming_end_date: ISO date for last day to show streamers.

    Returns:
        Dict with matchup_summary, upcoming_starts, recommendations, off_day_pitchers.
    """
    from backend.data.pitcherlist import get_rankings_for_date, get_streaming_options

    # Step 1: Classify all 10 categories
    cat_states: dict[str, str] = {}
    for cat, vals in matchup_categories.items():
        yours = vals["yours"]
        theirs = vals["theirs"]
        cat_states[cat] = classify_category(
            cat, yours, theirs, days_remaining, team_ip=team_ip
        )

    # Step 2: Fetch PitcherList data for today and upcoming
    todays_starters_raw, upcoming_starts_raw, off_day_raw = get_rankings_for_date(
        today_date, roster_pitcher_names, matchup_end_date=matchup_end_date
    )

    # Adapt field names from scraper output to what the engine expects
    def _adapt(entry: dict) -> dict:
        return {
            "pitcher_name": entry.get("roster_name", entry.get("pitcher_name")),
            "date": entry.get("date", ""),
            "tier": entry.get("mapped_tier", "sit"),
            "score": entry.get("score", 0),
            "pitcherlist_raw": entry.get("raw", ""),
            "opponent": entry.get("opponent", "???"),
        }

    todays_starters = [_adapt(e) for e in todays_starters_raw]
    upcoming_starts = [_adapt(e) for e in upcoming_starts_raw]

    starts_today = len(todays_starters)
    starts_after_today = len(upcoming_starts)
    total_starts_remaining = starts_today + starts_after_today
    ratio_exposure = compute_ratio_exposure(total_starts_remaining)

    # SP-specific cat_states for decision logic
    sp_cat_states = {c: cat_states.get(c, "losing_close") for c in SP_AFFECTED_CATS}

    # Step 3: Build recommendations for today's starters
    recommendations = []
    for starter in todays_starters:
        tier = starter.get("tier", "sit")
        raw = starter.get("pitcherlist_raw", "")
        opp = starter.get("opponent", "???")
        score = starter.get("score", 0)

        rec = decide_recommendation(tier, sp_cat_states, ratio_exposure)
        rationale = generate_rationale(
            pitcherlist_raw=raw,
            opponent=opp,
            recommendation=rec,
            pitcherlist_tier=tier,
            cats=sp_cat_states,
            ratio_exposure=ratio_exposure,
            starts_remaining=total_starts_remaining,
        )

        recommendations.append({
            "pitcher_name": starter.get("pitcher_name"),
            "matchup": f"vs. {opp}",
            "pitcherlist_tier": tier,
            "pitcherlist_score": score,
            "pitcherlist_raw": raw,
            "our_recommendation": rec,
            "rationale": rationale,
        })

    # Step 4: Off-day pitchers (already computed by get_rankings_for_date)
    off_day_pitchers = off_day_raw

    # Step 5: Compute W/L/T from RAW values
    wins = 0
    losses = 0
    ties = 0
    for cat, vals in matchup_categories.items():
        yours = vals["yours"]
        theirs = vals["theirs"]
        if cat in LOWER_IS_BETTER:
            if yours < theirs:
                wins += 1
            elif yours > theirs:
                losses += 1
            else:
                ties += 1
        else:
            if yours > theirs:
                wins += 1
            elif yours < theirs:
                losses += 1
            else:
                ties += 1

    overall = f"W{wins} - L{losses} - T{ties}"

    # Build category summary
    categories_summary = {
        cat: {
            "yours": vals["yours"],
            "theirs": vals["theirs"],
            "status": cat_states[cat],
        }
        for cat, vals in matchup_categories.items()
    }

    # Step 6: Compute streaming options (unrostered pitchers with good ratings)
    # Use streaming-specific dates (targeting tomorrow, since waiver claims
    # process overnight — no point showing today's streamers)
    streamers = []
    if all_rostered_names:
        s_target = streaming_target_date or today_date
        s_end = streaming_end_date or matchup_end_date
        streamers = get_streaming_options(
            all_rostered_names=all_rostered_names,
            target_date=s_target,
            matchup_end_date=s_end,
        )

    return {
        "matchup_summary": {
            "opponent": opponent_name,
            "categories": categories_summary,
            "days_remaining": days_remaining,
            "overall": overall,
            "starts_today": starts_today,
            "starts_remaining_after_today": starts_after_today,
            "ratio_exposure": ratio_exposure,
        },
        "upcoming_starts": [
            {
                "date": p.get("date"),
                "pitcher_name": p.get("pitcher_name"),
                "opponent": p.get("opponent"),
                "pitcherlist_raw": p.get("pitcherlist_raw"),
            }
            for p in upcoming_starts
        ],
        "recommendations": recommendations,
        "off_day_pitchers": off_day_pitchers,
        "streamers": streamers,
    }
