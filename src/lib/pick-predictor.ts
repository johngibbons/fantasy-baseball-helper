/**
 * Pick availability predictor using normal CDF model.
 *
 * Estimates the probability a player will still be available
 * when your next pick comes around, based on their ADP.
 */

/** Approximate the standard normal CDF using Abramowitz & Stegun formula */
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
  const absX = Math.abs(x)
  const t = 1.0 / (1.0 + p * absX)
  const y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * Math.exp(-absX * absX / 2)

  return 0.5 * (1.0 + sign * y)
}

/**
 * Compute the probability a player is still available at your next pick.
 *
 * Uses a normal CDF model where sigma scales with draft depth — early
 * picks are more predictable (tighter ADP clustering), later picks have
 * more variance.
 *
 * @param espnAdp - The player's ESPN average draft position
 * @param currentPick - The current overall pick number (0-based index)
 * @param picksUntilMyTurn - Number of picks until it's your turn again
 * @returns Probability between 0 and 1 that the player will still be available
 */
export function computeAvailability(
  espnAdp: number,
  currentPick: number,
  picksUntilMyTurn: number,
): number {
  const targetPick = currentPick + picksUntilMyTurn
  // Sigma scales with ADP: top picks are predictable (~6), later picks more noisy (~12)
  const sigma = 6 + (espnAdp / 250) * 6
  const z = (targetPick - espnAdp) / sigma
  return Math.max(0, Math.min(1, 1 - normalCDF(z)))
}
