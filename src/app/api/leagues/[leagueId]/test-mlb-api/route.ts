// @ts-nocheck
import { NextRequest, NextResponse } from 'next/server'

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ leagueId: string }> }
) {
  try {
    const { leagueId } = await params
    
    console.log('🔍 Testing MLB Stats API for Saves/Holds data')
    console.log('='.repeat(80))
    
    // Test target relief pitchers with known saves/holds values
    const targetPlayers = {
      'Tyler Rogers': { teamId: 137, expectedSV: 1, expectedHD: 19 }, // Giants
      'Ronny Henriquez': { teamId: 142, expectedSV: 5, expectedHD: 13 } // Twins
    }
    
    const results: any[] = []
    
    // Test MLB Stats API endpoints
    const baseUrl = 'http://statsapi.mlb.com/api/v1'
    
    for (const [playerName, info] of Object.entries(targetPlayers)) {
      console.log(`\n🎯 Testing ${playerName} (Team ${info.teamId})`)
      
      try {
        // Get team roster to find player ID
        const rosterResponse = await fetch(`${baseUrl}/teams/${info.teamId}/roster?season=2024`)
        const rosterData = await rosterResponse.json()
        
        console.log(`   Roster data:`, rosterData?.roster?.length, 'players')
        
        // Find player by name
        const player = rosterData?.roster?.find((p: any) => 
          p.person?.fullName?.includes(playerName.split(' ')[1]) // Search by last name
        )
        
        if (player) {
          console.log(`   Found player: ${player.person.fullName} (ID: ${player.person.id})`)
          
          // Get player stats
          const statsResponse = await fetch(`${baseUrl}/people/${player.person.id}/stats?stats=season&season=2024&group=pitching`)
          const statsData = await statsResponse.json()
          
          console.log(`   Stats data:`, JSON.stringify(statsData, null, 2))
          
          // Look for saves and holds in the stats
          const pitchingStats = statsData?.stats?.[0]?.splits?.[0]?.stat
          if (pitchingStats) {
            console.log(`   📊 Pitching Stats:`)
            console.log(`      Saves: ${pitchingStats.saves || 'N/A'}`)
            console.log(`      Holds: ${pitchingStats.holds || 'N/A'}`)
            console.log(`      Games: ${pitchingStats.games || 'N/A'}`)
            console.log(`      Games Started: ${pitchingStats.gamesStarted || 'N/A'}`)
            console.log(`      Quality Starts: ${pitchingStats.qualityStarts || 'N/A'}`)
            
            results.push({
              player: player.person.fullName,
              playerId: player.person.id,
              expected: info,
              actual: {
                saves: pitchingStats.saves,
                holds: pitchingStats.holds,
                qualityStarts: pitchingStats.qualityStarts
              },
              source: 'MLB Stats API'
            })
          }
        } else {
          console.log(`   ❌ Player not found in roster`)
        }
        
      } catch (playerError) {
        console.error(`   Error fetching data for ${playerName}:`, playerError)
      }
    }
    
    console.log('\n' + '='.repeat(80))
    console.log('🎯 MLB API TEST COMPLETE')
    
    return NextResponse.json({
      success: true,
      message: 'MLB Stats API test complete - check console for results',
      results,
      summary: {
        playersAnalyzed: results.length,
        dataSource: 'MLB Stats API',
        apiEndpoint: baseUrl
      }
    })
    
  } catch (error) {
    console.error('Error testing MLB API:', error)
    return NextResponse.json({ 
      error: error instanceof Error ? error.message : 'Failed to test MLB API' 
    }, { status: 500 })
  }
}