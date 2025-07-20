import { ESPNApi } from '../../lib/espn-api'

// Mock fetch
const mockFetch = jest.fn()
global.fetch = mockFetch

describe('ESPN API Player Stats', () => {
  beforeEach(() => {
    mockFetch.mockClear()
  })

  const mockSettings = {
    swid: 'test_swid',
    espn_s2: 'test_espn_s2'
  }

  it('should extract player stats from ESPN API response', async () => {
    const mockESPNResponse = {
      teams: [{
        id: 1,
        roster: {
          entries: [{
            playerId: 12345,
            lineupSlotId: 0,
            acquisitionType: 'DRAFT',
            acquisitionDate: 1234567890,
            playerPoolEntry: {
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
                    0: 150,    // at bats
                    1: 25,     // home runs  
                    2: 80,     // RBI
                    3: 75,     // runs
                    4: 120,    // hits
                    5: 0.285,  // batting average
                    6: 15,     // stolen bases
                    7: 30,     // doubles
                    8: 2,      // triples
                    9: 0.365,  // on base percentage
                    10: 0.520  // slugging percentage
                  }
                }]
              }
            }
          }]
        }
      }]
    }

    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => mockESPNResponse
    })

    const result = await ESPNApi.getRosters('123456', '2024', mockSettings)

    expect(result).toEqual({
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
              0: 150,
              1: 25,
              2: 80,
              3: 75,
              4: 120,
              5: 0.285,
              6: 15,
              7: 30,
              8: 2,
              9: 0.365,
              10: 0.520
            }
          }]
        }
      }]
    })
  })

  it('should handle players without stats data', async () => {
    const mockESPNResponse = {
      teams: [{
        id: 1,
        roster: {
          entries: [{
            playerId: 12345,
            lineupSlotId: 0,
            acquisitionType: 'DRAFT',
            acquisitionDate: 1234567890,
            playerPoolEntry: {
              player: {
                id: 12345,
                fullName: 'Mike Trout',
                firstName: 'Mike',
                lastName: 'Trout',
                eligibleSlots: [0, 5],
                defaultPositionId: 5
                // No stats property
              }
            }
          }]
        }
      }]
    }

    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => mockESPNResponse
    })

    const result = await ESPNApi.getRosters('123456', '2024', mockSettings)

    expect(result[1][0].player?.stats).toBeUndefined()
  })
})