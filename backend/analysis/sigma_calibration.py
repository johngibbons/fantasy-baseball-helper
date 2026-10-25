"""Category sigma calibration: pure math.

Computes per-category σ values from historical team-period observations.
For count stats (R, TB, K, etc): σ is the stddev of (observed - rate * period_days).
For rate stats (OBP, ERA, WHIP): σ is the stddev of (observed - season_rate).
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class CountStatObservation:
    """One team's observed value for one category over one matchup period."""
    team_id: int
    period_id: int
    period_days: int
    cat: str
    observed: float


def _stddev(values: list[float]) -> float:
    """Sample standard deviation. Returns 0.0 for fewer than 2 values."""
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return math.sqrt(var)


def compute_category_sigma(
    observations: list[CountStatObservation],
    team_rates_per_day: dict[int, dict[str, float]],
    cat_keys: list[str],
    cat_kinds: dict[str, str],
) -> dict[str, float]:
    """Compute calibrated σ per category.

    Args:
        observations: All team-period observations (across teams, periods, cats).
        team_rates_per_day: team_id → cat → per-day rate. For count stats this is
            (season_total / total_season_days). For rate stats this is the season rate.
        cat_keys: Categories to calibrate (e.g. ["R", "TB", "OBP", ...]).
        cat_kinds: cat → "count" or "rate". Determines residual formula.

    Returns:
        cat → σ. Cats with no observations get 0.0.
    """
    residuals_by_cat: dict[str, list[float]] = {cat: [] for cat in cat_keys}

    for obs in observations:
        if obs.cat not in residuals_by_cat:
            continue
        rate = team_rates_per_day.get(obs.team_id, {}).get(obs.cat, 0.0)
        kind = cat_kinds.get(obs.cat, "count")
        if kind == "count":
            expected = rate * obs.period_days
        else:  # rate
            expected = rate
        residuals_by_cat[obs.cat].append(obs.observed - expected)

    return {cat: _stddev(residuals_by_cat[cat]) for cat in cat_keys}


TYPICAL_PERIOD_DAYS = 7


def compute_between_team_sigma(
    team_rates_per_day: dict[int, dict[str, float]],
    cat_keys: list[str],
    cat_kinds: dict[str, str],
    typical_period_days: int = TYPICAL_PERIOD_DAYS,
) -> dict[str, float]:
    """σ_between per category — spread across teams of typical-period production.

    For count stats: stddev across teams of (per_day_rate × typical_period_days),
    yielding units that match the count-stat CATEGORY_SIGMA (per-typical-period).
    For rate stats: stddev across teams of season_rate, in rate units.

    Returns 0.0 for cats with fewer than 2 teams (no variance signal).
    """
    out: dict[str, float] = {}
    team_ids = list(team_rates_per_day.keys())
    for cat in cat_keys:
        kind = cat_kinds.get(cat, "count")
        if kind == "count":
            values = [
                team_rates_per_day[tid].get(cat, 0.0) * typical_period_days
                for tid in team_ids
            ]
        else:  # rate
            values = [team_rates_per_day[tid].get(cat, 0.0) for tid in team_ids]
        out[cat] = _stddev(values)
    return out


def true_between_team_variance(
    between_sigma: dict[str, float],
    within_sigma: dict[str, float],
    periods_per_team: list[int],
) -> dict[str, float]:
    """Variance of teams' true typical-period means, per category.

    compute_between_team_sigma measures the spread of each team's season
    average, and every average carries its own weekly noise: σ_within² / n
    for a team with n periods. Subtracting the mean of that noise is the
    method-of-moments estimate of the spread of true means. It comes out
    negative when the observed spread is no wider than noise alone would
    make it, and is left that way so seasons can be pooled before truncating.
    """
    noise = {
        cat: sum(within_sigma[cat] ** 2 / n for n in periods_per_team) / len(periods_per_team)
        for cat in between_sigma
    }
    return {cat: between_sigma[cat] ** 2 - noise[cat] for cat in between_sigma}


def split_half_between_variance(
    periods_by_team: dict[int, list[tuple[int, int, float]]],
    kind: str,
    typical_period_days: int = TYPICAL_PERIOD_DAYS,
) -> float:
    """Covariance across teams of odd-period and even-period averages.

    `periods_by_team` maps team → [(period_id, period_days, observed)]. Weekly
    noise is independent between the two halves, so it drops out of the
    covariance and only what persists from week to week is left: an estimate
    of the true between-team variance that does not use σ_within at all.
    """
    def average(periods: list[tuple[int, int, float]]) -> float:
        if kind == "count":
            days = sum(d for _, d, _ in periods)
            return sum(v for _, _, v in periods) / days * typical_period_days
        return sum(v for _, _, v in periods) / len(periods)

    odd, even = [], []
    for periods in periods_by_team.values():
        odd_periods = [p for p in periods if p[0] % 2]
        even_periods = [p for p in periods if not p[0] % 2]
        if odd_periods and even_periods:
            odd.append(average(odd_periods))
            even.append(average(even_periods))
    if len(odd) < 2:
        return 0.0
    mean_odd, mean_even = sum(odd) / len(odd), sum(even) / len(even)
    return sum((a - mean_odd) * (b - mean_even)
               for a, b in zip(odd, even)) / (len(odd) - 1)


def pool_variance(estimates: list[tuple[dict[str, float], int]]) -> dict[str, float]:
    """Combine per-season variance estimates: Σ(n−1)·v / Σ(n−1) per category.

    Each estimate is (cat → variance, sample size), centred on that season's
    own mean, so this is the variance of all samples together with each
    season centred on itself. Negative estimates pool like any other.
    Pooling the raw records directly would not work: team IDs repeat across
    seasons, so each team's two seasons would merge into one.
    """
    cats = estimates[0][0].keys() if estimates else []
    out: dict[str, float] = {}
    for cat in cats:
        dof = sum(n - 1 for _, n in estimates if n > 1)
        if dof <= 0:
            out[cat] = 0.0
            continue
        out[cat] = sum((n - 1) * v[cat] for v, n in estimates if n > 1) / dof
    return out
