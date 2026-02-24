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
  1: 'Jess Barron',       // COUG – Atlanta Cougars
  2: 'Chris Herbst',      // BOOM – You're F****** Out
  3: 'Tim Riker',         // TR   – Rikers Island
  4: 'Harris Cook',       // SHC  – Tax Nation
  5: 'Jason McComb',      // JAMC – Last Place Champs
  6: 'Matt Wayne',        // BP   – Batt Payne
  7: 'David Rotatori',    // WORK – This Ain't No Hobby
  8: 'John Gibbons',      // NOTO – The Notorious G.I.B.
  9: 'Eric Mercado',      // ROP  – Trash Pandas
  10: 'Bryan Lewis',      // BLEW – Mile High And Tight
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

// ── Keeper History (Item 3) ──

export interface KeeperHistoryEntry {
  year: number
  manager: string
  roundCost: number
  seasonsKept: number
}

export interface KeeperHistory {
  playerName: string
  entries: KeeperHistoryEntry[]
}

/**
 * Historical keeper lifecycles from 2022–2025 draft data + 2026 keeper sheet.
 * Tracks players kept across multiple seasons with escalating round costs.
 * Sorted by total seasons kept (longest first).
 */
export const KEEPER_HISTORY: KeeperHistory[] = [
  // ── 5-season keepers ──
  {
    playerName: 'Gunnar Henderson',
    entries: [
      { year: 2023, manager: 'Tim Riker', roundCost: 25, seasonsKept: 1 },
      { year: 2024, manager: 'Tim Riker', roundCost: 20, seasonsKept: 2 },
      { year: 2025, manager: 'Tim Riker', roundCost: 15, seasonsKept: 3 },
      { year: 2026, manager: 'Tim Riker', roundCost: 15, seasonsKept: 3 },
    ],
  },
  {
    playerName: 'Michael Harris II',
    entries: [
      { year: 2023, manager: 'David Rotatori', roundCost: 25, seasonsKept: 1 },
      { year: 2024, manager: 'David Rotatori', roundCost: 20, seasonsKept: 2 },
      { year: 2025, manager: 'David Rotatori', roundCost: 15, seasonsKept: 3 },
      { year: 2026, manager: 'David Rotatori', roundCost: 15, seasonsKept: 3 },
    ],
  },
  {
    playerName: 'Spencer Strider',
    entries: [
      { year: 2023, manager: 'Jess Barron', roundCost: 25, seasonsKept: 1 },
      { year: 2024, manager: 'Jess Barron', roundCost: 20, seasonsKept: 2 },
      { year: 2025, manager: 'Jess Barron', roundCost: 15, seasonsKept: 3 },
      { year: 2026, manager: 'Jess Barron', roundCost: 15, seasonsKept: 3 },
    ],
  },
  // ── 4-season keepers ──
  {
    playerName: 'Freddy Peralta',
    entries: [
      { year: 2022, manager: 'Harris Cook', roundCost: 25, seasonsKept: 1 },
      { year: 2023, manager: 'Harris Cook', roundCost: 20, seasonsKept: 2 },
      { year: 2024, manager: 'Harris Cook', roundCost: 15, seasonsKept: 3 },
    ],
  },
  {
    playerName: 'Kyle Tucker',
    entries: [
      { year: 2022, manager: 'Tim Riker', roundCost: 17, seasonsKept: 1 },
      { year: 2023, manager: 'Tim Riker', roundCost: 12, seasonsKept: 2 },
      { year: 2024, manager: 'Tim Riker', roundCost: 6, seasonsKept: 3 },
    ],
  },
  {
    playerName: 'Julio Rodriguez',
    entries: [
      { year: 2023, manager: 'Tim Riker', roundCost: 18, seasonsKept: 1 },
      { year: 2024, manager: 'Tim Riker', roundCost: 13, seasonsKept: 2 },
      { year: 2025, manager: 'Tim Riker', roundCost: 8, seasonsKept: 3 },
      { year: 2026, manager: 'Tim Riker', roundCost: 8, seasonsKept: 3 },
    ],
  },
  {
    playerName: 'Cedric Mullins',
    entries: [
      { year: 2022, manager: 'Jason McComb', roundCost: 25, seasonsKept: 1 },
      { year: 2023, manager: 'Jason McComb', roundCost: 17, seasonsKept: 2 },
      { year: 2024, manager: 'Jason McComb', roundCost: 12, seasonsKept: 3 },
    ],
  },
  {
    playerName: 'Zac Gallen',
    entries: [
      { year: 2022, manager: 'Chris Herbst', roundCost: 14, seasonsKept: 1 },
      { year: 2023, manager: 'Chris Herbst', roundCost: 14, seasonsKept: 1 },
      { year: 2024, manager: 'Chris Herbst', roundCost: 9, seasonsKept: 2 },
    ],
  },
  // ── 3-season keepers ──
  {
    playerName: 'Tyler Glasnow',
    entries: [
      { year: 2023, manager: 'Chris Herbst', roundCost: 25, seasonsKept: 1 },
      { year: 2024, manager: 'Chris Herbst', roundCost: 20, seasonsKept: 2 },
      { year: 2025, manager: 'Chris Herbst', roundCost: 15, seasonsKept: 2 },
      { year: 2026, manager: 'Chris Herbst', roundCost: 15, seasonsKept: 2 },
    ],
  },
  {
    playerName: 'Ketel Marte',
    entries: [
      { year: 2022, manager: 'David Rotatori', roundCost: 20, seasonsKept: 1 },
      { year: 2024, manager: 'Jess Barron', roundCost: 19, seasonsKept: 1 },
      { year: 2025, manager: 'Jess Barron', roundCost: 14, seasonsKept: 2 },
      { year: 2026, manager: 'Jess Barron', roundCost: 14, seasonsKept: 2 },
    ],
  },
  {
    playerName: 'Bryce Harper',
    entries: [
      { year: 2024, manager: 'Jess Barron', roundCost: 9, seasonsKept: 1 },
      { year: 2025, manager: 'Jess Barron', roundCost: 4, seasonsKept: 2 },
      { year: 2026, manager: 'Jess Barron', roundCost: 4, seasonsKept: 2 },
    ],
  },
  {
    playerName: 'CJ Abrams',
    entries: [
      { year: 2024, manager: 'Harris Cook', roundCost: 22, seasonsKept: 1 },
      { year: 2025, manager: 'Harris Cook', roundCost: 17, seasonsKept: 2 },
      { year: 2026, manager: 'Harris Cook', roundCost: 17, seasonsKept: 2 },
    ],
  },
  {
    playerName: 'Tarik Skubal',
    entries: [
      { year: 2024, manager: 'Harris Cook', roundCost: 24, seasonsKept: 1 },
      { year: 2025, manager: 'Harris Cook', roundCost: 18, seasonsKept: 2 },
      { year: 2026, manager: 'Harris Cook', roundCost: 19, seasonsKept: 2 },
    ],
  },
  {
    playerName: 'Paul Skenes',
    entries: [
      { year: 2024, manager: 'Bryan Lewis', roundCost: 25, seasonsKept: 1 },
      { year: 2025, manager: 'Bryan Lewis', roundCost: 20, seasonsKept: 2 },
      { year: 2026, manager: 'Bryan Lewis', roundCost: 20, seasonsKept: 2 },
    ],
  },
  {
    playerName: 'Austin Riley',
    entries: [
      { year: 2022, manager: 'Tim Riker', roundCost: 25, seasonsKept: 1 },
      { year: 2023, manager: 'Tim Riker', roundCost: 20, seasonsKept: 2 },
    ],
  },
  {
    playerName: 'Emmanuel Clase',
    entries: [
      { year: 2022, manager: 'John Gibbons', roundCost: 25, seasonsKept: 1 },
      { year: 2023, manager: 'John Gibbons', roundCost: 20, seasonsKept: 2 },
      { year: 2024, manager: 'John Gibbons', roundCost: 15, seasonsKept: 3 },
    ],
  },
  {
    playerName: 'Adley Rutschman',
    entries: [
      { year: 2023, manager: 'John Gibbons', roundCost: 19, seasonsKept: 1 },
      { year: 2024, manager: 'John Gibbons', roundCost: 14, seasonsKept: 2 },
    ],
  },
  {
    playerName: 'Bobby Witt Jr.',
    entries: [
      { year: 2023, manager: 'Harris Cook', roundCost: 8, seasonsKept: 1 },
      { year: 2024, manager: 'David Rotatori', roundCost: 3, seasonsKept: 2 },
    ],
  },
  {
    playerName: 'Fernando Tatis Jr.',
    entries: [
      { year: 2022, manager: 'Harris Cook', roundCost: 15, seasonsKept: 1 },
      { year: 2023, manager: 'Harris Cook', roundCost: 15, seasonsKept: 1 },
      { year: 2024, manager: 'Chris Herbst', roundCost: 2, seasonsKept: 1 },
    ],
  },
  {
    playerName: 'Vladimir Guerrero Jr.',
    entries: [
      { year: 2022, manager: 'Eric Mercado', roundCost: 15, seasonsKept: 1 },
      { year: 2023, manager: 'Eric Mercado', roundCost: 15, seasonsKept: 1 },
    ],
  },
  {
    playerName: 'Adolis Garcia',
    entries: [
      { year: 2023, manager: 'Eric Mercado', roundCost: 24, seasonsKept: 1 },
      { year: 2024, manager: 'Eric Mercado', roundCost: 19, seasonsKept: 2 },
    ],
  },
  {
    playerName: 'Wander Franco',
    entries: [
      { year: 2022, manager: 'Jason McComb', roundCost: 18, seasonsKept: 1 },
      { year: 2023, manager: 'Jason McComb', roundCost: 13, seasonsKept: 2 },
    ],
  },
  {
    playerName: 'Bo Bichette',
    entries: [
      { year: 2022, manager: 'John Gibbons', roundCost: 16, seasonsKept: 1 },
      { year: 2023, manager: 'John Gibbons', roundCost: 11, seasonsKept: 2 },
    ],
  },
  {
    playerName: 'Shohei Ohtani',
    entries: [
      { year: 2022, manager: 'Eric Mercado', roundCost: 14, seasonsKept: 1 },
      { year: 2023, manager: 'Eric Mercado', roundCost: 9, seasonsKept: 2 },
    ],
  },
  {
    playerName: 'Yordan Alvarez',
    entries: [
      { year: 2022, manager: 'Matt Wayne', roundCost: 19, seasonsKept: 1 },
      { year: 2023, manager: 'Matt Wayne', roundCost: 14, seasonsKept: 2 },
    ],
  },
  {
    playerName: 'Logan Webb',
    entries: [
      { year: 2022, manager: 'David Rotatori', roundCost: 25, seasonsKept: 1 },
      { year: 2023, manager: 'David Rotatori', roundCost: 20, seasonsKept: 2 },
    ],
  },
  {
    playerName: 'Sandy Alcantara',
    entries: [
      { year: 2022, manager: 'Matt Wayne', roundCost: 25, seasonsKept: 1 },
      { year: 2023, manager: 'Matt Wayne', roundCost: 20, seasonsKept: 2 },
    ],
  },
  {
    playerName: 'Corbin Carroll',
    entries: [
      { year: 2024, manager: 'David Rotatori', roundCost: 3, seasonsKept: 1 },
    ],
  },
  // ── 2026 single-season keepers (first year kept) ──
  {
    playerName: 'Bryan Woo',
    entries: [
      { year: 2026, manager: 'Harris Cook', roundCost: 17, seasonsKept: 1 },
    ],
  },
  {
    playerName: 'Spencer Schwellenbach',
    entries: [
      { year: 2026, manager: 'Harris Cook', roundCost: 25, seasonsKept: 1 },
    ],
  },
  {
    playerName: 'Mark Vientos',
    entries: [
      { year: 2026, manager: 'Chris Herbst', roundCost: 25, seasonsKept: 1 },
    ],
  },
  {
    playerName: 'Cristopher Sanchez',
    entries: [
      { year: 2026, manager: 'Chris Herbst', roundCost: 23, seasonsKept: 1 },
    ],
  },
  {
    playerName: 'Ezequiel Tovar',
    entries: [
      { year: 2026, manager: 'Chris Herbst', roundCost: 19, seasonsKept: 1 },
    ],
  },
  {
    playerName: 'Jackson Chourio',
    entries: [
      { year: 2025, manager: 'John Gibbons', roundCost: 12, seasonsKept: 1 },
      { year: 2026, manager: 'John Gibbons', roundCost: 12, seasonsKept: 1 },
    ],
  },
  {
    playerName: 'Lawrence Butler',
    entries: [
      { year: 2026, manager: 'John Gibbons', roundCost: 25, seasonsKept: 1 },
    ],
  },
  {
    playerName: 'Jordan Westburg',
    entries: [
      { year: 2026, manager: 'John Gibbons', roundCost: 24, seasonsKept: 1 },
    ],
  },
  {
    playerName: 'Luis Gil',
    entries: [
      { year: 2026, manager: 'John Gibbons', roundCost: 23, seasonsKept: 1 },
    ],
  },
  {
    playerName: 'Chris Sale',
    entries: [
      { year: 2026, manager: 'Bryan Lewis', roundCost: 8, seasonsKept: 1 },
    ],
  },
  {
    playerName: 'Mookie Betts',
    entries: [
      { year: 2025, manager: 'Bryan Lewis', roundCost: 1, seasonsKept: 1 },
      { year: 2026, manager: 'Bryan Lewis', roundCost: 1, seasonsKept: 1 },
    ],
  },
  {
    playerName: 'Francisco Lindor',
    entries: [
      { year: 2026, manager: 'Bryan Lewis', roundCost: 4, seasonsKept: 1 },
    ],
  },
  {
    playerName: 'Jackson Merrill',
    entries: [
      { year: 2026, manager: 'Tim Riker', roundCost: 25, seasonsKept: 1 },
    ],
  },
  {
    playerName: 'Bryce Miller',
    entries: [
      { year: 2026, manager: 'Tim Riker', roundCost: 14, seasonsKept: 1 },
    ],
  },
  {
    playerName: 'Shohei Ohtani (2025)',
    entries: [
      { year: 2025, manager: 'Jess Barron', roundCost: 1, seasonsKept: 1 },
      { year: 2026, manager: 'Jess Barron', roundCost: 1, seasonsKept: 1 },
    ],
  },
  {
    playerName: 'Aaron Judge',
    entries: [
      { year: 2025, manager: 'Eric Mercado', roundCost: 1, seasonsKept: 1 },
      { year: 2026, manager: 'Eric Mercado', roundCost: 1, seasonsKept: 1 },
    ],
  },
  {
    playerName: 'Kodai Senga',
    entries: [
      { year: 2026, manager: 'Eric Mercado', roundCost: 14, seasonsKept: 1 },
    ],
  },
  {
    playerName: 'Shane Baz',
    entries: [
      { year: 2026, manager: 'Eric Mercado', roundCost: 24, seasonsKept: 1 },
    ],
  },
  {
    playerName: 'Mason Miller',
    entries: [
      { year: 2026, manager: 'Eric Mercado', roundCost: 25, seasonsKept: 1 },
    ],
  },
  {
    playerName: 'Elly De La Cruz',
    entries: [
      { year: 2025, manager: 'Matt Wayne', roundCost: 4, seasonsKept: 1 },
      { year: 2026, manager: 'Matt Wayne', roundCost: 4, seasonsKept: 1 },
    ],
  },
  {
    playerName: 'Garrett Crochet',
    entries: [
      { year: 2026, manager: 'Matt Wayne', roundCost: 23, seasonsKept: 1 },
    ],
  },
  {
    playerName: 'Jarren Duran',
    entries: [
      { year: 2026, manager: 'Matt Wayne', roundCost: 24, seasonsKept: 1 },
    ],
  },
  {
    playerName: 'James Wood',
    entries: [
      { year: 2026, manager: 'Matt Wayne', roundCost: 25, seasonsKept: 1 },
    ],
  },
  {
    playerName: "O'Neil Cruz",
    entries: [
      { year: 2026, manager: 'David Rotatori', roundCost: 8, seasonsKept: 1 },
    ],
  },
  {
    playerName: 'Hunter Brown',
    entries: [
      { year: 2026, manager: 'David Rotatori', roundCost: 17, seasonsKept: 1 },
    ],
  },
  {
    playerName: 'Jack Flaherty',
    entries: [
      { year: 2026, manager: 'David Rotatori', roundCost: 25, seasonsKept: 1 },
    ],
  },
]

/** Get all keeper histories, sorted by total seasons kept (longest first) */
export function getKeeperHistory(): KeeperHistory[] {
  return [...KEEPER_HISTORY].sort((a, b) => b.entries.length - a.entries.length)
}

// ── Draft History (Item 4) ──

export interface DraftHistoryEntry {
  year: number
  round: number
  pick: number
  manager: string
}

/** Normalize a player name for matching: lowercase, strip suffixes, periods, extra whitespace */
export function normalizeName(name: string): string {
  return name
    .toLowerCase()
    .replace(/\b(jr|sr|ii|iii|iv)\b\.?/g, '')
    .replace(/\./g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

/**
 * Recent draft history (2023–2025). For each player, only the most recent
 * appearance is stored. Key is normalized player name.
 */
export const RECENT_DRAFT_HISTORY: Record<string, DraftHistoryEntry> = {
  // ── 2025 Draft (most recent, takes priority) ──
  [normalizeName('Bobby Witt Jr.')]: { year: 2025, round: 1, pick: 1, manager: 'Harris Cook' },
  [normalizeName('Jose Ramirez')]: { year: 2025, round: 1, pick: 2, manager: 'Chris Herbst' },
  [normalizeName('Juan Soto')]: { year: 2025, round: 1, pick: 3, manager: 'John Gibbons' },
  [normalizeName('Vladimir Guerrero Jr.')]: { year: 2025, round: 1, pick: 4, manager: 'Jason McComb' },
  [normalizeName('Mookie Betts')]: { year: 2025, round: 1, pick: 5, manager: 'Bryan Lewis' },
  [normalizeName('Fernando Tatis Jr.')]: { year: 2025, round: 1, pick: 6, manager: 'Tim Riker' },
  [normalizeName('Shohei Ohtani')]: { year: 2025, round: 1, pick: 7, manager: 'Jess Barron' },
  [normalizeName('Aaron Judge')]: { year: 2025, round: 1, pick: 8, manager: 'Eric Mercado' },
  [normalizeName('Yordan Alvarez')]: { year: 2025, round: 1, pick: 9, manager: 'Matt Wayne' },
  [normalizeName('Corbin Carroll')]: { year: 2025, round: 1, pick: 10, manager: 'David Rotatori' },
  [normalizeName('Kyle Tucker')]: { year: 2025, round: 2, pick: 11, manager: 'David Rotatori' },
  [normalizeName('Zack Wheeler')]: { year: 2025, round: 2, pick: 12, manager: 'Matt Wayne' },
  [normalizeName('Ronald Acuna Jr.')]: { year: 2025, round: 2, pick: 13, manager: 'Harris Cook' },
  [normalizeName('Logan Gilbert')]: { year: 2025, round: 2, pick: 14, manager: 'Jess Barron' },
  [normalizeName('Corbin Burnes')]: { year: 2025, round: 2, pick: 15, manager: 'Tim Riker' },
  [normalizeName('Freddie Freeman')]: { year: 2025, round: 2, pick: 16, manager: 'Bryan Lewis' },
  [normalizeName('Marcell Ozuna')]: { year: 2025, round: 2, pick: 17, manager: 'Jason McComb' },
  [normalizeName('Jazz Chisholm Jr.')]: { year: 2025, round: 2, pick: 18, manager: 'John Gibbons' },
  [normalizeName('Trea Turner')]: { year: 2025, round: 2, pick: 19, manager: 'Chris Herbst' },
  [normalizeName('Jose Altuve')]: { year: 2025, round: 2, pick: 20, manager: 'Harris Cook' },
  [normalizeName('Austin Riley')]: { year: 2025, round: 3, pick: 21, manager: 'Harris Cook' },
  [normalizeName('Matt Olson')]: { year: 2025, round: 3, pick: 22, manager: 'Chris Herbst' },
  [normalizeName('Cole Ragans')]: { year: 2025, round: 3, pick: 23, manager: 'John Gibbons' },
  [normalizeName('Blake Snell')]: { year: 2025, round: 3, pick: 24, manager: 'Jason McComb' },
  [normalizeName('Gerrit Cole')]: { year: 2025, round: 3, pick: 25, manager: 'Bryan Lewis' },
  [normalizeName('Pete Alonso')]: { year: 2025, round: 3, pick: 26, manager: 'Tim Riker' },
  [normalizeName('William Contreras')]: { year: 2025, round: 3, pick: 27, manager: 'Jess Barron' },
  [normalizeName('Rafael Devers')]: { year: 2025, round: 3, pick: 28, manager: 'John Gibbons' },
  [normalizeName('George Kirby')]: { year: 2025, round: 3, pick: 29, manager: 'Matt Wayne' },
  [normalizeName('Corey Seager')]: { year: 2025, round: 3, pick: 30, manager: 'John Gibbons' },
  [normalizeName('Wyatt Langford')]: { year: 2025, round: 4, pick: 31, manager: 'David Rotatori' },
  [normalizeName('Elly De La Cruz')]: { year: 2025, round: 4, pick: 32, manager: 'Matt Wayne' },
  [normalizeName('Willy Adames')]: { year: 2025, round: 4, pick: 33, manager: 'Eric Mercado' },
  [normalizeName('Bryce Harper')]: { year: 2025, round: 4, pick: 34, manager: 'Jess Barron' },
  [normalizeName('Yoshinobu Yamamoto')]: { year: 2025, round: 4, pick: 35, manager: 'Tim Riker' },
  [normalizeName('Francisco Lindor')]: { year: 2025, round: 4, pick: 36, manager: 'Bryan Lewis' },
  [normalizeName('Pablo Lopez')]: { year: 2025, round: 4, pick: 37, manager: 'Jason McComb' },
  [normalizeName('Framber Valdez')]: { year: 2025, round: 4, pick: 38, manager: 'John Gibbons' },
  [normalizeName('Michael King')]: { year: 2025, round: 4, pick: 39, manager: 'Chris Herbst' },
  [normalizeName('Josh Naylor')]: { year: 2025, round: 4, pick: 40, manager: 'Harris Cook' },
  [normalizeName('Jacob deGrom')]: { year: 2025, round: 5, pick: 41, manager: 'Harris Cook' },
  [normalizeName('Shota Imanaga')]: { year: 2025, round: 5, pick: 42, manager: 'Chris Herbst' },
  [normalizeName('Ozzie Albies')]: { year: 2025, round: 5, pick: 43, manager: 'John Gibbons' },
  [normalizeName('Manny Machado')]: { year: 2025, round: 5, pick: 44, manager: 'Jason McComb' },
  [normalizeName('Kyle Schwarber')]: { year: 2025, round: 5, pick: 45, manager: 'Bryan Lewis' },
  [normalizeName('Hunter Greene')]: { year: 2025, round: 5, pick: 46, manager: 'Tim Riker' },
  [normalizeName('Devin Williams')]: { year: 2025, round: 5, pick: 47, manager: 'Jess Barron' },
  [normalizeName('Logan Webb')]: { year: 2025, round: 5, pick: 48, manager: 'Eric Mercado' },
  [normalizeName('Luis Castillo')]: { year: 2025, round: 5, pick: 49, manager: 'Harris Cook' },
  [normalizeName('Adley Rutschman')]: { year: 2025, round: 5, pick: 50, manager: 'John Gibbons' },
  [normalizeName('Alex Bregman')]: { year: 2025, round: 6, pick: 51, manager: 'David Rotatori' },
  [normalizeName('Brent Rooker')]: { year: 2025, round: 6, pick: 52, manager: 'Matt Wayne' },
  [normalizeName('Aaron Nola')]: { year: 2025, round: 6, pick: 53, manager: 'Eric Mercado' },
  [normalizeName('Emmanuel Clase')]: { year: 2025, round: 6, pick: 54, manager: 'Jess Barron' },
  [normalizeName('Christian Walker')]: { year: 2025, round: 6, pick: 55, manager: 'Tim Riker' },
  [normalizeName('Teoscar Hernandez')]: { year: 2025, round: 6, pick: 56, manager: 'Bryan Lewis' },
  [normalizeName('Bryan Reynolds')]: { year: 2025, round: 6, pick: 57, manager: 'Jason McComb' },
  [normalizeName('Max Fried')]: { year: 2025, round: 6, pick: 58, manager: 'John Gibbons' },
  [normalizeName('Marcus Semien')]: { year: 2025, round: 6, pick: 59, manager: 'Chris Herbst' },
  [normalizeName('Anthony Santander')]: { year: 2025, round: 6, pick: 60, manager: 'Harris Cook' },
  [normalizeName('Brenton Doyle')]: { year: 2025, round: 7, pick: 61, manager: 'Harris Cook' },
  [normalizeName('Bailey Ober')]: { year: 2025, round: 7, pick: 62, manager: 'Chris Herbst' },
  [normalizeName('Spencer Steer')]: { year: 2025, round: 7, pick: 63, manager: 'John Gibbons' },
  [normalizeName('Dylan Cease')]: { year: 2025, round: 7, pick: 64, manager: 'Jason McComb' },
  [normalizeName('Josh Hader')]: { year: 2025, round: 7, pick: 65, manager: 'Bryan Lewis' },
  [normalizeName('Mike Trout')]: { year: 2025, round: 7, pick: 66, manager: 'Tim Riker' },
  [normalizeName('Matt Chapman')]: { year: 2025, round: 7, pick: 67, manager: 'Jess Barron' },
  [normalizeName('Zac Gallen')]: { year: 2025, round: 7, pick: 68, manager: 'Eric Mercado' },
  [normalizeName('Triston Casas')]: { year: 2025, round: 7, pick: 69, manager: 'Matt Wayne' },
  [normalizeName('Bo Bichette')]: { year: 2025, round: 7, pick: 70, manager: 'David Rotatori' },
  [normalizeName("Oneil Cruz")]: { year: 2025, round: 8, pick: 71, manager: 'David Rotatori' },
  [normalizeName('Junior Caminero')]: { year: 2025, round: 8, pick: 72, manager: 'Matt Wayne' },
  [normalizeName('Grayson Rodriguez')]: { year: 2025, round: 8, pick: 73, manager: 'Eric Mercado' },
  [normalizeName('Randy Arozarena')]: { year: 2025, round: 8, pick: 74, manager: 'Jess Barron' },
  [normalizeName('Julio Rodriguez')]: { year: 2025, round: 8, pick: 75, manager: 'Tim Riker' },
  [normalizeName('Chris Sale')]: { year: 2025, round: 8, pick: 76, manager: 'Bryan Lewis' },
  [normalizeName('Steven Kwan')]: { year: 2025, round: 8, pick: 77, manager: 'Jason McComb' },
  [normalizeName('Roki Sasaki')]: { year: 2025, round: 8, pick: 78, manager: 'John Gibbons' },
  [normalizeName('Edwin Diaz')]: { year: 2025, round: 8, pick: 79, manager: 'Chris Herbst' },
  [normalizeName('Tanner Bibee')]: { year: 2025, round: 8, pick: 80, manager: 'Harris Cook' },
  [normalizeName('Riley Greene')]: { year: 2025, round: 9, pick: 81, manager: 'Harris Cook' },
  [normalizeName('Dylan Crews')]: { year: 2025, round: 9, pick: 82, manager: 'Chris Herbst' },
  [normalizeName('Joe Ryan')]: { year: 2025, round: 9, pick: 83, manager: 'John Gibbons' },
  [normalizeName('Brice Turang')]: { year: 2025, round: 9, pick: 84, manager: 'Jason McComb' },
  [normalizeName('Freddy Peralta')]: { year: 2025, round: 9, pick: 85, manager: 'Bryan Lewis' },
  [normalizeName('Jake Burger')]: { year: 2025, round: 9, pick: 86, manager: 'Tim Riker' },
  [normalizeName('Christian Yelich')]: { year: 2025, round: 9, pick: 87, manager: 'Jess Barron' },
  [normalizeName('Cody Bellinger')]: { year: 2025, round: 9, pick: 88, manager: 'Eric Mercado' },
  [normalizeName('Ryan Walker')]: { year: 2025, round: 9, pick: 89, manager: 'Matt Wayne' },
  [normalizeName('Shane McClanahan')]: { year: 2025, round: 9, pick: 90, manager: 'John Gibbons' },
  [normalizeName('Willson Contreras')]: { year: 2025, round: 10, pick: 91, manager: 'David Rotatori' },
  [normalizeName('Justin Steele')]: { year: 2025, round: 10, pick: 92, manager: 'Matt Wayne' },
  [normalizeName('Sonny Gray')]: { year: 2025, round: 10, pick: 93, manager: 'Eric Mercado' },
  [normalizeName('Matt McLain')]: { year: 2025, round: 10, pick: 94, manager: 'Jess Barron' },
  [normalizeName('Cal Raleigh')]: { year: 2025, round: 10, pick: 95, manager: 'Tim Riker' },
  [normalizeName('Salvador Perez')]: { year: 2025, round: 10, pick: 96, manager: 'Bryan Lewis' },
  [normalizeName('Ian Happ')]: { year: 2025, round: 10, pick: 97, manager: 'Jason McComb' },
  [normalizeName('Royce Lewis')]: { year: 2025, round: 10, pick: 98, manager: 'John Gibbons' },
  [normalizeName('Luis Robert Jr.')]: { year: 2025, round: 10, pick: 99, manager: 'Chris Herbst' },
  [normalizeName('Ryan Helsley')]: { year: 2025, round: 10, pick: 100, manager: 'Harris Cook' },
  [normalizeName('Yainer Diaz')]: { year: 2025, round: 11, pick: 101, manager: 'Harris Cook' },
  [normalizeName('Raisel Iglesias')]: { year: 2025, round: 11, pick: 102, manager: 'Chris Herbst' },
  [normalizeName('Seiya Suzuki')]: { year: 2025, round: 11, pick: 103, manager: 'John Gibbons' },
  [normalizeName('Masyn Winn')]: { year: 2025, round: 11, pick: 104, manager: 'Jason McComb' },
  [normalizeName('Felix Bautista')]: { year: 2025, round: 11, pick: 105, manager: 'Bryan Lewis' },
  [normalizeName('Jhoan Duran')]: { year: 2025, round: 11, pick: 106, manager: 'Tim Riker' },
  [normalizeName('Reynaldo Lopez')]: { year: 2025, round: 11, pick: 107, manager: 'Jess Barron' },
  [normalizeName('Luis Arraez')]: { year: 2025, round: 11, pick: 108, manager: 'Eric Mercado' },
  [normalizeName('Sandy Alcantara')]: { year: 2025, round: 11, pick: 109, manager: 'Matt Wayne' },
  [normalizeName('Andres Munoz')]: { year: 2025, round: 11, pick: 110, manager: 'David Rotatori' },
  [normalizeName('Vinnie Pasquantino')]: { year: 2025, round: 12, pick: 111, manager: 'David Rotatori' },
  [normalizeName('Will Smith')]: { year: 2025, round: 12, pick: 112, manager: 'Matt Wayne' },
  [normalizeName('Adolis Garcia')]: { year: 2025, round: 12, pick: 113, manager: 'Eric Mercado' },
  [normalizeName('Kevin Gausman')]: { year: 2025, round: 12, pick: 114, manager: 'Jess Barron' },
  [normalizeName('Tanner Scott')]: { year: 2025, round: 12, pick: 115, manager: 'Tim Riker' },
  [normalizeName('Nolan Arenado')]: { year: 2025, round: 12, pick: 116, manager: 'Bryan Lewis' },
  [normalizeName('Lucas Erceg')]: { year: 2025, round: 12, pick: 117, manager: 'Jason McComb' },
  [normalizeName('Jackson Chourio')]: { year: 2025, round: 12, pick: 118, manager: 'John Gibbons' },
  [normalizeName('Jasson Dominguez')]: { year: 2025, round: 12, pick: 119, manager: 'Chris Herbst' },
  [normalizeName('Robert Suarez')]: { year: 2025, round: 12, pick: 120, manager: 'Harris Cook' },
  [normalizeName('Pete Crow-Armstrong')]: { year: 2025, round: 13, pick: 121, manager: 'Harris Cook' },
  [normalizeName('Carlos Rodon')]: { year: 2025, round: 13, pick: 122, manager: 'Chris Herbst' },
  [normalizeName('Jared Jones')]: { year: 2025, round: 13, pick: 123, manager: 'John Gibbons' },
  [normalizeName('Seth Lugo')]: { year: 2025, round: 13, pick: 124, manager: 'Jason McComb' },
  [normalizeName('Yusei Kikuchi')]: { year: 2025, round: 13, pick: 125, manager: 'Bryan Lewis' },
  [normalizeName('Xavier Edwards')]: { year: 2025, round: 13, pick: 126, manager: 'Tim Riker' },
  [normalizeName('Brandon Nimmo')]: { year: 2025, round: 13, pick: 127, manager: 'Jess Barron' },
  [normalizeName('Eugenio Suarez')]: { year: 2025, round: 13, pick: 128, manager: 'Eric Mercado' },
  [normalizeName('Luke Weaver')]: { year: 2025, round: 13, pick: 129, manager: 'Matt Wayne' },
  [normalizeName('Jeff Hoffman')]: { year: 2025, round: 13, pick: 130, manager: 'David Rotatori' },
  [normalizeName('Jonathan India')]: { year: 2025, round: 14, pick: 131, manager: 'David Rotatori' },
  [normalizeName('Jurickson Profar')]: { year: 2025, round: 14, pick: 132, manager: 'Matt Wayne' },
  [normalizeName('Kodai Senga')]: { year: 2025, round: 14, pick: 133, manager: 'Eric Mercado' },
  [normalizeName('Ketel Marte')]: { year: 2025, round: 14, pick: 134, manager: 'Jess Barron' },
  [normalizeName('Bryce Miller')]: { year: 2025, round: 14, pick: 135, manager: 'Tim Riker' },
  [normalizeName('Jackson Holliday')]: { year: 2025, round: 14, pick: 136, manager: 'Bryan Lewis' },
  [normalizeName('J.T. Realmuto')]: { year: 2025, round: 14, pick: 137, manager: 'Jason McComb' },
  [normalizeName('Matthew Shaw')]: { year: 2025, round: 14, pick: 138, manager: 'John Gibbons' },
  [normalizeName('Nico Hoerner')]: { year: 2025, round: 14, pick: 140, manager: 'Harris Cook' },
  [normalizeName('Brandon Pfaadt')]: { year: 2025, round: 15, pick: 141, manager: 'Harris Cook' },
  [normalizeName('Tyler Glasnow')]: { year: 2025, round: 15, pick: 142, manager: 'Chris Herbst' },
  [normalizeName('Ryan Pepiot')]: { year: 2025, round: 15, pick: 143, manager: 'John Gibbons' },
  [normalizeName('Lourdes Gurriel Jr.')]: { year: 2025, round: 15, pick: 144, manager: 'Jason McComb' },
  [normalizeName('Nick Castellanos')]: { year: 2025, round: 15, pick: 145, manager: 'Bryan Lewis' },
  [normalizeName('Gunnar Henderson')]: { year: 2025, round: 15, pick: 146, manager: 'Tim Riker' },
  [normalizeName('Spencer Strider')]: { year: 2025, round: 15, pick: 147, manager: 'Jess Barron' },
  [normalizeName('Sean Manaea')]: { year: 2025, round: 15, pick: 148, manager: 'Harris Cook' },
  [normalizeName('Griffin Jax')]: { year: 2025, round: 15, pick: 149, manager: 'Matt Wayne' },
  [normalizeName('Michael Harris II')]: { year: 2025, round: 15, pick: 150, manager: 'David Rotatori' },
  [normalizeName('Brandon Woodruff')]: { year: 2025, round: 16, pick: 151, manager: 'David Rotatori' },
  [normalizeName('Spencer Arrighetti')]: { year: 2025, round: 16, pick: 152, manager: 'Matt Wayne' },
  [normalizeName('Tyler O\'Neill')]: { year: 2025, round: 16, pick: 154, manager: 'Jess Barron' },
  [normalizeName('Max Muncy')]: { year: 2025, round: 16, pick: 155, manager: 'Eric Mercado' },
  [normalizeName('Taj Bradley')]: { year: 2025, round: 16, pick: 156, manager: 'Bryan Lewis' },
  [normalizeName('Tanner Houck')]: { year: 2025, round: 16, pick: 157, manager: 'Jason McComb' },
  [normalizeName('Trevor Megill')]: { year: 2025, round: 16, pick: 158, manager: 'John Gibbons' },
  [normalizeName('Paul Goldschmidt')]: { year: 2025, round: 16, pick: 159, manager: 'Chris Herbst' },
  [normalizeName('Bryan Woo')]: { year: 2025, round: 16, pick: 160, manager: 'Harris Cook' },
  [normalizeName('CJ Abrams')]: { year: 2025, round: 17, pick: 161, manager: 'Harris Cook' },
  [normalizeName('Xander Bogaerts')]: { year: 2025, round: 17, pick: 162, manager: 'Chris Herbst' },
  [normalizeName('Anthony Volpe')]: { year: 2025, round: 17, pick: 163, manager: 'John Gibbons' },
  [normalizeName('Zach Eflin')]: { year: 2025, round: 17, pick: 164, manager: 'Jason McComb' },
  [normalizeName('Alec Bohm')]: { year: 2025, round: 17, pick: 165, manager: 'Bryan Lewis' },
  [normalizeName('Drew Rasmussen')]: { year: 2025, round: 17, pick: 166, manager: 'Tim Riker' },
  [normalizeName('Pete Fairbanks')]: { year: 2025, round: 17, pick: 167, manager: 'Jess Barron' },
  [normalizeName('Heliot Ramos')]: { year: 2025, round: 17, pick: 168, manager: 'Eric Mercado' },
  [normalizeName('Gavin Williams')]: { year: 2025, round: 17, pick: 169, manager: 'Matt Wayne' },
  [normalizeName('Hunter Brown')]: { year: 2025, round: 17, pick: 170, manager: 'David Rotatori' },
  [normalizeName('Walker Buehler')]: { year: 2025, round: 18, pick: 171, manager: 'David Rotatori' },
  [normalizeName('Isaac Paredes')]: { year: 2025, round: 18, pick: 172, manager: 'Matt Wayne' },
  [normalizeName('Jorge Soler')]: { year: 2025, round: 18, pick: 173, manager: 'Eric Mercado' },
  [normalizeName('A.J. Puk')]: { year: 2025, round: 18, pick: 174, manager: 'Jess Barron' },
  [normalizeName('Evan Carter')]: { year: 2025, round: 18, pick: 175, manager: 'Tim Riker' },
  [normalizeName('Luis Garcia Jr.')]: { year: 2025, round: 18, pick: 176, manager: 'Bryan Lewis' },
  [normalizeName('Colton Cowser')]: { year: 2025, round: 18, pick: 177, manager: 'Jason McComb' },
  [normalizeName('Luis Gil')]: { year: 2025, round: 18, pick: 178, manager: 'John Gibbons' },
  [normalizeName('Francisco Alvarez')]: { year: 2025, round: 18, pick: 179, manager: 'Chris Herbst' },
  [normalizeName('Tarik Skubal')]: { year: 2025, round: 18, pick: 180, manager: 'Harris Cook' },
  [normalizeName('MacKenzie Gore')]: { year: 2025, round: 19, pick: 181, manager: 'Eric Mercado' },
  [normalizeName('Ezequiel Tovar')]: { year: 2025, round: 19, pick: 182, manager: 'Chris Herbst' },
  [normalizeName('Jordan Westburg')]: { year: 2025, round: 19, pick: 183, manager: 'John Gibbons' },
  [normalizeName('Porter Hodge')]: { year: 2025, round: 19, pick: 184, manager: 'Jason McComb' },
  [normalizeName('Mitch Keller')]: { year: 2025, round: 19, pick: 185, manager: 'Bryan Lewis' },
  [normalizeName('Jackson Jobe')]: { year: 2025, round: 19, pick: 186, manager: 'Tim Riker' },
  [normalizeName('Josh Lowe')]: { year: 2025, round: 19, pick: 187, manager: 'Jess Barron' },
  [normalizeName('Ronel Blanco')]: { year: 2025, round: 19, pick: 188, manager: 'Eric Mercado' },
  [normalizeName('Maikel Garcia')]: { year: 2025, round: 19, pick: 189, manager: 'Matt Wayne' },
  [normalizeName('David Bednar')]: { year: 2025, round: 19, pick: 190, manager: 'David Rotatori' },
  [normalizeName('Merrill Kelly')]: { year: 2025, round: 20, pick: 191, manager: 'David Rotatori' },
  [normalizeName('Edwin Uceta')]: { year: 2025, round: 20, pick: 192, manager: 'Matt Wayne' },
  [normalizeName('Kenley Jansen')]: { year: 2025, round: 20, pick: 193, manager: 'Eric Mercado' },
  [normalizeName('Jose Berrios')]: { year: 2025, round: 20, pick: 194, manager: 'Jess Barron' },
  [normalizeName('Jason Adam')]: { year: 2025, round: 20, pick: 195, manager: 'Tim Riker' },
  [normalizeName('Paul Skenes')]: { year: 2025, round: 20, pick: 196, manager: 'Bryan Lewis' },
  [normalizeName('Ranger Suarez')]: { year: 2025, round: 20, pick: 197, manager: 'Jason McComb' },
  [normalizeName('Shea Langeliers')]: { year: 2025, round: 20, pick: 198, manager: 'Eric Mercado' },
  [normalizeName('Yennier Cano')]: { year: 2025, round: 20, pick: 200, manager: 'Harris Cook' },
  [normalizeName('Bowden Francis')]: { year: 2025, round: 21, pick: 201, manager: 'Harris Cook' },
  [normalizeName('Lawrence Butler')]: { year: 2025, round: 21, pick: 203, manager: 'John Gibbons' },
  [normalizeName('Jeremy Pena')]: { year: 2025, round: 21, pick: 204, manager: 'Jason McComb' },
  [normalizeName('Nick Pivetta')]: { year: 2025, round: 21, pick: 205, manager: 'Bryan Lewis' },
  [normalizeName('Jack Leiter')]: { year: 2025, round: 21, pick: 206, manager: 'Tim Riker' },
  [normalizeName('Nathan Eovaldi')]: { year: 2025, round: 21, pick: 207, manager: 'Jess Barron' },
  [normalizeName('Justin Martinez')]: { year: 2025, round: 21, pick: 208, manager: 'Eric Mercado' },
  [normalizeName('Thairo Estrada')]: { year: 2025, round: 21, pick: 209, manager: 'Matt Wayne' },
  [normalizeName('Rhys Hoskins')]: { year: 2025, round: 21, pick: 210, manager: 'David Rotatori' },
  [normalizeName('Clarke Schmidt')]: { year: 2025, round: 22, pick: 212, manager: 'Matt Wayne' },
  [normalizeName('Clay Holmes')]: { year: 2025, round: 22, pick: 213, manager: 'Eric Mercado' },
  [normalizeName('Nestor Cortes')]: { year: 2025, round: 22, pick: 214, manager: 'Jess Barron' },
  [normalizeName('Jesus Luzardo')]: { year: 2025, round: 22, pick: 215, manager: 'Tim Riker' },
  [normalizeName('Bryan Abreu')]: { year: 2025, round: 22, pick: 216, manager: 'Bryan Lewis' },
  [normalizeName('Ben Joyce')]: { year: 2025, round: 22, pick: 217, manager: 'Jason McComb' },
  [normalizeName('Nick Lodolo')]: { year: 2025, round: 22, pick: 218, manager: 'David Rotatori' },
  [normalizeName('Kerry Carpenter')]: { year: 2025, round: 22, pick: 219, manager: 'Harris Cook' },
  [normalizeName('Spencer Schwellenbach')]: { year: 2025, round: 23, pick: 220, manager: 'Harris Cook' },
  [normalizeName('Cristopher Sanchez')]: { year: 2025, round: 23, pick: 221, manager: 'Chris Herbst' },
  [normalizeName('Taylor Ward')]: { year: 2025, round: 23, pick: 223, manager: 'Bryan Lewis' },
  [normalizeName('Brandon Lowe')]: { year: 2025, round: 23, pick: 224, manager: 'Tim Riker' },
  [normalizeName('Lars Nootbaar')]: { year: 2025, round: 23, pick: 225, manager: 'Jess Barron' },
  [normalizeName('Gleyber Torres')]: { year: 2025, round: 23, pick: 226, manager: 'Eric Mercado' },
  [normalizeName('Garrett Crochet')]: { year: 2025, round: 23, pick: 227, manager: 'Matt Wayne' },
  [normalizeName('Christopher Morel')]: { year: 2025, round: 23, pick: 228, manager: 'David Rotatori' },
  [normalizeName('Yu Darvish')]: { year: 2025, round: 24, pick: 229, manager: 'David Rotatori' },
  [normalizeName('Jarren Duran')]: { year: 2025, round: 24, pick: 230, manager: 'Matt Wayne' },
  [normalizeName('Shane Baz')]: { year: 2025, round: 24, pick: 231, manager: 'Eric Mercado' },
  [normalizeName('Jeffrey Springs')]: { year: 2025, round: 24, pick: 232, manager: 'Jess Barron' },
  [normalizeName('Orion Kerkering')]: { year: 2025, round: 24, pick: 233, manager: 'Tim Riker' },
  [normalizeName('Max Scherzer')]: { year: 2025, round: 24, pick: 234, manager: 'Bryan Lewis' },
  [normalizeName('Justin Verlander')]: { year: 2025, round: 24, pick: 235, manager: 'Jason McComb' },
  [normalizeName('Brady Singer')]: { year: 2025, round: 24, pick: 236, manager: 'Chris Herbst' },
  [normalizeName('Mark Vientos')]: { year: 2025, round: 25, pick: 237, manager: 'Chris Herbst' },
  [normalizeName('Connor Norby')]: { year: 2025, round: 25, pick: 238, manager: 'Jason McComb' },
  [normalizeName('Victor Robles')]: { year: 2025, round: 25, pick: 239, manager: 'Bryan Lewis' },
  [normalizeName('Jackson Merrill')]: { year: 2025, round: 25, pick: 240, manager: 'Tim Riker' },
  [normalizeName('Kutter Crawford')]: { year: 2025, round: 25, pick: 241, manager: 'Jess Barron' },
  [normalizeName('Mason Miller')]: { year: 2025, round: 25, pick: 242, manager: 'Eric Mercado' },
  [normalizeName('James Wood')]: { year: 2025, round: 25, pick: 243, manager: 'Matt Wayne' },
  [normalizeName('Jack Flaherty')]: { year: 2025, round: 25, pick: 244, manager: 'David Rotatori' },
  // ── 2024 Draft (fills in players not in 2025) ──
  [normalizeName('Dansby Swanson')]: { year: 2024, round: 11, pick: 106, manager: 'Jason McComb' },
  [normalizeName('Bryson Stott')]: { year: 2024, round: 16, pick: 155, manager: 'Jason McComb' },
  [normalizeName('Bobby Miller')]: { year: 2024, round: 4, pick: 37, manager: 'Chris Herbst' },
  [normalizeName('Nolan Jones')]: { year: 2024, round: 6, pick: 56, manager: 'Matt Wayne' },
  [normalizeName('Joe Musgrove')]: { year: 2024, round: 6, pick: 57, manager: 'Chris Herbst' },
  [normalizeName('Jordan Montgomery')]: { year: 2024, round: 7, pick: 67, manager: 'John Gibbons' },
  [normalizeName('Evan Phillips')]: { year: 2024, round: 11, pick: 101, manager: 'Bryan Lewis' },
  [normalizeName('Jose Alvarado')]: { year: 2024, round: 11, pick: 102, manager: 'Jess Barron' },
  [normalizeName('Charlie Morton')]: { year: 2024, round: 11, pick: 110, manager: 'David Rotatori' },
  [normalizeName('Shane Bieber')]: { year: 2024, round: 12, pick: 112, manager: 'Eric Mercado' },
  [normalizeName('Josh Jung')]: { year: 2024, round: 12, pick: 113, manager: 'Harris Cook' },
  [normalizeName('Eloy Jimenez')]: { year: 2024, round: 12, pick: 116, manager: 'Matt Wayne' },
  [normalizeName('Andres Gimenez')]: { year: 2024, round: 14, pick: 137, manager: 'Chris Herbst' },
  [normalizeName('Lane Thomas')]: { year: 2024, round: 14, pick: 139, manager: 'Jess Barron' },
  [normalizeName('TJ Friedl')]: { year: 2024, round: 14, pick: 133, manager: 'Harris Cook' },
  [normalizeName('James Outman')]: { year: 2024, round: 14, pick: 136, manager: 'Matt Wayne' },
  [normalizeName('Christian Encarnacion-Strand')]: { year: 2024, round: 15, pick: 143, manager: 'Tim Riker' },
  [normalizeName('Zack Gelof')]: { year: 2024, round: 15, pick: 144, manager: 'Tim Riker' },
  [normalizeName('A.J. Minter')]: { year: 2024, round: 15, pick: 145, manager: 'Matt Wayne' },
  [normalizeName('Masataka Yoshida')]: { year: 2024, round: 16, pick: 154, manager: 'John Gibbons' },
  [normalizeName('Craig Kimbrel')]: { year: 2024, round: 16, pick: 158, manager: 'Tim Riker' },
  [normalizeName('Jordan Walker')]: { year: 2024, round: 10, pick: 97, manager: 'Chris Herbst' },
  [normalizeName('Spencer Torkelson')]: { year: 2024, round: 10, pick: 93, manager: 'Harris Cook' },
  [normalizeName('Ha-Seong Kim')]: { year: 2024, round: 10, pick: 94, manager: 'John Gibbons' },
  [normalizeName('George Springer')]: { year: 2024, round: 10, pick: 92, manager: 'Bryan Lewis' },
  [normalizeName('Logan O\'Hoppe')]: { year: 2024, round: 19, pick: 189, manager: 'David Rotatori' },
  [normalizeName('Nolan Gorman')]: { year: 2024, round: 19, pick: 182, manager: 'Tim Riker' },
  [normalizeName('Tommy Edman')]: { year: 2024, round: 20, pick: 194, manager: 'Jason McComb' },
  [normalizeName('Andrew Abbott')]: { year: 2024, round: 20, pick: 193, manager: 'John Gibbons' },
  [normalizeName('Jung Hoo Lee')]: { year: 2024, round: 18, pick: 171, manager: 'David Rotatori' },
  [normalizeName('Kyle Harrison')]: { year: 2024, round: 18, pick: 173, manager: 'Harris Cook' },
  [normalizeName('Braxton Garrett')]: { year: 2024, round: 18, pick: 174, manager: 'John Gibbons' },
  [normalizeName('Reid Detmers')]: { year: 2024, round: 18, pick: 175, manager: 'Jason McComb' },
  [normalizeName('Carlos Correa')]: { year: 2024, round: 21, pick: 204, manager: 'John Gibbons' },
  [normalizeName('Giancarlo Stanton')]: { year: 2024, round: 22, pick: 208, manager: 'David Rotatori' },
  [normalizeName('Brandon Drury')]: { year: 2024, round: 22, pick: 213, manager: 'Matt Wayne' },
  [normalizeName('Jake Cronenworth')]: { year: 2024, round: 23, pick: 220, manager: 'Jason McComb' },
  [normalizeName('Edouard Julien')]: { year: 2024, round: 24, pick: 225, manager: 'David Rotatori' },
  [normalizeName('Eury Perez')]: { year: 2024, round: 25, pick: 240, manager: 'Harris Cook' },
  [normalizeName('Jonah Heim')]: { year: 2024, round: 25, pick: 238, manager: 'Jason McComb' },
  [normalizeName('Yandy Diaz')]: { year: 2024, round: 25, pick: 239, manager: 'John Gibbons' },
  [normalizeName('J.P. Crawford')]: { year: 2024, round: 21, pick: 203, manager: 'Jason McComb' },
  [normalizeName('Luis Severino')]: { year: 2024, round: 17, pick: 162, manager: 'Jess Barron' },
  [normalizeName('Eduardo Rodriguez')]: { year: 2024, round: 14, pick: 131, manager: 'Jess Barron' },
  [normalizeName('Triston McKenzie')]: { year: 2024, round: 13, pick: 125, manager: 'Matt Wayne' },
  [normalizeName('Byron Buxton')]: { year: 2024, round: 13, pick: 130, manager: 'David Rotatori' },
  [normalizeName('Chris Bassitt')]: { year: 2024, round: 11, pick: 109, manager: 'Eric Mercado' },
  [normalizeName('Paul Sewald')]: { year: 2024, round: 11, pick: 108, manager: 'Harris Cook' },
  [normalizeName('Sean Murphy')]: { year: 2024, round: 20, pick: 192, manager: 'Harris Cook' },
  [normalizeName('Starling Marte')]: { year: 2024, round: 22, pick: 214, manager: 'Chris Herbst' },
  [normalizeName('Anthony Rizzo')]: { year: 2024, round: 23, pick: 224, manager: 'David Rotatori' },
  [normalizeName('Ryan Pressly')]: { year: 2024, round: 21, pick: 207, manager: 'David Rotatori' },
  [normalizeName('Kenta Maeda')]: { year: 2024, round: 23, pick: 222, manager: 'Harris Cook' },
  [normalizeName('Lance Lynn')]: { year: 2024, round: 24, pick: 230, manager: 'Matt Wayne' },
  [normalizeName('DJ LeMahieu')]: { year: 2024, round: 24, pick: 231, manager: 'Chris Herbst' },
  [normalizeName('Trevor Story')]: { year: 2024, round: 24, pick: 232, manager: 'Tim Riker' },
  // ── 2023 Draft (fills in players not in 2024 or 2025) ──
  [normalizeName('Shane McClanahan')]: { year: 2023, round: 7, pick: 63, manager: 'Chris Herbst' },
  [normalizeName('Kyle Schwarber')]: { year: 2023, round: 10, pick: 99, manager: 'John Gibbons' },
  [normalizeName('Wander Franco')]: { year: 2023, round: 13, pick: 121, manager: 'Jason McComb' },
  [normalizeName('Ty France')]: { year: 2023, round: 17, pick: 166, manager: 'Bryan Lewis' },
  [normalizeName('Jose Miranda')]: { year: 2023, round: 19, pick: 181, manager: 'Jason McComb' },
  [normalizeName('Alek Manoah')]: { year: 2023, round: 19, pick: 187, manager: 'David Rotatori' },
  [normalizeName('Lucas Giolito')]: { year: 2023, round: 20, pick: 192, manager: 'Harris Cook' },
  [normalizeName('Nathaniel Lowe')]: { year: 2023, round: 25, pick: 241, manager: 'Harris Cook' },
  [normalizeName('Jeff McNeil')]: { year: 2023, round: 25, pick: 240, manager: 'Eric Mercado' },
}

const _draftHistoryMap = new Map(
  Object.entries(RECENT_DRAFT_HISTORY).map(([k, v]) => [k, v])
)

/** Look up a player's most recent draft history in this league */
export function getDraftHistory(playerName: string): DraftHistoryEntry | null {
  return _draftHistoryMap.get(normalizeName(playerName)) ?? null
}
