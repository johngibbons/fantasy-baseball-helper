// src/app/api/matchup/projections/route.ts

import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { ESPNApi } from '@/lib/espn-api'
import {
  getTeamGamesInRange,
  getProbablePitchers,
  getRemainingSeasonGames,
} from '@/lib/mlb-schedule'

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000'

// ESPN stat ID -> category name mapping (same as start-sit route)
const ESPN_STAT_MAP: Record<string, string> = {
  '20': 'R', '8': 'TB', '21': 'RBI', '23': 'SB', '17': 'OBP',
  '48': 'K', '63': 'QS', '47': 'ERA', '41': 'WHIP', '83': 'SVHD',
}

// ESPN position ID -> abbreviation
const ESPN_POSITION_MAP: Record<number, string> = {
  1: 'SP', 2: 'C', 3: '1B', 4: '2B', 5: '3B', 6: 'SS',
  7: 'LF', 8: 'CF', 9: 'RF', 10: 'DH', 11: 'RP',
}

// ESPN team ID -> MLB team abbreviation
const ESPN_TEAM_MAP: Record<number, string> = {
  1: 'BAL', 2: 'BOS', 3: 'LAA', 4: 'CWS', 5: 'CLE',
  6: 'DET', 7: 'KC', 8: 'MIL', 9: 'MIN', 10: 'NYY',
  11: 'OAK', 12: 'SEA', 13: 'TEX', 14: 'TOR', 15: 'ATL',
  16: 'CHC', 17: 'CIN', 18: 'HOU', 19: 'LAD', 20: 'WSH',
  21: 'NYM', 22: 'PHI', 23: 'PIT', 24: 'STL', 25: 'SD',
  26: 'SF', 27: 'COL', 28: 'MIA', 29: 'ARI', 30: 'TB',
}

function sanitize(val: number | undefined, fallback: number = 0): number {
  const v = val ?? fallback
  return Number.isFinite(v) ? v : fallback
}

/**
 * Derive matchup period date range from ESPN league settings.
 *
 * ESPN's scheduleSettings.matchupPeriods maps matchup period ID → array of
 * scoring period IDs. We derive the epoch (scoring period 1 = which date)
 * from the current date and latestScoringPeriod, then convert.
 */
function getMatchupDateRangeFromESPN(
  leagueData: any,
  matchupPeriodId: number,
  today: Date,
): { startDate: string; endDate: string; remainingDates: string[] } {
  const scheduleSettings = (leagueData.settings as any)?.scheduleSettings
  const matchupPeriodLengthWeeks: number = scheduleSettings?.matchupPeriodLength || 1
  const matchupPeriods: Record<string, number[]> = scheduleSettings?.matchupPeriods || {}
  const scoringPeriodIds: number[] = matchupPeriods[String(matchupPeriodId)] || []

  // Derive the epoch: scoring period 1 = which calendar date?
  // We know today's date and today's scoring period ID from ESPN status.
  const latestScoringPeriod = leagueData.status?.latestScoringPeriod
    || leagueData.latestScoringPeriod
    || 0

  if (latestScoringPeriod > 0) {
    // epoch = today - (latestScoringPeriod - 1) days
    const epochDate = new Date(today)
    epochDate.setDate(today.getDate() - (latestScoringPeriod - 1))

    // ESPN matchupPeriods map may only contain elapsed scoring periods.
    // Use the full range: if we have scoring period IDs AND they span
    // the expected length, use them. Otherwise, compute from
    // matchupPeriodLength (in weeks) and the epoch.
    let firstScoringPeriod: number
    let lastScoringPeriod: number

    const expectedDays = matchupPeriodLengthWeeks * 7

    if (scoringPeriodIds.length >= expectedDays) {
      // ESPN has the full map — use it directly
      firstScoringPeriod = Math.min(...scoringPeriodIds)
      lastScoringPeriod = Math.max(...scoringPeriodIds)
    } else {
      // Compute from matchupPeriodLength and current period ID.
      // Each matchup period spans matchupPeriodLengthWeeks * 7 scoring periods.
      // Period 1 starts at scoring period 1, period 2 starts at 1 + expectedDays, etc.
      firstScoringPeriod = 1 + (matchupPeriodId - 1) * expectedDays
      lastScoringPeriod = firstScoringPeriod + expectedDays - 1
    }

    const matchupStart = new Date(epochDate)
    matchupStart.setDate(epochDate.getDate() + firstScoringPeriod - 1)

    const matchupEnd = new Date(epochDate)
    matchupEnd.setDate(epochDate.getDate() + lastScoringPeriod - 1)

    const startStr = matchupStart.toISOString().split('T')[0]
    const endStr = matchupEnd.toISOString().split('T')[0]

    // Remaining dates: tomorrow through end of matchup
    const remainingDates: string[] = []
    const tomorrow = new Date(today)
    tomorrow.setDate(today.getDate() + 1)
    const cursor = new Date(tomorrow)
    while (cursor <= matchupEnd) {
      remainingDates.push(cursor.toISOString().split('T')[0])
      cursor.setDate(cursor.getDate() + 1)
    }

    console.log(`Matchup period ${matchupPeriodId}: scoring periods ${firstScoringPeriod}-${lastScoringPeriod}, dates ${startStr} to ${endStr}, ${remainingDates.length} days remaining (periodLength=${matchupPeriodLengthWeeks}w)`)

    return { startDate: startStr, endDate: endStr, remainingDates }
  }

  // Fallback: Mon-Sun estimate
  console.log('Matchup period: falling back to Mon-Sun estimate (no ESPN schedule data)')
  const dayOfWeek = today.getDay()
  const mondayOffset = dayOfWeek === 0 ? -6 : 1 - dayOfWeek
  const monday = new Date(today)
  monday.setDate(today.getDate() + mondayOffset)
  const sunday = new Date(monday)
  sunday.setDate(monday.getDate() + 6)

  const startDate = monday.toISOString().split('T')[0]
  const endDate = sunday.toISOString().split('T')[0]

  const remainingDates: string[] = []
  const tomorrow = new Date(today)
  tomorrow.setDate(today.getDate() + 1)
  const cursor = new Date(tomorrow)
  while (cursor <= sunday) {
    remainingDates.push(cursor.toISOString().split('T')[0])
    cursor.setDate(cursor.getDate() + 1)
  }

  return { startDate, endDate, remainingDates }
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json()
    const { leagueId, teamId, season = '2026' } = body

    if (!leagueId || !teamId) {
      return NextResponse.json(
        { error: 'Missing required fields: leagueId, teamId' },
        { status: 400 },
      )
    }

    // Look up credentials
    const league = await prisma.league.findUnique({ where: { id: leagueId } })
    if (!league) {
      return NextResponse.json({ error: 'League not found' }, { status: 404 })
    }

    const leagueSettings = league.settings as any
    const credentials = leagueSettings?.credentials
    if (!credentials?.espn_s2 || !credentials?.swid) {
      return NextResponse.json(
        { error: 'ESPN credentials not configured. Set them up in Settings.' },
        { status: 400 },
      )
    }

    const espnSettings = { swid: credentials.swid, espn_s2: credentials.espn_s2 }

    // Fetch league info → currentMatchupPeriod
    const leagueData = await ESPNApi.getLeague(league.externalId, season, espnSettings)
    const matchupPeriod = leagueData.status?.currentMatchupPeriod
      || leagueData.currentMatchupPeriod
      || 1

    // Fetch ESPN data in parallel
    const [rosters, scoreboard, teams] = await Promise.all([
      ESPNApi.getRosters(league.externalId, season, espnSettings),
      ESPNApi.getMatchupScoreboard(league.externalId, season, espnSettings, matchupPeriod),
      ESPNApi.getTeams(league.externalId, season, espnSettings),
    ])

    const myTeamId = parseInt(teamId)

    // Find my matchup
    const myMatchup = scoreboard.schedule.find(
      (m) => m.home.teamId === myTeamId || m.away.teamId === myTeamId
    )
    if (!myMatchup) {
      return NextResponse.json(
        { error: 'Could not find your matchup for this week' },
        { status: 404 },
      )
    }

    const isHome = myMatchup.home.teamId === myTeamId
    const mySide = isHome ? myMatchup.home : myMatchup.away
    const theirSide = isHome ? myMatchup.away : myMatchup.home

    // Extract current actuals from scoreboard
    const myStats = mySide.cumulativeScore?.scoreByStat || {}
    const theirStats = theirSide.cumulativeScore?.scoreByStat || {}

    const myActuals: Record<string, number> = {}
    const oppActuals: Record<string, number> = {}
    for (const [statId, catName] of Object.entries(ESPN_STAT_MAP)) {
      myActuals[catName] = sanitize(myStats[statId]?.score)
      oppActuals[catName] = sanitize(theirStats[statId]?.score)
    }
    // IP and PA for rate stat blending
    myActuals['IP'] = sanitize(myStats['34']?.score)   // stat ID 34 = IP
    myActuals['PA'] = sanitize(myStats['0']?.score)     // stat ID 0 = AB (approximate PA)
    oppActuals['IP'] = sanitize(theirStats['34']?.score)
    oppActuals['PA'] = sanitize(theirStats['0']?.score)

    // Get opponent info
    const opponentTeam = teams.find((t) => t.id === theirSide.teamId)
    const opponentName = opponentTeam
      ? [opponentTeam.location, opponentTeam.nickname].filter(Boolean).join(' ')
      : `Team ${theirSide.teamId}`

    // Compute matchup date range from ESPN league settings
    const today = new Date()
    const scheduleSettings = (leagueData.settings as any)?.scheduleSettings
    console.log('ESPN matchupPeriodLength:', scheduleSettings?.matchupPeriodLength)
    console.log('ESPN matchupPeriodCount:', scheduleSettings?.matchupPeriodCount)
    console.log('ESPN matchupPeriods keys:', scheduleSettings?.matchupPeriods ? Object.keys(scheduleSettings.matchupPeriods).slice(0, 5) : 'none')
    console.log('ESPN matchupPeriods[1]:', JSON.stringify(scheduleSettings?.matchupPeriods?.['1']))
    console.log('ESPN matchupPeriods[2]:', JSON.stringify(scheduleSettings?.matchupPeriods?.['2']))
    const { startDate, endDate, remainingDates } = getMatchupDateRangeFromESPN(leagueData, matchupPeriod, today)

    // Fetch MLB data in parallel
    const [teamGamesRemaining, probablePitchers, remainingSeasonGames] = await Promise.all([
      getTeamGamesInRange(
        remainingDates.length > 0 ? remainingDates[0] : endDate,
        endDate,
      ),
      getProbablePitchers(
        remainingDates.length > 0 ? remainingDates[0] : endDate,
        endDate,
      ),
      getRemainingSeasonGames(season),
    ])

    // Build probable pitcher lookup: date → [mlb_id, ...]
    const probablePitcherIds: Record<string, number[]> = {}
    for (const entry of probablePitchers) {
      if (!probablePitcherIds[entry.date]) {
        probablePitcherIds[entry.date] = []
      }
      probablePitcherIds[entry.date].push(entry.mlbPlayerId)
    }

    // Build roster player lists for both teams
    function buildRosterPayload(espnTeamId: number) {
      const entries = rosters[espnTeamId] || []
      return entries.map((entry) => {
        const player = entry.player
        const posId = player?.defaultPositionId || 0
        const position = ESPN_POSITION_MAP[posId] || ''
        const playerType = posId === 1 || posId === 11 ? 'pitcher' : 'hitter'
        // ESPN proTeamId → MLB team abbreviation
        // The proTeamId is available in the player stats array
        const proTeamId = (player?.stats?.[0] as any)?.proTeamId || 0
        const mlbTeam = ESPN_TEAM_MAP[proTeamId] || ''

        return {
          name: player?.fullName || '',
          position,
          player_type: playerType,
          lineup_slot_id: entry.lineupSlotId,
          mlb_team: mlbTeam,
          eligible_positions: (player?.eligibleSlots || [])
            .map((s: number) => ESPN_POSITION_MAP[s])
            .filter(Boolean)
            .join('/'),
        }
      })
    }

    const myRosterPayload = buildRosterPayload(myTeamId)
    const oppRosterPayload = buildRosterPayload(theirSide.teamId)

    // Call Python backend
    const backendResponse = await fetch(`${BACKEND_URL}/api/matchup/projections`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        my_roster: myRosterPayload,
        opponent_roster: oppRosterPayload,
        actuals: { my: myActuals, opponent: oppActuals },
        team_games_remaining: teamGamesRemaining,
        probable_pitcher_ids: probablePitcherIds,
        remaining_season_games: remainingSeasonGames,
        days_remaining: remainingDates.length,
        remaining_dates: remainingDates,
        season: parseInt(season),
      }),
    })

    if (!backendResponse.ok) {
      const errorText = await backendResponse.text()
      console.error('Matchup backend error:', errorText)
      return NextResponse.json(
        { error: `Backend error: ${backendResponse.status}` },
        { status: 502 },
      )
    }

    const result = await backendResponse.json()

    // Enrich response with matchup metadata
    return NextResponse.json({
      ...result,
      matchup_period: {
        week: matchupPeriod,
        start_date: startDate,
        end_date: endDate,
        days_remaining: remainingDates.length,
      },
      opponent_name: opponentName,
      my_team_id: myTeamId,
      opponent_team_id: theirSide.teamId,
    })
  } catch (error: any) {
    console.error('Matchup projection error:', error)
    return NextResponse.json(
      { error: error.message || 'Failed to compute matchup projections' },
      { status: 500 },
    )
  }
}
