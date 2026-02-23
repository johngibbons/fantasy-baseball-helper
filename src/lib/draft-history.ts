/**
 * Historical draft analysis for the Juiced Fantasy Baseball league.
 * Data computed from league drafts (2018–2025, ~2000 picks analyzed).
 *
 * Provides:
 * 1. Manager draft tendency profiles (position preferences by round range)
 * 2. League-specific positional ADP (when each position typically gets drafted)
 */

// ── Team ID → Manager name mapping (ESPN league team IDs, stable across seasons) ──
export const TEAM_MANAGER: Record<number, string> = {
  1: 'Matt Wayne',
  2: 'John Gibbons',
  3: 'Bryan Lewis',
  4: 'Jess Barron',
  5: 'Harris Cook',
  6: 'Eric Mercado',
  7: 'David Rotatori',
  8: 'Jason McComb',
  9: 'Chris Herbst',
  10: 'Tim Riker',
}

// ── Position group for tendency analysis ──
export type PosGroup = 'SP' | 'RP' | 'C' | 'IF' | 'OF'

// ── Manager tendency profile ──
export interface ManagerProfile {
  /** % of early-round picks (R1–8) by position group */
  earlyPct: Record<PosGroup, number>
  /** Average round of first pick at key positions */
  firstSP: number
  firstRP: number
  firstC: number
  /** Short tendency labels for display */
  labels: string[]
}

/**
 * Manager tendency data computed from 2018–2025 draft history.
 *
 * earlyPct: approximate % of rounds 1–8 picks spent on each group.
 * firstSP/RP/C: typical round the manager first drafts that position.
 * labels: 2–3 short descriptors for UI display.
 */
export const MANAGER_PROFILES: Record<string, ManagerProfile> = {
  'Harris Cook': {
    earlyPct: { SP: 28, RP: 5, C: 5, IF: 32, OF: 30 },
    firstSP: 4, firstRP: 8, firstC: 11,
    labels: ['Balanced drafter', 'SP rounds 3–5', 'Late-round gems'],
  },
  'Chris Herbst': {
    earlyPct: { SP: 38, RP: 8, C: 8, IF: 22, OF: 24 },
    firstSP: 2, firstRP: 9, firstC: 8,
    labels: ['SP-heavy early', 'Invests in aces', 'C mid-rounds'],
  },
  'John Gibbons': {
    earlyPct: { SP: 30, RP: 3, C: 3, IF: 34, OF: 30 },
    firstSP: 3, firstRP: 11, firstC: 13,
    labels: ['Hitting-first', 'SP rounds 3–6', 'Waits on C & RP'],
  },
  'Jason McComb': {
    earlyPct: { SP: 25, RP: 8, C: 3, IF: 30, OF: 34 },
    firstSP: 3, firstRP: 6, firstC: 14,
    labels: ['Balanced', 'Likes elite closers', 'Waits on C'],
  },
  'Bryan Lewis': {
    earlyPct: { SP: 30, RP: 8, C: 5, IF: 27, OF: 30 },
    firstSP: 3, firstRP: 6, firstC: 8,
    labels: ['Balanced', 'RP mid-rounds', 'SP depth rounds 3–8'],
  },
  'Tim Riker': {
    earlyPct: { SP: 32, RP: 12, C: 5, IF: 25, OF: 26 },
    firstSP: 2, firstRP: 5, firstC: 7,
    labels: ['SP + RP heavy', 'Closers early', 'Upside arms'],
  },
  'Jess Barron': {
    earlyPct: { SP: 25, RP: 10, C: 8, IF: 25, OF: 32 },
    firstSP: 3, firstRP: 6, firstC: 5,
    labels: ['OF-heavy early', 'C earlier than avg', 'Keeper strategist'],
  },
  'Eric Mercado': {
    earlyPct: { SP: 38, RP: 8, C: 3, IF: 22, OF: 29 },
    firstSP: 2, firstRP: 6, firstC: 13,
    labels: ['Pitching-first', 'SP rounds 1–3', 'Waits on C'],
  },
  'Matt Wayne': {
    earlyPct: { SP: 28, RP: 8, C: 5, IF: 30, OF: 29 },
    firstSP: 3, firstRP: 6, firstC: 9,
    labels: ['Balanced', 'SP mid-rounds', 'Keeper value late'],
  },
  'David Rotatori': {
    earlyPct: { SP: 30, RP: 8, C: 5, IF: 30, OF: 27 },
    firstSP: 3, firstRP: 7, firstC: 9,
    labels: ['Adaptive / BPA', 'SP rounds 3–6', '5× champion'],
  },
}

// ── League-specific positional ADP ──
export interface LeaguePosADP {
  position: string
  /** Average round the first player at this position goes each year */
  firstOffBoard: number
  /** Round range where the bulk of this position gets drafted */
  peakRange: [number, number]
  /** Typical total drafted per year at this position */
  perDraft: number
}

/**
 * League-specific positional ADP data (2018–2025 averages).
 * More accurate than ESPN general-population ADP for this 10-team H2H categories league.
 */
export const LEAGUE_POS_ADP: LeaguePosADP[] = [
  { position: 'C',  firstOffBoard: 5,  peakRange: [7, 16],  perDraft: 12 },
  { position: '1B', firstOffBoard: 1,  peakRange: [2, 13],  perDraft: 18 },
  { position: '2B', firstOffBoard: 2,  peakRange: [3, 14],  perDraft: 15 },
  { position: '3B', firstOffBoard: 1,  peakRange: [1, 12],  perDraft: 18 },
  { position: 'SS', firstOffBoard: 1,  peakRange: [1, 12],  perDraft: 18 },
  { position: 'OF', firstOffBoard: 1,  peakRange: [1, 18],  perDraft: 55 },
  { position: 'SP', firstOffBoard: 1,  peakRange: [2, 20],  perDraft: 95 },
  { position: 'RP', firstOffBoard: 4,  peakRange: [5, 17],  perDraft: 30 },
]

const posADPMap = new Map(LEAGUE_POS_ADP.map(p => [p.position, p]))

/** Get manager profile by team ID */
export function getManagerProfile(teamId: number): ManagerProfile | null {
  const name = TEAM_MANAGER[teamId]
  return name ? MANAGER_PROFILES[name] ?? null : null
}

/** Get manager name by team ID */
export function getManagerName(teamId: number): string {
  return TEAM_MANAGER[teamId] ?? `Team ${teamId}`
}

/** Get league positional ADP for a given position string */
export function getLeaguePosADP(position: string): LeaguePosADP | null {
  return posADPMap.get(position.toUpperCase()) ?? null
}

/**
 * Map a player's position list to a PosGroup for tendency comparison.
 * Priority: SP > RP > C > IF > OF
 */
export function toPosGroup(positions: string[]): PosGroup {
  for (const p of positions) {
    if (p === 'SP') return 'SP'
    if (p === 'RP') return 'RP'
  }
  if (positions.includes('C')) return 'C'
  if (positions.some(p => ['1B', '2B', '3B', 'SS'].includes(p))) return 'IF'
  return 'OF'
}

/**
 * Get a short position-run warning for the current round.
 * Returns a label like "RP run typically starts" if we're at the round
 * where a position's peak range begins.
 */
export function getPositionRunAlert(currentRound: number): string | null {
  for (const adp of LEAGUE_POS_ADP) {
    if (currentRound === adp.peakRange[0] && adp.peakRange[0] >= 4) {
      return `${adp.position} run typically starts around Rd ${adp.peakRange[0]}`
    }
  }
  return null
}
