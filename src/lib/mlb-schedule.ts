const MLB_API_BASE = 'https://statsapi.mlb.com/api/v1'

const MLB_TEAM_ABBREVS: Record<number, string> = {
  108: 'LAA', 109: 'ARI', 110: 'BAL', 111: 'BOS', 112: 'CHC',
  113: 'CIN', 114: 'CLE', 115: 'COL', 116: 'DET', 117: 'HOU',
  118: 'KC', 119: 'LAD', 120: 'WSH', 121: 'NYM', 133: 'OAK',
  134: 'PIT', 135: 'SD', 136: 'SEA', 137: 'SF', 138: 'STL',
  139: 'TB', 140: 'TEX', 141: 'TOR', 142: 'MIN', 143: 'PHI',
  144: 'ATL', 145: 'CWS', 146: 'MIA', 147: 'NYY', 158: 'MIL',
}

export interface TeamGamesRemaining {
  [teamAbbrev: string]: number
}

export interface ProbablePitcherEntry {
  date: string
  mlbPlayerId: number
  fullName: string
  teamId: number
  opponentTeamId: number
}

export async function getTeamGamesInRange(
  startDate: string,
  endDate: string,
): Promise<TeamGamesRemaining> {
  const url = `${MLB_API_BASE}/schedule?sportId=1&startDate=${startDate}&endDate=${endDate}`
  const response = await fetch(url)
  if (!response.ok) {
    throw new Error(`MLB Schedule API error: ${response.status}`)
  }

  const data = await response.json()
  const teamGames: Record<string, number> = {}

  for (const dateEntry of data.dates || []) {
    for (const game of dateEntry.games || []) {
      if (game.status?.abstractGameCode === 'F' || game.gameType !== 'R') continue
      const homeId = game.teams?.home?.team?.id
      const awayId = game.teams?.away?.team?.id
      if (homeId) {
        const abbrev = MLB_TEAM_ABBREVS[homeId] || `T${homeId}`
        teamGames[abbrev] = (teamGames[abbrev] || 0) + 1
      }
      if (awayId) {
        const abbrev = MLB_TEAM_ABBREVS[awayId] || `T${awayId}`
        teamGames[abbrev] = (teamGames[abbrev] || 0) + 1
      }
    }
  }

  return teamGames
}

export async function getProbablePitchers(
  startDate: string,
  endDate: string,
): Promise<ProbablePitcherEntry[]> {
  const url = `${MLB_API_BASE}/schedule?sportId=1&startDate=${startDate}&endDate=${endDate}&hydrate=probablePitcher`
  const response = await fetch(url)
  if (!response.ok) {
    throw new Error(`MLB Probable Pitchers API error: ${response.status}`)
  }

  const data = await response.json()
  const pitchers: ProbablePitcherEntry[] = []

  for (const dateEntry of data.dates || []) {
    const date = dateEntry.date
    for (const game of dateEntry.games || []) {
      if (game.gameType !== 'R') continue
      const homePitcher = game.teams?.home?.probablePitcher
      const awayPitcher = game.teams?.away?.probablePitcher
      const homeTeamId = game.teams?.home?.team?.id
      const awayTeamId = game.teams?.away?.team?.id
      if (homePitcher?.id) {
        pitchers.push({
          date,
          mlbPlayerId: homePitcher.id,
          fullName: homePitcher.fullName ?? '',
          teamId: homeTeamId,
          opponentTeamId: awayTeamId,
        })
      }
      if (awayPitcher?.id) {
        pitchers.push({
          date,
          mlbPlayerId: awayPitcher.id,
          fullName: awayPitcher.fullName ?? '',
          teamId: awayTeamId,
          opponentTeamId: homeTeamId,
        })
      }
    }
  }

  return pitchers
}

export async function getRemainingSeasonGames(
  season: string,
): Promise<TeamGamesRemaining> {
  const url = `${MLB_API_BASE}/standings?leagueId=103,104&season=${season}`
  const response = await fetch(url)
  if (!response.ok) {
    throw new Error(`MLB Standings API error: ${response.status}`)
  }

  const data = await response.json()
  const remaining: Record<string, number> = {}

  for (const record of data.records || []) {
    for (const teamRecord of record.teamRecords || []) {
      const teamId = teamRecord.team?.id
      const gamesPlayed = teamRecord.gamesPlayed || 0
      const abbrev = MLB_TEAM_ABBREVS[teamId] || `T${teamId}`
      remaining[abbrev] = Math.max(1, 162 - gamesPlayed)
    }
  }

  return remaining
}
