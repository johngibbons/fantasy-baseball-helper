import { NextRequest, NextResponse } from 'next/server'
import { MLBApi } from '@/lib/mlb-api'
import { prisma } from '@/lib/prisma'

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params
    const playerId = parseInt(id)
    const { searchParams } = new URL(request.url)
    const season = searchParams.get('season') || '2024'
    
    if (isNaN(playerId)) {
      return NextResponse.json({ error: 'Invalid player ID' }, { status: 400 })
    }

    // Check if we have cached stats
    const cachedStats = await prisma.playerStats.findUnique({
      where: {
        playerId_season: {
          playerId,
          season
        }
      }
    })

    if (cachedStats) {
      return NextResponse.json({ stats: cachedStats })
    }

    // Fetch fresh stats from MLB API
    const stats = await MLBApi.getPlayerStats(playerId, season)
    
    if (!stats) {
      return NextResponse.json({ error: 'Player stats not found' }, { status: 404 })
    }

    // Store stats in database
    const savedStats = await prisma.playerStats.create({
      data: {
        playerId,
        season,
        gamesPlayed: stats.gamesPlayed,
        atBats: stats.atBats,
        runs: stats.runs,
        hits: stats.hits,
        doubles: stats.doubles,
        triples: stats.triples,
        homeRuns: stats.homeRuns,
        rbi: stats.rbi,
        stolenBases: stats.stolenBases,
        caughtStealing: stats.caughtStealing,
        baseOnBalls: stats.baseOnBalls,
        strikeOuts: stats.strikeOuts,
        battingAverage: stats.avg ? parseFloat(stats.avg) : null,
        onBasePercentage: stats.obp ? parseFloat(stats.obp) : null,
        sluggingPercentage: stats.slg ? parseFloat(stats.slg) : null,
        onBasePlusSlugging: stats.ops ? parseFloat(stats.ops) : null,
        totalBases: stats.totalBases,
        hitByPitch: stats.hitByPitch,
        intentionalWalks: stats.intentionalWalks,
        groundIntoDoublePlay: stats.groundIntoDoublePlay,
        leftOnBase: stats.leftOnBase,
        plateAppearances: stats.plateAppearances,
        babip: stats.babip ? parseFloat(stats.babip) : null,
      },
    })

    return NextResponse.json({ stats: savedStats })
  } catch (error) {
    console.error('Error fetching player stats:', error)
    return NextResponse.json({ error: 'Failed to fetch player stats' }, { status: 500 })
  }
}