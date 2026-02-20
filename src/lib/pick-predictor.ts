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
 * @param espnAdp - The player's ESPN average draft position
 * @param currentPick - The current overall pick number (0-based index)
 * @param picksUntilMyTurn - Number of picks until it's your turn again
 * @param sigma - Standard deviation of ADP noise (default 18 = ~68% of players go within 18 picks of ADP)
 * @returns Probability between 0 and 1 that the player will still be available
 */
export function computeAvailability(
  espnAdp: number,
  currentPick: number,
  picksUntilMyTurn: number,
  sigma = 18
): number {
  // The pick at which we'd be selecting
  const targetPick = currentPick + picksUntilMyTurn
  // How far this player's ADP is from the target pick
  // If ADP is much lower (earlier) than targetPick, they'll likely be gone
  const z = (targetPick - espnAdp) / sigma
  // P(available) = P(player has NOT been taken yet) = P(their actual draft pos > targetPick)
  // Since lower ADP = drafted earlier, we want P(actual > target) = 1 - CDF(z)
  // But z is (target - ADP)/sigma, so:
  // - If ADP << target: z large, CDF(z) ~1, player likely available
  // - If ADP >> target: z negative, CDF(z) ~0, player likely gone
  return Math.max(0, Math.min(1, normalCDF(z)))
}
