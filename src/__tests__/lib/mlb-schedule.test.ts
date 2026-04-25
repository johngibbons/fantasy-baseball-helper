import { getTeamGamesInRange } from '../../lib/mlb-schedule'

const mockFetch = jest.fn()
global.fetch = mockFetch

describe('getTeamGamesInRange', () => {
  beforeEach(() => mockFetch.mockClear())

  it('counts only unstarted games and reports their dates', async () => {
    // Saturday: NYY @ BOS scheduled, MIA @ ATL live (already started),
    //           LAD @ SF scheduled
    // Sunday:   all 3 games scheduled
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
                gameType: 'R', status: { abstractGameCode: 'P' },
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

    // Live MIA/ATL game should NOT contribute to teamGames
    expect(result.teamGames.MIA).toBeUndefined()
    expect(result.teamGames.ATL).toBeUndefined()
    // NYY plays Sat + Sun (both 'P') → 2 games
    expect(result.teamGames.NYY).toBe(2)
    expect(result.teamGames.BOS).toBe(2)
    // LAD/SF play once on Sat
    expect(result.teamGames.LAD).toBe(1)
    expect(result.teamGames.SF).toBe(1)

    // Both dates should appear since each has at least one unstarted game
    expect(result.datesWithUnstartedGames).toEqual(['2026-04-25', '2026-04-26'])
  })

  it('omits dates where every game is live or final', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        dates: [
          {
            date: '2026-04-25',
            games: [
              {
                gameType: 'R', status: { abstractGameCode: 'F' },
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
    expect(result.datesWithUnstartedGames).toEqual(['2026-04-26'])
    expect(result.teamGames.NYY).toBe(1)
  })
})
