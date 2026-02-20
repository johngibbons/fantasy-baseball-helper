/**
 * Gap-based tier detection for draft board players.
 *
 * Sorts players by value descending, finds statistically significant gaps
 * between consecutive players, and assigns tier numbers.
 */

export function computeTiers(
  players: { mlb_id: number; value: number }[]
): Map<number, number> {
  const tiers = new Map<number, number>()
  if (players.length === 0) return tiers

  // Sort by value descending
  const sorted = [...players].sort((a, b) => b.value - a.value)

  // Compute gaps between consecutive values
  const gaps: number[] = []
  for (let i = 0; i < sorted.length - 1; i++) {
    gaps.push(sorted[i].value - sorted[i + 1].value)
  }

  if (gaps.length === 0) {
    // Single player — tier 1
    tiers.set(sorted[0].mlb_id, 1)
    return tiers
  }

  // Find threshold: median + 1 * stddev
  const sortedGaps = [...gaps].sort((a, b) => a - b)
  const median = sortedGaps[Math.floor(sortedGaps.length / 2)]
  const mean = gaps.reduce((s, g) => s + g, 0) / gaps.length
  const variance = gaps.reduce((s, g) => s + (g - mean) ** 2, 0) / gaps.length
  const stddev = Math.sqrt(variance)
  const threshold = median + stddev

  // Assign tiers: each gap above threshold starts a new tier
  let currentTier = 1
  tiers.set(sorted[0].mlb_id, currentTier)

  for (let i = 0; i < gaps.length; i++) {
    if (gaps[i] > threshold && currentTier < 15) {
      currentTier++
    }
    tiers.set(sorted[i + 1].mlb_id, currentTier)
  }

  return tiers
}
