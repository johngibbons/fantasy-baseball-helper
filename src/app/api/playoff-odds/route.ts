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

    const fetches = await Promise.allSettled([
      ESPNApi.getLeague(league.externalId, season, espnSettings),
      ESPNApi.getLeagueTeamsAndFaab(league.externalId, season, espnSettings),
      ESPNApi.getRosters(league.externalId, season, espnSettings),
      ESPNApi.getFullSchedule(league.externalId, season, espnSettings),
      ESPNApi.getMatchupHistory(league.externalId, season, espnSettings),
    ])

    // Required fetches (the first four) — bail if any failed
    const [leagueRes, teamsRes, rostersRes, fullScheduleRes, historyRes] = fetches
    if (leagueRes.status !== 'fulfilled' || teamsRes.status !== 'fulfilled'
        || rostersRes.status !== 'fulfilled' || fullScheduleRes.status !== 'fulfilled') {
      const failed = [leagueRes, teamsRes, rostersRes, fullScheduleRes]
        .find(r => r.status === 'rejected') as PromiseRejectedResult | undefined
      throw failed?.reason ?? new Error('Failed to fetch ESPN league data')
    }
    const leagueData = leagueRes.value
    const teamsAndFaab = teamsRes.value
    const rosters = rostersRes.value
    const fullSchedule = fullScheduleRes.value

    // Optional fetch — degrade gracefully if it fails
    let observedHistory: Awaited<ReturnType<typeof ESPNApi.getMatchupHistory>> = []
    let historyFetchOk = true
    if (historyRes.status === 'fulfilled') {
      observedHistory = historyRes.value
    } else {
      historyFetchOk = false
      console.warn('Playoff-odds: matchup history fetch failed, proceeding without shrinkage:', historyRes.reason)
    }

    const currentMatchupPeriod = leagueData.status?.currentMatchupPeriod
      || leagueData.currentMatchupPeriod
      || 1
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
      observedHistory,
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
      // If our TS-side fetch failed, override the backend's shrinkage_applied=true
      // anyway. If it succeeded but backend reports false (e.g. zero observations),
      // pass that through.
      shrinkage_applied: historyFetchOk && (result.shrinkage_applied ?? false),
      meta: {
        current_matchup_period: currentMatchupPeriod,
        final_regular_season_period: finalRegularSeasonPeriod,
        playoff_slots: playoffSlots,
        n_trials: nTrials,
        shrinkage_applied: historyFetchOk && (result.shrinkage_applied ?? false),
        completed_periods_observed: result.completed_periods_observed ?? 0,
        history_fetch_ok: historyFetchOk,
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
