"""Which part of the valuation model was wrong?

Two complementary views:

Attribution is exact rather than inferred. total_zscore is a sum of
per-category SGP terms plus a replacement adjustment, so the gap between what
the board said and what happened decomposes without residual:

    delta_total = sum_over_categories(realized_cat - projected_cat)
                + (realized_replacement_adj - projected_replacement_adj)

That says where the error landed, per player and in aggregate.

Ablations say what to do about it. Each rebuilds the preseason board with one
assumption changed, scores it against the fixed ex-post objective, and reports
the change in rank correlation with a bootstrap interval. A change whose effect
falls inside the interval is no effect — the discipline SCORING_IMPROVEMENTS.md
already applies to simulation sweeps, carried over to real outcomes.

Pure functions; callers supply the rows and the valuation function.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from backend.analysis.retro.valuation import (
    bootstrap_delta_spearman_ci,
    ranked_ids,
    spearman,
    top_n_precision,
)

HITTER_CATEGORIES = ("zscore_r", "zscore_tb", "zscore_rbi", "zscore_sb", "zscore_obp")
PITCHER_CATEGORIES = ("zscore_k", "zscore_qs", "zscore_era", "zscore_whip", "zscore_svhd")


def attribute(projected_board: list[dict], realized_board: list[dict],
              categories: tuple[str, ...]) -> dict:
    """Decompose projected-vs-realized error by category.

    Returns per-category aggregates plus the per-player rows, so the biggest
    individual misses can be inspected alongside the totals.
    """
    proj = {r["mlb_id"]: r for r in projected_board}
    rows = []
    for realized in realized_board:
        projected = proj.get(realized["mlb_id"])
        if projected is None:
            continue
        per_cat = {
            cat: round(float(realized.get(cat, 0.0)) - float(projected.get(cat, 0.0)), 4)
            for cat in categories
        }
        replacement_delta = round(
            float(realized.get("replacement_adj", 0.0))
            - float(projected.get("replacement_adj", 0.0)), 4)
        total_delta = round(
            float(realized["total_zscore"]) - float(projected["total_zscore"]), 4)
        rows.append({
            "mlb_id": realized["mlb_id"],
            "name": realized.get("full_name"),
            "projected_total": projected["total_zscore"],
            "realized_total": realized["total_zscore"],
            "delta_total": total_delta,
            "delta_by_category": per_cat,
            "delta_replacement": replacement_delta,
            # Whatever the category terms and replacement do not explain. The
            # streaming bonus and the playing-time discount live here, since
            # both adjust total_zscore without touching a category column.
            "unexplained": round(
                total_delta - sum(per_cat.values()) - replacement_delta, 4),
        })

    totals = {
        cat: round(float(np.sum([r["delta_by_category"][cat] for r in rows])), 3)
        for cat in categories
    }
    means = {
        cat: round(float(np.mean([r["delta_by_category"][cat] for r in rows])), 4)
        for cat in categories
    } if rows else {}
    mean_abs = {
        cat: round(float(np.mean(np.abs([r["delta_by_category"][cat] for r in rows]))), 4)
        for cat in categories
    } if rows else {}

    return {
        "n": len(rows),
        "total_delta_by_category": totals,
        "mean_delta_by_category": means,
        # Mean absolute error is the "how noisy is this category" measure;
        # mean signed error is the "is this category systematically off" one.
        "mean_abs_delta_by_category": mean_abs,
        "mean_delta_replacement": round(
            float(np.mean([r["delta_replacement"] for r in rows])), 4) if rows else None,
        "mean_unexplained": round(
            float(np.mean([r["unexplained"] for r in rows])), 4) if rows else None,
        "biggest_misses": sorted(rows, key=lambda r: r["delta_total"])[:25],
        "biggest_beats": sorted(rows, key=lambda r: -r["delta_total"])[:25],
    }


@dataclass(frozen=True)
class AblationResult:
    label: str
    spearman: float | None
    delta_spearman: float | None
    top_100_precision: float | None
    delta_top_100: float | None
    inside_noise: bool | None
    delta_ci: tuple[float | None, float | None] = (None, None)

    def as_dict(self) -> dict:
        return {
            "label": self.label,
            "spearman": self.spearman,
            "delta_spearman": self.delta_spearman,
            "delta_spearman_ci": list(self.delta_ci),
            "top_100_precision": self.top_100_precision,
            "delta_top_100": self.delta_top_100,
            "inside_noise": self.inside_noise,
        }


def score_board(projected_board: list[dict], realized_board: list[dict]) -> tuple[float | None, float | None]:
    """Rank correlation and top-100 precision of a board against realized value."""
    from backend.analysis.retro.valuation import paired_series

    _, projected, realized = paired_series(projected_board, realized_board)
    rho = spearman(projected, realized)
    precision = top_n_precision(ranked_ids(projected_board),
                                ranked_ids(realized_board), 100)
    return rho, precision


def run_ablations(
    baseline_board: list[dict],
    realized_board: list[dict],
    variants: dict[str, list[dict]],
) -> list[dict]:
    """Score each variant board against the fixed realized objective.

    Significance is assessed per variant with a paired bootstrap on the
    *difference* in rank correlation, resampling players. A variant whose
    interval contains zero has not been shown to differ from the baseline.
    """
    base_rho, base_precision = score_board(baseline_board, realized_board)
    results = [AblationResult(
        label="baseline",
        spearman=base_rho,
        delta_spearman=0.0 if base_rho is not None else None,
        top_100_precision=base_precision,
        delta_top_100=0.0 if base_precision is not None else None,
        inside_noise=None,
        delta_ci=(None, None),
    )]

    for label, board in variants.items():
        rho, precision = score_board(board, realized_board)

        # Align all three series on the players present in every board.
        base_by_id = {r["mlb_id"]: r["total_zscore"] for r in baseline_board}
        var_by_id = {r["mlb_id"]: r["total_zscore"] for r in board}
        real_by_id = {r["mlb_id"]: r["total_zscore"] for r in realized_board}
        ids = sorted(set(base_by_id) & set(var_by_id) & set(real_by_id))
        lo, hi = bootstrap_delta_spearman_ci(
            [float(var_by_id[i]) for i in ids],
            [float(base_by_id[i]) for i in ids],
            [float(real_by_id[i]) for i in ids],
        )
        inside = None if lo is None or hi is None else bool(lo <= 0 <= hi)

        results.append(AblationResult(
            label=label,
            spearman=rho,
            delta_spearman=(None if rho is None or base_rho is None
                            else round(rho - base_rho, 5)),
            top_100_precision=precision,
            delta_top_100=(None if precision is None or base_precision is None
                           else round(precision - base_precision, 4)),
            inside_noise=inside,
            delta_ci=(None if lo is None else round(lo, 5),
                      None if hi is None else round(hi, 5)),
        ))

    return [r.as_dict() for r in results]


def streaming_bonus_check(projected_board: list[dict], realized_board: list[dict],
                          era_threshold: float = 4.00,
                          whip_threshold: float = 1.25) -> dict:
    """Did the streaming criterion actually pick out more valuable starters?

    Compares realized value of starters who met the projected ERA/WHIP gate
    against those who did not, holding projected value roughly constant by
    reporting both groups' projected means alongside.
    """
    realized_by_id = {r["mlb_id"]: r for r in realized_board}
    qualifying, others = [], []
    for projected in projected_board:
        if (projected.get("proj_ip") or 0) <= 0:
            continue
        realized = realized_by_id.get(projected["mlb_id"])
        if realized is None:
            continue
        pair = (float(projected["total_zscore"]), float(realized["total_zscore"]))
        # The gate is applied to the *projections*, which is what the board saw.
        if (projected.get("proj_era") is not None
                and projected["proj_era"] <= era_threshold
                and projected.get("proj_whip") is not None
                and projected["proj_whip"] <= whip_threshold):
            qualifying.append(pair)
        else:
            others.append(pair)

    def summarize(pairs):
        if not pairs:
            return None
        p = np.asarray([a for a, _ in pairs])
        r = np.asarray([b for _, b in pairs])
        return {
            "n": len(pairs),
            "mean_projected": round(float(p.mean()), 4),
            "mean_realized": round(float(r.mean()), 4),
        }

    q, o = summarize(qualifying), summarize(others)
    realized_edge = None
    if q and o:
        realized_edge = round(q["mean_realized"] - o["mean_realized"], 4)
    return {
        "era_threshold": era_threshold,
        "whip_threshold": whip_threshold,
        "qualifying": q,
        "others": o,
        "realized_edge": realized_edge,
    }
