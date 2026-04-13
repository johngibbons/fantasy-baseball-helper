import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { ESPNApi } from '@/lib/espn-api'
import { MATCHUP_SCHEDULE } from '@/lib/matchup-schedule'

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000'

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
    const currentMatchupPeriod = leagueData.status?.currentMatchupPeriod
      || leagueData.currentMatchupPeriod
      || 1
    const nextMatchupPeriod = currentMatchupPeriod + 1

    // Look up next week's dates
    const nextSchedule = MATCHUP_SCHEDULE[nextMatchupPeriod]
    if (!nextSchedule) {
      return NextResponse.json(
        { error: `No schedule found for matchup period ${nextMatchupPeriod}` },
        { status: 400 },
      )
    }
    const [startDate, endDate] = nextSchedule

    // Fetch rosters and next period's scoreboard in parallel
    const [rosters, scoreboard, teams] = await Promise.all([
      ESPNApi.getRosters(league.externalId, season, espnSettings),
      ESPNApi.getMatchupScoreboard(league.externalId, season, espnSettings, nextMatchupPeriod),
      ESPNApi.getTeams(league.externalId, season, espnSettings),
    ])

    const myTeamId = parseInt(teamId)

    // Find next week's matchup
    const myMatchup = scoreboard.schedule.find(
      (m) => m.home.teamId === myTeamId || m.away.teamId === myTeamId
    )

    if (!myMatchup) {
      return NextResponse.json(
        { error: 'Could not find your matchup for next week' },
        { status: 404 },
      )
    }

    const isHome = myMatchup.home.teamId === myTeamId
    const theirSide = isHome ? myMatchup.away : myMatchup.home

    // Get opponent team name
    const opponentTeam = teams.find((t) => t.id === theirSide.teamId)
    const opponentName = opponentTeam
      ? [opponentTeam.location, opponentTeam.nickname].filter(Boolean).join(' ')
      : `Team ${theirSide.teamId}`

    // Get SP names from my roster
    const myRosterEntries = rosters[myTeamId] || []
    const spNames = myRosterEntries
      .filter((entry) =>
        entry.player?.defaultPositionId === 1 ||
        entry.player?.eligibleSlots?.includes(14)
      )
      .map((entry) => entry.player?.fullName || '')
      .filter(Boolean)

    // Get opponent SP names
    const oppRosterEntries = rosters[theirSide.teamId] || []
    const oppSpNames = oppRosterEntries
      .filter((entry) =>
        entry.player?.defaultPositionId === 1 ||
        entry.player?.eligibleSlots?.includes(14)
      )
      .map((entry) => entry.player?.fullName || '')
      .filter(Boolean)

    // Collect all rostered player names for streamer filtering
    const allRosteredNames: string[] = []
    for (const teamRoster of Object.values(rosters)) {
      for (const entry of teamRoster) {
        if (entry.player?.fullName) {
          allRosteredNames.push(entry.player.fullName)
        }
      }
    }

    // Call Python backend
    const backendResponse = await fetch(`${BACKEND_URL}/api/start-sit/preview`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        roster_pitcher_names: spNames,
        opponent_pitcher_names: oppSpNames,
        start_date: startDate,
        end_date: endDate,
        all_rostered_names: allRosteredNames,
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
    return NextResponse.json({
      ...result,
      opponent_name: opponentName,
      start_date: startDate,
      end_date: endDate,
      matchup_period: nextMatchupPeriod,
    })
  } catch (error: any) {
    console.error('Start/sit preview error:', error)
    return NextResponse.json(
      { error: error.message || 'Failed to compute next week preview' },
      { status: 500 },
    )
  }
}
