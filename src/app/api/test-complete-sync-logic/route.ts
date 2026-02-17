// @ts-nocheck
import { NextRequest, NextResponse } from 'next/server'
import { MLBStatsApi } from '@/lib/mlb-stats-api'

export async function POST(request: NextRequest) {
  try {
    console.log('🧪 Testing complete sync logic with exact same code as sync route')
    console.log('='.repeat(80))
    
    // Test the exact same players that are problematic
    const testCases = [
      { name: 'Juan Soto', espnPosition: 'SP', expectedType: 'hitter' },
      { name: 'Seiya Suzuki', espnPosition: 'SP', expectedType: 'hitter' },
      { name: 'Marcus Semien', espnPosition: 'RP', expectedType: 'hitter' },
      { name: 'Lawrence Butler', espnPosition: 'SP', expectedType: 'hitter' },
      { name: 'Max Fried', espnPosition: '1B', expectedType: 'pitcher' },
      { name: 'Cole Ragans', espnPosition: '1B', expectedType: 'pitcher' },
      { name: 'Tyler Rogers', espnPosition: 'P', expectedType: 'pitcher' },
      { name: 'Kris Bubic', espnPosition: 'P', expectedType: 'pitcher' }
    ]
    
    const results: any[] = []
    
    for (const testCase of testCases) {
      console.log(`\n🔍 Testing ${testCase.name} (ESPN shows as ${testCase.espnPosition})...`)
      
      // Step 1: Simulate ESPN position detection (using what we see in the UI)
      let primaryPosition = testCase.espnPosition
      
      // Step 2: Search for player in MLB API (use 2024 data since 2025 season hasn't started)
      const statsYear = 2024  // Same logic as sync route
      const mlbPlayer = await MLBStatsApi.findPlayerByName(testCase.name, statsYear)
      
      if (mlbPlayer) {
        console.log(`   ✅ Found in MLB API: ${mlbPlayer.fullName}`)
        
        // Step 3: Get both pitching and batting stats (exact same code as sync route)
        const pitchingStats = await MLBStatsApi.getPlayerPitchingStats(mlbPlayer.id, statsYear)
        const battingStats = await MLBStatsApi.getPlayerBattingStats(mlbPlayer.id, statsYear)
        
        // Step 4: EXACT SAME CLASSIFICATION LOGIC AS SYNC ROUTE
        const espnIsPitcher = primaryPosition === 'SP' || primaryPosition === 'RP' || primaryPosition === 'P'
        const hasPitchingStats = pitchingStats && (pitchingStats.games > 0 || pitchingStats.gamesStarted > 0)
        const hasBattingStats = battingStats && battingStats.atBats > 0
        
        // Use MLB stats as primary classifier, ESPN position as secondary
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
        
        console.log(`   📊 Stats availability: pitching=${hasPitchingStats}, batting=${hasBattingStats}`)
        console.log(`   🔍 Classification: ESPN=${primaryPosition}, espnIsPitcher=${espnIsPitcher}, isPitcher=${isPitcher}, isHitter=${isHitter}`)
        
        // Step 5: Create mapped stats (EXACT SAME LOGIC AS SYNC ROUTE)
        let mappedStats = null
        
        if (isPitcher && pitchingStats) {
          // Use MLB pitching stats with accurate saves/holds/QS
          const svhd = (pitchingStats.saves || 0) + (pitchingStats.holds || 0)
          
          mappedStats = {
            type: 'pitcher',
            gamesPlayed: pitchingStats.games || 0,                    // Games pitched
            atBats: pitchingStats.gamesStarted || 0,                  // Games started
            runs: pitchingStats.wins || 0,                           // Wins
            hits: pitchingStats.losses || 0,                         // Losses
            doubles: pitchingStats.saves || 0,                       // Saves
            triples: pitchingStats.qualityStarts || 0,               // Quality Starts
            homeRuns: svhd,                                          // SVHD (Saves + Holds)
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
          
          console.log(`   📊 PITCHER STATS: W=${mappedStats.runs} L=${mappedStats.hits} SV=${mappedStats.doubles} QS=${mappedStats.triples} SVHD=${mappedStats.homeRuns} K=${mappedStats.strikeOuts} ERA=${mappedStats.onBasePercentage} WHIP=${mappedStats.sluggingPercentage}`)
          
        } else if (isHitter && battingStats) {
          // Use MLB batting stats
          mappedStats = {
            type: 'hitter',
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
          
          console.log(`   📊 HITTER STATS: R=${mappedStats.runs} H=${mappedStats.hits} HR=${mappedStats.homeRuns} RBI=${mappedStats.rbi} SB=${mappedStats.stolenBases} AVG=${mappedStats.battingAverage} OBP=${mappedStats.onBasePercentage} TB=${mappedStats.totalBases}`)
          
        } else {
          console.log(`   ⚠️  No stats mapped - will get zero stats`)
          mappedStats = {
            type: 'zero',
            gamesPlayed: 0, atBats: 0, runs: 0, hits: 0, doubles: 0, triples: 0,
            homeRuns: 0, rbi: 0, stolenBases: 0, caughtStealing: 0, baseOnBalls: 0,
            strikeOuts: 0, battingAverage: 0, onBasePercentage: 0, sluggingPercentage: 0,
            totalBases: 0
          }
        }
        
        results.push({
          player: mlbPlayer.fullName,
          espnPosition: testCase.espnPosition,
          expectedType: testCase.expectedType,
          actualClassification: isPitcher ? 'pitcher' : (isHitter ? 'hitter' : 'unknown'),
          isCorrect: (testCase.expectedType === 'pitcher' && isPitcher) || (testCase.expectedType === 'hitter' && isHitter),
          mappedStats,
          debug: {
            espnIsPitcher,
            hasPitchingStats,
            hasBattingStats,
            isPitcher,
            isHitter
          }
        })
        
      } else {
        console.log(`   ❌ Not found in MLB API`)
        results.push({
          player: testCase.name,
          espnPosition: testCase.espnPosition,
          expectedType: testCase.expectedType,
          actualClassification: 'not_found',
          isCorrect: false,
          mappedStats: null,
          debug: null
        })
      }
    }
    
    console.log('\n' + '='.repeat(80))
    console.log('🎯 COMPLETE SYNC LOGIC TEST RESULTS')
    
    const correctClassifications = results.filter(r => r.isCorrect).length
    const totalClassifications = results.filter(r => r.actualClassification !== 'not_found').length
    
    console.log(`   Correct classifications: ${correctClassifications}/${totalClassifications}`)
    
    return NextResponse.json({
      success: true,
      message: 'Complete sync logic test complete - check console for detailed results',
      results,
      summary: {
        totalTested: results.length,
        correctClassifications,
        totalClassifications,
        accuracyRate: totalClassifications > 0 ? (correctClassifications / totalClassifications * 100).toFixed(1) + '%' : 'N/A'
      }
    })
    
  } catch (error) {
    console.error('Error testing complete sync logic:', error)
    return NextResponse.json({ 
      error: error instanceof Error ? error.message : 'Failed to test complete sync logic' 
    }, { status: 500 })
  }
}