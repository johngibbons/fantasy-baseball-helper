interface ESPNLeagueSettings {
  swid: string
  espn_s2: string
}

export interface ESPNLeague {
  id: string
  settings: {
    name: string
    size: number
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
    const url = `https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb/seasons/${season}/segments/0/leagues/${leagueId}`
    
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
    const url = `https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb/seasons/${season}/segments/0/leagues/${leagueId}?view=mRoster`
    
    const response = await fetch(url, {
      headers: this.getHeaders(settings)
    })

    if (!response.ok) {
      throw new Error(`ESPN API error: ${response.status} - ${response.statusText}`)
    }

    const data = await response.json()
    const rosters: { [teamId: number]: ESPNRosterEntry[] } = {}
    
    if (data.teams) {
      data.teams.forEach((team: any) => {
        if (team.roster && team.roster.entries) {
          rosters[team.id] = team.roster.entries.map((entry: any) => ({
            playerId: entry.playerId,
            lineupSlotId: entry.lineupSlotId,
            acquisitionType: entry.acquisitionType,
            acquisitionDate: entry.acquisitionDate
          }))
        }
      })
    }
    
    return rosters
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