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
