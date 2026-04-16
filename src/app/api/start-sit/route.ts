import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { ESPNApi } from '@/lib/espn-api'
import { getMatchupDateRange, getMatchupEndDateForDate } from '@/lib/matchup-schedule'
import { getProbablePitchers } from '@/lib/mlb-schedule'

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

    // Get SP names from roster — include players eligible for SP slot (14),
    // not just defaultPositionId 1, to catch RP/SP dual-eligible pitchers
    const myRosterEntries = rosters[myTeamId] || []
    const spNames = myRosterEntries
      .filter((entry) =>
        entry.player?.defaultPositionId === 1 ||
        entry.player?.eligibleSlots?.includes(14)
      )
      .map((entry) => entry.player?.fullName || '')
      .filter(Boolean)

    // Get opponent SP names from their roster
    const oppRosterEntries = rosters[theirSide.teamId] || []
    const oppSpNames = oppRosterEntries
      .filter((entry) =>
        entry.player?.defaultPositionId === 1 ||
        entry.player?.eligibleSlots?.includes(14)
      )
      .map((entry) => entry.player?.fullName || '')
      .filter(Boolean)

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
    const todayStr = today.toISOString().split('T')[0]

    // Use hardcoded league schedule (same as matchup page)
    const { endDate, daysRemaining } = getMatchupDateRange(matchupPeriod, today)
    const endDateStr = endDate

    // Streaming targets tomorrow (waiver claims process overnight)
    const tomorrow = new Date(today)
    tomorrow.setDate(today.getDate() + 1)
    const tomorrowStr = tomorrow.toISOString().split('T')[0]
    // If tomorrow is in a different matchup period, use that period's end date
    const streamingEndDate = getMatchupEndDateForDate(tomorrowStr) || endDateStr

    // Fetch MLB probable pitchers for the entire matchup period. MLB is the
    // source of truth for both "starts today" and "more this matchup" counts;
    // PitcherList entries that aren't confirmed by MLB are filtered out.
    let mlbProbablesByDate: Record<string, string[]> | null = null
    try {
      const probables = await getProbablePitchers(todayStr, endDateStr)
      mlbProbablesByDate = {}
      const cursor = new Date(`${todayStr}T00:00:00Z`)
      const end = new Date(`${endDateStr}T00:00:00Z`)
      while (cursor <= end) {
        mlbProbablesByDate[cursor.toISOString().split('T')[0]] = []
        cursor.setUTCDate(cursor.getUTCDate() + 1)
      }
      for (const p of probables) {
        if (!p.fullName) continue
        if (!mlbProbablesByDate[p.date]) mlbProbablesByDate[p.date] = []
        mlbProbablesByDate[p.date].push(p.fullName)
      }
    } catch (e) {
      console.warn('Failed to fetch MLB probable pitchers, falling back to PitcherList only:', e)
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
        mlb_probables_by_date: mlbProbablesByDate,
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
