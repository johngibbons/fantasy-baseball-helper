import { NextRequest, NextResponse } from 'next/server'
import { MLBStatsApi } from '@/lib/mlb-stats-api'

export async function POST(request: NextRequest) {
  try {
    const { players } = await request.json()
    
    console.log('🧪 Debugging player classification issues')
    console.log('=' * 80)
    
    const testPlayers = players || [
      'Juan Soto',
      'Seiya Suzuki', 
      'Lawrence Butler',
      'Max Fried',
      'Tyler Rogers',
      'Kris Bubic'
    ]
    
    const results: any[] = []
    
    for (const playerName of testPlayers) {
      console.log(`\n🔍 Analyzing ${playerName}...`)
      
      // Search in MLB API
      const mlbPlayer = await MLBStatsApi.findPlayerByName(playerName, 2024)
      
      if (mlbPlayer) {
        console.log(`   ✅ Found: ${mlbPlayer.fullName}`)
        console.log(`   📍 Position: ${mlbPlayer.primaryPosition?.abbreviation || 'Unknown'}`)
        
        // Get both types of stats
        const pitchingStats = await MLBStatsApi.getPlayerPitchingStats(mlbPlayer.id, 2024)
        const battingStats = await MLBStatsApi.getPlayerBattingStats(mlbPlayer.id, 2024)
        
        // Classification logic
        const hasPitchingStats = pitchingStats && (pitchingStats.games > 0 || pitchingStats.gamesStarted > 0)
        const hasBattingStats = battingStats && battingStats.atBats > 0
        
        const mlbPositionIsPitcher = ['P', 'SP', 'RP'].includes(mlbPlayer.primaryPosition?.abbreviation || '')
        
        console.log(`   📊 Stats availability:`)
        console.log(`      Pitching: games=${pitchingStats?.games}, GS=${pitchingStats?.gamesStarted}`)
        console.log(`      Batting: AB=${battingStats?.atBats}`)
        console.log(`   🏷️  Classification: MLB position=${mlbPlayer.primaryPosition?.abbreviation}, isPitcher=${mlbPositionIsPitcher}`)
        
        // Determine what type this player should be
        let playerType = 'Unknown'
        let recommendedStats = null
        
        if (mlbPositionIsPitcher && hasPitchingStats) {
          playerType = 'Pitcher'
          const svhd = (pitchingStats.saves || 0) + (pitchingStats.holds || 0)
          recommendedStats = {
            type: 'pitching',
            wins: pitchingStats.wins,
            losses: pitchingStats.losses,
            saves: pitchingStats.saves,
            holds: pitchingStats.holds,
            svhd: svhd,
            qualityStarts: pitchingStats.qualityStarts,
            era: pitchingStats.era,
            whip: pitchingStats.whip,
            strikeOuts: pitchingStats.strikeOuts,
            games: pitchingStats.games,
            gamesStarted: pitchingStats.gamesStarted
          }
        } else if (!mlbPositionIsPitcher && hasBattingStats) {
          playerType = 'Hitter'
          recommendedStats = {
            type: 'batting',
            runs: battingStats.runs,
            hits: battingStats.hits,
            homeRuns: battingStats.homeRuns,
            rbi: battingStats.rbi,
            stolenBases: battingStats.stolenBases,
            battingAverage: battingStats.battingAverage,
            onBasePercentage: battingStats.onBasePercentage,
            totalBases: battingStats.totalBases
          }
        }
        
        results.push({
          player: mlbPlayer.fullName,
          mlbId: mlbPlayer.id,
          mlbPosition: mlbPlayer.primaryPosition?.abbreviation,
          classification: playerType,
          hasPitchingStats,
          hasBattingStats,
          recommendedStats
        })
        
      } else {
        console.log(`   ❌ Not found in MLB API`)
        results.push({
          player: playerName,
          mlbId: null,
          mlbPosition: null,
          classification: 'Not Found',
          hasPitchingStats: false,
          hasBattingStats: false,
          recommendedStats: null
        })
      }
    }
    
    console.log('\n' + '=' * 80)
    console.log('🎯 PLAYER CLASSIFICATION DEBUG COMPLETE')
    
    return NextResponse.json({
      success: true,
      message: 'Player classification analysis complete',
      results,
      summary: {
        totalAnalyzed: results.length,
        pitchers: results.filter(p => p.classification === 'Pitcher').length,
        hitters: results.filter(p => p.classification === 'Hitter').length,
        notFound: results.filter(p => p.classification === 'Not Found').length
      }
    })
    
  } catch (error) {
    console.error('Error in player classification debug:', error)
    return NextResponse.json({ 
      error: error instanceof Error ? error.message : 'Failed to debug player classification' 
    }, { status: 500 })
  }
}