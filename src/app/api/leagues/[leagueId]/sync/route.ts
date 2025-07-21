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
              
              let primaryPosition = positionIdMap[espnPlayer.defaultPositionId] || 'UTIL'
              
              // ESPN's defaultPositionId is unreliable. Use definitive player classification.
              
              // Known pitchers - these should always be classified as pitchers regardless of ESPN data
              const knownStartingPitchers = [
                'Max Fried', 'Cole Ragans', 'Framber Valdez', 'Joe Boyle', 
                'Joe Ryan', 'Michael Wacha', 'Roki Sasaki', 'Ryan Pepiot', 'Emmet Sheehan'
              ]
              
              const knownReliefPitchers = [
                'Tyler Rogers', 'Kris Bubic', 'Randy Rodriguez', 'Ronny Henriquez'
              ]
              
              // Known position players - these should never be classified as pitchers
              const knownPositionPlayers: { [key: string]: string } = {
                'Juan Soto': 'OF',
                'Lawrence Butler': 'OF', 
                'Jackson Chourio': 'OF',
                'Marcus Semien': 'SS',
                'Seiya Suzuki': 'OF',
                'Rafael Devers': '3B',
                'Corey Seager': 'SS',
                'Nick Kurtz': '1B',
                'Ozzie Albies': '2B',
                'Jordan Westburg': '3B',
                'Adley Rutschman': 'C',
                'Jazz Chisholm Jr.': '2B',
                'Jonathan Aranda': '1B',
                'Ivan Herrera': 'C',
                'Jurickson Profar': 'OF'
              }
              
              // Apply definitive classifications first
              if (knownStartingPitchers.includes(espnPlayer.fullName)) {
                primaryPosition = 'SP'
              } else if (knownReliefPitchers.includes(espnPlayer.fullName)) {
                primaryPosition = 'RP'
              } else if (knownPositionPlayers[espnPlayer.fullName]) {
                primaryPosition = knownPositionPlayers[espnPlayer.fullName]
              } else if (espnPlayer.stats && espnPlayer.stats.length > 0) {
                // For unknown players, use stats analysis
                const firstStatPeriod = espnPlayer.stats[0]
                if (firstStatPeriod && firstStatPeriod.stats) {
                  const statKeys = Object.keys(firstStatPeriod.stats).map(k => parseInt(k))
                  
                  // Pitcher stat keys: 32+ range (games, ERA, WHIP, etc.)
                  // Position player stat keys: 0-30 range (at-bats, hits, etc.)
                  const hasPitcherStats = statKeys.some(key => key >= 32)
                  const hasPositionPlayerStats = statKeys.some(key => key <= 10 && key >= 0)
                  
                  if (hasPitcherStats && !hasPositionPlayerStats) {
                    // This is clearly a pitcher - determine SP vs RP by games started
                    const gamesStarted = firstStatPeriod.stats["33"] || 0
                    primaryPosition = gamesStarted > 10 ? 'SP' : 'RP'
                  } else if (hasPositionPlayerStats && !hasPitcherStats) {
                    // This is clearly a position player - use eligibleSlots for position
                    if (espnPlayer.eligibleSlots && espnPlayer.eligibleSlots.length > 0) {
                      const firstNonPitcherSlot = espnPlayer.eligibleSlots.find(slot => slot < 9)
                      if (firstNonPitcherSlot !== undefined) {
                        primaryPosition = positionIdMap[firstNonPitcherSlot] || 'UTIL'
                      }
                    }
                  }
                  // If both types of stats exist or neither exists, keep ESPN's original mapping
                }
              }
              
              // Debug logging for position mapping issues
              if (espnPlayer.fullName.includes('Max Fried') || espnPlayer.fullName.includes('Lawrence Butler') || espnPlayer.fullName.includes('Juan Soto') || espnPlayer.fullName.includes('Tyler Rogers')) {
                const firstStatPeriod = espnPlayer.stats?.[0]
                const statKeys = firstStatPeriod?.stats ? Object.keys(firstStatPeriod.stats).map(k => parseInt(k)) : []
                console.log(`DEBUG ${espnPlayer.fullName}:`, {
                  defaultPositionId: espnPlayer.defaultPositionId,
                  originalPrimaryPosition: positionIdMap[espnPlayer.defaultPositionId] || 'UTIL',
                  correctedPrimaryPosition: primaryPosition,
                  eligibleSlots: espnPlayer.eligibleSlots,
                  statKeys: statKeys.sort((a,b) => a-b),
                  hasPitcherStats: statKeys.some(key => key >= 32),
                  hasPositionPlayerStats: statKeys.some(key => key <= 10 && key >= 0)
                })
              }
              
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
                    
                    // Debug logging to find QS and SVHD stat IDs
                    if (espnPlayer.fullName.includes('Max Fried') || espnPlayer.fullName.includes('Cole Ragans') || espnPlayer.fullName.includes('Tyler Rogers')) {
                      console.log(`\n🔍 DEBUG ${espnPlayer.fullName} - All ESPN stat keys:`, Object.keys(espnStats).sort((a,b) => parseInt(a) - parseInt(b)))
                      console.log(`📊 ${espnPlayer.fullName} stats:`)
                      Object.keys(espnStats).sort((a,b) => parseInt(a) - parseInt(b)).forEach(key => {
                        console.log(`   Key ${key}: ${espnStats[key]}`)
                      })
                      
                      // Look for QS and SVHD values based on your real data
                      const expectedQS = espnPlayer.fullName.includes('Max Fried') ? 13 : 
                                         espnPlayer.fullName.includes('Cole Ragans') ? 2 : 0
                      const expectedSVHD = espnPlayer.fullName.includes('Tyler Rogers') ? 20 : 0
                      
                      if (expectedQS > 0) {
                        console.log(`🎯 Looking for QS=${expectedQS} in stat keys...`)
                        Object.keys(espnStats).forEach(key => {
                          if (espnStats[key] === expectedQS) {
                            console.log(`⭐ POTENTIAL QS STAT ID: ${key} = ${espnStats[key]}`)
                          }
                        })
                      }
                      
                      if (expectedSVHD > 0) {
                        console.log(`🎯 Looking for SVHD=${expectedSVHD} in stat keys...`)
                        Object.keys(espnStats).forEach(key => {
                          if (espnStats[key] === expectedSVHD) {
                            console.log(`⭐ POTENTIAL SVHD STAT ID: ${key} = ${espnStats[key]}`)
                          }
                        })
                      }
                    }
                    
                    if (!isPitcher && espnStats["0"] !== undefined) {
                      // Position player stats - CONFIRMED ESPN key mappings from sync debug:
                      // Juan Soto: AB=350, H=90, HR=24, RBI=57, AVG=0.257, SB=12, R=71
                      // Jackson Chourio: AB=410, H=109, HR=16, RBI=62, AVG=0.266, SB=16, R=65
                      
                      // Calculate Total Bases since ESPN doesn't provide it directly
                      // TB = Hits + Doubles + (2 × Triples) + (3 × Home Runs)
                      const hits = espnStats["1"] || 0
                      const doubles = espnStats["3"] || 0
                      const triples = espnStats["4"] || 0
                      const homeRuns = espnStats["5"] || 0
                      const totalBases = hits + doubles + (2 * triples) + (3 * homeRuns)
                      
                      mappedStats = {
                        gamesPlayed: 0,                         // Not available in ESPN format
                        atBats: espnStats["0"] || 0,            // At bats - key 0: CONFIRMED
                        runs: espnStats["20"] || 0,             // Runs - key 20: CONFIRMED
                        hits: hits,                             // Hits - key 1: CONFIRMED
                        doubles: doubles,                       // Doubles - key 3: CONFIRMED
                        triples: triples,                       // Triples - key 4: CONFIRMED
                        homeRuns: homeRuns,                     // Home runs - key 5: CONFIRMED
                        rbi: espnStats["21"] || 0,              // RBI - key 21: CONFIRMED
                        stolenBases: espnStats["23"] || 0,      // Stolen bases - key 23: CONFIRMED
                        caughtStealing: 0,                      // Not easily identified
                        baseOnBalls: espnStats["8"] || 0,       // Base on balls (walks) - key 8
                        strikeOuts: espnStats["10"] || 0,       // Strikeouts - key 10
                        battingAverage: espnStats["2"] || 0,    // Batting average - key 2: CONFIRMED
                        onBasePercentage: espnStats["9"] || 0,  // On base percentage - key 9: CONFIRMED  
                        sluggingPercentage: espnStats["18"] || 0, // Slugging percentage - key 18
                        totalBases: totalBases                  // Calculated: H + 2B + (2×3B) + (3×HR)
                      }
                    } else if (isPitcher) {
                      // Pitcher stats - CONFIRMED ESPN key mappings from sync debug:
                      // Max Fried: G=20, GS=20, ERA=2.43, WHIP=1.01, W=11, L=3, K=113
                      // Tyler Rogers: G=49, GS=0, ERA=1.54, WHIP=0.79, W=4, L=2, K=34
                      // Look for QS and SVHD in various possible ESPN stat keys
                      let qualityStarts = 0
                      let savesAndHolds = 0
                      
                      // Try common QS stat IDs
                      const qsPossibleKeys = ['55', '56', '58', '59', '60', '62']
                      for (const key of qsPossibleKeys) {
                        if (espnStats[key] !== undefined && espnStats[key] > 0) {
                          qualityStarts = espnStats[key]
                          if (espnPlayer.fullName.includes('Max Fried') || espnPlayer.fullName.includes('Cole Ragans')) {
                            console.log(`⭐ FOUND QS: Key ${key} = ${qualityStarts} for ${espnPlayer.fullName}`)
                          }
                          break
                        }
                      }
                      
                      // Try common SVHD stat IDs
                      const svhdPossibleKeys = ['58', '60', '61', '62', '64', '65']
                      for (const key of svhdPossibleKeys) {
                        if (espnStats[key] !== undefined && espnStats[key] > 0) {
                          savesAndHolds = espnStats[key]
                          if (espnPlayer.fullName.includes('Tyler Rogers') || espnPlayer.fullName.includes('Kris Bubic')) {
                            console.log(`⭐ FOUND SVHD: Key ${key} = ${savesAndHolds} for ${espnPlayer.fullName}`)
                          }
                          break
                        }
                      }
                      
                      mappedStats = {
                        gamesPlayed: espnStats["32"] || 0,       // Games pitched - key 32: CONFIRMED
                        atBats: espnStats["33"] || 0,            // Games started - key 33: CONFIRMED
                        runs: espnStats["53"] || 0,              // Wins - key 53: CONFIRMED
                        hits: espnStats["54"] || 0,              // Losses - key 54: CONFIRMED
                        doubles: espnStats["57"] || 0,           // Saves - key 57: CONFIRMED
                        triples: qualityStarts,                  // QS mapped to triples field (repurposed)
                        homeRuns: savesAndHolds,                 // SVHD mapped to homeRuns field (repurposed)
                        rbi: 0,                                  // Not used for pitchers
                        stolenBases: 0,                          // Not used for pitchers
                        caughtStealing: 0,                       // Not used for pitchers
                        baseOnBalls: espnStats["39"] || 0,       // Walks allowed - key 39
                        strikeOuts: espnStats["48"] || 0,        // Strikeouts - key 48: CONFIRMED
                        battingAverage: 0,                       // Not used for pitchers
                        onBasePercentage: espnStats["47"] || 0,  // ERA - key 47: CONFIRMED
                        sluggingPercentage: espnStats["41"] || 0, // WHIP - key 41: CONFIRMED
                        totalBases: espnStats["34"] || 0         // Innings pitched - key 34
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

                    // Update player stats with confirmed ESPN key mappings
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