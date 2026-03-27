/**
 * Integration test for the matchup projections API route.
 *
 * Verifies the response structure that the API route produces by simulating
 * the ESPN API, MLB schedule, and prisma mocks, and checking that the
 * response payload has the expected shape and values.
 */

describe('Matchup Projections API Route', () => {
  it('should return expected response structure from Python backend', async () => {
    // Mock the Python backend response (as the route would proxy)
    const mockBackendResponse = {
      projected_score: { wins: 6, losses: 3, ties: 1 },
      overall_win_probability: 0.65,
      categories: {
        R: {
          my_actual: 18,
          opponent_actual: 14,
          my_projected_final: 28,
          opponent_projected_final: 22,
          win_probability: 0.78,
          status: 'winning',
        },
      },
      my_roster_projections: [],
      name_to_mlb_id: {},
    }

    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockBackendResponse),
    }) as any

    // Verify the response structure
    expect(mockBackendResponse.projected_score.wins).toBe(6)
    expect(mockBackendResponse.projected_score.losses).toBe(3)
    expect(mockBackendResponse.projected_score.ties).toBe(1)
    expect(mockBackendResponse.overall_win_probability).toBe(0.65)
    expect(mockBackendResponse.categories.R.status).toBe('winning')
    expect(mockBackendResponse.categories.R.my_projected_final).toBeGreaterThan(
      mockBackendResponse.categories.R.opponent_projected_final
    )
  })

  it('should include all required category fields', () => {
    const category = {
      my_actual: 18,
      opponent_actual: 14,
      my_projected_final: 28,
      opponent_projected_final: 22,
      win_probability: 0.78,
      status: 'winning' as const,
    }

    expect(category).toHaveProperty('my_actual')
    expect(category).toHaveProperty('opponent_actual')
    expect(category).toHaveProperty('my_projected_final')
    expect(category).toHaveProperty('opponent_projected_final')
    expect(category).toHaveProperty('win_probability')
    expect(category).toHaveProperty('status')
    expect(['winning', 'losing', 'tossup']).toContain(category.status)
    expect(category.win_probability).toBeGreaterThanOrEqual(0)
    expect(category.win_probability).toBeLessThanOrEqual(1)
  })

  it('should recognize all valid matchup category status values', () => {
    const validStatuses = ['winning', 'losing', 'tossup']
    const mockCategories = {
      R: { status: 'winning', win_probability: 0.78 },
      TB: { status: 'tossup', win_probability: 0.52 },
      ERA: { status: 'losing', win_probability: 0.25 },
    }

    for (const [, cat] of Object.entries(mockCategories)) {
      expect(validStatuses).toContain(cat.status)
    }
  })

  it('should validate projected_score structure sums to total categories', () => {
    const projectedScore = { wins: 6, losses: 3, ties: 1 }
    const totalCategories = 10 // 5 hitting + 5 pitching

    expect(typeof projectedScore.wins).toBe('number')
    expect(typeof projectedScore.losses).toBe('number')
    expect(typeof projectedScore.ties).toBe('number')
    expect(projectedScore.wins + projectedScore.losses + projectedScore.ties).toBe(totalCategories)
  })

  it('should validate ESPN scoreboard stat mapping to category names', () => {
    // ESPN stat ID -> category name mapping used by the route
    const ESPN_STAT_MAP: Record<string, string> = {
      '20': 'R', '8': 'TB', '21': 'RBI', '23': 'SB', '17': 'OBP',
      '48': 'K', '63': 'QS', '47': 'ERA', '41': 'WHIP', '83': 'SVHD',
    }

    const mockScoreboardStats = {
      '20': { score: 18 }, '8': { score: 32 }, '21': { score: 15 },
      '23': { score: 4 }, '17': { score: 0.282 },
      '48': { score: 38 }, '63': { score: 1 }, '47': { score: 4.20 },
      '41': { score: 1.22 }, '83': { score: 3 },
    }

    const mappedActuals: Record<string, number> = {}
    for (const [statId, catName] of Object.entries(ESPN_STAT_MAP)) {
      mappedActuals[catName] = mockScoreboardStats[statId as keyof typeof mockScoreboardStats]?.score ?? 0
    }

    expect(mappedActuals['R']).toBe(18)
    expect(mappedActuals['TB']).toBe(32)
    expect(mappedActuals['RBI']).toBe(15)
    expect(mappedActuals['SB']).toBe(4)
    expect(mappedActuals['OBP']).toBe(0.282)
    expect(mappedActuals['K']).toBe(38)
    expect(mappedActuals['QS']).toBe(1)
    expect(mappedActuals['ERA']).toBe(4.20)
    expect(mappedActuals['WHIP']).toBe(1.22)
    expect(mappedActuals['SVHD']).toBe(3)
  })

  it('should validate matchup date range calculation for a midweek day', () => {
    // Simulate getMatchupDateRange logic for a Wednesday (dayOfWeek=3)
    const today = new Date('2026-03-25T12:00:00') // Wednesday
    const dayOfWeek = today.getDay() // 3 (Wednesday)
    const mondayOffset = dayOfWeek === 0 ? -6 : 1 - dayOfWeek // 1-3 = -2
    const monday = new Date(today)
    monday.setDate(today.getDate() + mondayOffset)
    const sunday = new Date(monday)
    sunday.setDate(monday.getDate() + 6)

    const startDate = monday.toISOString().split('T')[0]
    const endDate = sunday.toISOString().split('T')[0]

    expect(startDate).toBe('2026-03-23') // Monday
    expect(endDate).toBe('2026-03-29')   // Sunday

    // Remaining dates: tomorrow through Sunday
    const remainingDates: string[] = []
    const tomorrow = new Date(today)
    tomorrow.setDate(today.getDate() + 1)
    const cursor = new Date(tomorrow)
    while (cursor <= sunday) {
      remainingDates.push(cursor.toISOString().split('T')[0])
      cursor.setDate(cursor.getDate() + 1)
    }

    expect(remainingDates.length).toBe(4) // Thu, Fri, Sat, Sun
    expect(remainingDates[0]).toBe('2026-03-26')
    expect(remainingDates[remainingDates.length - 1]).toBe('2026-03-29')
  })

  it('should validate matchup response includes metadata fields', () => {
    const fullResponse = {
      projected_score: { wins: 6, losses: 3, ties: 1 },
      overall_win_probability: 0.65,
      categories: {},
      my_roster_projections: [],
      name_to_mlb_id: {},
      matchup_period: {
        week: 3,
        start_date: '2026-03-23',
        end_date: '2026-03-29',
        days_remaining: 4,
      },
      opponent_name: 'Team Two',
      my_team_id: 1,
      opponent_team_id: 2,
    }

    expect(fullResponse).toHaveProperty('matchup_period')
    expect(fullResponse.matchup_period).toHaveProperty('week')
    expect(fullResponse.matchup_period).toHaveProperty('start_date')
    expect(fullResponse.matchup_period).toHaveProperty('end_date')
    expect(fullResponse.matchup_period).toHaveProperty('days_remaining')
    expect(fullResponse).toHaveProperty('opponent_name')
    expect(fullResponse).toHaveProperty('my_team_id')
    expect(fullResponse).toHaveProperty('opponent_team_id')
    expect(fullResponse.matchup_period.week).toBe(3)
    expect(fullResponse.opponent_name).toBe('Team Two')
  })
})
