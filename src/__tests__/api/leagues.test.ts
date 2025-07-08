import { GET } from '../../app/api/leagues/route'

// Mock Prisma
jest.mock('../../lib/prisma', () => ({
  prisma: {
    league: {
      findMany: jest.fn(),
    },
  },
}))

// Mock Next.js Request
jest.mock('next/server', () => ({
  NextResponse: {
    json: jest.fn((data, options) => ({
      json: async () => data,
      status: options?.status || 200,
    })),
  },
}))

import { prisma } from '../../lib/prisma'

const mockPrisma = prisma as jest.Mocked<typeof prisma>

describe('/api/leagues', () => {
  beforeEach(() => {
    jest.clearAllMocks()
  })

  describe('GET', () => {
    it('should return all active leagues', async () => {
      const mockLeagues = [
        {
          id: 'espn_123456_2025',
          name: 'Test League',
          platform: 'ESPN',
          season: '2025',
          teamCount: 10,
          isActive: true,
          lastSyncAt: new Date('2025-01-01'),
        },
        {
          id: 'espn_789012_2025',
          name: 'Another League',
          platform: 'ESPN',
          season: '2025',
          teamCount: 12,
          isActive: true,
          lastSyncAt: new Date('2025-01-02'),
        },
      ]

      mockPrisma.league.findMany.mockResolvedValue(mockLeagues)

      const response = await GET()
      const data = await response.json()

      expect(response.status).toBe(200)
      expect(data).toEqual(mockLeagues)
      expect(mockPrisma.league.findMany).toHaveBeenCalledWith({
        select: {
          id: true,
          name: true,
          platform: true,
          season: true,
          teamCount: true,
          isActive: true,
          lastSyncAt: true,
        },
        where: {
          isActive: true,
        },
        orderBy: {
          lastSyncAt: 'desc',
        },
      })
    })

    it('should return empty array when no leagues exist', async () => {
      mockPrisma.league.findMany.mockResolvedValue([])

      const response = await GET()
      const data = await response.json()

      expect(response.status).toBe(200)
      expect(data).toEqual([])
    })

    it('should handle database errors gracefully', async () => {
      mockPrisma.league.findMany.mockRejectedValue(new Error('Database error'))

      const response = await GET()
      const data = await response.json()

      expect(response.status).toBe(500)
      expect(data).toEqual({ error: 'Failed to fetch leagues' })
    })

    it('should only return active leagues', async () => {
      const mockLeagues = [
        {
          id: 'espn_123456_2025',
          name: 'Active League',
          platform: 'ESPN',
          season: '2025',
          teamCount: 10,
          isActive: true,
          lastSyncAt: new Date('2025-01-01'),
        },
      ]

      mockPrisma.league.findMany.mockResolvedValue(mockLeagues)

      await GET()

      expect(mockPrisma.league.findMany).toHaveBeenCalledWith(
        expect.objectContaining({
          where: {
            isActive: true,
          },
        })
      )
    })

    it('should order leagues by lastSyncAt descending', async () => {
      const mockLeagues = [
        {
          id: 'espn_789012_2025',
          name: 'Newer League',
          platform: 'ESPN',
          season: '2025',
          teamCount: 12,
          isActive: true,
          lastSyncAt: new Date('2025-01-02'),
        },
        {
          id: 'espn_123456_2025',
          name: 'Older League',
          platform: 'ESPN',
          season: '2025',
          teamCount: 10,
          isActive: true,
          lastSyncAt: new Date('2025-01-01'),
        },
      ]

      mockPrisma.league.findMany.mockResolvedValue(mockLeagues)

      await GET()

      expect(mockPrisma.league.findMany).toHaveBeenCalledWith(
        expect.objectContaining({
          orderBy: {
            lastSyncAt: 'desc',
          },
        })
      )
    })
  })
})