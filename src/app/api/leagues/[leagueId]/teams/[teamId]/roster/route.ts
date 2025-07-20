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
        player: {
          include: {
            stats: {
              where: {
                season: league.season
              }
            }
          }
        },
        playerStats: true // This is the direct relation from RosterSlot to PlayerStats
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

    const roster = rosterSlots.map(slot => {
      // Try to get stats from the direct relation first, then from player.stats
      const playerStats = slot.playerStats || (slot.player.stats && slot.player.stats[0]) || null
      
      console.log(`Player ${slot.player.fullName}: direct stats = ${!!slot.playerStats}, player.stats = ${slot.player.stats?.length || 0}`)
      
      return {
        id: slot.player.id,
        fullName: slot.player.fullName,
        primaryPosition: slot.player.primaryPosition,
        position: slot.position,
        acquisitionType: slot.acquisitionType,
        acquisitionDate: slot.acquisitionDate,
        stats: playerStats ? {
          gamesPlayed: playerStats.gamesPlayed,
          homeRuns: playerStats.homeRuns,
          rbi: playerStats.rbi,
          battingAverage: playerStats.battingAverage,
          stolenBases: playerStats.stolenBases,
          runs: playerStats.runs,
          hits: playerStats.hits,
          onBasePercentage: playerStats.onBasePercentage,
          sluggingPercentage: playerStats.sluggingPercentage
        } : null
      }
    })

    return NextResponse.json({ roster })
  } catch (error) {
    console.error('Error fetching roster:', error)
    return NextResponse.json({ 
      error: 'Failed to fetch roster' 
    }, { status: 500 })
  }
}