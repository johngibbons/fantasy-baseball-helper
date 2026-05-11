import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { ESPNApi, ESPNRosterEntry } from '@/lib/espn-api'

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000'

function espnPlayerType(defaultPositionId?: number): string {
  return defaultPositionId === 1 || defaultPositionId === 11 ? 'pitcher' : 'hitter'
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json()
    const { leagueId, teamId, season = '2026' } = body
    if (!leagueId || !teamId) {
      return NextResponse.json({ error: 'Missing leagueId/teamId' }, { status: 400 })
    }
    const league = await prisma.league.findUnique({ where: { id: leagueId } })
    if (!league) {
      return NextResponse.json({ error: 'League not found' }, { status: 404 })
    }
    const settings = (league.settings as any)?.credentials
    if (!settings?.swid || !settings?.espn_s2) {
      return NextResponse.json({ error: 'No ESPN credentials' }, { status: 400 })
    }
    const rosters = await ESPNApi.getRosters(league.externalId, season, settings)
    const myRoster = (rosters[parseInt(teamId)] || []).map((e: ESPNRosterEntry) => ({
      name: e.player?.fullName || `Player ${e.playerId}`,
      player_type: espnPlayerType(e.player?.defaultPositionId),
    }))
    const resp = await fetch(`${BACKEND_URL}/api/waivers/roster-health`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ my_roster: myRoster, season: parseInt(season) }),
    })
    if (!resp.ok) {
      const text = await resp.text()
      return NextResponse.json({ error: `Backend error: ${resp.status} ${text}` }, { status: 502 })
    }
    return NextResponse.json(await resp.json())
  } catch (e: any) {
    return NextResponse.json({ error: e.message }, { status: 500 })
  }
}
