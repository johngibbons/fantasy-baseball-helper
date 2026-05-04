import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { ESPNApi, ESPNRosterEntry } from '@/lib/espn-api'

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000'

// ESPN defaultPositionId to readable name (single primary position)
const posMap: Record<number, string> = {
  1: 'SP', 2: 'C', 3: '1B', 4: '2B', 5: '3B',
  6: 'SS', 7: 'LF', 8: 'CF', 9: 'RF', 10: 'DH',
  11: 'RP',
}

// ESPN eligibleSlots ID -> position abbreviation (full eligibility list)
// Mirror of SLOT_TO_POS in fetch_espn_eligibility.py
const slotToPos: Record<number, string> = {
  0: 'C', 1: '1B', 2: '2B', 3: '3B', 4: 'SS',
  5: 'OF', 8: 'OF', 9: 'OF', 10: 'OF',
  11: 'DH', 14: 'SP', 15: 'RP',
}
const POS_ORDER = ['C', '1B', '2B', '3B', 'SS', 'OF', 'SP', 'RP', 'DH']

function eligiblePositionsFromSlots(eligibleSlots: number[] | undefined, fallbackId: number | undefined): string {
  if (eligibleSlots && eligibleSlots.length > 0) {
    const seen = new Set<string>()
    for (const s of eligibleSlots) {
      const pos = slotToPos[s]
      if (pos) seen.add(pos)
    }
    if (seen.size > 0) return POS_ORDER.filter((p) => seen.has(p)).join('/')
  }
  return posMap[fallbackId ?? 0] || 'UTIL'
}

// ESPN lineupSlotId to display slot name
const slotMap: Record<number, string> = {
  0: 'C', 1: '1B', 2: '2B', 3: '3B', 4: 'SS',
  5: 'OF', 6: 'OF', 7: 'OF', 12: 'UTIL',
  13: 'P', 14: 'SP', 15: 'RP',
  16: 'BE', 17: 'IL',
}

// ESPN defaultPositionId -> player type for backend disambiguation
function espnPlayerType(defaultPositionId: number | undefined): string {
  return defaultPositionId === 1 || defaultPositionId === 11 ? 'pitcher' : 'hitter'
}

// Max non-IL roster size (C+1B+2B+3B+SS+3OF+2UTIL+3SP+2RP+2P+8BE = 25)
const MAX_ROSTER_SIZE = 25

export async function POST(request: NextRequest) {
  try {
    const body = await request.json()
    const {
      leagueId,
      teamId,
      season = '2026',
      excludeStreamSlot = true,
      includeCrossType = false,
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

    // Fetch all data from ESPN in parallel
    const [rosters, freeAgents, teamsAndFaab] = await Promise.all([
      ESPNApi.getRosters(league.externalId, season, settings),
      ESPNApi.getFreeAgents(league.externalId, season, settings),
      ESPNApi.getLeagueTeamsAndFaab(league.externalId, season, settings),
    ])

    const myTeamId = parseInt(teamId)
    const remainingFaab = teamsAndFaab.faabByTeamId[myTeamId] ?? 100

    // Build my roster with position info for UI
    const myRosterEntries = rosters[myTeamId] || []
    const myRoster = myRosterEntries.map((entry: ESPNRosterEntry) => ({
      name: entry.player?.fullName || `Player ${entry.playerId}`,
      lineup_slot_id: entry.lineupSlotId,
      player_type: espnPlayerType(entry.player?.defaultPositionId),
    }))
    const myRosterDisplay = myRosterEntries.map((entry: ESPNRosterEntry) => ({
      name: entry.player?.fullName || `Player ${entry.playerId}`,
      position: eligiblePositionsFromSlots(entry.player?.eligibleSlots, entry.player?.defaultPositionId),
      slot: slotMap[entry.lineupSlotId] || 'BE',
      lineup_slot_id: entry.lineupSlotId,
    }))

    // Calculate open roster slots (IL players free up regular roster spots)
    const ilCount = myRosterEntries.filter((e: ESPNRosterEntry) => e.lineupSlotId >= 17).length
    const nonIlCount = myRosterEntries.length - ilCount
    const openRosterSlots = Math.max(0, MAX_ROSTER_SIZE - nonIlCount)

    // Build other teams' rosters
    const otherTeamRosters = Object.entries(rosters)
      .filter(([tid]) => parseInt(tid) !== myTeamId)
      .map(([, entries]) => ({
        players: entries.map((entry: ESPNRosterEntry) => ({
          name: entry.player?.fullName || `Player ${entry.playerId}`,
          lineup_slot_id: entry.lineupSlotId,
          player_type: espnPlayerType(entry.player?.defaultPositionId),
        })),
      }))

    // Build free agents list
    const faList = freeAgents.map((p) => ({
      name: p.fullName,
      lineup_slot_id: 0,
      player_type: espnPlayerType(p.defaultPositionId),
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
        open_roster_slots: openRosterSlots,
        exclude_stream_slot: excludeStreamSlot,
        include_cross_type: includeCrossType,
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
    const nameToMlbId: Record<string, number> = recommendations.name_to_mlb_id || {}

    // Merge mlb_ids into roster display for player detail links
    const rosterWithIds = myRosterDisplay.map((p: any) => ({
      ...p,
      mlb_id: nameToMlbId[p.name] || null,
    }))

    return NextResponse.json({
      ...recommendations,
      remaining_faab: remainingFaab,
      my_roster_count: myRoster.length,
      free_agent_count: faList.length,
      other_teams_count: otherTeamRosters.length,
      open_roster_slots: openRosterSlots,
      my_roster_display: rosterWithIds,
    })
  } catch (error: any) {
    console.error('Waiver recommendations error:', error)
    return NextResponse.json(
      { error: error.message || 'Failed to compute recommendations' },
      { status: 500 },
    )
  }
}
