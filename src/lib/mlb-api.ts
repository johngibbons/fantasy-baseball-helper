const MLB_API_BASE = 'https://statsapi.mlb.com/api/v1'

export interface MLBPlayer {
  id: number
  fullName: string
  firstName: string
  lastName: string
  primaryNumber?: string
  birthDate?: string
  currentAge?: number
  birthCity?: string
  birthStateProvince?: string
  birthCountry?: string
  height?: string
  weight?: number
  active: boolean
  primaryPosition?: {
    name: string
    abbreviation: string
  }
  useName?: string
  mlbDebutDate?: string
  batSide?: {
    code: string
    description: string
  }
  pitchHand?: {
    code: string
    description: string
  }
  nameSlug?: string
  strikeZoneTop?: number
  strikeZoneBottom?: number
}

export interface MLBPlayerStats {
  gamesPlayed?: number
  atBats?: number
  runs?: number
  hits?: number
  doubles?: number
  triples?: number
  homeRuns?: number
  rbi?: number
  stolenBases?: number
  caughtStealing?: number
  baseOnBalls?: number
  strikeOuts?: number
  avg?: string
  obp?: string
  slg?: string
  ops?: string
  totalBases?: number
  hitByPitch?: number
  intentionalWalks?: number
  groundIntoDoublePlay?: number
  leftOnBase?: number
  plateAppearances?: number
  babip?: string
}

export interface MLBSearchResponse {
  people: MLBPlayer[]
}

export interface MLBStatsResponse {
  stats: {
    splits: {
      season: string
      stat: MLBPlayerStats
    }[]
  }[]
}

export class MLBApi {
  static async searchPlayers(name: string): Promise<MLBPlayer[]> {
    const response = await fetch(`${MLB_API_BASE}/people/search?names=${encodeURIComponent(name)}`)
    if (!response.ok) {
      throw new Error(`MLB API error: ${response.status}`)
    }
    
    const data: MLBSearchResponse = await response.json()
    return data.people || []
  }

  static async getPlayerStats(playerId: number, season: string = '2024'): Promise<MLBPlayerStats | null> {
    const response = await fetch(`${MLB_API_BASE}/people/${playerId}/stats?stats=season&season=${season}`)
    if (!response.ok) {
      throw new Error(`MLB API error: ${response.status}`)
    }
    
    const data: MLBStatsResponse = await response.json()
    const seasonStats = data.stats?.[0]?.splits?.[0]
    
    return seasonStats ? seasonStats.stat : null
  }

  static async getPlayer(playerId: number): Promise<MLBPlayer | null> {
    const response = await fetch(`${MLB_API_BASE}/people/${playerId}`)
    if (!response.ok) {
      throw new Error(`MLB API error: ${response.status}`)
    }
    
    const data: { people: MLBPlayer[] } = await response.json()
    return data.people?.[0] || null
  }
}