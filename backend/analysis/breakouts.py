"""Breakout finder engine — Hot + Sustainable view and Stealth Breakouts view.

Both views share data plumbing but produce independent rankings:
- Hot view ranks free agents/rostered players by MCW-extrapolated wins added
  if the recent window's pace continues, filtered by Statcast sustainability.
- Stealth view ranks players by a composite skill-change z-score derived
  from `statcast_baselines`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from backend.analysis.skill_baselines import (
    LEAGUE_AVG_BARREL_PCT,
    LEAGUE_AVG_HARD_HIT_PCT,
    LEAGUE_AVG_WHIFF_PCT,
    LEAGUE_AVG_CSW_PCT,
    LEAGUE_AVG_BB_PCT,
)

logger = logging.getLogger(__name__)

# Sustainability hard-filter thresholds
HITTER_XWOBA_TOLERANCE = 0.020       # xwOBA >= wOBA - 0.020
HITTER_BARREL_THRESHOLD_RATIO = 0.85
HITTER_HARD_HIT_THRESHOLD_RATIO = 0.95
HITTER_SPRINT_SPEED_THRESHOLD = 27.0
PITCHER_XERA_TOLERANCE = 0.50         # xERA <= ERA + 0.50
PITCHER_WHIFF_THRESHOLD_RATIO = 0.95
PITCHER_CSW_THRESHOLD_RATIO = 0.95
PITCHER_BB_THRESHOLD_RATIO = 1.20


@dataclass
class HotPlayer:
    """A candidate for the Hot view, with pro-rated stats and metric badges."""
    mlb_id: int
    name: str
    eligible_positions: str
    player_type: str
    window_stats: dict
    prorated_stats: dict
    sustainability_badges: dict[str, str]
    sustainability_score: float


@dataclass
class BreakoutRecommendation:
    """One breakout-engine result row.

    Hot rows include drop_player and wins_added_if_rate_continues.
    Stealth rows leave those None and use skill_change_zscore + metric_deltas.
    """
    rank: int
    add_player: dict
    drop_player: Optional[dict] = None
    wins_added_if_rate_continues: Optional[float] = None
    suggested_faab_bid: int = 0
    sustainability_badges: dict = field(default_factory=dict)
    sustainability_score: Optional[float] = None
    window_stats: Optional[dict] = None
    skill_change_zscore: Optional[float] = None
    headline_delta: Optional[dict] = None
    metric_deltas: dict = field(default_factory=dict)
    current_vs_projection: dict = field(default_factory=dict)
    baseline_source: Optional[str] = None
    roster_status: Optional[str] = None  # "FA" | "team_<id>" | "my_team"


def prorate_window_to_ros(
    window_stats: dict,
    player_type: str,
    games_in_window: int,
    games_remaining: int,
) -> dict:
    """Pro-rate a window's stats to the rest-of-season pace.

    Counting stats scale by ``games_remaining / games_in_window``. Rate stats
    (OBP, ERA, WHIP, batting_avg, etc.) carry through unchanged.
    """
    if games_in_window <= 0 or games_remaining <= 0:
        return {}
    factor = games_remaining / games_in_window

    if player_type == "hitter":
        return {
            "pa": window_stats.get("pa", 0) * factor,
            "ab": window_stats.get("ab", 0) * factor,
            "r": window_stats.get("r", 0) * factor,
            "h": window_stats.get("h", 0) * factor,
            "hr": window_stats.get("hr", 0) * factor,
            "rbi": window_stats.get("rbi", 0) * factor,
            "sb": window_stats.get("sb", 0) * factor,
            "bb": window_stats.get("bb", 0) * factor,
            "k": window_stats.get("k", 0) * factor,
            "tb": window_stats.get("total_bases", 0) * factor,
            "obp": window_stats.get("obp", 0.0),
            "slg": window_stats.get("slg", 0.0),
        }

    # Pitcher
    return {
        "ip": window_stats.get("ip", 0.0) * factor,
        "k": window_stats.get("k", 0) * factor,
        "bb": window_stats.get("bb", 0) * factor,
        "qs": window_stats.get("quality_starts", 0) * factor,
        "saves": window_stats.get("saves", 0) * factor,
        "holds": window_stats.get("holds", 0) * factor,
        "svhd": (window_stats.get("saves", 0) + window_stats.get("holds", 0)) * factor,
        "era": window_stats.get("era", 0.0),
        "whip": window_stats.get("whip", 0.0),
    }


def _sustainability_check_results(statcast: dict, player_type: str) -> list[Optional[bool]]:
    """Run the three core checks. Each returns True/False; None when data is missing."""
    if player_type == "hitter":
        # Check 1: xwOBA-wOBA gap
        xwoba = statcast.get("xwoba")
        woba = statcast.get("woba")
        gap_check = (xwoba >= woba - HITTER_XWOBA_TOLERANCE) if (xwoba is not None and woba is not None) else None

        # Check 2: barrel% OR hard_hit%
        barrel = statcast.get("barrel_pct")
        hard_hit = statcast.get("hard_hit_pct")
        barrel_ok = barrel is not None and barrel >= LEAGUE_AVG_BARREL_PCT * HITTER_BARREL_THRESHOLD_RATIO
        hard_hit_ok = hard_hit is not None and hard_hit >= LEAGUE_AVG_HARD_HIT_PCT * HITTER_HARD_HIT_THRESHOLD_RATIO
        if barrel is None and hard_hit is None:
            quality_check = None
        else:
            quality_check = barrel_ok or hard_hit_ok

        # Check 3: sprint speed
        sprint = statcast.get("sprint_speed")
        sprint_check = sprint >= HITTER_SPRINT_SPEED_THRESHOLD if sprint is not None else None

        return [gap_check, quality_check, sprint_check]

    # Pitcher
    xera = statcast.get("xera")
    era = statcast.get("era")
    xera_check = (xera <= era + PITCHER_XERA_TOLERANCE) if (xera is not None and era is not None) else None

    whiff = statcast.get("whiff_pct")
    csw = statcast.get("csw_pct")
    whiff_ok = whiff is not None and whiff >= LEAGUE_AVG_WHIFF_PCT * PITCHER_WHIFF_THRESHOLD_RATIO
    csw_ok = csw is not None and csw >= LEAGUE_AVG_CSW_PCT * PITCHER_CSW_THRESHOLD_RATIO
    if whiff is None and csw is None:
        whiff_csw_check = None
    else:
        whiff_csw_check = whiff_ok or csw_ok

    bb = statcast.get("bb_pct")
    bb_check = bb <= LEAGUE_AVG_BB_PCT * PITCHER_BB_THRESHOLD_RATIO if bb is not None else None

    return [xera_check, whiff_csw_check, bb_check]


def sustainability_filter_passes(statcast: dict, player_type: str) -> bool:
    """≥ 2 of 3 core checks must pass. Missing checks are excluded from the count.

    If only 2 checks are evaluable, both must pass. If only 1, it must pass.
    If none, the player fails.
    """
    checks = _sustainability_check_results(statcast, player_type)
    evaluable = [c for c in checks if c is not None]
    if not evaluable:
        return False
    passed = sum(1 for c in evaluable if c)
    if len(evaluable) == 3:
        return passed >= 2
    # When fewer checks are evaluable, require all of them to pass
    return passed == len(evaluable)
