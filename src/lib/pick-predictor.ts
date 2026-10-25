/**
 * Pick availability predictor using normal CDF model.
 *
 * Estimates the probability a player will still be available
 * when your next pick comes around, based on their ADP.
 */

import { DRAFT_MODEL_CONFIG } from '@/lib/draft-model-config'

/**
 * Standard normal CDF: Abramowitz & Stegun 7.1.26, which approximates erf,
 * evaluated at x / √2. Max error ~7e-8. An earlier version scaled only the
 * exponential, which put it up to 0.037 off and understated tail availability
 * by about a fifth.
 */
function normalCDF(x: number): number {
  if (x < -8) return 0
  if (x > 8) return 1

  const a1 = 0.254829592
  const a2 = -0.284496736
  const a3 = 1.421413741
  const a4 = -1.453152027
  const a5 = 1.061405429
  const p = 0.3275911

  const sign = x < 0 ? -1 : 1
  const absX = Math.abs(x) / Math.SQRT2
  const t = 1.0 / (1.0 + p * absX)
  const y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * Math.exp(-absX * absX)

  return 0.5 * (1.0 + sign * y)
}

/**
 * How far a player's actual draft slot tends to stray from ADP, in picks.
 *
 * Measured against the real 2026 draft: about 6.5 picks for the top 50, 17 by
 * the 50–100 band, and 30–40 from pick 100 on. The previous formula,
 * 6 + adp/250 × 6, topped out at 12: twice too sure who would still be there
 * in the 50–100 band, and three to four times too sure from pick 100 on.
 */
export function availabilitySigma(effectiveAdp: number): number {
  const config = DRAFT_MODEL_CONFIG
  return config.USE_VARIABLE_SIGMA
    ? config.ADP_SIGMA_INTERCEPT + config.ADP_SIGMA_SLOPE * effectiveAdp
    : config.ADP_SIGMA
}

/**
 * Compute the probability a player is still available at your next pick.
 *
 * Uses a normal CDF model where sigma scales with draft depth — early
 * picks are more predictable (tighter ADP clustering), later picks have
 * more variance. This is player_availability in
 * backend/simulation/scoring_model.py; the parity fixture holds them together.
 *
 * In keeper leagues, redraft ADP doesn't account for keepers. We adjust by
 * counting how many competitive (non-keeper) picks will happen before our
 * turn, and shifting ADP down by the number of kept players with ADP below
 * this player's ADP.
 *
 * @param adp - The player's blended average draft position (65% ESPN + 35% NFBC)
 * @param competitivePicksSoFar - Number of non-keeper picks already made
 * @param competitivePicksUntilMyTurn - Number of non-keeper picks until my turn
 * @param keptBelowAdp - Number of kept players with ADP <= this player's ADP
 * @returns Probability between 0 and 1 that the player will still be available
 */
export function computeAvailability(
  adp: number,
  competitivePicksSoFar: number,
  competitivePicksUntilMyTurn: number,
  keptBelowAdp: number = 0,
): number {
  const effectiveTargetPick = competitivePicksSoFar + competitivePicksUntilMyTurn
  const effectiveAdp = adp - keptBelowAdp
  const sigma = availabilitySigma(effectiveAdp)
  const z = (effectiveTargetPick - effectiveAdp) / sigma
  return Math.max(0, Math.min(1, 1 - normalCDF(z)))
}
