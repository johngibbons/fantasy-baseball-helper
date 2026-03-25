import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { ESPNApi, ESPNRosterEntry } from '@/lib/espn-api'

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000'

const posMap: Record<number, string> = {
  1: 'SP', 2: 'C', 3: '1B', 4: '2B', 5: '3B',
  6: 'SS', 7: 'LF', 8: 'CF', 9: 'RF', 10: 'DH',
  11: 'RP',
}

function espnPlayerType(defaultPositionId: number | undefined): string {
  return defaultPositionId === 1 || defaultPositionId === 11 ? 'pitcher' : 'hitter'
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json()
    const {
      leagueId, teamId,
      season = '2026',
      max_trade_size = 2,
      fairness_threshold = 0.5,
      include_draft_picks = false,
      max_tradeable_per_team = 15,
    } = body

    if (!leagueId || !teamId) {
      return NextResponse.json(
        { error: 'Missing required fields: leagueId, teamId' },
        { status: 400 },
      )
    }

    const league = await prisma.league.findUnique({
      where: { id: leagueId },
    })

    if (!league) {
      return NextResponse.json({ error: 'League not found' }, { status: 404 })
    }

    const leagueSettings = league.settings as any
    const credentials = leagueSettings?.credentials
    if (!credentials?.swid || !credentials?.espn_s2) {
      return NextResponse.json(
        { error: 'ESPN credentials not configured. Set them up in Settings.' },
        { status: 400 },
      )
    }

    const settings = { swid: credentials.swid, espn_s2: credentials.espn_s2 }

    // Fetch rosters and team names from ESPN in parallel
    const [rosters, teams] = await Promise.all([
      ESPNApi.getRosters(league.externalId, season, settings),
      ESPNApi.getTeams(league.externalId, season, settings),
    ])

    const myTeamId = parseInt(teamId)

    // Build team name lookup
    const teamNames: Record<number, string> = {}
    for (const t of teams) {
      teamNames[t.id] = [t.location, t.nickname].filter(Boolean).join(' ') || t.abbrev || `Team ${t.id}`
    }

    // Build my roster
    const myRosterEntries = rosters[myTeamId] || []
    const myRoster = myRosterEntries.map((entry: ESPNRosterEntry) => ({
      name: entry.player?.fullName || `Player ${entry.playerId}`,
      lineup_slot_id: entry.lineupSlotId,
      player_type: espnPlayerType(entry.player?.defaultPositionId),
    }))

    // Build all team rosters (including mine, with team_id and team_name)
    const allTeamRosters: Array<{
      team_id: number
      team_name: string
      players: Array<{ name: string; lineup_slot_id: number; player_type: string }>
    }> = []
    let myTeamIndex = -1

    // Sort team IDs for consistent ordering
    const teamIds = Object.keys(rosters).map(Number).sort((a, b) => a - b)

    for (const tid of teamIds) {
      if (tid === myTeamId) {
        myTeamIndex = allTeamRosters.length
      }
      const entries = rosters[tid]
      allTeamRosters.push({
        team_id: tid,
        team_name: teamNames[tid] || `Team ${tid}`,
        players: entries.map((entry: ESPNRosterEntry) => ({
          name: entry.player?.fullName || `Player ${entry.playerId}`,
          lineup_slot_id: entry.lineupSlotId,
          player_type: espnPlayerType(entry.player?.defaultPositionId),
        })),
      })
    }

    if (myTeamIndex < 0) {
      return NextResponse.json(
        { error: `Team ${myTeamId} not found in rosters` },
        { status: 400 },
      )
    }

    // Call Python backend
    const backendResponse = await fetch(`${BACKEND_URL}/api/trades/suggestions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        my_roster: myRoster,
        all_team_rosters: allTeamRosters,
        my_team_index: myTeamIndex,
        season: parseInt(season),
        max_trade_size,
        fairness_threshold,
        include_draft_picks,
        max_tradeable_per_team,
      }),
    })

    if (!backendResponse.ok) {
      const errorText = await backendResponse.text()
      console.error('Backend error:', errorText)
      let detail = `Backend error: ${backendResponse.status}`
      try {
        const parsed = JSON.parse(errorText)
        if (parsed.detail) detail = parsed.detail
      } catch {}
      return NextResponse.json({ error: detail }, { status: 502 })
    }

    const result = await backendResponse.json()

    return NextResponse.json({
      ...result,
      team_names: teamNames,
      my_team_id: myTeamId,
      my_team_name: teamNames[myTeamId] || `Team ${myTeamId}`,
    })
  } catch (error: any) {
    console.error('Trade suggestions error:', error)
    return NextResponse.json(
      { error: error.message || 'Failed to compute trade suggestions' },
      { status: 500 },
    )
  }
}
