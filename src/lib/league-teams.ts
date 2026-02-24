// ── Shared team types, loading, storage, and keeper-draft utilities ──

import { TEAM_MANAGER } from './draft-history'

export interface DraftTeam {
  id: number
  name: string
}

/** Return team name with owner, e.g. "Team NOTO (John Gibbons)" */
export function teamDisplayName(team: DraftTeam): string {
  const owner = TEAM_MANAGER[team.id]
  return owner ? `${team.name} (${owner})` : team.name
}

export interface LeagueKeeperEntry {
  teamId: number
  mlb_id: number
  playerName: string
  roundCost: number
  primaryPosition?: string
}

const DEFAULT_NUM_TEAMS = 10

export function makeDefaultTeams(n: number): DraftTeam[] {
  return Array.from({ length: n }, (_, i) => ({ id: i + 1, name: `Team ${i + 1}` }))
}

export function loadTeamsFromStorage(): DraftTeam[] {
  try {
    const raw = localStorage.getItem('leagueTeams')
    if (raw) return JSON.parse(raw)
  } catch { /* ignore */ }
  return []
}

export function saveTeamsToStorage(teams: DraftTeam[]): void {
  localStorage.setItem('leagueTeams', JSON.stringify(teams))
}

/**
 * Fetch league teams from the ESPN API, falling back to localStorage or defaults.
 * Saves to localStorage on success.
 */
export async function fetchLeagueTeams(): Promise<DraftTeam[]> {
  try {
    const leaguesRes = await fetch('/api/leagues')
    const leagues: { id: string }[] = await leaguesRes.json()
    if (leagues.length > 0) {
      const teamsRes = await fetch(`/api/leagues/${leagues[0].id}/teams`)
      const data: { teams: { externalId: string; name: string }[] } = await teamsRes.json()
      const teams = data.teams.map(t => ({ id: parseInt(t.externalId), name: t.name }))
      if (teams.length > 0) {
        saveTeamsToStorage(teams)
        return teams
      }
    }
  } catch { /* fall through */ }

  // Fallback: localStorage then defaults
  const stored = loadTeamsFromStorage()
  if (stored.length > 0) return stored

  const defaults = makeDefaultTeams(DEFAULT_NUM_TEAMS)
  saveTeamsToStorage(defaults)
  return defaults
}

/**
 * Convert a keeper's (teamId, roundCost) into its snake-draft pick index (0-based).
 *
 * In a snake draft:
 *   - Even rounds (0-indexed): left to right in draftOrder
 *   - Odd rounds (0-indexed):  right to left in draftOrder
 *
 * roundCost is 1-based (round 1 = first round).
 */
export function keeperPickIndex(
  teamId: number,
  roundCost: number,
  draftOrder: number[]
): number {
  if (draftOrder.length === 0) return -1
  const numTeams = draftOrder.length
  const round0 = roundCost - 1 // 0-indexed round

  // Find the team's position within this round
  let posInRound: number
  if (round0 % 2 === 0) {
    // Even round: forward order
    posInRound = draftOrder.indexOf(teamId)
  } else {
    // Odd round: reverse order
    posInRound = numTeams - 1 - draftOrder.indexOf(teamId)
  }

  if (posInRound < 0) return -1
  return round0 * numTeams + posInRound
}

// ── Pick schedule types and utilities ──

export type PickSchedule = number[]  // pickSchedule[pickIndex] = teamId

export interface PickTrade {
  pickIndex: number
  fromTeamId: number
  toTeamId: number
}

/**
 * Generate a flat snake-order schedule: numRounds × numTeams entries.
 * schedule[pickIndex] = teamId that owns that pick.
 */
export function generateSnakeSchedule(draftOrder: number[], numRounds = 25): PickSchedule {
  const numTeams = draftOrder.length
  if (numTeams === 0) return []
  const schedule: number[] = []
  for (let round = 0; round < numRounds; round++) {
    for (let pos = 0; pos < numTeams; pos++) {
      schedule.push(
        round % 2 === 0 ? draftOrder[pos] : draftOrder[numTeams - 1 - pos]
      )
    }
  }
  return schedule
}

/**
 * Find a team's pick index in a specific round by scanning the schedule.
 * Returns -1 if the team has no pick in that round (e.g. traded away).
 */
export function keeperPickIndexFromSchedule(
  teamId: number,
  roundCost: number,
  schedule: PickSchedule,
  numTeams: number
): number {
  if (schedule.length === 0 || numTeams === 0) return -1
  const roundStart = (roundCost - 1) * numTeams
  const roundEnd = Math.min(roundStart + numTeams, schedule.length)
  for (let i = roundStart; i < roundEnd; i++) {
    if (schedule[i] === teamId) return i
  }
  return -1
}

/**
 * Ensure every team has at least `rosterSize` picks by appending supplemental picks.
 * Returns a new schedule (does not mutate the input).
 */
export function ensureSupplementalPicks(
  schedule: PickSchedule,
  allTeamIds: number[],
  rosterSize = 25
): PickSchedule {
  const counts = new Map<number, number>()
  for (const id of allTeamIds) counts.set(id, 0)
  for (const id of schedule) {
    counts.set(id, (counts.get(id) ?? 0) + 1)
  }

  const supplemental: number[] = []
  for (const id of allTeamIds) {
    const have = counts.get(id) ?? 0
    for (let i = have; i < rosterSize; i++) {
      supplemental.push(id)
    }
  }

  if (supplemental.length === 0) return schedule
  return [...schedule, ...supplemental]
}

/**
 * Reassign a pick and recalculate supplemental picks.
 * Returns { schedule, trade }.
 */
export function tradePickInSchedule(
  schedule: PickSchedule,
  pickIndex: number,
  toTeamId: number,
  allTeamIds: number[]
): { schedule: PickSchedule; trade: PickTrade } {
  const fromTeamId = schedule[pickIndex]
  const numTeams = allTeamIds.length
  // Strip any existing supplemental picks (beyond 25 * numTeams)
  const baseLength = 25 * numTeams
  const base = schedule.slice(0, baseLength)
  base[pickIndex] = toTeamId
  const newSchedule = ensureSupplementalPicks(base, allTeamIds)
  return {
    schedule: newSchedule,
    trade: { pickIndex, fromTeamId, toTeamId },
  }
}
