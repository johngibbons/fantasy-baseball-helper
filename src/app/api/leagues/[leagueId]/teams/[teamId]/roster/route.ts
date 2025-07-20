import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ leagueId: string; teamId: string }> }
) {
  try {
    const { leagueId, teamId } = await params

    // Get the league to determine the season
    const league = await prisma.league.findUnique({
      where: { id: leagueId }
    })

    if (!league) {
      return NextResponse.json({ 
        error: 'League not found' 
      }, { status: 404 })
    }

    console.log('Fetching roster for:', { leagueId, teamId, season: league.season })

    const rosterSlots = await prisma.rosterSlot.findMany({
      where: {
        teamId: teamId,
        isActive: true
      },
      include: {
        player: true,
        playerStats: {
          where: {
            season: league.season
          }
        }
      },
      orderBy: [
        { position: 'asc' },
        { player: { fullName: 'asc' } }
      ]
    })

    console.log('Found roster slots:', rosterSlots.length)
    console.log('Roster slots data:', rosterSlots.map(slot => ({
      playerId: slot.playerId,
      playerName: slot.player.fullName,
      position: slot.position,
      season: slot.season
    })))

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