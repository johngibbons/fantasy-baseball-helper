// ── Schedule utilities for variable-width rounds ──
//
// Rounds can have different numbers of picks (e.g. 9 or 10) when pick
// trades cause teams to gain/lose slots. These helpers replace the old
// `Math.floor(idx / numTeams)` arithmetic that assumed uniform rounds.

/**
 * Find which round (0-indexed) a pick index belongs to.
 */
export function roundForIndex(idx: number, roundStarts: number[]): number {
  for (let r = roundStarts.length - 1; r >= 0; r--) {
    if (roundStarts[r] <= idx) return r
  }
  return 0
}

/**
 * Position within its round (0-indexed).
 */
export function posInRound(idx: number, roundStarts: number[]): number {
  return idx - roundStarts[roundForIndex(idx, roundStarts)]
}

/**
 * Number of picks in a given round (0-indexed).
 */
export function roundSize(round: number, roundStarts: number[], scheduleLength: number): number {
  if (round + 1 < roundStarts.length) return roundStarts[round + 1] - roundStarts[round]
  return scheduleLength - roundStarts[round]
}

/**
 * Build roundStarts from uniform rounds (fallback when no roundStarts in state).
 */
export function buildUniformRoundStarts(scheduleLength: number, numTeams: number): number[] {
  if (numTeams === 0) return []
  const numRounds = Math.ceil(scheduleLength / numTeams)
  return Array.from({ length: numRounds }, (_, r) => r * numTeams)
}
