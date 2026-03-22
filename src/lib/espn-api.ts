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
  stats?: any[]
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
                stats: espnPlayer.stats
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
}