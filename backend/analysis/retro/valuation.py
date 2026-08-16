"""Did the board's valuations predict realized value?

Metrics are deliberately rank-based first. SGP is close to homogeneous of
degree one in playing time, so an August board's *levels* are roughly the
full-season levels scaled by the fraction of the season played — but the
*ordering* is not, which makes rank correlation and top-N precision the
statistics that mean the same thing in August and in September.

Calibration is reported alongside: regressing realized value on projected
value gives a slope, and a slope below 1 says the board is over-dispersed —
it spreads players further apart than reality does, which is the signature of
a model that would benefit from shrinkage (backend/analysis/shrinkage.py).

Pure functions; no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def _ranks(values: np.ndarray) -> np.ndarray:
    """Ascending ranks with ties averaged (the Spearman convention)."""
    order = values.argsort()
    ranks = np.empty(len(values), dtype=float)
    ranks[order] = np.arange(1, len(values) + 1, dtype=float)

    # Average the ranks within each group of tied values.
    sorted_values = values[order]
    start = 0
    for i in range(1, len(values) + 1):
        if i == len(values) or sorted_values[i] != sorted_values[start]:
            if i - start > 1:
                ranks[order[start:i]] = ranks[order[start:i]].mean()
            start = i
    return ranks


def pearson(x: list[float], y: list[float]) -> float | None:
    xa, ya = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if len(xa) < 2:
        return None
    xs, ys = xa.std(), ya.std()
    if xs == 0 or ys == 0:
        return None
    return float(((xa - xa.mean()) * (ya - ya.mean())).mean() / (xs * ys))


def spearman(x: list[float], y: list[float]) -> float | None:
    """Rank correlation. Invariant to how much of the season has been played."""
    if len(x) < 2:
        return None
    return pearson(list(_ranks(np.asarray(x, dtype=float))),
                   list(_ranks(np.asarray(y, dtype=float))))


def kendall_tau(x: list[float], y: list[float]) -> float | None:
    """Tau-b: the share of player pairs the board ordered correctly.

    More directly interpretable than Spearman for a draft — every pick is a
    pairwise choice between two available players.
    """
    n = len(x)
    if n < 2:
        return None
    xa, ya = np.asarray(x, dtype=float), np.asarray(y, dtype=float)

    concordant = discordant = 0
    ties_x = ties_y = 0
    for i in range(n - 1):
        dx = xa[i + 1:] - xa[i]
        dy = ya[i + 1:] - ya[i]
        signs = np.sign(dx) * np.sign(dy)
        concordant += int((signs > 0).sum())
        discordant += int((signs < 0).sum())
        ties_x += int(((dx == 0) & (dy != 0)).sum())
        ties_y += int(((dy == 0) & (dx != 0)).sum())

    n0 = concordant + discordant + ties_x
    n1 = concordant + discordant + ties_y
    if n0 == 0 or n1 == 0:
        return None
    return float((concordant - discordant) / np.sqrt(n0 * n1))


def top_n_precision(projected_order: list[int], realized_order: list[int],
                    n: int) -> float | None:
    """Share of the board's top n who finished in the realized top n."""
    if n <= 0 or len(projected_order) < n or len(realized_order) < n:
        return None
    return len(set(projected_order[:n]) & set(realized_order[:n])) / n


@dataclass(frozen=True)
class Calibration:
    slope: float | None
    intercept: float | None
    r_squared: float | None


def ols(x: list[float], y: list[float]) -> Calibration:
    """Regress realized on projected. Slope < 1 ⇒ the board is over-dispersed."""
    xa, ya = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if len(xa) < 2 or xa.std() == 0:
        return Calibration(None, None, None)
    slope, intercept = np.polyfit(xa, ya, 1)
    predicted = slope * xa + intercept
    ss_res = float(((ya - predicted) ** 2).sum())
    ss_tot = float(((ya - ya.mean()) ** 2).sum())
    r2 = None if ss_tot == 0 else 1 - ss_res / ss_tot
    return Calibration(float(slope), float(intercept), r2)


def decile_table(projected: list[float], realized: list[float],
                 buckets: int = 10) -> list[dict]:
    """Mean realized value per projected-value bucket, best bucket first."""
    n = len(projected)
    if n < buckets:
        return []
    order = np.argsort(-np.asarray(projected, dtype=float))
    pa = np.asarray(projected, dtype=float)[order]
    ra = np.asarray(realized, dtype=float)[order]

    edges = np.linspace(0, n, buckets + 1).astype(int)
    out = []
    for i in range(buckets):
        lo, hi = edges[i], edges[i + 1]
        if hi <= lo:
            continue
        out.append({
            "bucket": i + 1,
            "count": int(hi - lo),
            "mean_projected": round(float(pa[lo:hi].mean()), 4),
            "mean_realized": round(float(ra[lo:hi].mean()), 4),
            "mean_error": round(float((ra[lo:hi] - pa[lo:hi]).mean()), 4),
        })
    return out


def bootstrap_spearman_ci(
    projected: list[float], realized: list[float],
    iterations: int = 1000, alpha: float = 0.05, seed: int = 42,
) -> tuple[float | None, float | None]:
    """Percentile bootstrap CI for a rank correlation.

    Ablations are compared against this: a change whose effect sits inside the
    interval is reported as no effect, matching the discipline in
    SCORING_IMPROVEMENTS.md, where most candidate improvements turned out to be
    noise.
    """
    n = len(projected)
    if n < 10:
        return (None, None)
    rng = np.random.default_rng(seed)
    pa = np.asarray(projected, dtype=float)
    ra = np.asarray(realized, dtype=float)

    samples = []
    for _ in range(iterations):
        idx = rng.integers(0, n, n)
        value = spearman(list(pa[idx]), list(ra[idx]))
        if value is not None:
            samples.append(value)
    if not samples:
        return (None, None)
    lo = float(np.percentile(samples, 100 * alpha / 2))
    hi = float(np.percentile(samples, 100 * (1 - alpha / 2)))
    return (lo, hi)


def bootstrap_delta_spearman_ci(
    board_a: list[float], board_b: list[float], realized: list[float],
    iterations: int = 1000, alpha: float = 0.05, seed: int = 42,
) -> tuple[float | None, float | None]:
    """Percentile CI for the *difference* in rank correlation between two boards.

    The right yardstick for an ablation. Comparing a variant's correlation to
    the confidence interval of the baseline correlation understates the test
    badly: both boards score the same players, so they move together and the
    paired difference is far less variable than either estimate alone. An
    interval that contains zero means the change has not been shown to matter.
    """
    n = len(realized)
    if n < 10 or len(board_a) != n or len(board_b) != n:
        return (None, None)
    rng = np.random.default_rng(seed)
    a = np.asarray(board_a, dtype=float)
    b = np.asarray(board_b, dtype=float)
    r = np.asarray(realized, dtype=float)

    deltas = []
    for _ in range(iterations):
        idx = rng.integers(0, n, n)
        rho_a = spearman(list(a[idx]), list(r[idx]))
        rho_b = spearman(list(b[idx]), list(r[idx]))
        if rho_a is not None and rho_b is not None:
            deltas.append(rho_a - rho_b)
    if not deltas:
        return (None, None)
    return (float(np.percentile(deltas, 100 * alpha / 2)),
            float(np.percentile(deltas, 100 * (1 - alpha / 2))))


def paired_series(projected_board: list[dict], realized_board: list[dict],
                  key: str = "total_zscore") -> tuple[list[int], list[float], list[float]]:
    """Join two boards on mlb_id.

    Order is by mlb_id so the pairing is deterministic and independent of how
    either board happened to be sorted.
    """
    proj = {r["mlb_id"]: r for r in projected_board}
    real = {r["mlb_id"]: r for r in realized_board}
    ids = sorted(set(proj) & set(real))
    return (ids,
            [float(proj[i][key]) for i in ids],
            [float(real[i][key]) for i in ids])


def ranked_ids(board: list[dict], key: str = "total_zscore") -> list[int]:
    """mlb_ids ordered best first, ties broken by id for determinism."""
    return [r["mlb_id"] for r in
            sorted(board, key=lambda r: (-float(r[key]), r["mlb_id"]))]


def accuracy_summary(projected_board: list[dict], realized_board: list[dict],
                     top_ns: tuple[int, ...] = (25, 50, 100, 200)) -> dict:
    """Headline accuracy for one pool (hitters or pitchers)."""
    ids, projected, realized = paired_series(projected_board, realized_board)
    if len(ids) < 2:
        return {"n": len(ids)}

    calibration = ols(projected, realized)
    lo, hi = bootstrap_spearman_ci(projected, realized)
    return {
        "n": len(ids),
        "spearman": spearman(projected, realized),
        "spearman_ci": [lo, hi],
        "kendall_tau": kendall_tau(projected, realized),
        "pearson": pearson(projected, realized),
        "ols_slope": calibration.slope,
        "ols_intercept": calibration.intercept,
        "r_squared": calibration.r_squared,
        "top_n_precision": {
            str(n): top_n_precision(ranked_ids(projected_board),
                                    ranked_ids(realized_board), n)
            for n in top_ns
        },
        "deciles": decile_table(projected, realized),
    }


def segment_bias(projected_board: list[dict], realized_board: list[dict],
                 segment_of) -> list[dict]:
    """Mean realized-minus-projected by segment.

    A non-zero mean for a whole segment is a structural bias — the kind that a
    single constant (the pitcher normalizer, a replacement level) is supposed
    to correct.
    """
    proj = {r["mlb_id"]: r for r in projected_board}
    groups: dict[str, list[tuple[float, float]]] = {}
    for realized in realized_board:
        projected = proj.get(realized["mlb_id"])
        if projected is None:
            continue
        label = segment_of(projected)
        if label is None:
            continue
        groups.setdefault(label, []).append(
            (float(projected["total_zscore"]), float(realized["total_zscore"])))

    out = []
    for label, pairs in sorted(groups.items()):
        p = [a for a, _ in pairs]
        r = [b for _, b in pairs]
        out.append({
            "segment": label,
            "n": len(pairs),
            "mean_projected": round(float(np.mean(p)), 4),
            "mean_realized": round(float(np.mean(r)), 4),
            "mean_error": round(float(np.mean(np.asarray(r) - np.asarray(p))), 4),
            "spearman": spearman(p, r),
        })
    return out
