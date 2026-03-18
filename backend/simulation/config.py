from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class SimConfig:
    # MCW strategy multipliers (how much MCW credit each category strategy gets)
    LOCK_MCW_WEIGHT: float = 1.0    # rank 1-2 with big gap below
    TARGET_MCW_WEIGHT: float = 1.0  # rank 3-8, where marginal improvement flips matchups

    # computeDraftScore coefficients
    MCW_WEIGHT: float = 22.09
    VONA_WEIGHT_MCW: float = 0.01
    VONA_WEIGHT_BPA: float = 0.97
    URGENCY_WEIGHT_MCW: float = 0.33
    URGENCY_WEIGHT_BPA: float = 0.68

    # Post-score adjustments
    AVAILABILITY_DISCOUNT: float = 0.03
    BENCH_PENALTY_RATE: float = 0.58

    # Bench contribution rates (how much bench stats count toward team totals)
    # SPs have high streaming value (start on rotation days). Bench RPs contribute
    # much less — starting RPs already play almost every day, so the 5th+ RP rarely swaps in.
    PITCHER_BENCH_CONTRIBUTION: float = 0.45
    RP_BENCH_CONTRIBUTION: float = 0.15
    HITTER_BENCH_CONTRIBUTION: float = 0.20

    # Opponent model
    ADP_SIGMA: float = 18.0
    OPP_BENCH_ADP_PENALTY: float = 15.0  # ADP penalty for bench-only picks
    OPP_SCARCITY_BONUS: float = 15.0     # Max ADP bonus for scarce position need
    OPP_CAT_NEED_BONUS: float = 4.0      # ADP bonus per weak category helped

    # Scale BPA urgency by draft progress (reduces urgency in early rounds)
    SCALE_BPA_URGENCY: bool = False

    # Slot scarcity: use 1/remaining_capacity instead of binary roster fit
    USE_SLOT_SCARCITY: bool = False

    # Variable ADP sigma: sigma = 10 + 0.1 * ADP instead of fixed 18
    USE_VARIABLE_SIGMA: bool = False

    # Window VONA: use availability-weighted replacement instead of literal next-best
    USE_WINDOW_VONA: bool = False

    # Surplus value (VORP): use per-position replacement-level-adjusted value in BPA
    USE_SURPLUS_VALUE: bool = True

    # Restrict normalization pool to draftable universe (top N by overall_rank)
    RESTRICT_NORM_POOL: bool = True

    # Standings confidence ramp
    CONFIDENCE_START: int = 1
    CONFIDENCE_END: int = 112

    # Category desperation bonus: extra credit for players contributing to
    # categories where win probability is critically low (addresses MCW's
    # myopic undervaluation when you're far behind but need to start building)
    DESPERATION_THRESHOLD: float = 0.35  # win prob below which bonus activates
    DESPERATION_WEIGHT: float = 6.0      # bonus per desperate category
    DESPERATION_CAP: float = 0.0         # max z-score credit per category (0 = uncapped)
    DESPERATION_MULTI_CAT: float = 0.25  # extra multiplier per additional desperate cat helped (0 = additive only)
    DESPERATION_MAX: float = 0.0          # max total desperation bonus (0 = unlimited)

    # Category floor penalty: when you have N categories with 0% win prob,
    # penalize players that don't help any of them (pushes away from overkilling
    # strong categories and toward filling holes)
    CAT_FLOOR_PENALTY: float = 0.0       # penalty per dead category not helped (0 = disabled)

    # Rollout-based scoring: simulate rest of draft to evaluate each candidate
    USE_ROLLOUT: bool = False
    ROLLOUT_TOP_N: int = 20          # pre-filter to top N candidates before running rollouts
    ROLLOUT_MIN_PICK: int = 20       # only use rollouts after this many total picks (let BPA handle early)

    # Composition steering (None = unconstrained)
    TARGET_SP: int | None = None   # target total SP count
    TARGET_RP: int | None = None   # target total RP count
    MAX_HITTERS: int | None = None # max hitters before treating as bench

    # League settings
    NUM_TEAMS: int = 10
    NUM_ROUNDS: int = 25
    PLAYOFF_SPOTS: int = 6

    def with_overrides(self, **kwargs: object) -> "SimConfig":
        return replace(self, **kwargs)
