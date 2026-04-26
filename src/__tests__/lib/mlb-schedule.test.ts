import { getTeamGamesInRange } from '../../lib/mlb-schedule'

const mockFetch = jest.fn()
global.fetch = mockFetch

describe('getTeamGamesInRange', () => {
  beforeEach(() => mockFetch.mockClear())

  it('counts every regular-season game and reports the dates that have any', async () => {
    // Mix of statuses: ESPN actuals lag by ~a day, so we count games regardless
    // of whether they are scheduled, in progress, or final until the local
    // clock rolls past midnight.
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        dates: [
          {
            date: '2026-04-25',
            games: [
              {
                gameType: 'R', status: { abstractGameCode: 'P' },
                teams: { home: { team: { id: 111 } }, away: { team: { id: 147 } } },
              },
              {
                gameType: 'R', status: { abstractGameCode: 'L' },
                teams: { home: { team: { id: 144 } }, away: { team: { id: 146 } } },
              },
              {
                gameType: 'R', status: { abstractGameCode: 'F' },
                teams: { home: { team: { id: 137 } }, away: { team: { id: 119 } } },
              },
            ],
          },
          {
            date: '2026-04-26',
            games: [
              {
                gameType: 'R', status: { abstractGameCode: 'P' },
                teams: { home: { team: { id: 111 } }, away: { team: { id: 147 } } },
              },
            ],
          },
        ],
      }),
    })

    const result = await getTeamGamesInRange('2026-04-25', '2026-04-26')

    // Every team in a regular-season game is counted, regardless of status
    expect(result.teamGames.NYY).toBe(2)
    expect(result.teamGames.BOS).toBe(2)
    expect(result.teamGames.MIA).toBe(1)
    expect(result.teamGames.ATL).toBe(1)
    expect(result.teamGames.LAD).toBe(1)
    expect(result.teamGames.SF).toBe(1)
    expect(result.datesWithGames).toEqual(['2026-04-25', '2026-04-26'])
  })

  it('skips spring training and other non-regular-season games', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        dates: [
          {
            date: '2026-04-25',
            games: [
              {
                gameType: 'S', status: { abstractGameCode: 'P' },
                teams: { home: { team: { id: 111 } }, away: { team: { id: 147 } } },
              },
            ],
          },
          {
            date: '2026-04-26',
            games: [
              {
                gameType: 'R', status: { abstractGameCode: 'P' },
                teams: { home: { team: { id: 111 } }, away: { team: { id: 147 } } },
              },
            ],
          },
        ],
      }),
    })

    const result = await getTeamGamesInRange('2026-04-25', '2026-04-26')
    expect(result.datesWithGames).toEqual(['2026-04-26'])
    expect(result.teamGames.NYY).toBe(1)
  })
})
