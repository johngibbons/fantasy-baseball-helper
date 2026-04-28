"""Projection vs. actual performance analysis.

Joins rankings (preseason projections) with batting_stats / pitching_stats
(season-to-date actuals) and computes volume + rate deltas per category.

Volume framing: actual vs. (full-season projection × season-elapsed fraction).
Rate framing:   per-PA / per-IP rate of actual vs. per-PA / per-IP rate of projection.
"""

from typing import Literal

from backend.database import get_connection

HITTER_COUNTING_CATS = ["r", "tb", "rbi", "sb"]
PITCHER_COUNTING_CATS = ["k", "qs", "svhd"]


def _safe_div(num, denom):
    if not denom:
        return None
    try:
        return num / denom
    except (TypeError, ZeroDivisionError):
        return None


def _delta(actual, expected):
    if actual is None or expected is None:
        return None
    return actual - expected


def compute_hitter_performance(season: int, season_elapsed_fraction: float) -> list[dict]:
    """Return one row per ranked hitter for the given season."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT
            r.mlb_id, r.overall_rank, r.position_rank,
            r.proj_pa, r.proj_r, r.proj_tb, r.proj_rbi, r.proj_sb, r.proj_obp,
            p.full_name, p.primary_position, p.team, p.eligible_positions,
            b.games AS a_g,
            b.plate_appearances AS a_pa,
            b.runs AS a_r,
            b.total_bases AS a_tb,
            b.rbi AS a_rbi,
            b.stolen_bases AS a_sb,
            b.obp AS a_obp,
            b.batting_average AS a_avg,
            b.home_runs AS a_hr
        FROM rankings r
        JOIN players p ON r.mlb_id = p.mlb_id
        LEFT JOIN batting_stats b ON b.mlb_id = r.mlb_id AND b.season = r.season
        WHERE r.season = ? AND r.player_type = 'hitter'
        ORDER BY r.overall_rank ASC
        """,
        (season,),
    ).fetchall()
    conn.close()

    out = []
    for r in rows:
        d = dict(r)
        proj_pa = d.get("proj_pa") or 0
        a_pa = d.get("a_pa") or 0

        # Per-PA projected rates (excluding OBP which is already a rate).
        proj_rates = {}
        actual_rates = {}
        for cat in HITTER_COUNTING_CATS:
            proj_total = d.get(f"proj_{cat}") or 0
            proj_rates[cat] = _safe_div(proj_total, proj_pa)
            actual_total = d.get(f"a_{cat}") or 0
            actual_rates[cat] = _safe_div(actual_total, a_pa)

        proj_rates["obp"] = d.get("proj_obp")
        actual_rates["obp"] = d.get("a_obp")

        # Build per-category breakdown
        cats = {}
        for cat in HITTER_COUNTING_CATS:
            proj_total = d.get(f"proj_{cat}") or 0
            proj_to_date = proj_total * season_elapsed_fraction
            actual = d.get(f"a_{cat}") or 0
            cats[cat] = {
                "proj_total": proj_total,
                "proj_to_date": proj_to_date,
                "actual": actual,
                "delta_volume": actual - proj_to_date,
                "proj_rate": proj_rates[cat],
                "actual_rate": actual_rates[cat] if a_pa > 0 else None,
                "delta_rate": (
                    (actual_rates[cat] - proj_rates[cat])
                    if (a_pa > 0 and proj_rates[cat] is not None and actual_rates[cat] is not None)
                    else None
                ),
            }

        # OBP — rate stat only
        proj_obp = d.get("proj_obp")
        a_obp = d.get("a_obp") if a_pa > 0 else None
        cats["obp"] = {
            "proj_total": proj_obp,
            "proj_to_date": proj_obp,  # rate stats don't accumulate
            "actual": a_obp,
            "delta_volume": None,  # not meaningful for rate stat
            "proj_rate": proj_obp,
            "actual_rate": a_obp,
            "delta_rate": _delta(a_obp, proj_obp) if (proj_obp is not None and a_obp is not None) else None,
        }

        out.append({
            "mlb_id": d["mlb_id"],
            "name": d["full_name"],
            "team": d.get("team"),
            "primary_position": d.get("primary_position"),
            "eligible_positions": d.get("eligible_positions"),
            "player_type": "hitter",
            "overall_rank": d.get("overall_rank"),
            "position_rank": d.get("position_rank"),
            "proj_pa": proj_pa,
            "actual_pa": a_pa,
            "actual_g": d.get("a_g") or 0,
            "actual_avg": d.get("a_avg"),
            "actual_hr": d.get("a_hr") or 0,
            "expected_pa_to_date": proj_pa * season_elapsed_fraction,
            "categories": cats,
        })

    return out


def compute_pitcher_performance(season: int, season_elapsed_fraction: float) -> list[dict]:
    """Return one row per ranked pitcher for the given season."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT
            r.mlb_id, r.overall_rank, r.position_rank,
            r.proj_ip, r.proj_k, r.proj_qs, r.proj_era, r.proj_whip, r.proj_svhd,
            p.full_name, p.primary_position, p.team, p.eligible_positions,
            ps.games AS a_g,
            ps.games_started AS a_gs,
            ps.innings_pitched AS a_ip,
            ps.strikeouts AS a_k,
            ps.quality_starts AS a_qs,
            ps.era AS a_era,
            ps.whip AS a_whip,
            ps.saves AS a_sv,
            ps.holds AS a_hld,
            ps.earned_runs AS a_er,
            ps.walks_allowed AS a_bb,
            ps.hits_allowed AS a_h
        FROM rankings r
        JOIN players p ON r.mlb_id = p.mlb_id
        LEFT JOIN pitching_stats ps ON ps.mlb_id = r.mlb_id AND ps.season = r.season
        WHERE r.season = ? AND r.player_type = 'pitcher'
        ORDER BY r.overall_rank ASC
        """,
        (season,),
    ).fetchall()
    conn.close()

    out = []
    for r in rows:
        d = dict(r)
        proj_ip = d.get("proj_ip") or 0
        a_ip = d.get("a_ip") or 0
        a_sv = d.get("a_sv") or 0
        a_hld = d.get("a_hld") or 0
        a_svhd = a_sv + a_hld

        cats = {}

        # K — counting stat with rate framing (K/9)
        proj_k = d.get("proj_k") or 0
        a_k = d.get("a_k") or 0
        cats["k"] = {
            "proj_total": proj_k,
            "proj_to_date": proj_k * season_elapsed_fraction,
            "actual": a_k,
            "delta_volume": a_k - (proj_k * season_elapsed_fraction),
            "proj_rate": _safe_div(proj_k * 9, proj_ip),  # K/9
            "actual_rate": _safe_div(a_k * 9, a_ip) if a_ip > 0 else None,
            "delta_rate": None,
        }
        if cats["k"]["proj_rate"] is not None and cats["k"]["actual_rate"] is not None:
            cats["k"]["delta_rate"] = cats["k"]["actual_rate"] - cats["k"]["proj_rate"]

        # QS — counting stat
        proj_qs = d.get("proj_qs") or 0
        a_qs = d.get("a_qs") or 0
        cats["qs"] = {
            "proj_total": proj_qs,
            "proj_to_date": proj_qs * season_elapsed_fraction,
            "actual": a_qs,
            "delta_volume": a_qs - (proj_qs * season_elapsed_fraction),
            # Rate proxy: QS per start. Use proj_ip / 6 as proxy for projected starts.
            "proj_rate": _safe_div(proj_qs, (proj_ip / 6.0) if proj_ip else 0),
            "actual_rate": _safe_div(a_qs, d.get("a_gs") or 0) if (d.get("a_gs") or 0) > 0 else None,
            "delta_rate": None,
        }
        if cats["qs"]["proj_rate"] is not None and cats["qs"]["actual_rate"] is not None:
            cats["qs"]["delta_rate"] = cats["qs"]["actual_rate"] - cats["qs"]["proj_rate"]

        # SVHD — counting stat
        proj_svhd = d.get("proj_svhd") or 0
        cats["svhd"] = {
            "proj_total": proj_svhd,
            "proj_to_date": proj_svhd * season_elapsed_fraction,
            "actual": a_svhd,
            "delta_volume": a_svhd - (proj_svhd * season_elapsed_fraction),
            # Rate proxy: SVHD per appearance.
            "proj_rate": None,  # not meaningful as a sustainable rate
            "actual_rate": None,
            "delta_rate": None,
        }

        # ERA — pure rate stat (lower is better)
        proj_era = d.get("proj_era")
        a_era = d.get("a_era") if a_ip > 0 else None
        cats["era"] = {
            "proj_total": proj_era,
            "proj_to_date": proj_era,
            "actual": a_era,
            "delta_volume": None,
            "proj_rate": proj_era,
            "actual_rate": a_era,
            "delta_rate": _delta(a_era, proj_era) if (proj_era is not None and a_era is not None) else None,
        }

        # WHIP — pure rate stat (lower is better)
        proj_whip = d.get("proj_whip")
        a_whip = d.get("a_whip") if a_ip > 0 else None
        cats["whip"] = {
            "proj_total": proj_whip,
            "proj_to_date": proj_whip,
            "actual": a_whip,
            "delta_volume": None,
            "proj_rate": proj_whip,
            "actual_rate": a_whip,
            "delta_rate": _delta(a_whip, proj_whip) if (proj_whip is not None and a_whip is not None) else None,
        }

        out.append({
            "mlb_id": d["mlb_id"],
            "name": d["full_name"],
            "team": d.get("team"),
            "primary_position": d.get("primary_position"),
            "eligible_positions": d.get("eligible_positions"),
            "player_type": "pitcher",
            "overall_rank": d.get("overall_rank"),
            "position_rank": d.get("position_rank"),
            "proj_ip": proj_ip,
            "actual_ip": a_ip,
            "actual_g": d.get("a_g") or 0,
            "actual_gs": d.get("a_gs") or 0,
            "expected_ip_to_date": proj_ip * season_elapsed_fraction,
            "categories": cats,
        })

    return out


def compute_performance(
    season: int,
    player_type: Literal["hitter", "pitcher"],
    season_elapsed_fraction: float,
) -> list[dict]:
    if player_type == "hitter":
        return compute_hitter_performance(season, season_elapsed_fraction)
    return compute_pitcher_performance(season, season_elapsed_fraction)
