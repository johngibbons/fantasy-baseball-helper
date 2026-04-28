// src/app/api/performance/route.ts

import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { ESPNApi } from '@/lib/espn-api'
import { toLocalDateStr } from '@/lib/matchup-schedule'

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000'

// MLB regular season runs from opening day through the last day of regular play.
// 2026: opening day 2026-03-25; regular season ends 2026-09-27 (≈186 days).
const SEASON_START = '2026-03-25'
const SEASON_END = '2026-09-27'

function dayDiff(a: string, b: string): number {
  const ad = new Date(`${a}T00:00:00`)
  const bd = new Date(`${b}T00:00:00`)
  return Math.round((bd.getTime() - ad.getTime()) / (1000 * 60 * 60 * 24))
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json().catch(() => ({}))
    const season = body.season ?? 2026
    const leagueId: string | undefined = body.leagueId
    const teamId: string | number | undefined = body.teamId

    const todayStr = toLocalDateStr(new Date())
    const seasonDays = dayDiff(SEASON_START, SEASON_END) // ~186
    let elapsedDays = dayDiff(SEASON_START, todayStr)
    if (elapsedDays < 0) elapsedDays = 0
    if (elapsedDays > seasonDays) elapsedDays = seasonDays
    const seasonElapsedFraction = seasonDays > 0 ? elapsedDays / seasonDays : 0

    // Fetch hitters + pitchers in parallel
    const [hittersResp, pitchersResp] = await Promise.all([
      fetch(`${BACKEND_URL}/api/performance`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          season,
          player_type: 'hitter',
          season_elapsed_fraction: seasonElapsedFraction,
        }),
      }),
      fetch(`${BACKEND_URL}/api/performance`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          season,
          player_type: 'pitcher',
          season_elapsed_fraction: seasonElapsedFraction,
        }),
      }),
    ])

    if (!hittersResp.ok || !pitchersResp.ok) {
      const detail = !hittersResp.ok ? await hittersResp.text() : await pitchersResp.text()
      console.error('Performance backend error:', detail)
      return NextResponse.json({ error: `Backend error` }, { status: 502 })
    }

    const [hittersJson, pitchersJson] = await Promise.all([
      hittersResp.json(),
      pitchersResp.json(),
    ])

    // Optionally resolve "my team" set of mlb_ids by matching ESPN roster names to DB.
    let myTeamMlbIds: number[] = []
    if (leagueId && teamId !== undefined) {
      try {
        const league = await prisma.league.findUnique({ where: { id: leagueId } })
        const credentials = (league?.settings as any)?.credentials
        if (league && credentials?.swid && credentials?.espn_s2) {
          const espnSettings = { swid: credentials.swid, espn_s2: credentials.espn_s2 }
          const rosters = await ESPNApi.getRosters(
            league.externalId,
            String(season),
            espnSettings,
          )
          const myTeamId = parseInt(String(teamId))
          const entries = rosters[myTeamId] || []
          const myNames = new Set<string>(
            entries
              .map((e: any) => (e.player?.fullName || '').toLowerCase().trim())
              .filter(Boolean),
          )

          // Build a name → mlb_id map across all rows
          const allRows = [...hittersJson.rows, ...pitchersJson.rows]
          for (const row of allRows) {
            if (myNames.has((row.name || '').toLowerCase().trim())) {
              myTeamMlbIds.push(row.mlb_id)
            }
          }

          // Accent-stripped fallback for unmatched (e.g., "Jesús" vs "Jesus")
          if (myTeamMlbIds.length < myNames.size) {
            const stripAccents = (s: string) =>
              s.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim()
            const normMyNames = new Set([...myNames].map(stripAccents))
            const matched = new Set(myTeamMlbIds)
            for (const row of allRows) {
              if (matched.has(row.mlb_id)) continue
              if (normMyNames.has(stripAccents(row.name || ''))) {
                myTeamMlbIds.push(row.mlb_id)
              }
            }
          }
        }
      } catch (err) {
        console.warn('Failed to resolve my team roster:', err)
      }
    }

    return NextResponse.json({
      hitters: hittersJson.rows,
      pitchers: pitchersJson.rows,
      season_elapsed_fraction: seasonElapsedFraction,
      season_elapsed_days: elapsedDays,
      season_total_days: seasonDays,
      my_team_mlb_ids: myTeamMlbIds,
      season,
    })
  } catch (error: any) {
    console.error('Performance route error:', error)
    return NextResponse.json(
      { error: error.message || 'Failed to compute performance' },
      { status: 500 },
    )
  }
}
