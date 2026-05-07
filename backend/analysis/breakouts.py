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

# Hot-pace dampening
PRORATION_CAP = 3.0          # Max factor when extrapolating window pace forward.
HOT_BLEND_ALPHA = 0.3        # Weight on hot pace vs ATC RoS (0=ATC only, 1=pure hot).


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

    Counting stats scale by ``min(games_remaining / games_in_window, PRORATION_CAP)``
    so a tiny window can't drive a 10× extrapolation. Rate stats (OBP, ERA,
    WHIP, batting_avg, etc.) carry through unchanged.
    """
    if games_in_window <= 0 or games_remaining <= 0:
        return {}
    factor = min(games_remaining / games_in_window, PRORATION_CAP)

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


def _blend_with_atc(
    prorated: dict,
    base_proj: PlayerProjection,
    alpha: float = HOT_BLEND_ALPHA,
) -> dict:
    """Blend prorated hot-pace stats with the ATC RoS projection.

    Counting stats are blended directly: ``alpha * hot + (1-alpha) * atc``.
    Rate stats (OBP, ERA, WHIP) are PA/IP-weighted so a tiny hot window can't
    swing the rate (e.g., 5 PA at 1.000 OBP shouldn't override 472 PA at .317).
    """
    if not prorated:
        return prorated

    # If ATC has no meaningful volume, skip blend — there's nothing to blend
    # against, and a zero ATC would otherwise crater the rate stats.
    has_atc_volume = (
        base_proj.pa > 0 if base_proj.player_type == "hitter" else base_proj.ip > 0
    )
    if not has_atc_volume:
        return prorated

    def _blend_count(hot_v: float, atc_v: float) -> float:
        return alpha * hot_v + (1 - alpha) * atc_v

    def _blend_rate(hot_v: float, hot_vol: float, atc_v: float, atc_vol: float) -> float:
        w_hot = alpha * hot_vol
        w_atc = (1 - alpha) * atc_vol
        denom = w_hot + w_atc
        if denom <= 0:
            return atc_v
        return (w_hot * hot_v + w_atc * atc_v) / denom

    if base_proj.player_type == "hitter":
        hot_pa = prorated.get("pa", 0)
        return {
            "pa": _blend_count(hot_pa, base_proj.pa),
            "r": _blend_count(prorated.get("r", 0), base_proj.r),
            "tb": _blend_count(prorated.get("tb", 0), base_proj.tb),
            "rbi": _blend_count(prorated.get("rbi", 0), base_proj.rbi),
            "sb": _blend_count(prorated.get("sb", 0), base_proj.sb),
            "obp": _blend_rate(
                prorated.get("obp", 0.0), hot_pa,
                base_proj.obp, base_proj.pa,
            ),
        }

    hot_ip = prorated.get("ip", 0.0)
    return {
        "ip": _blend_count(hot_ip, base_proj.ip),
        "k": _blend_count(prorated.get("k", 0), base_proj.k),
        "qs": _blend_count(prorated.get("qs", 0), base_proj.qs),
        "svhd": _blend_count(prorated.get("svhd", 0), base_proj.svhd),
        "era": _blend_rate(
            prorated.get("era", 0.0), hot_ip,
            base_proj.era, base_proj.ip,
        ),
        "whip": _blend_rate(
            prorated.get("whip", 0.0), hot_ip,
            base_proj.whip, base_proj.ip,
        ),
    }


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


def _build_hot_blended_proj(
    mlb_id: int,
    base_proj: PlayerProjection,
    rolling: dict,
    games_in_window: int,
    games_remaining: int,
) -> Optional[PlayerProjection]:
    """Compose prorate + blend + build into a single hot-blended projection.

    Returns None if proration produced no usable values.
    """
    prorated = prorate_window_to_ros(
        rolling, base_proj.player_type, games_in_window, games_remaining,
    )
    if not prorated:
        return None
    blended = _blend_with_atc(prorated, base_proj)
    return _build_proj_from_prorated(
        mlb_id, base_proj.name, base_proj, blended, base_proj.player_type,
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

    Symmetric proration: any player (rostered or FA) with rolling-window stats
    is valued at a blend of their hot pace and ATC RoS. This avoids the bias
    where a hot FA's prorated counting stats dwarf a rostered player's plain
    ATC line.
    """
    # Build a hot-blended projection for every player with rolling stats.
    # Used for BOTH baseline and trial computations so the comparison is fair.
    hot_projections: dict[int, PlayerProjection] = {}
    for pid, rolling in rolling_stats_by_id.items():
        base = projections.get(pid)
        if base is None:
            continue
        blended = _build_hot_blended_proj(
            pid, base, rolling, games_in_window, games_remaining,
        )
        if blended is not None:
            hot_projections[pid] = blended

    # Effective projections override ATC with hot-blended where available
    effective_projections = {**projections, **hot_projections}

    my_totals, _ = build_team_totals(my_roster_slots, effective_projections)
    other_team_totals = []
    for slots in all_team_roster_slots:
        tt, _ = build_team_totals(slots, effective_projections)
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

        # FA must have a hot-blended projection (skipped above only when
        # proration produced nothing usable).
        if fa_id not in hot_projections:
            continue

        best_drop_id: Optional[int] = None
        best_delta: float = float("-inf")
        for drop_id in droppable_ids:
            drop_proj = effective_projections.get(drop_id)
            if drop_proj is None or drop_proj.player_type != ptype:
                continue
            trial_slots = [s for s in my_roster_slots if s["mlb_id"] != drop_id]
            trial_slots.append({"mlb_id": fa_id, "lineup_slot_id": 0})
            trial_totals, _ = build_team_totals(trial_slots, effective_projections)
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


def _format_headline_delta(baseline: dict) -> Optional[dict]:
    """Pick the largest single-metric jump as a headline."""
    candidates = []
    for k, label in [
        ("delta_xwoba", "xwOBA"),
        ("delta_barrel_pct", "barrel%"),
        ("delta_hard_hit_pct", "hard-hit%"),
        ("delta_sprint_speed", "sprint speed"),
        ("delta_xera", "xERA"),
        ("delta_whiff_pct", "whiff%"),
        ("delta_k_pct", "K%"),
        ("delta_bb_pct", "BB%"),
        ("delta_chase_rate", "chase%"),
    ]:
        v = baseline.get(k)
        if v is None:
            continue
        # Normalize for "magnitude of improvement" — invert xera and bb_pct
        magnitude = -v if k in ("delta_xera", "delta_bb_pct") else v
        candidates.append((magnitude, k, label, v))
    if not candidates:
        return None
    candidates.sort(key=lambda t: -t[0])
    _, key, label, raw_value = candidates[0]
    sign = "+" if raw_value > 0 else ""
    return {
        "metric": key,
        "label": f"{sign}{round(raw_value, 2)} {label}",
    }


def compute_stealth_view(
    baselines: list[dict],
    player_meta: dict[int, dict],
    roster_status_by_id: dict[int, str],
    current_stats: dict[int, dict],
    proj_stats: dict[int, dict],
    scope: str = "FA",
    position_filter: Optional[str] = None,
    player_type_filter: Optional[str] = None,
    limit: int = 50,
) -> dict:
    """Stealth Breakouts: rank players by skill-change z-score.

    Inputs:
      baselines: rows from ``statcast_baselines`` (dicts).
      player_meta: mlb_id -> {"name", "team", "position"}.
      roster_status_by_id: mlb_id -> "FA" | "team_<id>" | "my_team".
      current_stats / proj_stats: mlb_id -> sparse dict with surface stats
        for the "current vs projection" footnote.
      scope: "FA" | "rostered" | "all".
      position_filter: e.g. "OF", or None for all.
      player_type_filter: "hitter" | "pitcher" | None.
    """
    filtered: list[dict] = []
    for b in baselines:
        if not b.get("qualifies_pa_ip"):
            continue
        if b.get("skill_change_zscore") is None:
            continue
        mid = b["mlb_id"]
        rs = roster_status_by_id.get(mid, "FA")
        if scope == "FA" and rs != "FA":
            continue
        if scope == "rostered" and rs == "FA":
            continue
        if player_type_filter and b.get("player_type") != player_type_filter:
            continue
        meta = player_meta.get(mid, {})
        if position_filter and position_filter != "All":
            if position_filter not in (meta.get("position") or ""):
                continue
        filtered.append(b)

    filtered.sort(key=lambda b: -(b["skill_change_zscore"] or 0))
    filtered = filtered[:limit]

    recommendations: list[BreakoutRecommendation] = []
    for i, b in enumerate(filtered):
        mid = b["mlb_id"]
        meta = player_meta.get(mid, {})
        rs = roster_status_by_id.get(mid, "FA")
        # Build metric_deltas with badges
        metric_deltas = {}
        for k in ("delta_xwoba", "delta_barrel_pct", "delta_hard_hit_pct",
                  "delta_sprint_speed", "delta_xera", "delta_whiff_pct",
                  "delta_k_pct", "delta_bb_pct", "delta_chase_rate"):
            v = b.get(k)
            if v is None:
                continue
            inverted = k in ("delta_xera", "delta_bb_pct")
            sign_value = -v if inverted else v
            if sign_value > 0.5:
                badge = "green"
            elif sign_value > -0.5:
                badge = "yellow"
            else:
                badge = "red"
            metric_deltas[k] = {"value": round(v, 3), "badge": badge}

        cur = current_stats.get(mid, {})
        proj = proj_stats.get(mid, {})
        current_vs_projection = {
            k: {"current": cur.get(k), "projected": proj.get(k)}
            for k in cur.keys()
            if proj.get(k) is not None
        }

        recommendations.append(BreakoutRecommendation(
            rank=i + 1,
            add_player={
                "id": mid, "name": meta.get("name", ""),
                "team": meta.get("team", ""),
                "position": meta.get("position", ""),
                "roster_status": rs,
            },
            skill_change_zscore=round(b["skill_change_zscore"], 3),
            headline_delta=_format_headline_delta(b),
            metric_deltas=metric_deltas,
            current_vs_projection=current_vs_projection,
            baseline_source=b.get("baseline_source"),
        ))

    return {"recommendations": recommendations}
