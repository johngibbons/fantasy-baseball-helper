// @ts-nocheck
import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { MLBStatsApi } from '@/lib/mlb-stats-api'

export async function POST(request: NextRequest) {
  try {
    const { players } = await request.json()
    
    console.log('🔄 Force updating player stats with correct classification')
    console.log('='.repeat(80))
    
    // Default to problematic players if none specified
    const playersToUpdate = players || [
      { name: 'Juan Soto', espnId: 665742 },
      { name: 'Max Fried', espnId: 608331 },
      { name: 'Seiya Suzuki', espnId: 673548 },
      { name: 'Marcus Semien', espnId: 543760 },
      { name: 'Lawrence Butler', espnId: 671732 },
      { name: 'Cole Ragans', espnId: 663905 }
    ]
    
    const results: any[] = []
    
    for (const player of playersToUpdate) {
      console.log(`\n🔄 Updating ${player.name}...`)
      
      // Get player from MLB API
      const mlbPlayer = await MLBStatsApi.findPlayerByName(player.name, 2024)
      
      if (mlbPlayer) {
        console.log(`   ✅ Found: ${mlbPlayer.fullName}`)
        
        // Get stats
        const pitchingStats = await MLBStatsApi.getPlayerPitchingStats(mlbPlayer.id, 2024)
        const battingStats = await MLBStatsApi.getPlayerBattingStats(mlbPlayer.id, 2024)
        
        // Apply correct classification logic
        const hasPitchingStats = pitchingStats && (pitchingStats.games > 0 || pitchingStats.gamesStarted > 0)
        const hasBattingStats = battingStats && battingStats.atBats > 0
        
        let mappedStats = null
        let playerType = 'unknown'
        
        if (!hasPitchingStats && hasBattingStats) {
          // Only has batting stats - definitely a hitter
          playerType = 'hitter'
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
          
          console.log(`   📊 HITTER: R=${mappedStats.runs} HR=${mappedStats.homeRuns} RBI=${mappedStats.rbi} SB=${mappedStats.stolenBases} OBP=${mappedStats.onBasePercentage}`)
          
        } else if (hasPitchingStats && !hasBattingStats) {
          // Only has pitching stats - definitely a pitcher
          playerType = 'pitcher'
          const svhd = (pitchingStats.saves || 0) + (pitchingStats.holds || 0)
          
          mappedStats = {
            gamesPlayed: pitchingStats.games || 0,
            atBats: pitchingStats.gamesStarted || 0,
            runs: pitchingStats.wins || 0,
            hits: pitchingStats.losses || 0,
            doubles: pitchingStats.saves || 0,
            triples: pitchingStats.qualityStarts || 0,
            homeRuns: svhd,
            rbi: 0,
            stolenBases: 0,
            caughtStealing: 0,
            baseOnBalls: 0,
            strikeOuts: pitchingStats.strikeOuts || 0,
            battingAverage: 0,
            onBasePercentage: parseFloat(pitchingStats.era?.toString() || '0'),
            sluggingPercentage: parseFloat(pitchingStats.whip?.toString() || '0'),
            totalBases: parseFloat(pitchingStats.inningsPitched?.replace('.', '') || '0')
          }
          
          console.log(`   📊 PITCHER: W=${mappedStats.runs} L=${mappedStats.hits} SV=${mappedStats.doubles} QS=${mappedStats.triples} SVHD=${mappedStats.homeRuns} K=${mappedStats.strikeOuts}`)
        }
        
        if (mappedStats) {
          // Update the player stats in database
          await prisma.playerStats.upsert({
            where: {
              playerId_season: {
                playerId: player.espnId,
                season: '2025'
              }
            },
            update: mappedStats,
            create: {
              playerId: player.espnId,
              season: '2025',
              ...mappedStats
            }
          })
          
          console.log(`   ✅ Updated ${player.name} as ${playerType}`)
          
          results.push({
            player: player.name,
            espnId: player.espnId,
            mlbId: mlbPlayer.id,
            type: playerType,
            updated: true,
            stats: mappedStats
          })
        }
        
      } else {
        console.log(`   ❌ Not found in MLB API`)
        results.push({
          player: player.name,
          espnId: player.espnId,
          type: 'not_found',
          updated: false
        })
      }
    }
    
    console.log('\n' + '='.repeat(80))
    console.log('🎯 PLAYER STATS FORCE UPDATE COMPLETE')
    
    return NextResponse.json({
      success: true,
      message: 'Player stats updated with correct classification',
      results,
      summary: {
        playersUpdated: results.filter(r => r.updated).length,
        hitters: results.filter(r => r.type === 'hitter').length,
        pitchers: results.filter(r => r.type === 'pitcher').length
      }
    })
    
  } catch (error) {
    console.error('Error force updating player stats:', error)
    return NextResponse.json({ 
      error: error instanceof Error ? error.message : 'Failed to force update player stats' 
    }, { status: 500 })
  }
}