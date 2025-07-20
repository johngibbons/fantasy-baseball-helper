import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { ESPNApi } from '@/lib/espn-api'

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ leagueId: string }> }
) {
  try {
    const { leagueId } = await params

    // Get the league from database
    const league = await prisma.league.findUnique({
      where: { id: leagueId }
    })

    if (!league) {
      return NextResponse.json({ 
        error: 'League not found' 
      }, { status: 404 })
    }

    if (league.platform !== 'ESPN') {
      return NextResponse.json({ 
        error: 'Only ESPN leagues are supported for sync' 
      }, { status: 400 })
    }

    // For now, we'll need credentials passed in the request body
    // In a real app, these would be stored securely for the user
    const body = await request.json()
    const { swid, espn_s2 } = body

    if (!swid || !espn_s2) {
      return NextResponse.json({ 
        error: 'ESPN credentials (swid and espn_s2) are required for sync' 
      }, { status: 400 })
    }

    const settings = { swid, espn_s2 }

    console.log('Syncing roster data for league:', league.id)
    console.log('ESPN API params:', { externalId: league.externalId, season: league.season })
    
    // Fetch fresh roster data from ESPN
    const rosters = await ESPNApi.getRosters(league.externalId, league.season, settings)
    console.log('ESPN rosters response:', Object.keys(rosters).length, 'teams')
    console.log('Rosters data:', JSON.stringify(rosters, null, 2))
    
    // Get teams for this league
    const teams = await prisma.team.findMany({
      where: { leagueId: league.id }
    })

    let playersProcessed = 0
    let rostersProcessed = 0

    // Process rosters for each team
    for (const team of teams) {
      const teamRoster = rosters[parseInt(team.externalId)]
      
      if (teamRoster && Array.isArray(teamRoster)) {
        // Clear existing roster slots for this team
        await prisma.rosterSlot.deleteMany({
          where: {
            teamId: team.id,
            season: league.season
          }
        })

        for (const rosterEntry of teamRoster) {
          try {
            // Skip entries without player data
            if (!rosterEntry.player) {
              console.log(`Skipping roster entry with missing player data: playerId ${rosterEntry.playerId}`)
              continue
            }

            // Create or update player record if player data is available
            if (rosterEntry.player) {
              const espnPlayer = rosterEntry.player
              
              // Map ESPN position IDs to readable positions
              const positionIdMap: { [key: number]: string } = {
                0: 'C', 1: '1B', 2: '2B', 3: '3B', 4: 'SS', 5: 'OF', 
                6: 'OF', 7: 'OF', 8: 'DH', 9: 'SP', 10: 'RP', 11: 'P'
              }
              
              const primaryPosition = positionIdMap[espnPlayer.defaultPositionId] || 'UTIL'
              
              await prisma.player.upsert({
                where: { id: espnPlayer.id },
                update: {
                  fullName: espnPlayer.fullName,
                  firstName: espnPlayer.firstName,
                  lastName: espnPlayer.lastName,
                  primaryPosition: primaryPosition,
                  active: true
                },
                create: {
                  id: espnPlayer.id,
                  fullName: espnPlayer.fullName,
                  firstName: espnPlayer.firstName,
                  lastName: espnPlayer.lastName,
                  primaryPosition: primaryPosition,
                  active: true
                }
              })

              // Create player stats if available
              if (espnPlayer.stats && espnPlayer.stats.length > 0) {
                for (const statPeriod of espnPlayer.stats) {
                  if (statPeriod.stats) {
                    await prisma.playerStats.upsert({
                      where: {
                        playerId_season: {
                          playerId: espnPlayer.id,
                          season: league.season
                        }
                      },
                      update: {
                        gamesPlayed: statPeriod.stats.gamesPlayed || 0,
                        atBats: statPeriod.stats.atBats || 0,
                        runs: statPeriod.stats.runs || 0,
                        hits: statPeriod.stats.hits || 0,
                        doubles: statPeriod.stats.doubles || 0,
                        triples: statPeriod.stats.triples || 0,
                        homeRuns: statPeriod.stats.homeRuns || 0,
                        rbi: statPeriod.stats.rbi || 0,
                        stolenBases: statPeriod.stats.stolenBases || 0,
                        caughtStealing: statPeriod.stats.caughtStealing || 0,
                        baseOnBalls: statPeriod.stats.baseOnBalls || 0,
                        strikeOuts: statPeriod.stats.strikeOuts || 0,
                        battingAverage: statPeriod.stats.battingAverage || 0,
                        onBasePercentage: statPeriod.stats.onBasePercentage || 0,
                        sluggingPercentage: statPeriod.stats.sluggingPercentage || 0
                      },
                      create: {
                        playerId: espnPlayer.id,
                        season: league.season,
                        gamesPlayed: statPeriod.stats.gamesPlayed || 0,
                        atBats: statPeriod.stats.atBats || 0,
                        runs: statPeriod.stats.runs || 0,
                        hits: statPeriod.stats.hits || 0,
                        doubles: statPeriod.stats.doubles || 0,
                        triples: statPeriod.stats.triples || 0,
                        homeRuns: statPeriod.stats.homeRuns || 0,
                        rbi: statPeriod.stats.rbi || 0,
                        stolenBases: statPeriod.stats.stolenBases || 0,
                        caughtStealing: statPeriod.stats.caughtStealing || 0,
                        baseOnBalls: statPeriod.stats.baseOnBalls || 0,
                        strikeOuts: statPeriod.stats.strikeOuts || 0,
                        battingAverage: statPeriod.stats.battingAverage || 0,
                        onBasePercentage: statPeriod.stats.onBasePercentage || 0,
                        sluggingPercentage: statPeriod.stats.sluggingPercentage || 0
                      }
                    })
                    break // Only use the first stat period for now
                  }
                }
              }

              playersProcessed++
            }

            // Map lineup slot IDs to position names for roster slots
            const positionMap: { [key: number]: string } = {
              0: 'C', 1: '1B', 2: '2B', 3: '3B', 4: 'SS', 5: 'OF', 6: 'OF', 7: 'OF',
              8: 'UTIL', 9: 'SP', 10: 'SP', 11: 'RP', 12: 'RP', 13: 'P', 20: 'BENCH'
            }

            const position = positionMap[rosterEntry.lineupSlotId] || 'BENCH'

            await prisma.rosterSlot.create({
              data: {
                teamId: team.id,
                playerId: rosterEntry.playerId || 0,
                season: league.season,
                position,
                acquisitionType: rosterEntry.acquisitionType || 'UNKNOWN',
                acquisitionDate: rosterEntry.acquisitionDate ? new Date(rosterEntry.acquisitionDate) : new Date()
              }
            })
          } catch (rosterError) {
            console.error('Error processing roster entry during sync:', rosterError, rosterEntry)
          }
        }
        rostersProcessed++
      }
    }

    // Update league sync timestamp
    await prisma.league.update({
      where: { id: league.id },
      data: { lastSyncAt: new Date() }
    })

    return NextResponse.json({ 
      success: true,
      message: `Successfully synced ${playersProcessed} players across ${rostersProcessed} team rosters`,
      playersProcessed,
      rostersProcessed
    })

  } catch (error) {
    console.error('Error syncing league roster data:', error)
    return NextResponse.json({ 
      error: error instanceof Error ? error.message : 'Failed to sync roster data' 
    }, { status: 500 })
  }
}