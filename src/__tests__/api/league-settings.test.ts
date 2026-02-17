import { GET } from '../../app/api/leagues/[leagueId]/settings/route'

// Mock Next.js
jest.mock('next/server', () => ({
  NextResponse: {
    json: jest.fn((data, options) => ({
      json: async () => data,
      status: options?.status || 200,
    })),
  },
}))

// Mock Prisma
jest.mock('../../lib/prisma', () => ({
  prisma: {
    league: {
      findUnique: jest.fn(),
    },
  },
}))

import { prisma } from '../../lib/prisma'

const mockPrisma = prisma as any

describe('/api/leagues/[leagueId]/settings', () => {
  beforeEach(() => {
    jest.clearAllMocks()
  })

  describe('GET', () => {
    it('should return league settings including scoring configuration', async () => {
      const mockLeague = {
        id: 'espn_123456_2025',
        name: 'Test League',
        platform: 'ESPN',
        season: '2025',
        settings: {
          currentMatchupPeriod: 1,
          finalScoringPeriod: 23,
          isActive: true,
          latestScoringPeriod: 1,
          scoringSettings: {
            battingCategories: [
              { statId: 0, name: 'Batting Average', abbrev: 'AVG' },
              { statId: 1, name: 'Home Runs', abbrev: 'HR' },
              { statId: 2, name: 'RBI', abbrev: 'RBI' },
              { statId: 3, name: 'Runs', abbrev: 'R' },
              { statId: 4, name: 'Stolen Bases', abbrev: 'SB' }
            ],
            pitchingCategories: [
              { statId: 20, name: 'ERA', abbrev: 'ERA' },
              { statId: 21, name: 'WHIP', abbrev: 'WHIP' },
              { statId: 22, name: 'Wins', abbrev: 'W' },
              { statId: 23, name: 'Saves', abbrev: 'SV' },
              { statId: 24, name: 'Strikeouts', abbrev: 'K' }
            ]
          },
          rosterSettings: {
            lineupSlots: [
              { slotId: 0, count: 1, name: 'C' },
              { slotId: 1, count: 1, name: '1B' },
              { slotId: 2, count: 1, name: '2B' },
              { slotId: 3, count: 1, name: '3B' },
              { slotId: 4, count: 1, name: 'SS' },
              { slotId: 5, count: 3, name: 'OF' },
              { slotId: 8, count: 1, name: 'UTIL' },
              { slotId: 9, count: 2, name: 'SP' },
              { slotId: 11, count: 2, name: 'RP' },
              { slotId: 20, count: 5, name: 'BENCH' }
            ]
          }
        }
      }

      mockPrisma.league.findUnique.mockResolvedValue(mockLeague)

      const params = Promise.resolve({ leagueId: 'espn_123456_2025' })
      const response = await GET({} as any, { params })
      const data = await response.json()

      expect(response.status).toBe(200)
      expect(data.league.id).toBe('espn_123456_2025')
      expect(data.league.name).toBe('Test League')
      
      // Check scoring settings
      expect(data.scoringSettings.battingCategories).toHaveLength(5)
      expect(data.scoringSettings.battingCategories[0].name).toBe('Batting Average')
      expect(data.scoringSettings.pitchingCategories).toHaveLength(5)
      expect(data.scoringSettings.pitchingCategories[0].name).toBe('ERA')
      
      // Check roster settings
      expect(data.rosterSettings.lineupSlots).toHaveLength(10)
      expect(data.rosterSettings.lineupSlots[0].name).toBe('C')
      
      // Check general settings
      expect(data.generalSettings.currentMatchupPeriod).toBe(1)
      expect(data.generalSettings.isActive).toBe(true)
    })

    it('should return null scoring settings when not available', async () => {
      const mockLeague = {
        id: 'espn_123456_2025',
        name: 'Test League',
        platform: 'ESPN',
        season: '2025',
        settings: {
          currentMatchupPeriod: 1,
          finalScoringPeriod: 23,
          isActive: true,
          latestScoringPeriod: 1
          // No scoring/roster settings
        }
      }

      mockPrisma.league.findUnique.mockResolvedValue(mockLeague)

      const params = Promise.resolve({ leagueId: 'espn_123456_2025' })
      const response = await GET({} as any, { params })
      const data = await response.json()

      expect(response.status).toBe(200)
      expect(data.scoringSettings).toBeNull()
      expect(data.rosterSettings).toBeNull()
      expect(data.acquisitionSettings).toBeNull()
      expect(data.generalSettings.currentMatchupPeriod).toBe(1)
    })

    it('should return 404 when league not found', async () => {
      mockPrisma.league.findUnique.mockResolvedValue(null)

      const params = Promise.resolve({ leagueId: 'nonexistent' })
      const response = await GET({} as any, { params })
      const data = await response.json()

      expect(response.status).toBe(404)
      expect(data.error).toBe('League not found')
    })

    it('should handle database errors gracefully', async () => {
      mockPrisma.league.findUnique.mockRejectedValue(new Error('Database error'))

      const params = Promise.resolve({ leagueId: 'espn_123456_2025' })
      const response = await GET({} as any, { params })
      const data = await response.json()

      expect(response.status).toBe(500)
      expect(data.error).toBe('Failed to fetch league settings')
    })

    it('should handle leagues with null settings', async () => {
      const mockLeague = {
        id: 'espn_123456_2025',
        name: 'Test League',
        platform: 'ESPN',
        season: '2025',
        settings: null
      }

      mockPrisma.league.findUnique.mockResolvedValue(mockLeague)

      const params = Promise.resolve({ leagueId: 'espn_123456_2025' })
      const response = await GET({} as any, { params })
      const data = await response.json()

      expect(response.status).toBe(200)
      expect(data.scoringSettings).toBeNull()
      expect(data.generalSettings.currentMatchupPeriod).toBe(0)
      expect(data.generalSettings.isActive).toBe(true)
    })
  })
})