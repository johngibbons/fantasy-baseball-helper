import { NextRequest, NextResponse } from 'next/server'
import { MLBStatsApi } from '@/lib/mlb-stats-api'

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ leagueId: string }> }
) {
  try {
    const { leagueId } = await params
    
    console.log('🎯 DEMO: Hybrid approach for accurate SVHD calculation')
    console.log('=' * 80)
    
    // Demo players that we know have save/hold data
    const demoPlayers = [
      'Tyler Rogers',
      'Ronny Henriquez', 
      'Randy Rodriguez',
      'Edwin Diaz',
      'Josh Hader'
    ]
    
    const results: any[] = []
    
    for (const playerName of demoPlayers) {
      console.log(`\n🔍 Analyzing ${playerName}...`)
      
      // Step 1: Find player using MLB API
      const mlbPlayer = await MLBStatsApi.findPlayerByName(playerName, 2024)
      
      if (mlbPlayer) {
        console.log(`   ✅ Found: ${mlbPlayer.fullName} (ID: ${mlbPlayer.id})`)
        
        // Step 2: Get pitching stats including saves/holds
        const pitchingStats = await MLBStatsApi.getPlayerPitchingStats(mlbPlayer.id, 2024)
        
        if (pitchingStats) {
          const svhd = (pitchingStats.saves || 0) + (pitchingStats.holds || 0)
          
          console.log(`   📊 Stats: SV=${pitchingStats.saves}, HD=${pitchingStats.holds}, SVHD=${svhd}`)
          console.log(`   📊 Other: QS=${pitchingStats.qualityStarts}, ERA=${pitchingStats.era}, WHIP=${pitchingStats.whip}`)
          
          results.push({
            player: mlbPlayer.fullName,
            playerId: mlbPlayer.id,
            position: mlbPlayer.primaryPosition?.abbreviation,
            stats: {
              saves: pitchingStats.saves,
              holds: pitchingStats.holds,
              svhd: svhd,
              qualityStarts: pitchingStats.qualityStarts,
              wins: pitchingStats.wins,
              losses: pitchingStats.losses,
              era: pitchingStats.era,
              whip: pitchingStats.whip,
              strikeOuts: pitchingStats.strikeOuts,
              games: pitchingStats.games,
              gamesStarted: pitchingStats.gamesStarted
            },
            dataSource: 'MLB Stats API'
          })
        } else {
          console.log(`   ❌ No pitching stats found`)
        }
      } else {
        console.log(`   ❌ Player not found in MLB API`)
      }
    }
    
    console.log('\n' + '=' * 80)
    console.log('🎯 DEMO COMPLETE: MLB API provides accurate saves/holds data')
    console.log(`   Total players analyzed: ${results.length}`)
    console.log(`   Average SVHD per player: ${(results.reduce((sum, p) => sum + p.stats.svhd, 0) / results.length).toFixed(1)}`)
    
    return NextResponse.json({
      success: true,
      message: 'Hybrid approach demo complete - check console for detailed results',
      results,
      summary: {
        playersAnalyzed: results.length,
        dataSource: 'MLB Stats API',
        approach: 'Hybrid (MLB stats + ESPN rosters)',
        benefits: [
          'Accurate Saves + Holds calculation',
          'Quality Starts data available', 
          'Official MLB statistics',
          'No ESPN stat ID guesswork needed'
        ]
      }
    })
    
  } catch (error) {
    console.error('Error in hybrid demo:', error)
    return NextResponse.json({ 
      error: error instanceof Error ? error.message : 'Failed to run hybrid demo' 
    }, { status: 500 })
  }
}