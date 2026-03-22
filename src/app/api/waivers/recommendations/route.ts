import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { ESPNApi, ESPNRosterEntry } from '@/lib/espn-api'

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000'

// ESPN position ID to readable name
const posMap: Record<number, string> = {
  0: 'C', 1: '1B', 2: '2B', 3: '3B', 4: 'SS',
  5: 'LF', 6: 'CF', 7: 'RF', 8: 'DH',
  9: 'SP', 10: 'RP', 11: 'P',
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json()
    const { leagueId, teamId, swid, espn_s2, season = '2026' } = body

    if (!leagueId || !teamId || !swid || !espn_s2) {
      return NextResponse.json(
        { error: 'Missing required fields: leagueId, teamId, swid, espn_s2' },
        { status: 400 },
      )
    }

    const league = await prisma.league.findUnique({
      where: { id: leagueId },
    })

    if (!league) {
      return NextResponse.json({ error: 'League not found' }, { status: 404 })
    }

    const settings = { swid, espn_s2 }

    // Fetch all data from ESPN in parallel
    const [rosters, freeAgents, teamsAndFaab] = await Promise.all([
      ESPNApi.getRosters(league.externalId, season, settings),
      ESPNApi.getFreeAgents(league.externalId, season, settings),
      ESPNApi.getLeagueTeamsAndFaab(league.externalId, season, settings),
    ])

    const myTeamId = parseInt(teamId)
    const remainingFaab = teamsAndFaab.faabByTeamId[myTeamId] ?? 100

    // Build my roster
    const myRoster = (rosters[myTeamId] || []).map((entry: ESPNRosterEntry) => ({
      name: entry.player?.fullName || `Player ${entry.playerId}`,
      lineup_slot_id: entry.lineupSlotId,
    }))

    // Build other teams' rosters
    const otherTeamRosters = Object.entries(rosters)
      .filter(([tid]) => parseInt(tid) !== myTeamId)
      .map(([, entries]) => ({
        players: entries.map((entry: ESPNRosterEntry) => ({
          name: entry.player?.fullName || `Player ${entry.playerId}`,
          lineup_slot_id: entry.lineupSlotId,
        })),
      }))

    // Build free agents list
    const faList = freeAgents.map((p) => ({
      name: p.fullName,
      lineup_slot_id: 0,
    }))

    // Call Python backend for recommendations
    const backendResponse = await fetch(`${BACKEND_URL}/api/waivers/recommendations`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        my_roster: myRoster,
        other_team_rosters: otherTeamRosters,
        free_agents: faList,
        remaining_faab: remainingFaab,
        season: parseInt(season),
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
      return NextResponse.json(
        { error: detail },
        { status: 502 },
      )
    }

    const recommendations = await backendResponse.json()
    return NextResponse.json({
      ...recommendations,
      remaining_faab: remainingFaab,
      my_roster_count: myRoster.length,
      free_agent_count: faList.length,
      other_teams_count: otherTeamRosters.length,
      roster_names_debug: myRoster.slice(0, 5).map((r: any) => r.name),
    })
  } catch (error: any) {
    console.error('Waiver recommendations error:', error)
    return NextResponse.json(
      { error: error.message || 'Failed to compute recommendations' },
      { status: 500 },
    )
  }
}
