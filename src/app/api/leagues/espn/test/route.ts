import { NextRequest, NextResponse } from 'next/server'

export async function POST(request: NextRequest) {
  try {
    const { leagueId, season, swid, espn_s2 } = await request.json()

    console.log('Testing ESPN API with:', {
      leagueId,
      season,
      swid,
      espn_s2_length: espn_s2?.length,
      espn_s2_start: espn_s2?.substring(0, 20) + '...'
    })

    // Test different game codes and seasons
    const testCases = [
      { game: 'flb', season: '2024' },
      { game: 'flb', season: '2025' },
      { game: 'FLB', season: '2024' },
      { game: 'FLB', season: '2025' }
    ]

    const results = []

    for (const testCase of testCases) {
      const url = `https://lm-api-reads.fantasy.espn.com/apis/v3/games/${testCase.game}/seasons/${testCase.season}/segments/0/leagues/${leagueId}`
      
      try {
        const response = await fetch(url, {
          headers: {
            'Cookie': `swid=${swid}; espn_s2=${espn_s2}`,
            'Content-Type': 'application/json'
          }
        })

        const data = await response.text()
        
        results.push({
          testCase,
          url,
          status: response.status,
          success: response.ok,
          dataPreview: data.substring(0, 200) + (data.length > 200 ? '...' : '')
        })

        if (response.ok) {
          // If successful, try to parse and return the full data
          try {
            const parsedData = JSON.parse(data)
            results[results.length - 1].parsedKeys = Object.keys(parsedData)
          } catch (e) {
            // data might not be JSON
          }
        }
      } catch (error) {
        results.push({
          testCase,
          url,
          error: error instanceof Error ? error.message : 'Unknown error'
        })
      }
    }

    return NextResponse.json({ 
      message: 'ESPN API test completed',
      results
    })

  } catch (error) {
    console.error('Test endpoint error:', error)
    return NextResponse.json({ 
      error: error instanceof Error ? error.message : 'Test failed' 
    }, { status: 500 })
  }
}