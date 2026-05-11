"""Compute per-player skill-change baselines: deltas vs prior season,
composite z-scores, and sustainability scores.

The Stealth Breakouts view ranks players by ``skill_change_zscore``.
The Hot + Sustainable view filters/sorts using ``sustainability_score``.
"""

from __future__ import annotations

import logging
import math
from typing import Optional

from backend.database import get_connection

logger = logging.getLogger(__name__)

# League averages — refreshed annually, hardcoded constants are fine.
LEAGUE_AVG_BARREL_PCT = 7.0
LEAGUE_AVG_HARD_HIT_PCT = 35.0
LEAGUE_AVG_WHIFF_PCT = 25.0
LEAGUE_AVG_CSW_PCT = 28.0
LEAGUE_AVG_BB_PCT = 8.5
LEAGUE_AVG_K_PCT = 22.0
LEAGUE_AVG_XWOBA = 0.320
LEAGUE_AVG_XERA = 4.10
LEAGUE_AVG_SPRINT_SPEED = 27.0
LEAGUE_AVG_CHASE_RATE = 30.0

# Z-score weights for skill-change aggregation
HITTER_WEIGHTS = {
    "delta_xwoba": 3.0,
    "delta_barrel_pct": 2.0,
    "delta_hard_hit_pct": 1.5,
    "delta_sprint_speed": 1.0,
}
PITCHER_WEIGHTS = {
    "delta_xera": 3.0,
    "delta_whiff_pct": 2.0,
    "delta_k_minus_bb_pct": 2.0,
    "delta_chase_rate": 1.0,
}


def _league_avg_for(metric: str) -> float:
    return {
        "xwoba": LEAGUE_AVG_XWOBA,
        "barrel_pct": LEAGUE_AVG_BARREL_PCT,
        "hard_hit_pct": LEAGUE_AVG_HARD_HIT_PCT,
        "sprint_speed": LEAGUE_AVG_SPRINT_SPEED,
        "xera": LEAGUE_AVG_XERA,
        "whiff_pct": LEAGUE_AVG_WHIFF_PCT,
        "k_pct": LEAGUE_AVG_K_PCT,
        "bb_pct": LEAGUE_AVG_BB_PCT,
        "chase_rate": LEAGUE_AVG_CHASE_RATE,
    }.get(metric, 0.0)


def compute_metric_deltas(
    current: dict[str, Optional[float]],
    prior: Optional[dict[str, Optional[float]]],
    player_type: str,
) -> dict[str, Optional[float]]:
    """Compute current-season vs baseline deltas for one player.

    ``prior`` is the player's prior-season Statcast row. If None or empty for
    the player_type's metrics, falls back to league averages and records
    ``baseline_source = 'league_avg'``.
    """
    metrics_for_type = {
        "hitter": ["xwoba", "barrel_pct", "hard_hit_pct", "sprint_speed"],
        "pitcher": ["xera", "whiff_pct", "k_pct", "bb_pct", "chase_rate"],
    }[player_type]

    if prior is not None and any(prior.get(m) is not None for m in metrics_for_type):
        baseline_source = "prior_season"
    else:
        baseline_source = "league_avg"

    out: dict[str, Optional[float]] = {"baseline_source": baseline_source}
    for m in metrics_for_type:
        cur_v = current.get(m)
        if cur_v is None:
            out[f"delta_{m}"] = None
            continue
        if baseline_source == "prior_season" and prior is not None and prior.get(m) is not None:
            base_v = prior[m]
        else:
            base_v = _league_avg_for(m)
        out[f"delta_{m}"] = cur_v - base_v
    return out


def compute_skill_change_zscore(
    deltas: dict[str, Optional[float]],
    pop_stats: dict[str, tuple[float, float]],
    player_type: str,
) -> Optional[float]:
    """Aggregate per-metric deltas into one weighted z-score.

    For pitchers, ``delta_xera`` is inverted (negative xERA delta = improving =
    good); ``delta_bb_pct`` is also inverted in the K%-BB% composite. Hitters:
    all metrics are "higher is better".
    """
    if player_type == "hitter":
        components = []
        for metric, weight in HITTER_WEIGHTS.items():
            if deltas.get(metric) is None or metric not in pop_stats:
                continue
            mean, sd = pop_stats[metric]
            if sd <= 0:
                continue
            z = (deltas[metric] - mean) / sd
            components.append((z, weight))
        if not components:
            return None
        total_w = sum(w for _, w in components)
        return sum(z * w for z, w in components) / total_w if total_w > 0 else None

    # Pitcher
    components: list[tuple[float, float]] = []
    if deltas.get("delta_xera") is not None and "delta_xera" in pop_stats:
        mean, sd = pop_stats["delta_xera"]
        if sd > 0:
            z = (deltas["delta_xera"] - mean) / sd
            components.append((-z, PITCHER_WEIGHTS["delta_xera"]))  # invert

    if deltas.get("delta_whiff_pct") is not None and "delta_whiff_pct" in pop_stats:
        mean, sd = pop_stats["delta_whiff_pct"]
        if sd > 0:
            z = (deltas["delta_whiff_pct"] - mean) / sd
            components.append((z, PITCHER_WEIGHTS["delta_whiff_pct"]))

    # K% - BB%: avg the K% z-score and the (inverted) BB% z-score
    k_z = None
    bb_z = None
    if deltas.get("delta_k_pct") is not None and "delta_k_pct" in pop_stats:
        mean, sd = pop_stats["delta_k_pct"]
        if sd > 0:
            k_z = (deltas["delta_k_pct"] - mean) / sd
    if deltas.get("delta_bb_pct") is not None and "delta_bb_pct" in pop_stats:
        mean, sd = pop_stats["delta_bb_pct"]
        if sd > 0:
            bb_z = -(deltas["delta_bb_pct"] - mean) / sd  # invert: lower BB is better
    pieces = [v for v in (k_z, bb_z) if v is not None]
    if pieces:
        components.append((sum(pieces) / len(pieces), PITCHER_WEIGHTS["delta_k_minus_bb_pct"]))

    if deltas.get("delta_chase_rate") is not None and "delta_chase_rate" in pop_stats:
        mean, sd = pop_stats["delta_chase_rate"]
        if sd > 0:
            z = (deltas["delta_chase_rate"] - mean) / sd
            components.append((z, PITCHER_WEIGHTS["delta_chase_rate"]))

    if not components:
        return None
    total_w = sum(w for _, w in components)
    return sum(z * w for z, w in components) / total_w if total_w > 0 else None


def compute_sustainability_score(
    current: dict[str, Optional[float]],
    player_type: str,
) -> float:
    """0-100 composite that surface stats are likely to hold up.

    Hitters: rewards positive xwOBA-wOBA gap, above-avg barrel%, above-avg
    hard-hit%. Pitchers: rewards xERA below ERA, above-avg whiff%, above-avg
    CSW%, below-avg BB%.

    Returns 0 when essential metrics are missing.
    """
    if player_type == "hitter":
        xwoba = current.get("xwoba")
        woba = current.get("woba")
        barrel = current.get("barrel_pct")
        hard_hit = current.get("hard_hit_pct")
        if xwoba is None or woba is None or barrel is None or hard_hit is None:
            return 0.0
        gap = xwoba - woba
        gap_score = 50 + (gap / 0.005) * 10
        gap_score = max(0.0, min(100.0, gap_score))
        barrel_score = 50 + (barrel - LEAGUE_AVG_BARREL_PCT) * 5
        barrel_score = max(0.0, min(100.0, barrel_score))
        hard_hit_score = 50 + (hard_hit - LEAGUE_AVG_HARD_HIT_PCT) * 2.5
        hard_hit_score = max(0.0, min(100.0, hard_hit_score))
        return round((gap_score + barrel_score + hard_hit_score) / 3, 1)

    # Pitcher
    xera = current.get("xera")
    era = current.get("era")
    whiff = current.get("whiff_pct")
    csw = current.get("csw_pct")
    bb = current.get("bb_pct")
    if xera is None or era is None or whiff is None or csw is None or bb is None:
        return 0.0
    gap = era - xera  # positive when xera below era (good for pitcher)
    gap_score = 50 + (gap / 0.20) * 10
    gap_score = max(0.0, min(100.0, gap_score))
    whiff_score = 50 + (whiff - LEAGUE_AVG_WHIFF_PCT) * 4
    whiff_score = max(0.0, min(100.0, whiff_score))
    csw_score = 50 + (csw - LEAGUE_AVG_CSW_PCT) * 4
    csw_score = max(0.0, min(100.0, csw_score))
    bb_score = 50 + (LEAGUE_AVG_BB_PCT - bb) * 6
    bb_score = max(0.0, min(100.0, bb_score))
    return round((gap_score + whiff_score + csw_score + bb_score) / 4, 1)


# Qualification thresholds
MIN_PA_HITTER = 80
MIN_IP_PITCHER = 25.0


def _population_stats(values: list[float]) -> tuple[float, float]:
    """Return (mean, sd) for a list of floats. SD is sample stdev."""
    n = len(values)
    if n < 2:
        return (0.0, 0.0)
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return (mean, math.sqrt(var))


def compute_skill_baselines(season: int) -> None:
    """Compute and persist per-player skill baselines for the current season.

    Writes to ``statcast_baselines``. Idempotent — re-running overwrites the
    row for each (mlb_id, season).
    """
    conn = get_connection()
    try:
        # Load current and prior season Statcast tables
        cur_bat = {r["mlb_id"]: dict(r) for r in conn.execute(
            "SELECT * FROM statcast_batting WHERE season = ?", (season,)
        ).fetchall()}
        prior_bat = {r["mlb_id"]: dict(r) for r in conn.execute(
            "SELECT * FROM statcast_batting WHERE season = ?", (season - 1,)
        ).fetchall()}
        cur_pit = {r["mlb_id"]: dict(r) for r in conn.execute(
            "SELECT * FROM statcast_pitching WHERE season = ?", (season,)
        ).fetchall()}
        prior_pit = {r["mlb_id"]: dict(r) for r in conn.execute(
            "SELECT * FROM statcast_pitching WHERE season = ?", (season - 1,)
        ).fetchall()}

        pa_by_id = {r["mlb_id"]: r["plate_appearances"] for r in conn.execute(
            "SELECT mlb_id, plate_appearances FROM batting_stats WHERE season = ?", (season,)
        ).fetchall()}
        ip_by_id = {r["mlb_id"]: r["innings_pitched"] for r in conn.execute(
            "SELECT mlb_id, innings_pitched FROM pitching_stats WHERE season = ?", (season,)
        ).fetchall()}

        # First pass: compute deltas for everyone, accumulate populations for z-score normalization
        hitter_rows: list[tuple[int, dict, str]] = []
        pitcher_rows: list[tuple[int, dict, str]] = []
        hitter_population: dict[str, list[float]] = {k: [] for k in HITTER_WEIGHTS}
        pitcher_population: dict[str, list[float]] = {
            "delta_xera": [], "delta_whiff_pct": [],
            "delta_k_pct": [], "delta_bb_pct": [], "delta_chase_rate": [],
        }

        for mid, cur in cur_bat.items():
            prior = prior_bat.get(mid)
            deltas = compute_metric_deltas(cur, prior, player_type="hitter")
            for k in HITTER_WEIGHTS:
                v = deltas.get(k)
                if v is not None:
                    hitter_population[k].append(v)
            hitter_rows.append((mid, {**cur, **deltas}, deltas.get("baseline_source", "league_avg")))

        for mid, cur in cur_pit.items():
            prior = prior_pit.get(mid)
            deltas = compute_metric_deltas(cur, prior, player_type="pitcher")
            for k in pitcher_population:
                v = deltas.get(k)
                if v is not None:
                    pitcher_population[k].append(v)
            pitcher_rows.append((mid, {**cur, **deltas}, deltas.get("baseline_source", "league_avg")))

        hitter_pop_stats = {k: _population_stats(v) for k, v in hitter_population.items()}
        pitcher_pop_stats = {k: _population_stats(v) for k, v in pitcher_population.items()}

        for mid, payload, source in hitter_rows:
            pa = pa_by_id.get(mid, 0) or 0
            qualifies = 1 if pa >= MIN_PA_HITTER else 0
            z = compute_skill_change_zscore(payload, hitter_pop_stats, "hitter") if qualifies else None
            sustain = compute_sustainability_score(payload, "hitter") if qualifies else 0.0
            conn.execute(
                """INSERT INTO statcast_baselines
                   (mlb_id, season, player_type,
                    delta_xwoba, delta_barrel_pct, delta_hard_hit_pct, delta_sprint_speed,
                    delta_xera, delta_whiff_pct, delta_k_pct, delta_bb_pct, delta_chase_rate,
                    skill_change_zscore, sustainability_score, baseline_source, qualifies_pa_ip)
                   VALUES (?, ?, ?,
                           ?, ?, ?, ?,
                           ?, ?, ?, ?, ?,
                           ?, ?, ?, ?)
                   ON CONFLICT (mlb_id, season) DO UPDATE SET
                     player_type = EXCLUDED.player_type,
                     delta_xwoba = EXCLUDED.delta_xwoba,
                     delta_barrel_pct = EXCLUDED.delta_barrel_pct,
                     delta_hard_hit_pct = EXCLUDED.delta_hard_hit_pct,
                     delta_sprint_speed = EXCLUDED.delta_sprint_speed,
                     skill_change_zscore = EXCLUDED.skill_change_zscore,
                     sustainability_score = EXCLUDED.sustainability_score,
                     baseline_source = EXCLUDED.baseline_source,
                     qualifies_pa_ip = EXCLUDED.qualifies_pa_ip""",
                (
                    mid, season, "hitter",
                    payload.get("delta_xwoba"), payload.get("delta_barrel_pct"),
                    payload.get("delta_hard_hit_pct"), payload.get("delta_sprint_speed"),
                    None, None, None, None, None,
                    z, sustain, source, qualifies,
                ),
            )

        for mid, payload, source in pitcher_rows:
            ip = ip_by_id.get(mid, 0.0) or 0.0
            qualifies = 1 if ip >= MIN_IP_PITCHER else 0
            z = compute_skill_change_zscore(payload, pitcher_pop_stats, "pitcher") if qualifies else None
            sustain = compute_sustainability_score(payload, "pitcher") if qualifies else 0.0
            conn.execute(
                """INSERT INTO statcast_baselines
                   (mlb_id, season, player_type,
                    delta_xwoba, delta_barrel_pct, delta_hard_hit_pct, delta_sprint_speed,
                    delta_xera, delta_whiff_pct, delta_k_pct, delta_bb_pct, delta_chase_rate,
                    skill_change_zscore, sustainability_score, baseline_source, qualifies_pa_ip)
                   VALUES (?, ?, ?,
                           ?, ?, ?, ?,
                           ?, ?, ?, ?, ?,
                           ?, ?, ?, ?)
                   ON CONFLICT (mlb_id, season) DO UPDATE SET
                     player_type = EXCLUDED.player_type,
                     delta_xera = EXCLUDED.delta_xera,
                     delta_whiff_pct = EXCLUDED.delta_whiff_pct,
                     delta_k_pct = EXCLUDED.delta_k_pct,
                     delta_bb_pct = EXCLUDED.delta_bb_pct,
                     delta_chase_rate = EXCLUDED.delta_chase_rate,
                     skill_change_zscore = EXCLUDED.skill_change_zscore,
                     sustainability_score = EXCLUDED.sustainability_score,
                     baseline_source = EXCLUDED.baseline_source,
                     qualifies_pa_ip = EXCLUDED.qualifies_pa_ip""",
                (
                    mid, season, "pitcher",
                    None, None, None, None,
                    payload.get("delta_xera"), payload.get("delta_whiff_pct"),
                    payload.get("delta_k_pct"), payload.get("delta_bb_pct"),
                    payload.get("delta_chase_rate"),
                    z, sustain, source, qualifies,
                ),
            )

        logger.info(
            f"Skill baselines computed: {len(hitter_rows)} hitters, {len(pitcher_rows)} pitchers"
        )
        conn.commit()
    finally:
        conn.close()
