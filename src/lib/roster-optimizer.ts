/**
 * Roster optimizer — greedy lineup assignment for fantasy baseball rosters.
 *
 * Assigns players to their most constrained eligible roster slot first,
 * producing an optimal (or near-optimal) starting lineup.
 */

import type { RankedPlayer } from './valuations-api'

// ── Roster slot configuration ──
export const ROSTER_SLOTS: Record<string, number> = {
  C: 1, '1B': 1, '2B': 1, '3B': 1, SS: 1, OF: 3, UTIL: 2, SP: 3, RP: 2, P: 2, BE: 8,
}

/** Number of starter (non-bench) slots */
export const STARTER_SLOT_COUNT = Object.entries(ROSTER_SLOTS)
  .filter(([k]) => k !== 'BE')
  .reduce((sum, [, v]) => sum + v, 0)

/**
 * Fraction of projected stats a bench player contributes over a season.
 * Split by player type: pitchers contribute more in daily leagues (streaming SPs,
 * swapping in RPs on their days) while hitters only cover rest days (~1-2 games/week).
 */
export const PITCHER_BENCH_CONTRIBUTION = 0.45
export const HITTER_BENCH_CONTRIBUTION = 0.20

// Maps ESPN positions to the roster slots they can fill (most restrictive first)
export const POSITION_TO_SLOTS: Record<string, string[]> = {
  C: ['C', 'UTIL', 'BE'], '1B': ['1B', 'UTIL', 'BE'], '2B': ['2B', 'UTIL', 'BE'],
  '3B': ['3B', 'UTIL', 'BE'], SS: ['SS', 'UTIL', 'BE'],
  OF: ['OF', 'UTIL', 'BE'], LF: ['OF', 'UTIL', 'BE'], CF: ['OF', 'UTIL', 'BE'], RF: ['OF', 'UTIL', 'BE'],
  DH: ['UTIL', 'BE'],
  SP: ['SP', 'P', 'BE'], RP: ['RP', 'P', 'BE'],
  TWP: ['UTIL', 'SP', 'P', 'BE'],
}

// ── Roster slot display order ──
export const SLOT_ORDER = ['C', '1B', '2B', '3B', 'SS', 'OF', 'UTIL', 'SP', 'RP', 'P', 'BE']

// ── Helpers ──

/** Classify a pitcher as SP or RP using z-score data (matches zscores.py logic) */
export function pitcherRole(p: RankedPlayer): 'SP' | 'RP' {
  if (p.zscore_qs && p.zscore_qs !== 0) return 'SP'
  if (p.zscore_svhd && p.zscore_svhd !== 0) return 'RP'
  return 'SP' // default — matches backend's IP >= 80 heuristic
}

/** Parse eligible_positions string into raw position list, inferring SP/RP for pitchers */
export function getPositions(p: RankedPlayer): string[] {
  if (p.eligible_positions) {
    const positions = p.eligible_positions.split('/')
    // Sort DH to the end — it only fills UTIL, so a real position should take priority
    // for display and VONA scarcity calculations
    positions.sort((a, b) => (a === 'DH' ? 1 : 0) - (b === 'DH' ? 1 : 0))
    return positions
  }
  if (p.player_type === 'pitcher') return [pitcherRole(p)]
  return [p.primary_position]
}

/** Parse eligible_positions string into array of roster slots a player can fill */
export function getEligibleSlots(p: RankedPlayer): string[] {
  const positions = getPositions(p)
  const slotSet = new Set<string>()
  for (const pos of positions) {
    const slots = POSITION_TO_SLOTS[pos]
    if (slots) slots.forEach((s) => slotSet.add(s))
  }
  return [...slotSet]
}

// ── Optimizer result ──

export interface RosterResult {
  assignments: { slot: string; player: RankedPlayer }[]
  remainingCapacity: Record<string, number>
  unassigned: RankedPlayer[]
  starters: RankedPlayer[]
  bench: RankedPlayer[]
}

/**
 * Greedy roster optimizer — assigns players to roster slots.
 *
 * Algorithm: sort players by fewest eligible slots (most constrained first),
 * then assign each to the first available slot in priority order.
 */
export function optimizeRoster(players: RankedPlayer[]): RosterResult {
  const capacity: Record<string, number> = { ...ROSTER_SLOTS }
  const assignments: { slot: string; player: RankedPlayer }[] = []
  const unassigned: RankedPlayer[] = []

  // Sort by fewest eligible slots first (most constrained)
  const sorted = [...players].sort((a, b) => getEligibleSlots(a).length - getEligibleSlots(b).length)

  for (const player of sorted) {
    const slots = getEligibleSlots(player)
    let placed = false
    for (const slot of slots) {
      if ((capacity[slot] || 0) > 0) {
        capacity[slot]--
        assignments.push({ slot, player })
        placed = true
        break
      }
    }
    if (!placed) unassigned.push(player)
  }

  const starters: RankedPlayer[] = []
  const bench: RankedPlayer[] = []
  for (const a of assignments) {
    if (a.slot === 'BE') {
      bench.push(a.player)
    } else {
      starters.push(a.player)
    }
  }

  return { assignments, remainingCapacity: capacity, unassigned, starters, bench }
}
