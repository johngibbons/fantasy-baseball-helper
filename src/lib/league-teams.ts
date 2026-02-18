// ── Shared team types, loading, storage, and keeper-draft utilities ──

export interface DraftTeam {
  id: number
  name: string
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
