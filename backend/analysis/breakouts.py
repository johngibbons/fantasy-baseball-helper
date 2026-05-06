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


from backend.analysis.waivers import (
    PlayerProjection,
    TeamTotals,
    HITTER_BENCH_WEIGHT,
    IL_WEIGHT,
    IL_SLOT_THRESHOLD,
    ALL_CATS,
    INVERTED_CATS,
    build_team_totals,
    compute_expected_wins,
    assign_faab_bids,
    WaiverRecommendation,
)


def _badge_for_metric(value: Optional[float], population: list[float]) -> str:
    """Color-code a metric vs the current population's distribution."""
    if value is None or not population:
        return "gray"
    sorted_pop = sorted(population)
    n = len(sorted_pop)
    rank = sum(1 for v in sorted_pop if v < value)
    pct = rank / n
    if pct >= 0.60:
        return "green"
    if pct >= 0.40:
        return "yellow"
    return "red"


def _build_badges(statcast: dict, player_type: str,
                  population: dict[str, list[float]]) -> dict[str, str]:
    if player_type == "hitter":
        return {
            "xwoba_gap": _badge_for_metric(
                (statcast.get("xwoba") or 0) - (statcast.get("woba") or 0)
                if statcast.get("xwoba") is not None and statcast.get("woba") is not None
                else None,
                population.get("xwoba_gap", []),
            ),
            "barrel_pct": _badge_for_metric(statcast.get("barrel_pct"), population.get("barrel_pct", [])),
            "hard_hit_pct": _badge_for_metric(statcast.get("hard_hit_pct"), population.get("hard_hit_pct", [])),
            "sprint_speed": _badge_for_metric(statcast.get("sprint_speed"), population.get("sprint_speed", [])),
        }
    return {
        "xera_gap": _badge_for_metric(
            (statcast.get("era") or 0) - (statcast.get("xera") or 0)
            if statcast.get("xera") is not None and statcast.get("era") is not None
            else None,
            population.get("xera_gap", []),
        ),
        "whiff_pct": _badge_for_metric(statcast.get("whiff_pct"), population.get("whiff_pct", [])),
        "csw_pct": _badge_for_metric(statcast.get("csw_pct"), population.get("csw_pct", [])),
        "bb_pct": _badge_for_metric(statcast.get("bb_pct"), population.get("bb_pct", []), ),
    }


def _build_population_dist(statcast_by_id: dict[int, dict],
                           player_type: str) -> dict[str, list[float]]:
    """Build per-metric value lists for badge percentile computation."""
    pop: dict[str, list[float]] = {}
    if player_type == "hitter":
        keys = [("xwoba_gap", lambda s: (s.get("xwoba") - s.get("woba"))
                 if s.get("xwoba") is not None and s.get("woba") is not None else None),
                ("barrel_pct", lambda s: s.get("barrel_pct")),
                ("hard_hit_pct", lambda s: s.get("hard_hit_pct")),
                ("sprint_speed", lambda s: s.get("sprint_speed"))]
    else:
        keys = [("xera_gap", lambda s: (s.get("era") - s.get("xera"))
                 if s.get("xera") is not None and s.get("era") is not None else None),
                ("whiff_pct", lambda s: s.get("whiff_pct")),
                ("csw_pct", lambda s: s.get("csw_pct")),
                ("bb_pct", lambda s: s.get("bb_pct"))]
    for k, fn in keys:
        pop[k] = [v for v in (fn(s) for s in statcast_by_id.values()) if v is not None]
    return pop


def _build_proj_from_prorated(
    mlb_id: int,
    name: str,
    base_proj: PlayerProjection,
    prorated: dict,
    player_type: str,
) -> PlayerProjection:
    """Build a PlayerProjection that uses the prorated rolling-window pace."""
    return PlayerProjection(
        mlb_id=mlb_id, name=name,
        position=base_proj.position,
        player_type=player_type,
        eligible_positions=base_proj.eligible_positions,
        overall_rank=base_proj.overall_rank,
        pa=int(prorated.get("pa", 0)),
        r=int(prorated.get("r", 0)),
        tb=int(prorated.get("tb", 0)),
        rbi=int(prorated.get("rbi", 0)),
        sb=int(prorated.get("sb", 0)),
        obp=float(prorated.get("obp", 0.0)),
        ip=float(prorated.get("ip", 0.0)),
        k=int(prorated.get("k", 0)),
        qs=int(prorated.get("qs", 0)),
        era=float(prorated.get("era", 0.0)),
        whip=float(prorated.get("whip", 0.0)),
        svhd=int(prorated.get("svhd", 0)),
    )


def compute_hot_view(
    my_roster_ids: list[int],
    my_roster_slots: list[dict],
    all_team_roster_slots: list[list[dict]],
    free_agent_ids: list[int],
    projections: dict[int, PlayerProjection],
    rolling_stats_by_id: dict[int, dict],
    statcast_by_id: dict[int, dict],
    games_in_window: int,
    games_remaining: int,
    remaining_faab: float = 100.0,
) -> dict:
    """Hot + Sustainable view: rank candidates by wins added if their recent
    pace continues, filtered by sustainability checks.
    """
    # Build my baseline using existing projections (steady-state expectation)
    my_totals, _ = build_team_totals(my_roster_slots, projections)
    other_team_totals = []
    for slots in all_team_roster_slots:
        tt, _ = build_team_totals(slots, projections)
        other_team_totals.append(tt)

    my_cat_values = my_totals.category_values()
    other_cat_values = [t.category_values() for t in other_team_totals]
    baseline_wins, baseline_cat_probs = compute_expected_wins(my_cat_values, other_cat_values)

    droppable_ids = [
        s["mlb_id"] for s in my_roster_slots
        if s.get("lineup_slot_id", 0) < IL_SLOT_THRESHOLD
    ]

    hitter_statcast = {pid: s for pid, s in statcast_by_id.items()
                       if projections.get(pid) and projections[pid].player_type == "hitter"}
    pitcher_statcast = {pid: s for pid, s in statcast_by_id.items()
                        if projections.get(pid) and projections[pid].player_type == "pitcher"}
    hitter_pop = _build_population_dist(hitter_statcast, "hitter")
    pitcher_pop = _build_population_dist(pitcher_statcast, "pitcher")

    recommendations: list[BreakoutRecommendation] = []

    for fa_id in free_agent_ids:
        fa_proj = projections.get(fa_id)
        rolling = rolling_stats_by_id.get(fa_id)
        statcast = statcast_by_id.get(fa_id, {})
        if fa_proj is None or rolling is None:
            continue

        ptype = fa_proj.player_type
        if not sustainability_filter_passes(statcast, ptype):
            continue

        prorated = prorate_window_to_ros(rolling, ptype, games_in_window, games_remaining)
        if not prorated:
            continue

        hot_proj = _build_proj_from_prorated(fa_id, fa_proj.name, fa_proj, prorated, ptype)

        best_drop_id: Optional[int] = None
        best_delta: float = float("-inf")
        for drop_id in droppable_ids:
            drop_proj = projections.get(drop_id)
            if drop_proj is None or drop_proj.player_type != ptype:
                continue
            trial_slots = [s for s in my_roster_slots if s["mlb_id"] != drop_id]
            trial_slots.append({"mlb_id": fa_id, "lineup_slot_id": 0})
            trial_projections = dict(projections)
            trial_projections[fa_id] = hot_proj
            trial_totals, _ = build_team_totals(trial_slots, trial_projections)
            trial_wins, _ = compute_expected_wins(
                trial_totals.category_values(), other_cat_values
            )
            delta = trial_wins - baseline_wins
            if delta > best_delta:
                best_delta = delta
                best_drop_id = drop_id

        if best_drop_id is None or best_delta <= 0.01:
            continue

        drop_proj = projections.get(best_drop_id)
        pop = hitter_pop if ptype == "hitter" else pitcher_pop
        badges = _build_badges(statcast, ptype, pop)
        from backend.analysis.skill_baselines import compute_sustainability_score
        sustain = compute_sustainability_score(statcast, ptype)

        recommendations.append(BreakoutRecommendation(
            rank=0,
            add_player={
                "id": fa_id, "name": fa_proj.name,
                "position": fa_proj.eligible_positions or fa_proj.position,
                "team": "",
                "roster_status": "FA",
            },
            drop_player={
                "id": best_drop_id, "name": drop_proj.name if drop_proj else "",
                "position": (drop_proj.eligible_positions or drop_proj.position)
                            if drop_proj else "",
            } if drop_proj else None,
            wins_added_if_rate_continues=round(best_delta, 4),
            sustainability_badges=badges,
            sustainability_score=sustain,
            window_stats=rolling,
        ))

    recommendations.sort(
        key=lambda r: (
            -(r.wins_added_if_rate_continues or 0),
            -(r.sustainability_score or 0),
        )
    )
    for i, r in enumerate(recommendations):
        r.rank = i + 1

    waiver_recs = [
        WaiverRecommendation(
            add_player_id=r.add_player["id"],
            add_player_name=r.add_player["name"],
            add_player_position=r.add_player["position"],
            drop_player_id=r.drop_player["id"] if r.drop_player else None,
            drop_player_name=r.drop_player["name"] if r.drop_player else None,
            drop_player_position=r.drop_player["position"] if r.drop_player else None,
            delta_expected_wins=0.0,
            suggested_faab_bid=0,
            category_impact={}, category_stat_delta={},
            wins_added_if_rate_continues=r.wins_added_if_rate_continues,
        )
        for r in recommendations
    ]
    assign_faab_bids(waiver_recs, remaining_faab,
                     metric_attr="wins_added_if_rate_continues")
    for r, w in zip(recommendations, waiver_recs):
        r.suggested_faab_bid = w.suggested_faab_bid

    return {
        "baseline_expected_wins": round(baseline_wins, 3),
        "baseline_category_probs": {cat: round(v, 4) for cat, v in baseline_cat_probs.items()},
        "recommendations": recommendations,
    }
