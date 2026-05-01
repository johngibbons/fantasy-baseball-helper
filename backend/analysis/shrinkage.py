"""Empirical Bayes shrinkage for the playoff odds simulator.

Pure-math helpers. No I/O. Operates in typical-period units (~7-day weeks) for
both σ_within (calibrated CATEGORY_SIGMA) and σ_between (calibrated
CATEGORY_BETWEEN_SIGMA), matching the existing simulator's period-length
approximation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

TYPICAL_PERIOD_DAYS = 7


def compute_shrinkage_weight(
    W: int,
    sigma_within: float,
    sigma_between: float,
) -> float:
    """Conjugate normal-normal posterior weight on the observed mean.

    Args:
        W: Number of completed periods observed for this (team, cat).
        sigma_within: σ for one period's noise around team's true mean (typical-period units).
        sigma_between: σ for spread of teams' true means around the ATC prior (typical-period units).

    Returns:
        Weight in [0, 1]. 0 when no observations or when σ_between == 0.
    """
    if W <= 0 or sigma_between <= 0.0:
        return 0.0
    num = (sigma_between ** 2) * W
    return num / (num + sigma_within ** 2)


@dataclass
class ObservedPeriod:
    """One completed matchup period's category totals for one team."""

    matchup_period_id: int
    period_days: int
    cats: dict[str, float] = field(default_factory=dict)


def compute_observed_typical_period_count(
    observations: list[ObservedPeriod],
    cat: str,
) -> tuple[float, int]:
    """Mean count for *cat* normalized to a typical 7-day period.

    Combines all periods' observed totals divided by total days, then multiplies
    by TYPICAL_PERIOD_DAYS. Periods missing this cat are skipped (and reduce n).

    Returns:
        (mean_per_typical_period, n_periods_used).
    """
    relevant = [o for o in observations if cat in o.cats]
    if not relevant:
        return 0.0, 0
    total_obs = sum(o.cats[cat] for o in relevant)
    total_days = sum(o.period_days for o in relevant)
    if total_days <= 0:
        return 0.0, len(relevant)
    return (total_obs / total_days) * TYPICAL_PERIOD_DAYS, len(relevant)


def compute_observed_period_rate(
    observations: list[ObservedPeriod],
    cat: str,
) -> tuple[float, int]:
    """Unweighted mean of rate values across periods.

    PA / IP weights are not available in ESPN's matchup response, so we use
    an unweighted mean — same approximation the σ calibration uses.

    Returns:
        (mean_rate, n_periods_used).
    """
    relevant = [o for o in observations if cat in o.cats]
    if not relevant:
        return 0.0, 0
    return sum(o.cats[cat] for o in relevant) / len(relevant), len(relevant)
