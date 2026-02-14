// MLB Stats API integration for comprehensive baseball statistics
// Official MLB API provides reliable saves, holds, quality starts, and advanced metrics

interface MLBPlayer {
  id: number
  fullName: string
  firstName: string
  lastName: string
  primaryPosition: {
    code: string
    name: string
    type: string
    abbreviation: string
  }
}

interface MLBPitchingStats {
  saves?: number
  holds?: number
  qualityStarts?: number
  wins?: number
  losses?: number
  era?: number
  whip?: number
  strikeOuts?: number
  inningsPitched?: string
  games?: number
  gamesStarted?: number
}

interface MLBBattingStats {
  runs?: number
  hits?: number
  doubles?: number
  triples?: number
  homeRuns?: number
  rbi?: number
  stolenBases?: number
  baseOnBalls?: number
  strikeOuts?: number
  battingAverage?: number
  onBasePercentage?: number
  sluggingPercentage?: number
  totalBases?: number
  atBats?: number
}

export class MLBStatsApi {
  private static baseUrl = 'http://statsapi.mlb.com/api/v1'
  
  /**
   * Get team roster for a specific season
   */
  static async getTeamRoster(teamId: number, season: number = 2024): Promise<MLBPlayer[]> {
    try {
      const response = await fetch(`${this.baseUrl}/teams/${teamId}/roster?season=${season}`)
      const data = await response.json()
      
      return data.roster?.map((p: any) => ({
        id: p.person.id,
        fullName: p.person.fullName,
        firstName: p.person.firstName,
        lastName: p.person.lastName,
        primaryPosition: p.position
      })) || []
    } catch (error) {
      console.error(`Error fetching roster for team ${teamId}:`, error)
      return []
    }
  }
  
  /**
   * Get player pitching stats for a specific season
   */
  static async getPlayerPitchingStats(playerId: number, season: number = 2024): Promise<MLBPitchingStats | null> {
    try {
      const response = await fetch(`${this.baseUrl}/people/${playerId}/stats?stats=season&season=${season}&group=pitching`)
      const data = await response.json()
      
      // Debug: log full response for problematic players
      if (playerId === 643511) { // Tyler Rogers
        console.log(`DEBUG Tyler Rogers pitching data:`, JSON.stringify(data, null, 2))
      }
      
      const stats = data.stats?.[0]?.splits?.[0]?.stat
      if (!stats) {
        console.log(`No pitching stats found for player ${playerId} in ${season}`)
        return null
      }
      
      return {
        saves: stats.saves || 0,
        holds: stats.holds || 0,
        qualityStarts: stats.qualityStarts || 0,
        wins: stats.wins || 0,
        losses: stats.losses || 0,
        era: stats.era ? parseFloat(stats.era) : 0,
        whip: stats.whip ? parseFloat(stats.whip) : 0,
        strikeOuts: stats.strikeOuts || 0,
        inningsPitched: stats.inningsPitched || '0.0',
        games: stats.gamesPitched || stats.games || 0,  // Use gamesPitched if games is not available
        gamesStarted: stats.gamesStarted || 0
      }
    } catch (error) {
      console.error(`Error fetching pitching stats for player ${playerId}:`, error)
      return null
    }
  }
  
  /**
   * Get player batting stats for a specific season
   */
  static async getPlayerBattingStats(playerId: number, season: number = 2024): Promise<MLBBattingStats | null> {
    try {
      const response = await fetch(`${this.baseUrl}/people/${playerId}/stats?stats=season&season=${season}&group=hitting`)
      const data = await response.json()
      
      const stats = data.stats?.[0]?.splits?.[0]?.stat
      if (!stats) return null
      
      return {
        runs: stats.runs || 0,
        hits: stats.hits || 0,
        doubles: stats.doubles || 0,
        triples: stats.triples || 0,
        homeRuns: stats.homeRuns || 0,
        rbi: stats.rbi || 0,
        stolenBases: stats.stolenBases || 0,
        baseOnBalls: stats.baseOnBalls || 0,
        strikeOuts: stats.strikeOuts || 0,
        battingAverage: stats.avg ? parseFloat(stats.avg) : 0,
        onBasePercentage: stats.obp ? parseFloat(stats.obp) : 0,
        sluggingPercentage: stats.slg ? parseFloat(stats.slg) : 0,
        totalBases: stats.totalBases || 0,
        atBats: stats.atBats || 0
      }
    } catch (error) {
      console.error(`Error fetching batting stats for player ${playerId}:`, error)
      return null
    }
  }
  
  /**
   * Search for a player by name using MLB search API (more efficient)
   */
  static async findPlayerByName(playerName: string, season: number = 2024): Promise<MLBPlayer | null> {
    try {
      // Use MLB search API for more efficient player lookup
      const searchUrl = `${this.baseUrl}/sports/1/players?season=${season}&activeStatus=Y`
      const response = await fetch(searchUrl)
      const data = await response.json()
      
      const players = data.people || []
      
      // Search for exact or partial name match
      const player = players.find((p: any) => {
        const fullName = p.fullName?.toLowerCase() || ''
        const firstName = p.firstName?.toLowerCase() || ''
        const lastName = p.lastName?.toLowerCase() || ''
        const searchName = playerName.toLowerCase()
        
        return fullName.includes(searchName) || 
               lastName.includes(searchName) ||
               fullName === searchName
      })
      
      if (player) {
        return {
          id: player.id,
          fullName: player.fullName,
          firstName: player.firstName,
          lastName: player.lastName,
          primaryPosition: player.primaryPosition
        }
      }
      
      return null
    } catch (error) {
      console.error(`Error searching for player ${playerName}:`, error)
      return null
    }
  }
  
  /**
   * Search for player by partial name match (more flexible)
   */
  static async searchPlayers(searchTerm: string, season: number = 2024): Promise<MLBPlayer[]> {
    try {
      const searchUrl = `${this.baseUrl}/sports/1/players?season=${season}&activeStatus=Y`
      const response = await fetch(searchUrl)
      const data = await response.json()
      
      const players = data.people || []
      const searchLower = searchTerm.toLowerCase()
      
      return players
        .filter((p: any) => {
          const fullName = p.fullName?.toLowerCase() || ''
          const lastName = p.lastName?.toLowerCase() || ''
          return fullName.includes(searchLower) || lastName.includes(searchLower)
        })
        .slice(0, 10) // Limit to top 10 matches
        .map((p: any) => ({
          id: p.id,
          fullName: p.fullName,
          firstName: p.firstName,
          lastName: p.lastName,
          primaryPosition: p.primaryPosition
        }))
    } catch (error) {
      console.error(`Error searching players with term ${searchTerm}:`, error)
      return []
    }
  }
  
  /**
   * Calculate SVHD (Saves + Holds) for a pitcher
   */
  static async calculateSVHD(playerId: number, season: number = 2024): Promise<number> {
    const stats = await this.getPlayerPitchingStats(playerId, season)
    if (!stats) return 0
    
    return (stats.saves || 0) + (stats.holds || 0)
  }
}