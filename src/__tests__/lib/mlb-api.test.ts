import { MLBApi } from '../../lib/mlb-api'

// Mock fetch
const mockFetch = jest.fn()
global.fetch = mockFetch

describe('MLB API', () => {
  beforeEach(() => {
    mockFetch.mockClear()
  })

  describe('searchPlayers', () => {
    it('should search for players successfully', async () => {
      const mockResponse = {
        people: [
          {
            id: 545361,
            fullName: 'Mike Trout',
            firstName: 'Mike',
            lastName: 'Trout',
            active: true,
            primaryPosition: { name: 'Outfield', abbreviation: 'OF' }
          }
        ]
      }

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse
      })

      const result = await MLBApi.searchPlayers('Mike Trout')

      expect(mockFetch).toHaveBeenCalledWith(
        'https://statsapi.mlb.com/api/v1/people/search?names=Mike%20Trout'
      )
      expect(result).toEqual(mockResponse.people)
    })

    it('should handle API errors', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 500
      })

      await expect(MLBApi.searchPlayers('Invalid Player')).rejects.toThrow(
        'MLB API error: 500'
      )
    })

    it('should handle empty search results', async () => {
      const mockResponse = { people: [] }

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse
      })

      const result = await MLBApi.searchPlayers('NonexistentPlayer')
      expect(result).toEqual([])
    })
  })

  describe('getPlayerStats', () => {
    it('should fetch player stats successfully', async () => {
      const mockResponse = {
        stats: [{
          splits: [{
            season: '2024',
            stat: {
              gamesPlayed: 140,
              avg: '.283',
              homeRuns: 40,
              rbi: 104
            }
          }]
        }]
      }

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse
      })

      const result = await MLBApi.getPlayerStats(545361, '2024')

      expect(mockFetch).toHaveBeenCalledWith(
        'https://statsapi.mlb.com/api/v1/people/545361/stats?stats=season&season=2024'
      )
      expect(result).toEqual(mockResponse.stats[0].splits[0].stat)
    })

    it('should handle player with no stats', async () => {
      const mockResponse = {
        stats: []
      }

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse
      })

      const result = await MLBApi.getPlayerStats(999999, '2024')
      expect(result).toBeNull()
    })
  })

  describe('getPlayer', () => {
    it('should fetch player details successfully', async () => {
      const mockResponse = {
        people: [{
          id: 545361,
          fullName: 'Mike Trout',
          firstName: 'Mike',
          lastName: 'Trout',
          birthDate: '1991-08-07',
          height: "6' 2\"",
          weight: 235,
          active: true,
          primaryPosition: { name: 'Outfield', abbreviation: 'OF' }
        }]
      }

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse
      })

      const result = await MLBApi.getPlayer(545361)

      expect(mockFetch).toHaveBeenCalledWith(
        'https://statsapi.mlb.com/api/v1/people/545361'
      )
      expect(result).toEqual(mockResponse.people[0])
    })

    it('should handle invalid player ID', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 404
      })

      await expect(MLBApi.getPlayer(999999)).rejects.toThrow(
        'MLB API error: 404'
      )
    })
  })
})