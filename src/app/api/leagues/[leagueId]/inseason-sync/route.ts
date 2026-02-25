import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { ESPNApi } from '@/lib/espn-api'

const FASTAPI_BASE = process.env.FASTAPI_URL || 'http://localhost:8000'

/**
 * In-season sync pipeline:
 * 1. Fetch ESPN data (matchups, ownership, standings) -> write to SQLite
 * 2. Call FastAPI /api/inseason/sync to fetch FanGraphs ROS projections + recalculate rankings
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ leagueId: string }> }
) {
  try {
    const { leagueId } = await params
    const body = await request.json()
    const { swid, espn_s2, season = '2026', my_team_id } = body

    // Get the league from database
    const league = await prisma.league.findUnique({
      where: { id: leagueId },
    })

    if (!league) {
      return NextResponse.json({ error: 'League not found' }, { status: 404 })
    }

    if (!swid || !espn_s2) {
      return NextResponse.json(
        { error: 'ESPN credentials (swid and espn_s2) are required' },
        { status: 400 }
      )
    }

    const settings = { swid, espn_s2 }
    const espnSeason = season.toString()
    const leagueExternalId = league.externalId

    console.log(`In-season sync for league ${leagueExternalId}, season ${espnSeason}`)

    // Step 1: Fetch ESPN league info for current matchup period
    let currentMatchupPeriod = 1
    try {
      const leagueData = await ESPNApi.getLeague(leagueExternalId, espnSeason, settings)
      currentMatchupPeriod =
        leagueData.status?.currentMatchupPeriod ||
        leagueData.currentMatchupPeriod ||
        1
    } catch (e) {
      console.warn('Could not fetch league info for matchup period:', e)
    }

    // Step 2: Fetch matchup scores for current period
    let matchupCount = 0
    try {
      const matchups = await ESPNApi.getMatchupScores(
        leagueExternalId,
        espnSeason,
        currentMatchupPeriod,
        settings
      )

      // Store matchups in FastAPI backend via direct fetch
      for (const m of matchups) {
        if (!m.home?.teamId || !m.away?.teamId) continue
        const matchupData = {
          league_external_id: leagueExternalId,
          season: parseInt(espnSeason),
          matchup_period: currentMatchupPeriod,
          home_team_id: m.home.teamId,
          away_team_id: m.away.teamId,
          home_scores: m.home.categoryScores,
          away_scores: m.away.categoryScores,
        }
        try {
          await fetch(`${FASTAPI_BASE}/api/inseason/store-matchup`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(matchupData),
          })
          matchupCount++
        } catch {
          // Store directly if endpoint not available yet
          console.warn('Could not store matchup via FastAPI')
        }
      }
    } catch (e) {
      console.warn('Could not fetch matchup scores:', e)
    }

    // Step 3: Fetch rosters to determine ownership
    let ownershipCount = 0
    try {
      const rosters = await ESPNApi.getRosters(leagueExternalId, espnSeason, settings)
      // Store ownership data
      for (const [teamIdStr, entries] of Object.entries(rosters)) {
        const teamId = parseInt(teamIdStr)
        for (const entry of entries) {
          if (!entry.player) continue
          const ownershipData = {
            espn_player_id: entry.player.id,
            league_external_id: leagueExternalId,
            season: parseInt(espnSeason),
            owner_team_id: teamId,
            roster_status: 'ROSTERED',
            lineup_slot: entry.lineupSlotId?.toString(),
          }
          try {
            await fetch(`${FASTAPI_BASE}/api/inseason/store-ownership`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(ownershipData),
            })
            ownershipCount++
          } catch {
            // Non-fatal
          }
        }
      }
    } catch (e) {
      console.warn('Could not fetch roster/ownership data:', e)
    }

    // Step 4: Fetch standings
    let standingsCount = 0
    try {
      const standings = await ESPNApi.getStandings(leagueExternalId, espnSeason, settings)
      for (const team of standings) {
        const standingsData = {
          league_external_id: leagueExternalId,
          season: parseInt(espnSeason),
          team_id: team.teamId,
          category_values: team.categoryValues,
        }
        try {
          await fetch(`${FASTAPI_BASE}/api/inseason/store-standings`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(standingsData),
          })
          standingsCount++
        } catch {
          // Non-fatal
        }
      }
    } catch (e) {
      console.warn('Could not fetch standings:', e)
    }

    // Step 5: Trigger FastAPI to fetch ROS projections and recalculate rankings
    let syncResult = null
    try {
      const syncResp = await fetch(
        `${FASTAPI_BASE}/api/inseason/sync?season=${espnSeason}`,
        { method: 'POST' }
      )
      if (syncResp.ok) {
        syncResult = await syncResp.json()
      }
    } catch (e) {
      console.warn('FastAPI inseason sync failed:', e)
    }

    return NextResponse.json({
      success: true,
      message: 'In-season sync complete',
      currentMatchupPeriod,
      matchupCount,
      ownershipCount,
      standingsCount,
      syncResult,
    })
  } catch (error) {
    console.error('Error in inseason-sync:', error)
    return NextResponse.json(
      { error: error instanceof Error ? error.message : 'Failed to sync' },
      { status: 500 }
    )
  }
}
