interface ESPNLeagueSettings {
  swid: string
  espn_s2: string
}

export interface ESPNLeague {
  id: string
  settings: {
    name: string
    size: number
    scoringSettings?: any
    rosterSettings?: any
    acquisitionSettings?: any
  }
  status?: {
    currentMatchupPeriod?: number
    finalScoringPeriod?: number
    isActive?: boolean
    latestScoringPeriod?: number
  }
  currentMatchupPeriod?: number
  finalScoringPeriod?: number
  isActive?: boolean
  latestScoringPeriod?: number
}

export interface ESPNTeam {
  id: number
  abbrev: string
  location: string
  nickname: string
  owners: string[]
  record?: {
    overall: {
      wins: number
      losses: number
      ties: number
      pointsFor: number
      pointsAgainst: number
    }
  }
}

export interface ESPNRosterEntry {
  playerId: number
  lineupSlotId: number
  acquisitionType: string
  acquisitionDate: number
  player?: ESPNPlayer
}

export interface ESPNPlayer {
  id: number
  fullName: string
  firstName: string
  lastName: string
  eligibleSlots: number[]
  defaultPositionId: number
  proTeamId?: number
  injuryStatus?: string
  stats?: any[]
  /** Maps ESPN game event ID → starter status (e.g. "PROBABLE"). This is the PP tag. */
  starterStatusByProGame?: Record<string, string>
}

export class ESPNApi {
  private static getHeaders(settings: ESPNLeagueSettings) {
    return {
      'Cookie': `swid=${settings.swid}; espn_s2=${settings.espn_s2}`,
      'Content-Type': 'application/json'
    }
  }

  static async getLeague(leagueId: string, season: string, settings: ESPNLeagueSettings): Promise<ESPNLeague> {
    // ESPN Fantasy Baseball game code is 'flb'
    // Request settings view to get scoring configuration
    const url = `https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb/seasons/${season}/segments/0/leagues/${leagueId}?view=mSettings`
    
    console.log('ESPN API URL:', url)
    
    const response = await fetch(url, {
      headers: this.getHeaders(settings)
    })

    console.log('ESPN API response status:', response.status)

    if (!response.ok) {
      const errorText = await response.text()
      console.error('ESPN API error response:', errorText)
      throw new Error(`ESPN API error: ${response.status} - ${response.statusText}`)
    }

    const data = await response.json()
    console.log('ESPN API response data keys:', Object.keys(data))
    
    // Log scoring settings if available
    if (data.settings?.scoringSettings) {
      console.log('ESPN Scoring Settings:', JSON.stringify(data.settings.scoringSettings, null, 2))
    }
    
    return data
  }

  static async getTeams(leagueId: string, season: string, settings: ESPNLeagueSettings): Promise<ESPNTeam[]> {
    const url = `https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb/seasons/${season}/segments/0/leagues/${leagueId}?view=mTeam`
    
    const response = await fetch(url, {
      headers: this.getHeaders(settings)
    })

    if (!response.ok) {
      throw new Error(`ESPN API error: ${response.status} - ${response.statusText}`)
    }

    const data = await response.json()
    return data.teams || []
  }

  static async getRosters(leagueId: string, season: string, settings: ESPNLeagueSettings): Promise<{ [teamId: number]: ESPNRosterEntry[] }> {
    // Use multiple views to get comprehensive roster and player data
    const url = `https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb/seasons/${season}/segments/0/leagues/${leagueId}?view=mRoster&view=kona_player_info`
    
    console.log('ESPN Roster API URL:', url)
    
    const response = await fetch(url, {
      headers: this.getHeaders(settings)
    })

    if (!response.ok) {
      throw new Error(`ESPN API error: ${response.status} - ${response.statusText}`)
    }

    const data = await response.json()
    const rosters: { [teamId: number]: ESPNRosterEntry[] } = {}
    
    console.log('ESPN roster response teams count:', data.teams?.length || 0)
    
    if (data.teams) {
      data.teams.forEach((team: any) => {
        console.log(`Processing team ${team.id}, roster entries:`, team.roster?.entries?.length || 0)
        
        if (team.roster && team.roster.entries) {
          rosters[team.id] = team.roster.entries.map((entry: any) => {
            // Extract player data if available in the entry
            let player: ESPNPlayer | null = null
            
            if (entry.playerPoolEntry && entry.playerPoolEntry.player) {
              const espnPlayer = entry.playerPoolEntry.player
              player = {
                id: espnPlayer.id,
                fullName: espnPlayer.fullName,
                firstName: espnPlayer.firstName,
                lastName: espnPlayer.lastName,
                eligibleSlots: espnPlayer.eligibleSlots || [],
                defaultPositionId: espnPlayer.defaultPositionId,
                proTeamId: espnPlayer.proTeamId,
                injuryStatus: espnPlayer.injuryStatus,
                stats: espnPlayer.stats,
                starterStatusByProGame: espnPlayer.starterStatusByProGame,
              }
              console.log(`Found player data for ${player.fullName} (ID: ${player.id})`)
            } else {
              console.log(`No player data found for playerId ${entry.playerId}`)
            }
            
            return {
              playerId: entry.playerId,
              lineupSlotId: entry.lineupSlotId,
              acquisitionType: entry.acquisitionType,
              acquisitionDate: entry.acquisitionDate,
              player: player
            }
          })
        }
      })
    }
    
    console.log('Final rosters object keys:', Object.keys(rosters))
    Object.entries(rosters).forEach(([teamId, teamRoster]) => {
      const playersWithData = teamRoster.filter(entry => entry.player !== null).length
      console.log(`Team ${teamId}: ${teamRoster.length} total entries, ${playersWithData} with player data`)
    })
    
    return rosters
  }

  /**
   * Fetch a single page of free agents with an optional slot filter.
   * filterSlotIds: ESPN eligible slot IDs to filter by (e.g. [0,1,2,3,4,5,6,7,12] for hitters).
   */
  private static async fetchFreeAgentPage(
    leagueId: string,
    season: string,
    settings: ESPNLeagueSettings,
    limit: number,
    filterSlotIds?: number[],
  ): Promise<ESPNPlayer[]> {
    const url = `https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb/seasons/${season}/segments/0/leagues/${leagueId}?view=kona_player_info`

    const filterObj: Record<string, unknown> = {
      filterStatus: { value: ['FREEAGENT', 'WAIVERS'] },
      sortPercOwned: { sortPriority: 1, sortAsc: false },
      limit,
      offset: 0,
    }
    if (filterSlotIds && filterSlotIds.length > 0) {
      filterObj.filterSlotIds = { value: filterSlotIds }
    }

    const response = await fetch(url, {
      headers: {
        ...this.getHeaders(settings),
        'x-fantasy-filter': JSON.stringify({ players: filterObj }),
      },
    })

    if (!response.ok) {
      throw new Error(`ESPN API error: ${response.status} - ${response.statusText}`)
    }

    const data = await response.json()
    const players: ESPNPlayer[] = []

    if (data.players) {
      for (const entry of data.players) {
        const p = entry.player
        if (p) {
          players.push({
            id: p.id,
            fullName: p.fullName,
            firstName: p.firstName,
            lastName: p.lastName,
            eligibleSlots: p.eligibleSlots || [],
            defaultPositionId: p.defaultPositionId,
            stats: p.stats,
          })
        }
      }
    }

    return players
  }

  /**
   * Fetch free agents — hitters and pitchers separately to ensure both are represented.
   */
  static async getFreeAgents(
    leagueId: string,
    season: string,
    settings: ESPNLeagueSettings,
    hitterLimit: number = 200,
    pitcherLimit: number = 100,
  ): Promise<ESPNPlayer[]> {
    // ESPN eligible slot IDs:
    // Hitters: 0=C, 1=1B, 2=2B, 3=3B, 4=SS, 5=LF, 6=CF, 7=RF, 12=DH/UTIL
    // Pitchers: 13=P, 14=SP, 15=RP
    const HITTER_SLOTS = [0, 1, 2, 3, 4, 5, 6, 7, 12]
    const PITCHER_SLOTS = [13, 14, 15]

    const [hitters, pitchers] = await Promise.all([
      this.fetchFreeAgentPage(leagueId, season, settings, hitterLimit, HITTER_SLOTS),
      this.fetchFreeAgentPage(leagueId, season, settings, pitcherLimit, PITCHER_SLOTS),
    ])

    // Deduplicate (two-way players could appear in both)
    const seen = new Set<number>()
    const players: ESPNPlayer[] = []
    for (const p of [...hitters, ...pitchers]) {
      if (!seen.has(p.id)) {
        seen.add(p.id)
        players.push(p)
      }
    }

    console.log(`ESPN Free Agents: ${hitters.length} hitters + ${pitchers.length} pitchers = ${players.length} unique`)
    return players
  }

  static async getLeagueTeamsAndFaab(
    leagueId: string,
    season: string,
    settings: ESPNLeagueSettings,
  ): Promise<{ teams: ESPNTeam[]; faabByTeamId: Record<number, number> }> {
    const url = `https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb/seasons/${season}/segments/0/leagues/${leagueId}?view=mTeam&view=mSettings`

    const response = await fetch(url, {
      headers: this.getHeaders(settings),
    })

    if (!response.ok) {
      throw new Error(`ESPN API error: ${response.status} - ${response.statusText}`)
    }

    const data = await response.json()
    const teams: ESPNTeam[] = data.teams || []
    const faabByTeamId: Record<number, number> = {}

    // FAAB budget remaining is in each team's transactionCounter
    for (const team of data.teams || []) {
      const budget = team.transactionCounter?.acquisitionBudgetSpent
      const totalBudget = data.settings?.acquisitionSettings?.acquisitionBudget || 100
      faabByTeamId[team.id] = budget != null ? totalBudget - budget : totalBudget
    }

    return { teams, faabByTeamId }
  }

  static async testConnection(leagueId: string, season: string, settings: ESPNLeagueSettings): Promise<boolean> {
    try {
      await this.getLeague(leagueId, season, settings)
      return true
    } catch (error) {
      console.error('ESPN connection test failed:', error)
      return false
    }
  }

  static async getMatchupScoreboard(
    leagueId: string,
    season: string,
    settings: ESPNLeagueSettings,
    matchupPeriodId: number,
  ): Promise<{
    schedule: Array<{
      matchupPeriodId: number
      home: { teamId: number; cumulativeScore?: { scoreByStat?: Record<string, { score: number; result: string }> } }
      away: { teamId: number; cumulativeScore?: { scoreByStat?: Record<string, { score: number; result: string }> } }
    }>
  }> {
    const url = `https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb/seasons/${season}/segments/0/leagues/${leagueId}?view=mMatchupScore&view=mScoreboard`

    const response = await fetch(url, {
      headers: this.getHeaders(settings),
    })

    if (!response.ok) {
      throw new Error(`ESPN API error: ${response.status} - ${response.statusText}`)
    }

    const data = await response.json()
    const schedule = (data.schedule || []).filter(
      (m: any) => m.matchupPeriodId === matchupPeriodId
    )

    return { schedule }
  }

  /**
   * Fetch the complete season schedule — all matchup pairings for every
   * scoring period — without filtering to a single period. Used by the
   * playoff-odds simulator to build the remaining schedule.
   */
  static async getFullSchedule(
    leagueId: string,
    season: string,
    settings: ESPNLeagueSettings,
  ): Promise<Array<{
    matchupPeriodId: number
    home: { teamId: number }
    away: { teamId: number }
  }>> {
    const url = `https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb/seasons/${season}/segments/0/leagues/${leagueId}?view=mMatchupScore`

    const response = await fetch(url, { headers: this.getHeaders(settings) })
    if (!response.ok) {
      throw new Error(`ESPN API error: ${response.status} - ${response.statusText}`)
    }

    const data = await response.json()
    return (data.schedule || []).map((m: any) => ({
      matchupPeriodId: m.matchupPeriodId,
      home: { teamId: m.home.teamId },
      away: { teamId: m.away.teamId },
    }))
  }

  /**
   * Fetch all completed matchup periods' category totals per team. Used for
   * empirical Bayes shrinkage in the playoff odds simulator. Skips any matchup
   * that lacks `cumulativeScore.scoreByStat` (future or in-progress).
   */
  static async getMatchupHistory(
    leagueId: string,
    season: string,
    settings: ESPNLeagueSettings,
  ): Promise<Array<{
    team_id: number
    matchup_period_id: number
    period_days: number
    cats: Record<string, number>
  }>> {
    const url = `https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb/seasons/${season}/segments/0/leagues/${leagueId}?view=mMatchup&scoringPeriodId=7`

    const response = await fetch(url, { headers: this.getHeaders(settings) })
    if (!response.ok) {
      throw new Error(`ESPN API error: ${response.status} - ${response.statusText}`)
    }

    const data = await response.json()
    const ESPN_STAT_ID_TO_CAT: Record<string, string> = {
      '20': 'R', '8': 'TB', '21': 'RBI', '23': 'SB', '17': 'OBP',
      '48': 'K', '63': 'QS', '47': 'ERA', '41': 'WHIP', '83': 'SVHD',
    }

    const out: Array<{
      team_id: number
      matchup_period_id: number
      period_days: number
      cats: Record<string, number>
    }> = []

    for (const m of data.schedule || []) {
      const periodId = m.matchupPeriodId
      if (periodId == null) continue
      for (const sideKey of ['home', 'away'] as const) {
        const side = m[sideKey]
        if (!side) continue
        const scoreByStat = side.cumulativeScore?.scoreByStat
        if (!scoreByStat) continue
        const cats: Record<string, number> = {}
        for (const [statId, catName] of Object.entries(ESPN_STAT_ID_TO_CAT)) {
          const obj = scoreByStat[statId]
          if (obj && typeof obj.score === 'number') {
            cats[catName] = obj.score
          }
        }
        const periodDays = Object.keys(side.pointsByScoringPeriod || {}).length
        out.push({
          team_id: side.teamId,
          matchup_period_id: periodId,
          period_days: periodDays,
          cats,
        })
      }
    }
    return out
  }

  /**
   * Map ESPN game event IDs to dates using the public MLB scoreboard API.
   * This resolves the IDs found in starterStatusByProGame to actual dates.
   * No auth required — this is a public ESPN endpoint.
   */
  static async getGameIdToDateMap(
    startDate: string,
    endDate: string,
  ): Promise<Record<string, string>> {
    const gameIdToDate: Record<string, string> = {}
    const cursor = new Date(`${startDate}T12:00:00`)
    const end = new Date(`${endDate}T12:00:00`)

    // Fetch scoreboard for each date in the range (typically 5-7 days)
    const fetches: Promise<void>[] = []
    while (cursor <= end) {
      const isoDate = cursor.toISOString().split('T')[0]
      const espnDate = isoDate.replace(/-/g, '')
      const url = `https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard?dates=${espnDate}`

      fetches.push(
        fetch(url)
          .then((r) => r.json())
          .then((data) => {
            for (const event of data.events || []) {
              gameIdToDate[event.id] = isoDate
            }
          })
          .catch((e) => {
            console.warn(`Failed to fetch ESPN scoreboard for ${isoDate}:`, e)
          }),
      )
      cursor.setDate(cursor.getDate() + 1)
    }

    await Promise.all(fetches)
    return gameIdToDate
  }
}