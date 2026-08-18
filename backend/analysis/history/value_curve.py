"""Phase 4: is the value-at-pick curve stable enough to fit?

`expectedValueAtRound` in src/app/keepers/page.tsx assumes the value available
at round R equals the value of the player ranked R x 10 on the board. Every
keeper surplus the app displays rests on it. The 2026 retrospective could only
check that assumption against a single season, which cannot distinguish "the
shape is right" from "that season happened to look like that".

Nine seasons can. Two questions, and they have different answers:

**Is the curve stable year to year?** Measured as the spread of each round's
mean return across seasons, against the spread *within* a round in a single
season. If between-season variation is small relative to within-round
variation, one pooled curve describes every season and can be fitted.

**Does rank-linear describe it?** Measured by comparing what round R actually
returned against the value of the player ranked 10R on the same board. This is
a test of the *shape* on realized values; the app applies the assumption to
projected values, so a deviation here is evidence about the assumption, not a
direct measurement of the app's error.

Pure functions.
"""

from __future__ import annotations

import numpy as np

from backend.analysis.retro.keeper_eval import NUM_TEAMS


def pooled_curve(curves_by_season: dict[int, list[dict]],
                 min_seasons: int = 5) -> list[dict]:
    """Each round's return, pooled across seasons.

    `min_seasons` drops rounds only a few seasons reached (26 and 27 exist in
    three seasons only), because a "mean" over two observations invites being
    read as a curve point when it is a coin flip.
    """
    by_round: dict[int, list[tuple[int, float]]] = {}
    for season, curve in curves_by_season.items():
        for entry in curve:
            by_round.setdefault(entry["round"], []).append(
                (season, entry["mean_realized_value"]))

    rows = []
    for round_number, observations in sorted(by_round.items()):
        values = [v for _, v in observations]
        if len(values) < min_seasons:
            continue
        array = np.asarray(values, dtype=float)
        rows.append({
            "round": round_number,
            "seasons": len(values),
            "mean": round(float(array.mean()), 3),
            "sd_across_seasons": round(float(array.std(ddof=1)), 3),
            "min": round(float(array.min()), 3),
            "max": round(float(array.max()), 3),
            "range": round(float(array.max() - array.min()), 3),
        })
    return rows


def stability(curves_by_season: dict[int, list[dict]],
              within_round_sd: dict[int, float] | None = None) -> dict:
    """Is one curve enough, or does each season need its own?

    The comparison that matters is between-season spread against within-season
    spread. A round whose mean swings 4 SGP between seasons is not usable as a
    point estimate; a round whose mean swings 0.5 SGP while individual picks in
    it swing 8 SGP is a stable target hidden behind noisy picks.
    """
    pooled = pooled_curve(curves_by_season)
    if not pooled:
        return {"rounds": 0}

    between = np.asarray([r["sd_across_seasons"] for r in pooled], dtype=float)
    result = {
        "rounds": len(pooled),
        "seasons": len(curves_by_season),
        "mean_between_season_sd": round(float(between.mean()), 3),
        "max_between_season_sd": round(float(between.max()), 3),
        "worst_round": int(pooled[int(between.argmax())]["round"]),
    }
    if within_round_sd:
        within = np.asarray(
            [within_round_sd.get(r["round"], np.nan) for r in pooled], dtype=float)
        usable = ~np.isnan(within)
        if usable.any():
            result["mean_within_round_sd"] = round(float(within[usable].mean()), 3)
            # A ratio below 1 means seasons agree with each other more closely
            # than picks within a single round do -- i.e. the curve is a real
            # signal and the noise is at the pick level, where it belongs.
            result["between_over_within"] = round(
                float(between[usable].mean() / within[usable].mean()), 3)
    return result


def season_correlations(curves_by_season: dict[int, list[dict]]) -> dict:
    """Do seasons agree on the *shape* even when they disagree on the level?

    Spearman between every pair of seasons over their shared rounds. High
    correlation with a varying level would mean the shape can be fitted once
    and rescaled per season, which is a different fix from a fixed curve.
    """
    seasons = sorted(curves_by_season)
    values = {s: {e["round"]: e["mean_realized_value"]
                  for e in curves_by_season[s]} for s in seasons}

    pairs = []
    for i, a in enumerate(seasons):
        for b in seasons[i + 1:]:
            shared = sorted(set(values[a]) & set(values[b]))
            if len(shared) < 5:
                continue
            x = np.asarray([values[a][r] for r in shared])
            y = np.asarray([values[b][r] for r in shared])
            if x.std() == 0 or y.std() == 0:
                continue
            rank_x = np.argsort(np.argsort(x))
            rank_y = np.argsort(np.argsort(y))
            rho = float(np.corrcoef(rank_x, rank_y)[0, 1])
            pairs.append({"a": a, "b": b, "rounds": len(shared),
                          "spearman": round(rho, 3)})

    if not pairs:
        return {"pairs": 0}
    rhos = np.asarray([p["spearman"] for p in pairs])
    return {
        "pairs": len(pairs),
        "mean_spearman": round(float(rhos.mean()), 3),
        "min_spearman": round(float(rhos.min()), 3),
        "max_spearman": round(float(rhos.max()), 3),
        "by_pair": pairs,
    }


# ── candidate shapes ─────────────────────────────────────────────────────


def rank_linear_prediction(round_number: int, sorted_board: list[float],
                           teams: int = NUM_TEAMS) -> float | None:
    """The app's assumption: the value of the player ranked round x teams."""
    if not sorted_board:
        return None
    index = min(max(round_number * teams - 1, 0), len(sorted_board) - 1)
    return float(sorted_board[index])


def fit_shapes(rounds: list[int], values: list[float]) -> dict:
    """Fit candidate curve shapes and score each by RMSE.

    Candidates are deliberately few and simple. With 25 points there is room to
    overfit, and a curve that beats the others by 0.05 SGP is not a reason to
    replace a shipped assumption.
    """
    if len(rounds) < 5:
        return {"n": len(rounds)}

    x = np.asarray(rounds, dtype=float)
    y = np.asarray(values, dtype=float)

    def rmse(predicted: np.ndarray) -> float:
        return float(np.sqrt(((y - predicted) ** 2).mean()))

    fits: dict[str, dict] = {}

    slope, intercept = np.polyfit(x, y, 1)
    fits["linear"] = {
        "rmse": round(rmse(slope * x + intercept), 4),
        "params": {"slope": round(float(slope), 4),
                   "intercept": round(float(intercept), 4)},
        "formula": f"{intercept:.3f} + {slope:.4f} * round",
    }

    quad = np.polyfit(x, y, 2)
    fits["quadratic"] = {
        "rmse": round(rmse(np.polyval(quad, x)), 4),
        "params": {"a": round(float(quad[0]), 5), "b": round(float(quad[1]), 4),
                   "c": round(float(quad[2]), 4)},
    }

    # Logarithmic decay: steep early, flattening. The shape a value curve is
    # usually assumed to have.
    log_slope, log_intercept = np.polyfit(np.log(x), y, 1)
    fits["logarithmic"] = {
        "rmse": round(rmse(log_slope * np.log(x) + log_intercept), 4),
        "params": {"slope": round(float(log_slope), 4),
                   "intercept": round(float(log_intercept), 4)},
        "formula": f"{log_intercept:.3f} + {log_slope:.4f} * ln(round)",
    }

    best = min(fits, key=lambda k: fits[k]["rmse"])
    spread = max(f["rmse"] for f in fits.values()) - min(
        f["rmse"] for f in fits.values())
    return {
        "n": len(rounds),
        "fits": fits,
        "best": best,
        "rmse_spread": round(spread, 4),
        # If every candidate lands within a small band, the shape is not
        # identified by this data and picking a winner would be noise-fitting.
        "shapes_separable": spread > 0.25,
    }


def concentration(values: list[float], roster_spots: int) -> dict:
    """How much of a season's realized value cleared replacement.

    `values` must come from a board whose pool is wide enough for replacement
    level to mean something -- a board over only the drafted players puts
    replacement near the bottom of its own pool and every player clears it.
    """
    array = np.asarray(values, dtype=float)
    above = int((array > 0).sum())
    return {
        "pool": len(array),
        "above_replacement": above,
        "roster_spots": roster_spots,
        "share_of_pool_above_replacement": round(above / len(array), 4)
        if len(array) else None,
        "rostered_spots_below_replacement": max(0, roster_spots - above),
        "share_of_rostered_spots_below_replacement": round(
            max(0, roster_spots - above) / roster_spots, 4) if roster_spots else None,
    }
