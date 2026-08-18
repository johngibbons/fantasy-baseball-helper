/**
 * @jest-environment node
 *
 * Stats no longer come from the numeric keys embedded in ESPN's roster
 * payload. Commit 76845c1 moved the sync to a hybrid approach: ESPN supplies
 * the roster, the MLB Stats API supplies the statistics, because ESPN's
 * numbers were unreliable for saves, holds and quality starts. These tests
 * were asserting the replaced mapping, so they now cover what the route
 * actually persists.
 */
import { NextRequest } from 'next/server'
import { POST } from '../../app/api/leagues/[leagueId]/sync/route'
import { prisma } from '../../lib/prisma'
import { ESPNApi } from '../../lib/espn-api'
import { MLBStatsApi } from '../../lib/mlb-stats-api'

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

jest.mock('../../lib/mlb-stats-api', () => ({
  MLBStatsApi: {
    findPlayerByName: jest.fn(),
    getPlayerPitchingStats: jest.fn(),
    getPlayerBattingStats: jest.fn(),
  },
}))

const mockPrisma = prisma as any
const mockESPNApi = ESPNApi as jest.Mocked<typeof ESPNApi>
const mockMLB = MLBStatsApi as jest.Mocked<typeof MLBStatsApi>

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

  it('should persist batting stats sourced from the MLB Stats API', async () => {
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

    // The route looks the player up in the MLB Stats API and takes the
    // statistics from there; the numbers embedded in the ESPN payload above
    // are ignored.
    mockMLB.findPlayerByName.mockResolvedValue({
      id: 545361, fullName: 'Mike Trout',
    } as any)
    mockMLB.getPlayerPitchingStats.mockResolvedValue(null as any)
    mockMLB.getPlayerBattingStats.mockResolvedValue({
      atBats: 450, runs: 85, hits: 140, doubles: 28, triples: 3,
      homeRuns: 35, rbi: 95, stolenBases: 20, baseOnBalls: 65,
      strikeOuts: 110, battingAverage: 0.311, onBasePercentage: 0.395,
      sluggingPercentage: 0.585, totalBases: 274,
    } as any)

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

  it('should store zeroes when the player is not found in the MLB Stats API', async () => {
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

    // Nobody by this name in the MLB Stats API, so no statistics are found.
    mockMLB.findPlayerByName.mockResolvedValue(null as any)
    mockMLB.getPlayerPitchingStats.mockResolvedValue(null as any)
    mockMLB.getPlayerBattingStats.mockResolvedValue(null as any)

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

    // With no MLB match, every statistic is stored as zero rather than
    // falling back to the numbers ESPN embedded in the roster payload.
    const zeroed = {
      atBats: 0, runs: 0, hits: 0, doubles: 0, triples: 0, homeRuns: 0,
      rbi: 0, stolenBases: 0, baseOnBalls: 0, strikeOuts: 0,
      battingAverage: 0, onBasePercentage: 0, sluggingPercentage: 0,
    }
    expect(mockPrisma.playerStats.upsert).toHaveBeenCalledWith({
      where: {
        playerId_season: {
          playerId: 12345,
          season: '2024'
        }
      },
      update: expect.objectContaining(zeroed),
      create: expect.objectContaining({
        playerId: 12345,
        season: '2024',
        ...zeroed,
      })
    })
  })
})