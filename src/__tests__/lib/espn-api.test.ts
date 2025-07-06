import { ESPNApi } from '../../lib/espn-api'

// Mock fetch
const mockFetch = jest.fn()
global.fetch = mockFetch

describe('ESPN API', () => {
  beforeEach(() => {
    mockFetch.mockClear()
  })

  const mockSettings = {
    swid: 'test_swid',
    espn_s2: 'test_espn_s2'
  }

  describe('getLeague', () => {
    it('should fetch league info successfully', async () => {
      const mockResponse = {
        settings: {
          name: 'Test League',
          size: 12
        },
        teams: [
          {
            id: 1,
            name: 'Team 1',
            location: 'Location 1',
            owners: ['Owner 1']
          }
        ]
      }

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse
      })

      const result = await ESPNApi.getLeague('123456', '2024', mockSettings)

      expect(mockFetch).toHaveBeenCalledWith(
        'https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb/seasons/2024/segments/0/leagues/123456',
        {
          headers: {
            'Cookie': 'swid=test_swid; espn_s2=test_espn_s2',
            'Content-Type': 'application/json'
          }
        }
      )
      expect(result).toEqual(mockResponse)
    })

    it('should handle authentication errors', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 401,
        statusText: 'Unauthorized',
        text: async () => 'Invalid credentials'
      })

      await expect(
        ESPNApi.getLeague('123456', '2024', mockSettings)
      ).rejects.toThrow('ESPN API error: 401 - Unauthorized')
    })

    it('should handle network errors', async () => {
      mockFetch.mockRejectedValueOnce(new Error('Network error'))

      await expect(
        ESPNApi.getLeague('123456', '2024', mockSettings)
      ).rejects.toThrow('Network error')
    })
  })

  describe('getTeams', () => {
    it('should fetch teams successfully', async () => {
      const mockResponse = {
        teams: [{
          id: 1,
          abbrev: 'TM1',
          location: 'Test',
          nickname: 'Team',
          owners: ['owner1']
        }]
      }

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse
      })

      const result = await ESPNApi.getTeams('123456', '2024', mockSettings)

      expect(mockFetch).toHaveBeenCalledWith(
        'https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb/seasons/2024/segments/0/leagues/123456?view=mTeam',
        {
          headers: {
            'Cookie': 'swid=test_swid; espn_s2=test_espn_s2',
            'Content-Type': 'application/json'
          }
        }
      )
      expect(result).toEqual(mockResponse.teams)
    })

    it('should handle teams not found', async () => {
      const mockResponse = { teams: [] }

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse
      })

      const result = await ESPNApi.getTeams('123456', '2024', mockSettings)
      expect(result).toEqual([])
    })
  })

  describe('testConnection', () => {
    it('should return true for successful connection', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ settings: { name: 'Test' } })
      })

      const result = await ESPNApi.testConnection('123456', '2024', mockSettings)
      expect(result).toBe(true)
    })

    it('should return false for failed connection', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 401,
        statusText: 'Unauthorized',
        text: async () => 'Invalid credentials'
      })

      const result = await ESPNApi.testConnection('123456', '2024', mockSettings)
      expect(result).toBe(false)
    })
  })
})