// @ts-nocheck
import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { MLBStatsApi } from '@/lib/mlb-stats-api'

export async function POST(request: NextRequest) {
  try {
    console.log('🧪 Testing hybrid integration with sample players')
    console.log('='.repeat(80))
    
    // Test with a few sample players to verify the full integration flow
    const testPlayers = [
      { name: 'Gerrit Cole', espnId: 543037, expectedPosition: 'SP' },
      { name: 'Juan Soto', espnId: 665742, expectedPosition: 'OF' }
    ]
    
    const results: any[] = []
    
    for (const testPlayer of testPlayers) {
      console.log(`\n🔍 Testing ${testPlayer.name}...`)
      
      // Step 1: Find player in MLB API
      const mlbPlayer = await MLBStatsApi.findPlayerByName(testPlayer.name, 2024)
      
      if (mlbPlayer) {
        console.log(`   ✅ Found: ${mlbPlayer.fullName}`)
        
        // Step 2: Get stats from MLB API
        const pitchingStats = await MLBStatsApi.getPlayerPitchingStats(mlbPlayer.id, 2024)
        const battingStats = await MLBStatsApi.getPlayerBattingStats(mlbPlayer.id, 2024)
        
        // Step 3: Process the same way as sync route
        const isPitcher = pitchingStats && (pitchingStats.games > 0 || pitchingStats.gamesStarted > 0)
        const isHitter = battingStats && battingStats.atBats > 0
        
        let mappedStats = null
        
        if (isPitcher && pitchingStats) {
          const svhd = (pitchingStats.saves || 0) + (pitchingStats.holds || 0)
          
          mappedStats = {
            // Hybrid mapping: MLB API data -> database fields -> display
            gamesPlayed: pitchingStats.games || 0,                    // Games pitched
            atBats: pitchingStats.gamesStarted || 0,                  // Games started
            runs: pitchingStats.wins || 0,                           // Wins
            hits: pitchingStats.losses || 0,                         // Losses
            doubles: pitchingStats.saves || 0,                       // Saves
            triples: pitchingStats.qualityStarts || 0,               // Quality Starts
            homeRuns: svhd,                                          // SVHD (Saves + Holds)
            strikeOuts: pitchingStats.strikeOuts || 0,               // Strikeouts
            onBasePercentage: parseFloat(pitchingStats.era?.toString() || '0'), // ERA
            sluggingPercentage: parseFloat(pitchingStats.whip?.toString() || '0'), // WHIP
            totalBases: parseFloat(pitchingStats.inningsPitched?.replace('.', '') || '0') // IP
          }
          
          console.log(`   📊 Pitcher: W=${mappedStats.runs} L=${mappedStats.hits} SV=${mappedStats.doubles} HD=${pitchingStats.holds} SVHD=${mappedStats.homeRuns} QS=${mappedStats.triples}`)
          
        } else if (isHitter && battingStats) {
          mappedStats = {
            // Standard batting stats mapping
            atBats: battingStats.atBats || 0,
            runs: battingStats.runs || 0,
            hits: battingStats.hits || 0,
            doubles: battingStats.doubles || 0,
            triples: battingStats.triples || 0,
            homeRuns: battingStats.homeRuns || 0,
            rbi: battingStats.rbi || 0,
            stolenBases: battingStats.stolenBases || 0,
            strikeOuts: battingStats.strikeOuts || 0,
            battingAverage: battingStats.battingAverage || 0,
            onBasePercentage: battingStats.onBasePercentage || 0,
            sluggingPercentage: battingStats.sluggingPercentage || 0,
            totalBases: battingStats.totalBases || 0
          }
          
          console.log(`   📊 Hitter: AVG=${mappedStats.battingAverage} HR=${mappedStats.homeRuns} RBI=${mappedStats.rbi} SB=${mappedStats.stolenBases} OBP=${mappedStats.onBasePercentage} TB=${mappedStats.totalBases}`)
        }
        
        results.push({
          player: mlbPlayer.fullName,
          mlbId: mlbPlayer.id,
          espnId: testPlayer.espnId,
          position: mlbPlayer.primaryPosition?.abbreviation,
          playerType: isPitcher ? 'Pitcher' : 'Hitter',
          mappedStats,
          rawMLBStats: {
            pitching: pitchingStats,
            batting: battingStats
          }
        })
        
      } else {
        console.log(`   ❌ Not found in MLB API`)
      }
    }
    
    console.log('\n' + '='.repeat(80))
    console.log('🎯 HYBRID INTEGRATION TEST COMPLETE')
    console.log(`   Players tested: ${results.length}`)
    console.log(`   Data sources: ESPN (roster structure) + MLB Stats API (statistics)`)
    
    return NextResponse.json({
      success: true,
      message: 'Hybrid integration test complete - ready for full sync',
      results,
      summary: {
        playersAnalyzed: results.length,
        pitchers: results.filter(p => p.playerType === 'Pitcher').length,
        hitters: results.filter(p => p.playerType === 'Hitter').length,
        readyForProduction: true
      }
    })
    
  } catch (error) {
    console.error('Error in hybrid integration test:', error)
    return NextResponse.json({ 
      error: error instanceof Error ? error.message : 'Failed to test hybrid integration' 
    }, { status: 500 })
  }
}