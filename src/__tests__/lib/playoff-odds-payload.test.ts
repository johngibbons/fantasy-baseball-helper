// src/__tests__/lib/playoff-odds-payload.test.ts
import {
  buildPlayoffOddsPayload,
  computePeriodWeights,
} from '@/lib/playoff-odds-payload'

describe('computePeriodWeights', () => {
  it('weights each period by its day count proportionally', () => {
    const weights = computePeriodWeights([1, 2], {
      1: ['2026-05-04', '2026-05-10'],   // 7 days
      2: ['2026-05-11', '2026-05-24'],   // 14 days
    })
    expect(weights[1]).toBeCloseTo(7 / 21, 5)
    expect(weights[2]).toBeCloseTo(14 / 21, 5)
  })

  it('returns equal weights when ranges have the same length', () => {
    const weights = computePeriodWeights([1, 2, 3], {
      1: ['2026-05-04', '2026-05-10'],
      2: ['2026-05-11', '2026-05-17'],
      3: ['2026-05-18', '2026-05-24'],
    })
    expect(weights[1]).toBeCloseTo(1 / 3, 5)
    expect(weights[2]).toBeCloseTo(1 / 3, 5)
    expect(weights[3]).toBeCloseTo(1 / 3, 5)
  })
})

describe('buildPlayoffOddsPayload', () => {
  const teams = [
    { id: 1, name: 'T1', record: { overall: { wins: 10, losses: 5, ties: 0 } } },
    { id: 2, name: 'T2', record: { overall: { wins: 5, losses: 10, ties: 0 } } },
  ] as any

  const rosters = {
    1: [
      { player: { fullName: 'A', defaultPositionId: 7,
                  eligibleSlots: [5, 12, 16], injuryStatus: 'ACTIVE' },
        lineupSlotId: 5 },
    ],
    2: [
      { player: { fullName: 'B', defaultPositionId: 1,
                  eligibleSlots: [14, 13, 16], injuryStatus: 'ACTIVE' },
        lineupSlotId: 14 },
    ],
  } as any

  const fullSchedule = [
    { matchupPeriodId: 1, home: { teamId: 1 }, away: { teamId: 2 } },
    { matchupPeriodId: 2, home: { teamId: 2 }, away: { teamId: 1 } },
    { matchupPeriodId: 3, home: { teamId: 1 }, away: { teamId: 2 } },
  ]

  it('emits remaining schedule from currentMatchupPeriod onward', () => {
    const payload = buildPlayoffOddsPayload({
      season: 2026,
      currentMatchupPeriod: 2,
      finalRegularSeasonPeriod: 3,
      teams,
      rosters,
      fullSchedule,
      matchupSchedule: {
        2: ['2026-04-06', '2026-04-12'],
        3: ['2026-04-13', '2026-04-19'],
      },
      playoffSlots: 1,
      nTrials: 100,
    })

    expect(payload.remaining_schedule).toHaveLength(2)
    expect(payload.remaining_schedule[0].matchup_period_id).toBe(2)
    expect(payload.period_weights['2']).toBeCloseTo(0.5, 5)
    expect(payload.teams).toHaveLength(2)
    expect(payload.teams[0].current_wins).toBe(10)
    expect(payload.teams[0].roster[0].name).toBe('A')
    expect(payload.teams[0].roster[0].eligible_positions).toBe('OF/UTIL')
  })
})

describe('buildPlayoffOddsPayload with observed history', () => {
  const teams = [
    { id: 1, name: 'T1', record: { overall: { wins: 10, losses: 5, ties: 0 } } },
    { id: 2, name: 'T2', record: { overall: { wins: 5, losses: 10, ties: 0 } } },
  ] as any
  const rosters = { 1: [], 2: [] } as any
  const fullSchedule = [
    { matchupPeriodId: 2, home: { teamId: 1 }, away: { teamId: 2 } },
    { matchupPeriodId: 3, home: { teamId: 2 }, away: { teamId: 1 } },
  ]

  it('emits observed_history filtered to completed periods preceding currentMatchupPeriod', () => {
    const observedHistory = [
      { team_id: 1, matchup_period_id: 1, period_days: 7,
        cats: { R: 70, TB: 200, RBI: 70, SB: 5, OBP: 0.330,
                K: 60, QS: 6, ERA: 3.50, WHIP: 1.20, SVHD: 5 } },
      { team_id: 2, matchup_period_id: 1, period_days: 7,
        cats: { R: 50, TB: 150, RBI: 50, SB: 3, OBP: 0.300,
                K: 40, QS: 4, ERA: 4.20, WHIP: 1.35, SVHD: 3 } },
      // matchup_period_id 2 is the CURRENT period — should NOT be in observed_history
      { team_id: 1, matchup_period_id: 2, period_days: 7,
        cats: { R: 30, TB: 70 } },
    ]

    const payload = buildPlayoffOddsPayload({
      season: 2026,
      currentMatchupPeriod: 2,
      finalRegularSeasonPeriod: 3,
      teams,
      rosters,
      fullSchedule,
      matchupSchedule: {
        2: ['2026-04-06', '2026-04-12'],
        3: ['2026-04-13', '2026-04-19'],
      },
      observedHistory,
      playoffSlots: 1,
      nTrials: 100,
    })

    expect(payload.observed_history).toHaveLength(2)
    const ids = payload.observed_history.map((o: any) => o.matchup_period_id)
    expect(ids).toEqual([1, 1])
    expect(payload.period_days_by_id).toEqual({ '2': 7, '3': 7 })
  })

  it('omits observed_history entirely when none provided', () => {
    const payload = buildPlayoffOddsPayload({
      season: 2026,
      currentMatchupPeriod: 2,
      finalRegularSeasonPeriod: 3,
      teams,
      rosters,
      fullSchedule,
      matchupSchedule: { 2: ['2026-04-06', '2026-04-12'], 3: ['2026-04-13', '2026-04-19'] },
      playoffSlots: 1,
      nTrials: 100,
    })
    expect(payload.observed_history).toEqual([])
  })
})
