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
    const { swid, espn_s2, dataSource = 'espn' } = body

    const league = await prisma.league.findUnique({
      where: { id: leagueId }
    })

    if (!league) {
      return NextResponse.json({ 
        error: 'League not found' 
      }, { status: 404 })
    }

    console.log(`🔄 Hybrid sync using ${dataSource.toUpperCase()} as data source`)
    console.log('=' * 80)

    let playersProcessed = 0
    let rostersProcessed = 0

    if (dataSource === 'mlb' || dataSource === 'hybrid') {
      // Use MLB Stats API for accurate saves/holds/quality starts data
      console.log('📊 Using MLB Stats API for comprehensive stat coverage')
      
      // Get teams for this league
      const teams = await prisma.team.findMany({
        where: { leagueId: league.id }
      })

      // For MLB API, we need to map ESPN team IDs to MLB team IDs
      // This would require a mapping table or manual configuration
      const espnToMLBTeamMap: { [key: string]: number } = {
        // Add mappings as needed - this is just an example
        '1': 147,  // Yankees example
        '2': 111,  // Red Sox example
        // ... more mappings needed
      }

      // Alternative approach: Get player data from ESPN rosters, then enhance with MLB stats
      if (swid && espn_s2) {
        const settings = { swid, espn_s2 }
        const espnRosters = await ESPNApi.getRosters(league.externalId, league.season, settings)
        
        for (const team of teams) {
          const teamRoster = espnRosters[parseInt(team.externalId)]
          
          if (teamRoster && Array.isArray(teamRoster)) {
            for (const rosterEntry of teamRoster) {
              if (rosterEntry.player) {
                const espnPlayer = rosterEntry.player
                
                // Get enhanced stats from MLB API
                const mlbPlayer = await MLBStatsApi.findPlayerByName(espnPlayer.fullName, parseInt(league.season))
                
                if (mlbPlayer) {
                  const pitchingStats = await MLBStatsApi.getPlayerPitchingStats(mlbPlayer.id, parseInt(league.season))
                  const battingStats = await MLBStatsApi.getPlayerBattingStats(mlbPlayer.id, parseInt(league.season))
                  
                  // Determine if player is pitcher or hitter based on stats availability
                  const isPitcher = pitchingStats && pitchingStats.games > 0
                  
                  let mappedStats
                  if (isPitcher && pitchingStats) {
                    // Use MLB API pitching stats with accurate saves/holds/QS
                    const svhd = (pitchingStats.saves || 0) + (pitchingStats.holds || 0)
                    
                    mappedStats = {
                      gamesPlayed: pitchingStats.games || 0,
                      atBats: pitchingStats.gamesStarted || 0,
                      runs: pitchingStats.wins || 0,
                      hits: pitchingStats.losses || 0,
                      doubles: pitchingStats.saves || 0,
                      triples: pitchingStats.qualityStarts || 0,    // QS mapped to triples
                      homeRuns: svhd,                               // SVHD mapped to home runs
                      rbi: 0,
                      stolenBases: 0,
                      caughtStealing: 0,
                      baseOnBalls: 0,
                      strikeOuts: pitchingStats.strikeOuts || 0,
                      battingAverage: 0,
                      onBasePercentage: pitchingStats.era || 0,
                      sluggingPercentage: pitchingStats.whip || 0,
                      totalBases: parseFloat(pitchingStats.inningsPitched?.replace('.', '') || '0')
                    }
                    
                    console.log(`✅ ${espnPlayer.fullName} (Pitcher): SV=${pitchingStats.saves}, HD=${pitchingStats.holds}, SVHD=${svhd}, QS=${pitchingStats.qualityStarts}`)
                  } else if (battingStats) {
                    // Use MLB API batting stats
                    mappedStats = {
                      gamesPlayed: 0,
                      atBats: battingStats.atBats || 0,
                      runs: battingStats.runs || 0,
                      hits: battingStats.hits || 0,
                      doubles: battingStats.doubles || 0,
                      triples: battingStats.triples || 0,
                      homeRuns: battingStats.homeRuns || 0,
                      rbi: battingStats.rbi || 0,
                      stolenBases: battingStats.stolenBases || 0,
                      caughtStealing: 0,
                      baseOnBalls: battingStats.baseOnBalls || 0,
                      strikeOuts: battingStats.strikeOuts || 0,
                      battingAverage: battingStats.battingAverage || 0,
                      onBasePercentage: battingStats.onBasePercentage || 0,
                      sluggingPercentage: battingStats.sluggingPercentage || 0,
                      totalBases: battingStats.totalBases || 0
                    }
                    
                    console.log(`✅ ${espnPlayer.fullName} (Hitter): R=${battingStats.runs}, HR=${battingStats.homeRuns}, RBI=${battingStats.rbi}, SB=${battingStats.stolenBases}`)
                  } else {
                    // Fallback to zero stats
                    mappedStats = {
                      gamesPlayed: 0, atBats: 0, runs: 0, hits: 0, doubles: 0, triples: 0,
                      homeRuns: 0, rbi: 0, stolenBases: 0, caughtStealing: 0, baseOnBalls: 0,
                      strikeOuts: 0, battingAverage: 0, onBasePercentage: 0, sluggingPercentage: 0,
                      totalBases: 0
                    }
                  }
                  
                  // Update player stats with MLB API data
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
                  
                  playersProcessed++
                } else {
                  console.log(`⚠️  Could not find ${espnPlayer.fullName} in MLB API`)
                }
              }
            }
            rostersProcessed++
          }
        }
      }
    } else {
      // Fallback to original ESPN-only sync
      return NextResponse.json({ 
        error: 'ESPN-only sync not implemented in hybrid route' 
      }, { status: 400 })
    }

    await prisma.league.update({
      where: { id: league.id },
      data: { lastSyncAt: new Date() }
    })

    return NextResponse.json({ 
      success: true,
      message: `Successfully synced ${playersProcessed} players using ${dataSource.toUpperCase()} API`,
      playersProcessed,
      rostersProcessed,
      dataSource
    })

  } catch (error) {
    console.error('Error in hybrid sync:', error)
    return NextResponse.json({ 
      error: error instanceof Error ? error.message : 'Failed to sync with hybrid approach' 
    }, { status: 500 })
  }
}