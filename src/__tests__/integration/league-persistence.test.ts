import { prisma } from '../../lib/prisma'
import { GET } from '../../app/api/leagues/route'

// Mock Next.js
jest.mock('next/server', () => ({
  NextResponse: {
    json: jest.fn((data, options) => ({
      json: async () => data,
      status: options?.status || 200,
    })),
  },
}))

// Add missing Node.js polyfills
global.setImmediate = global.setImmediate || ((fn, ...args) => setTimeout(fn, 0, ...args))

// Mock the ESPN API
jest.mock('../../lib/espn-api', () => ({
  ESPNApi: {
    testConnection: jest.fn(),
    getLeague: jest.fn(),
    getTeams: jest.fn(),
    getRosters: jest.fn(),
  },
}))

import { ESPNApi } from '../../lib/espn-api'

const mockESPNApi = ESPNApi as jest.Mocked<typeof ESPNApi>

describe('League Persistence Integration', () => {
  beforeEach(async () => {
    // Clean up database before each test
    await prisma.rosterSlot.deleteMany()
    await prisma.team.deleteMany()
    await prisma.league.deleteMany()
    
    jest.clearAllMocks()
  })

  afterAll(async () => {
    // Clean up database after all tests
    await prisma.rosterSlot.deleteMany()
    await prisma.team.deleteMany()
    await prisma.league.deleteMany()
    await prisma.$disconnect()
  })

  it('should create and retrieve league data from database', async () => {
    // Create league data directly in database
    const league = await prisma.league.create({
      data: {
        id: 'espn_123456_2025',
        platform: 'ESPN',
        externalId: '123456',
        season: '2025',
        name: 'Test League',
        teamCount: 10,
        isActive: true,
        lastSyncAt: new Date(),
      },
    })

    // Create teams
    await prisma.team.createMany({
      data: [
        {
          leagueId: league.id,
          externalId: '1',
          name: 'Test Team',
          ownerName: 'Owner One',
          wins: 5,
          losses: 3,
          pointsFor: 85.5,
          pointsAgainst: 75.2,
        },
        {
          leagueId: league.id,
          externalId: '2',
          name: 'Another Squad',
          ownerName: 'Owner Two',
          wins: 3,
          losses: 5,
          pointsFor: 70.1,
          pointsAgainst: 80.3,
        },
      ],
    })

    // Test that we can retrieve the league via the GET API
    const getResponse = await GET()
    const getData = await getResponse.json()

    expect(getResponse.status).toBe(200)
    expect(getData).toHaveLength(1)
    expect(getData[0].id).toBe(league.id)
    expect(getData[0].name).toBe('Test League')
    expect(getData[0].platform).toBe('ESPN')
    expect(getData[0].season).toBe('2025')
    expect(getData[0].teamCount).toBe(10)
    expect(getData[0].isActive).toBe(true)
  })

  it('should handle updating existing league data', async () => {
    // Create initial league
    const league = await prisma.league.create({
      data: {
        id: 'espn_123456_2025',
        platform: 'ESPN',
        externalId: '123456',
        season: '2025',
        name: 'Original League Name',
        teamCount: 8,
        isActive: true,
        lastSyncAt: new Date('2025-01-01'),
      },
    })

    // Update the league
    await prisma.league.update({
      where: { id: league.id },
      data: {
        name: 'Updated League Name',
        teamCount: 10,
        lastSyncAt: new Date('2025-01-02'),
      },
    })

    // Verify only one league exists in database
    const leagues = await prisma.league.findMany()
    expect(leagues).toHaveLength(1)
    expect(leagues[0].name).toBe('Updated League Name')
    expect(leagues[0].teamCount).toBe(10)

    // Verify GET API returns updated data
    const getResponse = await GET()
    const getData = await getResponse.json()

    expect(getData).toHaveLength(1)
    expect(getData[0].name).toBe('Updated League Name')
    expect(getData[0].teamCount).toBe(10)
  })

  it('should handle multiple leagues from different seasons', async () => {
    // Create 2025 league
    await prisma.league.create({
      data: {
        id: 'espn_123456_2025',
        platform: 'ESPN',
        externalId: '123456',
        season: '2025',
        name: '2025 League',
        teamCount: 10,
        isActive: true,
        lastSyncAt: new Date('2025-01-02'),
      },
    })

    // Create 2024 league
    await prisma.league.create({
      data: {
        id: 'espn_123456_2024',
        platform: 'ESPN',
        externalId: '123456',
        season: '2024',
        name: '2024 League',
        teamCount: 12,
        isActive: true,
        lastSyncAt: new Date('2025-01-01'),
      },
    })

    // Verify both leagues exist
    const leagues = await prisma.league.findMany()
    expect(leagues).toHaveLength(2)

    // Verify GET API returns both leagues (2025 first due to ordering)
    const getResponse = await GET()
    const getData = await getResponse.json()

    expect(getData).toHaveLength(2)
    expect(getData[0].name).toBe('2025 League')
    expect(getData[0].season).toBe('2025')
    expect(getData[1].name).toBe('2024 League')
    expect(getData[1].season).toBe('2024')
  })

  it('should only return active leagues via GET API', async () => {
    // Create inactive league directly in database
    await prisma.league.create({
      data: {
        id: 'inactive_league',
        platform: 'ESPN',
        externalId: '999999',
        season: '2024',
        name: 'Inactive League',
        teamCount: 10,
        isActive: false,
        lastSyncAt: new Date('2024-01-01'),
      },
    })

    // Create active league
    await prisma.league.create({
      data: {
        id: 'espn_123456_2025',
        platform: 'ESPN',
        externalId: '123456',
        season: '2025',
        name: 'Active League',
        teamCount: 10,
        isActive: true,
        lastSyncAt: new Date('2025-01-01'),
      },
    })

    // Verify GET API only returns active league
    const getResponse = await GET()
    const getData = await getResponse.json()

    expect(getData).toHaveLength(1)
    expect(getData[0].name).toBe('Active League')
  })
})