"""Derive H2H category weights from measured weekly correlations.

The weights in zscores.py (H2H_CATEGORY_WEIGHTS) discount categories that move
together and reward ones that win independently: taking R, TB and RBI from the
same slugger buys less than three separate category wins, while a stolen base
specialist buys something nobody else covers. The recipe is documented at
zscores.py:46-71 — independence score, normalize to sum to N, then dampen by
blending with equal weights.

The correlation matrix behind the shipped numbers is labelled "approximate" in
that comment block: the values were assumed, not measured. Every input needed
to measure them properly is available from ESPN's matchup history — one
observation per team per week per category — which is what this module does.

Pure math; the fetching and the CLI live in
backend/scripts/calibrate_category_weights.py, mirroring how
sigma_calibration.py and calibrate_category_sigma.py are split.
"""

from __future__ import annotations

import math

# Blend of measured independence with equal weights. 0.6 keeps the shipped
# convention: adjustments stay moderate rather than letting one noisy season's
# correlations swing a category by 30%.
DEFAULT_DAMPENING = 0.6

# ERA and WHIP are scored low-is-better, so their raw weekly totals move
# opposite to every other category. Correlating the raw values would report a
# good pitching week as *negative* correlation between QS and ERA. Flip them
# into "more is better" space first, matching _INVERTED_FOR_PERFORMANCE in
# performance.py. Independence uses absolute correlation, so this does not
# change the weights — but it makes the matrix mean what it appears to mean.
INVERTED_CATEGORIES = frozenset({"ERA", "WHIP"})


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _stddev(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = _mean(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1))


def correlation(xs: list[float], ys: list[float]) -> float | None:
    """Pearson correlation, or None when either series is constant."""
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    sx, sy = _stddev(xs), _stddev(ys)
    if sx == 0 or sy == 0:
        return None
    mx, my = _mean(xs), _mean(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (len(xs) - 1)
    return cov / (sx * sy)


def orient(observations: list[dict[str, float]],
           inverted: frozenset[str] = INVERTED_CATEGORIES) -> list[dict[str, float]]:
    """Flip low-is-better categories so every category reads more-is-better."""
    return [
        {cat: (-value if cat in inverted else value) for cat, value in obs.items()}
        for obs in observations
    ]


def correlation_matrix(
    observations: list[dict[str, float]],
    cat_keys: list[str],
) -> dict[str, dict[str, float | None]]:
    """Pairwise correlation of category values across team-weeks.

    Each observation is one team's totals for one matchup period. Correlating
    across those is the right unit: it captures how categories co-move in the
    weekly matchups that actually decide the season. Callers should pass
    observations through `orient` first.
    """
    matrix: dict[str, dict[str, float | None]] = {}
    for a in cat_keys:
        matrix[a] = {}
        for b in cat_keys:
            if a == b:
                matrix[a][b] = 1.0
                continue
            paired = [(obs[a], obs[b]) for obs in observations
                      if a in obs and b in obs]
            if len(paired) < 2:
                matrix[a][b] = None
                continue
            matrix[a][b] = correlation([p[0] for p in paired],
                                       [p[1] for p in paired])
    return matrix


def independence_scores(
    matrix: dict[str, dict[str, float | None]],
    cat_keys: list[str],
) -> dict[str, float]:
    """1 - mean absolute correlation with the other categories.

    Absolute value because a strong negative correlation is just as redundant
    as a strong positive one: if two categories always move opposite, winning
    one tells you about the other.
    """
    scores = {}
    for cat in cat_keys:
        others = [abs(value) for other, value in matrix.get(cat, {}).items()
                  if other != cat and value is not None]
        scores[cat] = 1.0 - _mean(others) if others else 1.0
    return scores


def weights_from_independence(
    scores: dict[str, float],
    cat_keys: list[str],
    dampening: float = DEFAULT_DAMPENING,
) -> dict[str, float]:
    """Normalize independence scores to average 1.0, then dampen toward equal.

    dampening=1.0 uses the raw measured weights; 0.0 returns all 1.0.
    """
    values = [scores[cat] for cat in cat_keys if cat in scores]
    if not values:
        return {cat: 1.0 for cat in cat_keys}
    mean_score = _mean(values)
    if mean_score == 0:
        return {cat: 1.0 for cat in cat_keys}

    out = {}
    for cat in cat_keys:
        normalized = scores.get(cat, mean_score) / mean_score
        out[cat] = round(1.0 + (normalized - 1.0) * dampening, 4)
    return out


def calibrate_category_weights(
    observations: list[dict[str, float]],
    cat_keys: list[str],
    dampening: float = DEFAULT_DAMPENING,
    inverted: frozenset[str] = INVERTED_CATEGORIES,
) -> dict:
    """Full pipeline: team-week observations to category weights."""
    matrix = correlation_matrix(orient(observations, inverted), cat_keys)
    scores = independence_scores(matrix, cat_keys)
    return {
        "n_observations": len(observations),
        "dampening": dampening,
        "correlation_matrix": matrix,
        "independence_scores": {k: round(v, 4) for k, v in scores.items()},
        "weights": weights_from_independence(scores, cat_keys, dampening),
    }
