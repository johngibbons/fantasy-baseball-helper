/**
 * @jest-environment node
 */
import { NextRequest } from 'next/server'
import { POST } from '../../app/api/leagues/[leagueId]/sync/route'
import { prisma } from '../../lib/prisma'
import { ESPNApi } from '../../lib/espn-api'

// Mock dependencies
jest.mock('../../lib/prisma', () => ({
  prisma: {
    league: {
      findUnique: jest.fn(),
      update: jest.fn()
    },
    team: {
      findMany: jest.fn()
    },
    rosterSlot: {
      deleteMany: jest.fn(),
      create: jest.fn()
    },
    player: {
      upsert: jest.fn()
    },
    playerStats: {
      upsert: jest.fn()
    }
  }
}))

jest.mock('../../lib/espn-api')

const mockPrisma = prisma as any
const mockESPNApi = ESPNApi as jest.Mocked<typeof ESPNApi>

describe('ESPN Stats Mapping in Sync Process', () => {
  beforeEach(() => {
    jest.clearAllMocks()
  })

  const mockLeague = {
    id: 'league-1',
    externalId: '123456',
    season: '2024',
    platform: 'ESPN',
    name: 'Test League'
  }

  const mockTeams = [
    { id: 'team-1', externalId: '1', name: 'Team 1' }
  ]

  it('should correctly map ESPN stats format to database format', async () => {
    const mockRosterWithESPNStats = {
      1: [{
        playerId: 12345,
        lineupSlotId: 0,
        acquisitionType: 'DRAFT',
        acquisitionDate: 1234567890,
        player: {
          id: 12345,
          fullName: 'Mike Trout',
          firstName: 'Mike',
          lastName: 'Trout',
          eligibleSlots: [0, 5],
          defaultPositionId: 5,
          stats: [{
            id: '002024',
            seasonId: 2024,
            stats: {
              // ESPN uses numeric keys for stats - based on REAL data analysis
              0: 450,    // at bats
              1: 140,    // hits  
              2: 0.311,  // batting average
              3: 28,     // doubles (corrected mapping)
              4: 3,      // triples (corrected mapping)
              5: 35,     // home runs (corrected mapping)
              8: 65,     // base on balls (walks)
              9: 0.395,  // on base percentage
              10: 110,   // strikeouts
              18: 0.585, // slugging percentage
              20: 85,    // runs (corrected mapping)
              21: 95,    // RBI (corrected mapping)
              23: 20     // stolen bases (corrected mapping)
            }
          }]
        }
      }]
    }

    // Setup mocks
    mockPrisma.league.findUnique.mockResolvedValue(mockLeague as any)
    mockPrisma.team.findMany.mockResolvedValue(mockTeams as any)
    mockESPNApi.getRosters.mockResolvedValue(mockRosterWithESPNStats)
    mockPrisma.rosterSlot.deleteMany.mockResolvedValue({ count: 0 })
    mockPrisma.player.upsert.mockResolvedValue({} as any)
    mockPrisma.playerStats.upsert.mockResolvedValue({} as any)
    mockPrisma.rosterSlot.create.mockResolvedValue({} as any)
    mockPrisma.league.update.mockResolvedValue(mockLeague as any)

    const request = new NextRequest('http://localhost/api/leagues/league-1/sync', {
      method: 'POST',
      body: JSON.stringify({
        swid: 'test_swid',
        espn_s2: 'test_espn_s2'
      })
    })

    const response = await POST(request, { 
      params: Promise.resolve({ leagueId: 'league-1' }) 
    })

    expect(response.status).toBe(200)

    // Verify player stats were upserted with correctly mapped values
    expect(mockPrisma.playerStats.upsert).toHaveBeenCalledWith({
      where: {
        playerId_season: {
          playerId: 12345,
          season: '2024'
        }
      },
      update: expect.objectContaining({
        atBats: 450,
        homeRuns: 35,
        rbi: 95,
        runs: 85,
        hits: 140,
        battingAverage: 0.311,
        stolenBases: 20,
        doubles: 28,
        triples: 3,
        onBasePercentage: 0.395,
        sluggingPercentage: 0.585,
        baseOnBalls: 65,
        strikeOuts: 110
      }),
      create: expect.objectContaining({
        playerId: 12345,
        season: '2024',
        atBats: 450,
        homeRuns: 35,
        rbi: 95,
        runs: 85,
        hits: 140,
        battingAverage: 0.311,
        stolenBases: 20,
        doubles: 28,
        triples: 3,
        onBasePercentage: 0.395,
        sluggingPercentage: 0.585,
        baseOnBalls: 65,
        strikeOuts: 110
      })
    })
  })

  it('should handle missing or null stat values gracefully', async () => {
    const mockRosterWithPartialStats = {
      1: [{
        playerId: 12345,
        lineupSlotId: 0,
        acquisitionType: 'DRAFT',
        acquisitionDate: 1234567890,
        player: {
          id: 12345,
          fullName: 'Rookie Player',
          firstName: 'Rookie',
          lastName: 'Player',
          eligibleSlots: [0],
          defaultPositionId: 0,
          stats: [{
            id: '002024',
            seasonId: 2024,
            stats: {
              // Only some stats available - using new correct mapping
              0: 50,    // at bats
              1: 15,    // hits
              5: 2,     // home runs (corrected key)
              21: 8,    // RBI (corrected key)
              // Missing other stats
            }
          }]
        }
      }]
    }

    mockPrisma.league.findUnique.mockResolvedValue(mockLeague as any)
    mockPrisma.team.findMany.mockResolvedValue(mockTeams as any)
    mockESPNApi.getRosters.mockResolvedValue(mockRosterWithPartialStats)
    mockPrisma.rosterSlot.deleteMany.mockResolvedValue({ count: 0 })
    mockPrisma.player.upsert.mockResolvedValue({} as any)
    mockPrisma.playerStats.upsert.mockResolvedValue({} as any)
    mockPrisma.rosterSlot.create.mockResolvedValue({} as any)
    mockPrisma.league.update.mockResolvedValue(mockLeague as any)

    const request = new NextRequest('http://localhost/api/leagues/league-1/sync', {
      method: 'POST',
      body: JSON.stringify({
        swid: 'test_swid',
        espn_s2: 'test_espn_s2'
      })
    })

    const response = await POST(request, { 
      params: Promise.resolve({ leagueId: 'league-1' }) 
    })

    expect(response.status).toBe(200)

    // Verify missing stats default to 0
    expect(mockPrisma.playerStats.upsert).toHaveBeenCalledWith({
      where: {
        playerId_season: {
          playerId: 12345,
          season: '2024'
        }
      },
      update: expect.objectContaining({
        homeRuns: 2,
        rbi: 8,
        atBats: 50,        // Should use provided value
        runs: 0,           // Should default to 0
        hits: 15,          // Should use provided value
        battingAverage: 0, // Should default to 0
        stolenBases: 0     // Should default to 0
      }),
      create: expect.objectContaining({
        playerId: 12345,
        season: '2024',
        homeRuns: 2,
        rbi: 8,
        atBats: 50,
        runs: 0,
        hits: 15,
        battingAverage: 0,
        stolenBases: 0
      })
    })
  })
})