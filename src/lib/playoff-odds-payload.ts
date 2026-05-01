// src/lib/playoff-odds-payload.ts
//
// Pure helper: shape ESPN data into the Python /playoff-odds payload.

import type { ESPNTeam, ESPNRosterEntry } from '@/lib/espn-api'

export interface ObservedPeriodPayload {
  team_id: number
  matchup_period_id: number
  period_days: number
  cats: Record<string, number>
}

const ESPN_POSITION_MAP: Record<number, string> = {
  1: 'SP', 2: 'C', 3: '1B', 4: '2B', 5: '3B', 6: 'SS',
  7: 'LF', 8: 'CF', 9: 'RF', 10: 'DH', 11: 'RP',
}

const ESPN_LINEUP_SLOT_MAP: Record<number, string> = {
  0: 'C', 1: '1B', 2: '2B', 3: '3B', 4: 'SS', 5: 'OF',
  6: 'OF', 7: 'OF', 10: 'DH', 12: 'UTIL', 13: 'P', 14: 'SP', 15: 'RP',
}

function daysBetweenInclusive(start: string, end: string): number {
  const s = new Date(start + 'T00:00:00').getTime()
  const e = new Date(end + 'T00:00:00').getTime()
  return Math.round((e - s) / (1000 * 60 * 60 * 24)) + 1
}

export function computePeriodWeights(
  periodIds: number[],
  matchupSchedule: Record<number, [string, string]>,
): Record<number, number> {
  const days: Record<number, number> = {}
  let total = 0
  for (const id of periodIds) {
    const range = matchupSchedule[id]
    if (!range) continue
    const d = daysBetweenInclusive(range[0], range[1])
    days[id] = d
    total += d
  }
  const weights: Record<number, number> = {}
  for (const id of periodIds) {
    weights[id] = total > 0 ? (days[id] || 0) / total : 0
  }
  return weights
}

interface BuildArgs {
  season: number
  currentMatchupPeriod: number
  finalRegularSeasonPeriod: number
  teams: ESPNTeam[]
  rosters: Record<number, ESPNRosterEntry[]>
  fullSchedule: Array<{
    matchupPeriodId: number
    home: { teamId: number }
    away: { teamId: number }
  }>
  matchupSchedule: Record<number, [string, string]>
  observedHistory?: ObservedPeriodPayload[]
  playoffSlots: number
  nTrials: number
  seed?: number
}

export function buildPlayoffOddsPayload(args: BuildArgs) {
  const remaining = args.fullSchedule.filter(
    m => m.matchupPeriodId >= args.currentMatchupPeriod
        && m.matchupPeriodId <= args.finalRegularSeasonPeriod,
  )
  const periodIds = Array.from(
    new Set(remaining.map(m => m.matchupPeriodId)),
  ).sort((a, b) => a - b)

  const period_weights = computePeriodWeights(periodIds, args.matchupSchedule)

  const teamsOut = args.teams.map(t => {
    const entries = args.rosters[t.id] || []
    return {
      team_id: t.id,
      team_name: (t as any).name?.trim()
                || [t.location, t.nickname].filter(Boolean).join(' ').trim()
                || `Team ${t.id}`,
      current_wins: t.record?.overall?.wins ?? 0,
      current_losses: t.record?.overall?.losses ?? 0,
      current_ties: t.record?.overall?.ties ?? 0,
      roster: entries.map(e => {
        const p = e.player
        const posId = p?.defaultPositionId ?? 0
        const position = ESPN_POSITION_MAP[posId] || ''
        const playerType = posId === 1 || posId === 11 ? 'pitcher' : 'hitter'
        const eligible = (p?.eligibleSlots || [])
          .map((s: number) => ESPN_LINEUP_SLOT_MAP[s])
          .filter(Boolean)
          .join('/')
        return {
          name: p?.fullName || `Player ${e.playerId}`,
          position,
          player_type: playerType,
          lineup_slot_id: e.lineupSlotId,
          eligible_positions: eligible,
          injury_status: p?.injuryStatus || 'ACTIVE',
        }
      }),
    }
  })

  // Filter observed history to fully-completed prior periods only
  const completedHistory = (args.observedHistory || []).filter(
    o => o.matchup_period_id < args.currentMatchupPeriod,
  )

  // Build period_days_by_id from matchupSchedule for the remaining periods
  const period_days_by_id: Record<number, number> = {}
  for (const id of periodIds) {
    const range = args.matchupSchedule[id]
    if (range) {
      period_days_by_id[id] = daysBetweenInclusive(range[0], range[1])
    }
  }

  return {
    season: args.season,
    teams: teamsOut,
    remaining_schedule: remaining.map(m => ({
      matchup_period_id: m.matchupPeriodId,
      home_team_id: m.home.teamId,
      away_team_id: m.away.teamId,
    })),
    period_weights: Object.fromEntries(
      Object.entries(period_weights).map(([k, v]) => [String(k), v]),
    ),
    period_days_by_id: Object.fromEntries(
      Object.entries(period_days_by_id).map(([k, v]) => [String(k), v]),
    ),
    observed_history: completedHistory,
    playoff_slots: args.playoffSlots,
    n_trials: args.nTrials,
    seed: args.seed,
  }
}
