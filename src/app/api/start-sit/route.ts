import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { ESPNApi } from '@/lib/espn-api'
import { getMatchupDateRange, getMatchupEndDateForDate, toLocalDateStr } from '@/lib/matchup-schedule'
import { getTeamScheduleByDate } from '@/lib/mlb-schedule'

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000'

// ESPN proTeamId → MLB team abbreviation (same mapping used in matchup projections)
const ESPN_TEAM_MAP: Record<number, string> = {
  1: 'BAL', 2: 'BOS', 3: 'LAA', 4: 'CWS', 5: 'CLE',
  6: 'DET', 7: 'KC', 8: 'MIL', 9: 'MIN', 10: 'NYY',
  11: 'OAK', 12: 'SEA', 13: 'TEX', 14: 'TOR', 15: 'ATL',
  16: 'CHC', 17: 'CIN', 18: 'HOU', 19: 'LAD', 20: 'WSH',
  21: 'NYM', 22: 'PHI', 23: 'PIT', 24: 'STL', 25: 'SD',
  26: 'SF', 27: 'COL', 28: 'MIA', 29: 'ARI', 30: 'TB',
}

// ESPN stat ID -> category name mapping
// Verified from league scoring settings (statIds in scoringItems)
const ESPN_STAT_MAP: Record<string, string> = {
  '20': 'R',
  '8': 'TB',
  '21': 'RBI',
  '23': 'SB',
  '17': 'OBP',
  '48': 'K',
  '63': 'QS',
  '47': 'ERA',
  '41': 'WHIP',
  '83': 'SVHD',
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

    // Look up credentials from DB
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

    // Fetch league info to get currentMatchupPeriod
    const leagueData = await ESPNApi.getLeague(league.externalId, season, espnSettings)
    const matchupPeriod = leagueData.status?.currentMatchupPeriod
      || leagueData.currentMatchupPeriod
      || 1

    // Fetch roster and matchup scoreboard in parallel
    const [rosters, scoreboard] = await Promise.all([
      ESPNApi.getRosters(league.externalId, season, espnSettings),
      ESPNApi.getMatchupScoreboard(league.externalId, season, espnSettings, matchupPeriod),
    ])

    const myTeamId = parseInt(teamId)

    // Find user's matchup
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

    // Extract category totals from scoreByStat
    const myStats = mySide.cumulativeScore?.scoreByStat || {}
    const theirStats = theirSide.cumulativeScore?.scoreByStat || {}

    // Helper to sanitize ESPN scores (Infinity/NaN from 0 IP → default)
    const sanitize = (val: number | undefined, fallback: number = 0): number => {
      const v = val ?? fallback
      return Number.isFinite(v) ? v : fallback
    }

    const matchupCategories: Record<string, { yours: number; theirs: number }> = {}
    for (const [statId, catName] of Object.entries(ESPN_STAT_MAP)) {
      // ERA/WHIP default to 0 when no IP (will be handled by low-IP override in engine)
      const fallback = 0
      matchupCategories[catName] = {
        yours: sanitize(myStats[statId]?.score, fallback),
        theirs: sanitize(theirStats[statId]?.score, fallback),
      }
    }

    // IP from stat ID 34 (confirmed via league statQualificationMinimum)
    const teamIp = {
      yours: myStats['34']?.score ?? 0,
      theirs: theirStats['34']?.score ?? 0,
    }
    console.log('Team IP:', teamIp)

    // Get SP names from roster — include players eligible for SP slot (14),
    // not just defaultPositionId 1, to catch RP/SP dual-eligible pitchers.
    // Also capture proTeamId for team schedule validation.
    const myRosterEntries = rosters[myTeamId] || []
    const isSP = (entry: typeof myRosterEntries[0]) =>
      entry.player?.defaultPositionId === 1 ||
      entry.player?.eligibleSlots?.includes(14)

    const spNames = myRosterEntries
      .filter(isSP)
      .map((entry) => entry.player?.fullName || '')
      .filter(Boolean)

    // Get opponent SP names from their roster
    const oppRosterEntries = rosters[theirSide.teamId] || []
    const oppSpNames = oppRosterEntries
      .filter(isSP)
      .map((entry) => entry.player?.fullName || '')
      .filter(Boolean)

    // Build pitcher → MLB team mapping from ESPN proTeamId
    const pitcherTeams: Record<string, string> = {}
    for (const entry of [...myRosterEntries, ...oppRosterEntries]) {
      if (isSP(entry) && entry.player?.fullName && entry.player?.proTeamId) {
        const team = ESPN_TEAM_MAP[entry.player.proTeamId]
        if (team) pitcherTeams[entry.player.fullName] = team
      }
    }

    // Collect all rostered player names across the league for streamer filtering
    const allRosteredNames: string[] = []
    for (const teamRoster of Object.values(rosters)) {
      for (const entry of teamRoster) {
        if (entry.player?.fullName) {
          allRosteredNames.push(entry.player.fullName)
        }
      }
    }

    // Get opponent team name
    const teams = await ESPNApi.getTeams(league.externalId, season, espnSettings)
    const opponentTeam = teams.find((t) => t.id === theirSide.teamId)
    const opponentName = opponentTeam
      ? [opponentTeam.location, opponentTeam.nickname].filter(Boolean).join(' ')
      : `Team ${theirSide.teamId}`

    const today = new Date()
    // Use local timezone for date strings (toISOString() is UTC and shifts dates in US evenings)
    const todayStr = toLocalDateStr(today)

    // Use hardcoded league schedule (same as matchup page)
    const { endDate, daysRemaining } = getMatchupDateRange(matchupPeriod, today)
    const endDateStr = endDate

    // Streaming targets tomorrow (waiver claims process overnight)
    const tomorrow = new Date(today.getFullYear(), today.getMonth(), today.getDate() + 1)
    const tomorrowStr = toLocalDateStr(tomorrow)
    // If tomorrow is in a different matchup period, use that period's end date
    const streamingEndDate = getMatchupEndDateForDate(tomorrowStr) || endDateStr

    // Fetch team schedule for the matchup period. This tells us which MLB
    // teams play on which dates — used to validate PitcherList start predictions
    // against the real schedule (replaces MLB probables which only worked 1-2 days out).
    let teamGamesByDate: Record<string, string[]> | null = null
    try {
      teamGamesByDate = await getTeamScheduleByDate(todayStr, endDateStr)
    } catch (e) {
      console.warn('Failed to fetch team schedule, PitcherList entries will not be validated:', e)
    }

    // Call Python backend
    const backendResponse = await fetch(`${BACKEND_URL}/api/start-sit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        roster_pitcher_names: spNames,
        opponent_pitcher_names: oppSpNames,
        matchup_categories: matchupCategories,
        team_ip: teamIp,
        days_remaining: daysRemaining,
        opponent_name: opponentName,
        today_date: todayStr,
        matchup_end_date: endDateStr,
        all_rostered_names: allRosteredNames,
        streaming_target_date: tomorrowStr,
        streaming_end_date: streamingEndDate,
        pitcher_teams: pitcherTeams,
        team_games_by_date: teamGamesByDate,
      }),
    })

    if (!backendResponse.ok) {
      const errorText = await backendResponse.text()
      console.error('Backend error:', errorText)
      return NextResponse.json(
        { error: `Backend error: ${backendResponse.status}` },
        { status: 502 },
      )
    }

    const result = await backendResponse.json()
    return NextResponse.json(result)
  } catch (error: any) {
    console.error('Start/sit error:', error)
    return NextResponse.json(
      { error: error.message || 'Failed to compute recommendations' },
      { status: 500 },
    )
  }
}
