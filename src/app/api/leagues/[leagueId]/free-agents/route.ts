import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { ESPNApi } from '@/lib/espn-api'

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ leagueId: string }> }
) {
  try {
    const { leagueId } = await params
    const body = await request.json()
    const { swid, espn_s2, limit = 200 } = body

    const league = await prisma.league.findUnique({
      where: { id: leagueId },
    })

    if (!league) {
      return NextResponse.json({ error: 'League not found' }, { status: 404 })
    }

    const settings = { swid, espn_s2 }

    const freeAgents = await ESPNApi.getFreeAgents(
      league.externalId,
      league.season,
      settings,
      limit,
    )

    // Map ESPN position IDs to readable positions
    const posMap: Record<number, string> = {
      0: 'C', 1: '1B', 2: '2B', 3: '3B', 4: 'SS',
      5: 'LF', 6: 'CF', 7: 'RF', 8: 'DH',
      9: 'SP', 10: 'RP', 11: 'P',
    }

    const players = freeAgents.map((p) => ({
      espn_id: p.id,
      name: p.fullName,
      position: posMap[p.defaultPositionId] || 'UTIL',
      eligible_slots: p.eligibleSlots,
    }))

    return NextResponse.json({ players })
  } catch (error: any) {
    console.error('Free agents fetch error:', error)
    return NextResponse.json(
      { error: error.message || 'Failed to fetch free agents' },
      { status: 500 },
    )
  }
}
