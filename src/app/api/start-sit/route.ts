import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { ESPNApi } from '@/lib/espn-api'
import { getMatchupDateRange } from '@/lib/matchup-schedule'

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000'

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

    // Get SP names from roster (defaultPositionId 1 = SP)
    const myRosterEntries = rosters[myTeamId] || []
    const spNames = myRosterEntries
      .filter((entry) => entry.player?.defaultPositionId === 1)
      .map((entry) => entry.player?.fullName || '')
      .filter(Boolean)

    // Get opponent team name
    const teams = await ESPNApi.getTeams(league.externalId, season, espnSettings)
    const opponentTeam = teams.find((t) => t.id === theirSide.teamId)
    const opponentName = opponentTeam
      ? [opponentTeam.location, opponentTeam.nickname].filter(Boolean).join(' ')
      : `Team ${theirSide.teamId}`

    const today = new Date()
    const todayStr = today.toISOString().split('T')[0]

    // Use hardcoded league schedule (same as matchup page)
    const { endDate, daysRemaining } = getMatchupDateRange(matchupPeriod, today)
    const endDateStr = endDate

    // Call Python backend
    const backendResponse = await fetch(`${BACKEND_URL}/api/start-sit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        roster_pitcher_names: spNames,
        matchup_categories: matchupCategories,
        team_ip: teamIp,
        days_remaining: daysRemaining,
        opponent_name: opponentName,
        today_date: todayStr,
        matchup_end_date: endDateStr,
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
