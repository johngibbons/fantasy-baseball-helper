from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class SimConfig:
    # computeDraftScore coefficients
    MCW_WEIGHT: float = 21.0
    VONA_WEIGHT_MCW: float = 0.16
    VONA_WEIGHT_BPA: float = 0.42
    URGENCY_WEIGHT_MCW: float = 0.02
    URGENCY_WEIGHT_BPA: float = 0.55

    # Post-score adjustments
    AVAILABILITY_DISCOUNT: float = 0.19
    BENCH_PENALTY_RATE: float = 0.63

    # Bench contribution rates (how much bench stats count toward team totals)
    # Pitchers contribute more in daily leagues (streaming SPs, swapping in RPs)
    PITCHER_BENCH_CONTRIBUTION: float = 0.45
    HITTER_BENCH_CONTRIBUTION: float = 0.20

    # Opponent model
    ADP_SIGMA: float = 18.0
    OPP_BENCH_ADP_PENALTY: float = 15.0  # ADP penalty for bench-only picks

    # Window VONA: use availability-weighted replacement instead of literal next-best
    USE_WINDOW_VONA: bool = False

    # Standings confidence ramp
    CONFIDENCE_START: int = 40
    CONFIDENCE_END: int = 81

    # League settings
    NUM_TEAMS: int = 10
    NUM_ROUNDS: int = 25
    PLAYOFF_SPOTS: int = 6

    def with_overrides(self, **kwargs: object) -> "SimConfig":
        return replace(self, **kwargs)
