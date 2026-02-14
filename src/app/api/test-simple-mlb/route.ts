import { NextRequest, NextResponse } from 'next/server'

export async function POST(request: NextRequest) {
  try {
    console.log('🔍 Testing simple MLB API calls')
    
    // Test direct MLB API call for a known relief pitcher (Edwin Diaz)
    const response = await fetch('http://statsapi.mlb.com/api/v1/people/621242/stats?stats=season&season=2024&group=pitching')
    const data = await response.json()
    
    console.log('MLB API Response:', JSON.stringify(data, null, 2))
    
    const stats = data.stats?.[0]?.splits?.[0]?.stat
    
    return NextResponse.json({
      success: true,
      playerData: data,
      extractedStats: {
        saves: stats?.saves,
        holds: stats?.holds,
        qualityStarts: stats?.qualityStarts,
        games: stats?.games,
        era: stats?.era
      }
    })
  } catch (error) {
    console.error('Error:', error)
    return NextResponse.json({ 
      error: error instanceof Error ? error.message : 'Failed to test MLB API' 
    }, { status: 500 })
  }
}