// ── Draft model coefficients ──
//
// These are the TypeScript half of a model that is implemented twice: here
// (used by the live draft board) and in backend/simulation/ (used by the
// simulator, the Optuna tuner, and the season retrospective). The two must
// agree, or the board recommends one thing while every offline experiment
// measures another.
//
// Source of truth for the values: backend/simulation/config.py (SimConfig).
// Parity is enforced by backend/data/fixtures/draft_scoring_parity.json, which
// is asserted from both languages — see src/__tests__/lib/draft-scoring-parity.test.ts
// and tests/backend/simulation/test_scoring_parity.py.
//
// Provenance: optimized 2026-04-02 via optimize_model.py (Optuna TPE, 100
// trials, seed=42) — see optimization_results.json. NOTE: these landed *after*
// the March 2026 draft, so the 2026 board ran on the previous coefficients
// (MCW 21.0 / VONA 0.16 / urgency 0.02, documented in SCORING_MODEL.md).

export const DRAFT_MODEL_CONFIG = {
  /** Weight on marginal category wins in the MCW-blended score. */
  MCW_WEIGHT: 7.47,
  /** Weight on VONA within the MCW score. */
  VONA_WEIGHT_MCW: 0.24,
  /** Weight on VONA within the best-player-available fallback score. */
  VONA_WEIGHT_BPA: 1.0,
  /** Weight on pick urgency within the MCW score. */
  URGENCY_WEIGHT_MCW: 0.65,
  /** Weight on pick urgency within the BPA fallback score. */
  URGENCY_WEIGHT_BPA: 0.44,

  /** Score is discounted by availability × this, so likely-available players wait. */
  AVAILABILITY_DISCOUNT: 0.12,
  /** Bench-hitter penalty rate, scaled by draft progress. */
  BENCH_PENALTY_RATE: 0.95,

  /** Standings confidence ramps linearly from 0 to 1 across these pick counts. */
  CONFIDENCE_START: 24,
  CONFIDENCE_END: 108,

  /** Desperation bonus for players helping critically weak categories. */
  DESPERATION_THRESHOLD: 0.35,
  DESPERATION_WEIGHT: 6.0,
  DESPERATION_CAP: 0.0,
  DESPERATION_MULTI_CAT: 0.25,
  DESPERATION_MAX: 0.0,

  /** Opponent pick model. */
  ADP_SIGMA: 18.0,

  /** League settings. */
  NUM_TEAMS: 10,
  NUM_ROUNDS: 25,
  PLAYOFF_SPOTS: 6,
} as const

export type DraftModelConfig = typeof DRAFT_MODEL_CONFIG
