"""Empirical Bayes shrinkage for the playoff odds simulator.

Pure-math helpers. No I/O. Operates in typical-period units (~7-day weeks) for
both σ_within (calibrated CATEGORY_SIGMA) and σ_between (calibrated
CATEGORY_BETWEEN_SIGMA), matching the existing simulator's period-length
approximation.
"""

from __future__ import annotations

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
