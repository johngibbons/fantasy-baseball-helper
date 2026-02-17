// @ts-nocheck
import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { ESPNApi } from '@/lib/espn-api'
import { MLBStatsApi } from '@/lib/mlb-stats-api'

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ leagueId: string }> }
) {
  try {
    const { leagueId } = await params
    const body = await request.json()
    const { swid, espn_s2, dataSource = 'hybrid' } = body

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

    if (!swid || !espn_s2) {
      return NextResponse.json({ 
        error: 'ESPN credentials (swid and espn_s2) are required for sync' 
      }, { status: 400 })
    }

    const settings = { swid, espn_s2 }

    console.log(`🔄 HYBRID SYNC for league: ${league.id}`)
    console.log('📋 Strategy: ESPN rosters + MLB Stats API for accurate statistics')
    console.log('='.repeat(80))
    
    // Step 1: Fetch roster structure from ESPN
    const rosters = await ESPNApi.getRosters(league.externalId, league.season, settings)
    console.log(`📊 ESPN rosters: ${Object.keys(rosters).length} teams`)
    
    // Get teams for this league
    const teams = await prisma.team.findMany({
      where: { leagueId: league.id }
    })

    let playersProcessed = 0
    let playersWithMLBStats = 0
    let playersMLBNotFound = 0
    let rostersProcessed = 0

    // Step 2: Process each team's roster
    for (const team of teams) {
      const teamRoster = rosters[parseInt(team.externalId)]
      
      if (teamRoster && Array.isArray(teamRoster)) {
        console.log(`\n🏟️  Processing ${team.name} (${teamRoster.length} players)`)
        
        // Clear existing roster slots for this team
        await prisma.rosterSlot.deleteMany({
          where: {
            teamId: team.id,
            season: league.season
          }
        })

        for (const rosterEntry of teamRoster) {
          try {
            if (!rosterEntry.player) {
              console.log(`   ⚠️  Skipping roster entry with missing player data`)
              continue
            }

            const espnPlayer = rosterEntry.player
            
            // Determine primary position from ESPN data with enhanced logic
            const positionIdMap: { [key: number]: string } = {
              0: 'C', 1: '1B', 2: '2B', 3: '3B', 4: 'SS', 5: 'OF', 
              6: 'OF', 7: 'OF', 8: 'DH', 9: 'SP', 10: 'RP', 11: 'P'
            }
            
            let primaryPosition = positionIdMap[espnPlayer.defaultPositionId] || 'UTIL'
            
            // Enhanced position detection using eligibleSlots for better accuracy
            if (espnPlayer.eligibleSlots && espnPlayer.eligibleSlots.length > 0) {
              // Check if player has pitcher slots (9=SP, 10=RP, 11=P)
              const hasPitcherSlots = espnPlayer.eligibleSlots.some(slot => slot >= 9 && slot <= 11)
              const hasPositionSlots = espnPlayer.eligibleSlots.some(slot => slot < 9)
              
              if (hasPitcherSlots && !hasPositionSlots) {
                // Pure pitcher - determine SP vs RP
                if (espnPlayer.eligibleSlots.includes(9)) primaryPosition = 'SP'
                else if (espnPlayer.eligibleSlots.includes(10)) primaryPosition = 'RP'
                else primaryPosition = 'P'
              } else if (hasPositionSlots && !hasPitcherSlots) {
                // Pure position player - use most specific position
                const positionSlot = espnPlayer.eligibleSlots.find(slot => slot < 9)
                if (positionSlot !== undefined) {
                  primaryPosition = positionIdMap[positionSlot] || primaryPosition
                }
              }
            }

            // Step 3: Create/update player record
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

            // Step 4: Get enhanced statistics from MLB Stats API
            let mappedStats = null
            
            if (dataSource === 'hybrid') {
              console.log(`   🔍 Looking up ${espnPlayer.fullName} in MLB API...`)
              
              // Search for player in MLB API (use 2024 data since 2025 season hasn't started)
              const statsYear = parseInt(league.season) === 2025 ? 2024 : parseInt(league.season)
              const mlbPlayer = await MLBStatsApi.findPlayerByName(espnPlayer.fullName, statsYear)
              
              if (mlbPlayer) {
                console.log(`   ✅ Found in MLB API: ${mlbPlayer.fullName}`)
                
                // Get both pitching and batting stats
                const pitchingStats = await MLBStatsApi.getPlayerPitchingStats(mlbPlayer.id, statsYear)
                const battingStats = await MLBStatsApi.getPlayerBattingStats(mlbPlayer.id, statsYear)
                
                // Determine player type based on primary position AND stats availability
                const espnIsPitcher = primaryPosition === 'SP' || primaryPosition === 'RP' || primaryPosition === 'P'
                const hasPitchingStats = pitchingStats && (pitchingStats.games > 0 || pitchingStats.gamesStarted > 0)
                const hasBattingStats = battingStats && battingStats.atBats > 0
                
                // Use MLB stats as primary classifier, ESPN position as secondary
                // This prevents misclassification when ESPN data is wrong
                let isPitcher = false
                let isHitter = false
                
                if (hasPitchingStats && hasBattingStats) {
                  // Player has both types of stats - use ESPN position to decide
                  isPitcher = espnIsPitcher
                  isHitter = !espnIsPitcher
                } else if (hasPitchingStats && !hasBattingStats) {
                  // Only has pitching stats - definitely a pitcher
                  isPitcher = true
                } else if (!hasPitchingStats && hasBattingStats) {
                  // Only has batting stats - definitely a hitter
                  isHitter = true
                } else {
                  // No stats found - use ESPN position as fallback
                  isPitcher = espnIsPitcher
                  isHitter = !espnIsPitcher
                }
                
                console.log(`   🔍 Classification: ESPN=${primaryPosition}, isPitcher=${isPitcher}, isHitter=${isHitter}`)
                
                if (isPitcher && pitchingStats) {
                  // Use MLB pitching stats with accurate saves/holds/QS
                  const svhd = (pitchingStats.saves || 0) + (pitchingStats.holds || 0)
                  
                  mappedStats = {
                    gamesPlayed: pitchingStats.games || 0,                    // Games pitched
                    atBats: pitchingStats.gamesStarted || 0,                  // Games started
                    runs: pitchingStats.wins || 0,                           // Wins
                    hits: pitchingStats.losses || 0,                         // Losses
                    doubles: pitchingStats.saves || 0,                       // Saves
                    triples: pitchingStats.qualityStarts || 0,               // Quality Starts
                    homeRuns: svhd,                                          // Saves + Holds (SVHD)
                    rbi: 0,                                                  // Not used for pitchers
                    stolenBases: 0,                                          // Not used for pitchers  
                    caughtStealing: 0,                                       // Not used for pitchers
                    baseOnBalls: 0,                                          // We could use walks allowed if needed
                    strikeOuts: pitchingStats.strikeOuts || 0,               // Strikeouts
                    battingAverage: 0,                                       // Not used for pitchers
                    onBasePercentage: parseFloat(pitchingStats.era?.toString() || '0'), // ERA
                    sluggingPercentage: parseFloat(pitchingStats.whip?.toString() || '0'), // WHIP
                    totalBases: parseFloat(pitchingStats.inningsPitched?.replace('.', '') || '0') // IP (formatted)
                  }
                  
                  console.log(`   📊 Pitcher stats: W=${pitchingStats.wins} L=${pitchingStats.losses} SV=${pitchingStats.saves} HD=${pitchingStats.holds} SVHD=${svhd} QS=${pitchingStats.qualityStarts}`)
                  playersWithMLBStats++
                  
                } else if (isHitter && battingStats) {
                  // Use MLB batting stats
                  mappedStats = {
                    gamesPlayed: 0,                                          // Games (not always available)
                    atBats: battingStats.atBats || 0,                       // At Bats
                    runs: battingStats.runs || 0,                           // Runs
                    hits: battingStats.hits || 0,                           // Hits
                    doubles: battingStats.doubles || 0,                     // Doubles
                    triples: battingStats.triples || 0,                     // Triples
                    homeRuns: battingStats.homeRuns || 0,                   // Home Runs
                    rbi: battingStats.rbi || 0,                             // RBI
                    stolenBases: battingStats.stolenBases || 0,             // Stolen Bases
                    caughtStealing: 0,                                      // Not always available
                    baseOnBalls: battingStats.baseOnBalls || 0,             // Walks
                    strikeOuts: battingStats.strikeOuts || 0,               // Strikeouts
                    battingAverage: battingStats.battingAverage || 0,       // Batting Average
                    onBasePercentage: battingStats.onBasePercentage || 0,   // On Base Percentage
                    sluggingPercentage: battingStats.sluggingPercentage || 0, // Slugging Percentage
                    totalBases: battingStats.totalBases || 0                // Total Bases
                  }
                  
                  console.log(`   📊 Hitter stats: AVG=${battingStats.battingAverage} HR=${battingStats.homeRuns} RBI=${battingStats.rbi} SB=${battingStats.stolenBases} OBP=${battingStats.onBasePercentage}`)
                  playersWithMLBStats++
                  
                } else {
                  console.log(`   ⚠️  No MLB stats found for ${espnPlayer.fullName}`)
                  playersMLBNotFound++
                }
              } else {
                console.log(`   ❌ ${espnPlayer.fullName} not found in MLB API - will use zero stats`)
                playersMLBNotFound++
                
                // For players not found in MLB API, we could potentially fall back to ESPN stats
                // For now, they'll get zero stats which is handled in the fallback section below
              }
            }

            // Step 5: Fallback to zero stats if no MLB data available
            if (!mappedStats) {
              mappedStats = {
                gamesPlayed: 0, atBats: 0, runs: 0, hits: 0, doubles: 0, triples: 0,
                homeRuns: 0, rbi: 0, stolenBases: 0, caughtStealing: 0, baseOnBalls: 0,
                strikeOuts: 0, battingAverage: 0, onBasePercentage: 0, sluggingPercentage: 0,
                totalBases: 0
              }
            }

            // Step 6: Update player stats in database
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

            // Step 7: Create roster slot entry
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

            playersProcessed++

          } catch (playerError) {
            console.error(`   ❌ Error processing ${rosterEntry.player?.fullName}:`, playerError)
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

    console.log('\n' + '='.repeat(80))
    console.log('🎯 HYBRID SYNC COMPLETE')
    console.log(`   Total players processed: ${playersProcessed}`)
    console.log(`   Players with MLB stats: ${playersWithMLBStats}`)
    console.log(`   Players not found in MLB: ${playersMLBNotFound}`)
    console.log(`   Teams processed: ${rostersProcessed}`)

    return NextResponse.json({ 
      success: true,
      message: `Hybrid sync complete: ${playersProcessed} players processed using ESPN rosters + MLB Stats API`,
      stats: {
        playersProcessed,
        playersWithMLBStats,
        playersMLBNotFound,
        rostersProcessed,
        dataSource: 'Hybrid (ESPN + MLB Stats API)'
      }
    })

  } catch (error) {
    console.error('Error in hybrid sync:', error)
    return NextResponse.json({ 
      error: error instanceof Error ? error.message : 'Failed to sync roster data' 
    }, { status: 500 })
  }
}