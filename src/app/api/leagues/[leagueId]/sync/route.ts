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
                // console.log(`${espnPlayer.fullName} has ${espnPlayer.stats.length} stat periods:`, 
                //   espnPlayer.stats.map(sp => ({ 
                //     id: sp.id, 
                //     seasonId: sp.seasonId,
                //     statSourceId: sp.statSourceId,
                //     statSplitTypeId: sp.statSplitTypeId 
                //   }))
                // )
                
                // Filter for PREVIOUS season (2024) regular season stats, not current (2025)
                // Since it's 2025 now, we want 2024 completed season stats for fantasy purposes
                const targetSeason = parseInt(league.season)
                const currentSeasonStats = espnPlayer.stats.filter(sp => 
                  sp.seasonId === targetSeason && 
                  sp.id && sp.id.startsWith('00') // Regular season stats start with '00'
                )
                
                // Debug code removed - stat period filtering working correctly
                
                // console.log(`${espnPlayer.fullName} filtered stat periods:`, currentSeasonStats.length)
                
                for (const statPeriod of currentSeasonStats) {
                  if (statPeriod.stats) {
                    // ESPN uses numeric keys for stats, map them to our named properties
                    const espnStats = statPeriod.stats
                    
                    // Debug: Log stat period information to understand what time period these stats represent
                    // console.log(`Player ${espnPlayer.fullName} stat period:`, {
                    //   id: statPeriod.id,
                    //   seasonId: statPeriod.seasonId,
                    //   statSourceId: statPeriod.statSourceId,
                    //   statSplitTypeId: statPeriod.statSplitTypeId,
                    //   externalId: statPeriod.externalId
                    // })
                    
                    // ESPN uses different stat key formats for position players vs pitchers
                    // Position players: 0=atBats, 1=homeRuns, 2=battingAverage, 3=runs, etc.
                    // Pitchers: 32=games, 33=games started, 34=innings pitched, etc.
                    
                    let mappedStats
                    
                    // Check if this is a pitcher by position first, then by stats format
                    const isPitcher = primaryPosition === 'SP' || primaryPosition === 'RP' || primaryPosition === 'P'
                    
                    if (!isPitcher && espnStats["0"] !== undefined) {
                      // Position player stats - Based on REAL ESPN data analysis:
                      // Agustin Ramirez: "0": 290 (at-bats), "1": 70 (hits), "2": 0.24 (avg), "3": 20 (runs), "6": 35 (HR), "7": 35 (RBI)
                      // Debug code removed - mapping now corrected based on Jackson Chourio analysis
                      
                      mappedStats = {
                        gamesPlayed: 0,                         // Not available in this format
                        atBats: espnStats["0"] || 0,            // At bats - key 0: confirmed (290)
                        runs: espnStats["20"] || 0,             // Runs - key 20: Jackson Chourio shows 65 (matches real 2025: 65 R)  
                        hits: espnStats["1"] || 0,              // Hits - key 1: confirmed (70)
                        doubles: espnStats["3"] || 0,           // Doubles - key 3: Jackson Chourio shows 25 (matches real 2025: 25 2B)
                        triples: espnStats["4"] || 0,           // Triples - key 4: Jackson Chourio shows 3 (matches real 2025: 3 3B)
                        homeRuns: espnStats["5"] || 0,          // Home runs - key 5: Jackson Chourio shows 16 (matches real 2025: 16 HR)
                        rbi: espnStats["21"] || 0,              // RBI - key 21: Jackson Chourio shows 62 (matches real 2025: 62 RBI)
                        stolenBases: espnStats["23"] || 0,      // Stolen bases - key 23: Jackson Chourio shows 16 (matches real 2025: 16 SB)
                        caughtStealing: 0,                      // Not easily identified
                        baseOnBalls: espnStats["8"] || 0,       // Base on balls (walks) - key 8
                        strikeOuts: espnStats["10"] || 0,       // Strikeouts - key 10
                        battingAverage: espnStats["2"] || 0,    // Batting average - key 2: confirmed (0.24137931)
                        onBasePercentage: espnStats["9"] || 0,  // On base percentage - key 9  
                        sluggingPercentage: espnStats["18"] || 0 // Slugging percentage - key 18
                      }
                    } else if (isPitcher) {
                      // Pitcher stats - zero out batting stats and add pitching stats later
                      mappedStats = {
                        gamesPlayed: espnStats["32"] || 0,      // Games pitched
                        atBats: 0,                              // Pitchers don't bat much
                        runs: 0,
                        hits: 0,
                        doubles: 0,
                        triples: 0,
                        homeRuns: 0,
                        rbi: 0,
                        stolenBases: 0,
                        caughtStealing: 0,
                        baseOnBalls: 0,
                        strikeOuts: 0,
                        battingAverage: 0,
                        onBasePercentage: 0,
                        sluggingPercentage: 0
                      }
                    } else {
                      // Unknown player type or no stats available
                      mappedStats = {
                        gamesPlayed: 0,
                        atBats: 0,
                        runs: 0,
                        hits: 0,
                        doubles: 0,
                        triples: 0,
                        homeRuns: 0,
                        rbi: 0,
                        stolenBases: 0,
                        caughtStealing: 0,
                        baseOnBalls: 0,
                        strikeOuts: 0,
                        battingAverage: 0,
                        onBasePercentage: 0,
                        sluggingPercentage: 0
                      }
                    }

                    await prisma.playerStats.upsert({
                      where: {
                        playerId_season: {
                          playerId: espnPlayer.id,
                          season: league.season
                        }
                      },
                      update: mappedStats,
                      create: {
                        playerId: espnPlayer.id,
                        season: league.season,
                        ...mappedStats
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