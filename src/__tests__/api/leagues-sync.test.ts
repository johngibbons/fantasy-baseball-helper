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

describe('/api/leagues/[leagueId]/sync', () => {
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
    { id: 'team-1', externalId: '1', name: 'Team 1' },
    { id: 'team-2', externalId: '2', name: 'Team 2' }
  ]

  const mockRosterData = {
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
          stats: {
            homeRuns: 25,
            rbi: 80,
            battingAverage: 0.285
          }
        }]
      }
    }]
  }

  it('should sync roster data successfully', async () => {
    // Setup mocks
    mockPrisma.league.findUnique.mockResolvedValue(mockLeague as any)
    mockPrisma.team.findMany.mockResolvedValue(mockTeams as any)
    mockESPNApi.getRosters.mockResolvedValue(mockRosterData)
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

    const data = await response.json()

    expect(response.status).toBe(200)
    expect(data.success).toBe(true)
    expect(data.playersProcessed).toBe(1)
    expect(data.rostersProcessed).toBe(1)

    // Verify ESPN API was called correctly
    expect(mockESPNApi.getRosters).toHaveBeenCalledWith(
      '123456',
      '2024',
      { swid: 'test_swid', espn_s2: 'test_espn_s2' }
    )

    // Verify player was created
    expect(mockPrisma.player.upsert).toHaveBeenCalledWith({
      where: { id: 12345 },
      update: {
        fullName: 'Mike Trout',
        firstName: 'Mike',
        lastName: 'Trout',
        primaryPosition: 'OF',
        active: true
      },
      create: {
        id: 12345,
        fullName: 'Mike Trout',
        firstName: 'Mike',
        lastName: 'Trout',
        primaryPosition: 'OF',
        active: true
      }
    })

    // Verify roster slot was created
    expect(mockPrisma.rosterSlot.create).toHaveBeenCalledWith({
      data: {
        teamId: 'team-1',
        playerId: 12345,
        season: '2024',
        position: 'C',
        acquisitionType: 'DRAFT',
        acquisitionDate: new Date(1234567890)
      }
    })
  })

  it('should return 404 for non-existent league', async () => {
    mockPrisma.league.findUnique.mockResolvedValue(null)

    const request = new NextRequest('http://localhost/api/leagues/invalid/sync', {
      method: 'POST',
      body: JSON.stringify({
        swid: 'test_swid',
        espn_s2: 'test_espn_s2'
      })
    })

    const response = await POST(request, {
      params: Promise.resolve({ leagueId: 'invalid' })
    })

    expect(response.status).toBe(404)
    const data = await response.json()
    expect(data.error).toBe('League not found')
  })

  it('should return 400 for non-ESPN leagues', async () => {
    const nonESPNLeague = { ...mockLeague, platform: 'YAHOO' }
    mockPrisma.league.findUnique.mockResolvedValue(nonESPNLeague as any)

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

    expect(response.status).toBe(400)
    const data = await response.json()
    expect(data.error).toBe('Only ESPN leagues are supported for sync')
  })

  it('should return 400 for missing credentials', async () => {
    mockPrisma.league.findUnique.mockResolvedValue(mockLeague as any)

    const request = new NextRequest('http://localhost/api/leagues/league-1/sync', {
      method: 'POST',
      body: JSON.stringify({
        swid: 'test_swid'
        // Missing espn_s2
      })
    })

    const response = await POST(request, {
      params: Promise.resolve({ leagueId: 'league-1' })
    })

    expect(response.status).toBe(400)
    const data = await response.json()
    expect(data.error).toBe('ESPN credentials (swid and espn_s2) are required for sync')
  })

  it('should skip roster entries without player data', async () => {
    const rosterWithMissingPlayer = {
      1: [{
        playerId: 12345,
        lineupSlotId: 0,
        acquisitionType: 'DRAFT',
        acquisitionDate: 1234567890,
        player: null // No player data
      }]
    }

    mockPrisma.league.findUnique.mockResolvedValue(mockLeague as any)
    mockPrisma.team.findMany.mockResolvedValue(mockTeams as any)
    mockESPNApi.getRosters.mockResolvedValue(rosterWithMissingPlayer)
    mockPrisma.rosterSlot.deleteMany.mockResolvedValue({ count: 0 })
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

    const data = await response.json()

    expect(response.status).toBe(200)
    expect(data.success).toBe(true)
    expect(data.playersProcessed).toBe(0) // No players processed due to missing data
    expect(data.rostersProcessed).toBe(1) // But roster was still processed

    // Verify player upsert was not called
    expect(mockPrisma.player.upsert).not.toHaveBeenCalled()
  })

  it('should handle ESPN API errors', async () => {
    mockPrisma.league.findUnique.mockResolvedValue(mockLeague as any)
    mockPrisma.team.findMany.mockResolvedValue(mockTeams as any)
    mockESPNApi.getRosters.mockRejectedValue(new Error('ESPN API error: 401 - Unauthorized'))

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

    expect(response.status).toBe(500)
    const data = await response.json()
    expect(data.error).toBe('ESPN API error: 401 - Unauthorized')
  })
})