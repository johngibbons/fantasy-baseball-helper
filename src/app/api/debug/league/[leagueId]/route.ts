import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ leagueId: string }> }
) {
  try {
    const { leagueId } = await params

    console.log('=== DEBUG: League Data Analysis ===')
    console.log('League ID:', leagueId)

    // Get league info
    const league = await prisma.league.findUnique({
      where: { id: leagueId }
    })

    if (!league) {
      return NextResponse.json({ error: 'League not found' }, { status: 404 })
    }

    console.log('League:', { id: league.id, name: league.name, season: league.season, platform: league.platform })

    // Get teams for this league
    const teams = await prisma.team.findMany({
      where: { leagueId: leagueId }
    })

    console.log('Teams count:', teams.length)
    teams.forEach(team => {
      console.log(`Team: ${team.id} - ${team.name} (external: ${team.externalId})`)
    })

    // Get roster slots for this league
    const rosterSlots = await prisma.rosterSlot.findMany({
      where: {
        team: {
          leagueId: leagueId
        }
      },
      include: {
        player: true,
        team: true
      }
    })

    console.log('Total roster slots:', rosterSlots.length)
    
    // Group by team
    const rosterByTeam: { [teamId: string]: any[] } = {}
    rosterSlots.forEach(slot => {
      if (!rosterByTeam[slot.teamId]) {
        rosterByTeam[slot.teamId] = []
      }
      rosterByTeam[slot.teamId].push({
        playerId: slot.playerId,
        playerName: slot.player?.fullName || 'Unknown',
        position: slot.position,
        season: slot.season,
        isActive: slot.isActive
      })
    })

    Object.entries(rosterByTeam).forEach(([teamId, roster]) => {
      const team = teams.find(t => t.id === teamId)
      console.log(`Team ${team?.name || teamId}: ${roster.length} players`)
      roster.forEach(player => {
        console.log(`  - ${player.playerName} (${player.position}, season: ${player.season}, active: ${player.isActive})`)
      })
    })

    // Get players
    const players = await prisma.player.findMany({
      where: {
        rosterSlots: {
          some: {
            team: {
              leagueId: leagueId
            }
          }
        }
      }
    })

    console.log('Players count:', players.length)

    return NextResponse.json({
      league: {
        id: league.id,
        name: league.name,
        season: league.season,
        platform: league.platform
      },
      teams: teams.map(t => ({ id: t.id, name: t.name, externalId: t.externalId })),
      rosterSlotsTotal: rosterSlots.length,
      rosterByTeam,
      playersTotal: players.length,
      players: players.map(p => ({ id: p.id, name: p.fullName, position: p.primaryPosition }))
    })

  } catch (error) {
    console.error('Debug endpoint error:', error)
    return NextResponse.json({ 
      error: error instanceof Error ? error.message : 'Debug failed' 
    }, { status: 500 })
  }
}