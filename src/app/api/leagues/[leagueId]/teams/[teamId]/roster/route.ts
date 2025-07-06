import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'

export async function GET(
  request: NextRequest,
  { params }: { params: { leagueId: string; teamId: string } }
) {
  try {
    const { teamId } = params

    const rosterSlots = await prisma.rosterSlot.findMany({
      where: {
        teamId: teamId,
        isActive: true
      },
      include: {
        player: true,
        playerStats: {
          where: {
            season: '2024' // TODO: Make this dynamic based on league season
          }
        }
      },
      orderBy: [
        { position: 'asc' },
        { player: { fullName: 'asc' } }
      ]
    })

    const roster = rosterSlots.map(slot => ({
      id: slot.player.id,
      fullName: slot.player.fullName,
      primaryPosition: slot.player.primaryPosition,
      position: slot.position,
      acquisitionType: slot.acquisitionType,
      acquisitionDate: slot.acquisitionDate,
      stats: slot.playerStats ? {
        gamesPlayed: slot.playerStats.gamesPlayed,
        homeRuns: slot.playerStats.homeRuns,
        rbi: slot.playerStats.rbi,
        battingAverage: slot.playerStats.battingAverage,
        stolenBases: slot.playerStats.stolenBases,
        runs: slot.playerStats.runs,
        hits: slot.playerStats.hits,
        onBasePercentage: slot.playerStats.onBasePercentage,
        sluggingPercentage: slot.playerStats.sluggingPercentage
      } : null
    }))

    return NextResponse.json({ roster })
  } catch (error) {
    console.error('Error fetching roster:', error)
    return NextResponse.json({ 
      error: 'Failed to fetch roster' 
    }, { status: 500 })
  }
}