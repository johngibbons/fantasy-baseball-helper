from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class SimConfig:
    # computeDraftScore coefficients
    MCW_WEIGHT: float = 12.0
    VONA_WEIGHT_MCW: float = 1.5
    VONA_WEIGHT_BPA: float = 0.5
    URGENCY_WEIGHT_MCW: float = 0.8
    URGENCY_WEIGHT_BPA: float = 0.3

    # Post-score adjustments
    AVAILABILITY_DISCOUNT: float = 0.5
    BENCH_PENALTY_RATE: float = 0.8

    # Opponent model
    ADP_SIGMA: float = 18.0

    # Standings confidence ramp
    CONFIDENCE_START: int = 30
    CONFIDENCE_END: int = 100

    # League settings
    NUM_TEAMS: int = 10
    NUM_ROUNDS: int = 25
    PLAYOFF_SPOTS: int = 6

    def with_overrides(self, **kwargs: object) -> "SimConfig":
        return replace(self, **kwargs)
