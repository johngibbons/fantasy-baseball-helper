// src/app/api/playoff-odds/route.ts
import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { ESPNApi } from '@/lib/espn-api'
import { MATCHUP_SCHEDULE } from '@/lib/matchup-schedule'
import { buildPlayoffOddsPayload } from '@/lib/playoff-odds-payload'

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000'

export async function POST(request: NextRequest) {
  try {
    const body = await request.json()
    const {
      leagueId,
      season = '2026',
      playoffSlots = 6,
      nTrials = 5000,
      seed,
    } = body

    if (!leagueId) {
      return NextResponse.json(
        { error: 'Missing required field: leagueId' },
        { status: 400 },
      )
    }

    const league = await prisma.league.findUnique({ where: { id: leagueId } })
    if (!league) {
      return NextResponse.json({ error: 'League not found' }, { status: 404 })
    }
    const settingsBlob = league.settings as any
    const credentials = settingsBlob?.credentials
    if (!credentials?.swid || !credentials?.espn_s2) {
      return NextResponse.json(
        { error: 'ESPN credentials not configured. Set them up in Settings.' },
        { status: 400 },
      )
    }
    const espnSettings = { swid: credentials.swid, espn_s2: credentials.espn_s2 }

    const [leagueData, teamsAndFaab, rosters, fullSchedule] = await Promise.all([
      ESPNApi.getLeague(league.externalId, season, espnSettings),
      ESPNApi.getLeagueTeamsAndFaab(league.externalId, season, espnSettings),
      ESPNApi.getRosters(league.externalId, season, espnSettings),
      ESPNApi.getFullSchedule(league.externalId, season, espnSettings),
    ])

    const currentMatchupPeriod = leagueData.status?.currentMatchupPeriod
      || leagueData.currentMatchupPeriod
      || 1
    // Pull regular-season length from settings (matchupPeriodCount).
    const finalRegularSeasonPeriod =
      (leagueData as any).settings?.scheduleSettings?.matchupPeriodCount
      ?? settingsBlob?.scheduleSettings?.matchupPeriodCount
      ?? 18

    const payload = buildPlayoffOddsPayload({
      season: parseInt(season),
      currentMatchupPeriod,
      finalRegularSeasonPeriod,
      teams: teamsAndFaab.teams,
      rosters,
      fullSchedule,
      matchupSchedule: MATCHUP_SCHEDULE,
      playoffSlots,
      nTrials,
      seed,
    })

    const backendResponse = await fetch(`${BACKEND_URL}/api/playoff-odds`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (!backendResponse.ok) {
      const errorText = await backendResponse.text()
      console.error('Playoff-odds backend error:', errorText)
      return NextResponse.json(
        { error: `Backend error: ${backendResponse.status}` },
        { status: 502 },
      )
    }
    const result = await backendResponse.json()
    return NextResponse.json({
      ...result,
      meta: {
        current_matchup_period: currentMatchupPeriod,
        final_regular_season_period: finalRegularSeasonPeriod,
        playoff_slots: playoffSlots,
        n_trials: nTrials,
      },
    })
  } catch (error: any) {
    console.error('Playoff odds error:', error)
    return NextResponse.json(
      { error: error.message || 'Failed to compute playoff odds' },
      { status: 500 },
    )
  }
}
