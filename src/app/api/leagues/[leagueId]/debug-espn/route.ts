// @ts-nocheck
import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { ESPNApi } from '@/lib/espn-api'

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ leagueId: string }> }
) {
  try {
    const { leagueId } = await params
    const body = await request.json()
    const { swid, espn_s2 } = body

    if (!swid || !espn_s2) {
      return NextResponse.json({ 
        error: 'ESPN credentials (swid and espn_s2) are required' 
      }, { status: 400 })
    }

    // Get league info
    const league = await prisma.league.findUnique({
      where: { id: leagueId }
    })

    if (!league) {
      return NextResponse.json({ 
        error: 'League not found' 
      }, { status: 404 })
    }

    console.log('🔍 ESPN STAT ID DISCOVERY MODE - READ ONLY')
    console.log('='*80)

    const settings = { swid, espn_s2 }
    
    // Fetch ESPN data but don't save anything
    const rosters = await ESPNApi.getRosters(league.externalId, league.season, settings)
    
    const analysisResults: any[] = []
    const targetPlayers = [
      'Max Fried', 'Tyler Rogers', 'Cole Ragans', 'Framber Valdez',
      'Juan Soto', 'Jackson Chourio', 'Kris Bubic', 'Randy Rodriguez'
    ]

    // Analyze specific players
    for (const [teamId, teamRoster] of Object.entries(rosters)) {
      if (Array.isArray(teamRoster)) {
        for (const rosterEntry of teamRoster) {
          if (rosterEntry.player) {
            const espnPlayer = rosterEntry.player
            
            if (targetPlayers.some(name => espnPlayer.fullName.includes(name))) {
              console.log(`\\n🎯 ANALYZING: ${espnPlayer.fullName}`)
              
              if (espnPlayer.stats && espnPlayer.stats.length > 0) {
                const statPeriod = espnPlayer.stats[0]
                if (statPeriod && statPeriod.stats) {
                  const espnStats = statPeriod.stats
                  
                  // Expected values for matching
                  const expectedValues: { [key: string]: { qs?: number, svhd?: number, obp?: number } } = {
                    'Max Fried': { qs: 13, svhd: 0 },
                    'Tyler Rogers': { qs: 0, svhd: 20 },
                    'Cole Ragans': { qs: 2, svhd: 0 },
                    'Framber Valdez': { qs: 14, svhd: 0 },
                    'Kris Bubic': { qs: 11, svhd: 0 },
                    'Randy Rodriguez': { qs: 0, svhd: 14 },
                    'Juan Soto': { obp: 0.391 },
                    'Jackson Chourio': { obp: 0.297 }
                  }
                  
                  const expected = expectedValues[espnPlayer.fullName]
                  const allStats = Object.keys(espnStats).sort((a,b) => parseInt(a) - parseInt(b))
                  
                  console.log(`   All ESPN stat keys (${allStats.length}):`, allStats.join(', '))
                  
                  const playerAnalysis = {
                    player: espnPlayer.fullName,
                    position: espnPlayer.defaultPositionId,
                    totalStatKeys: allStats.length,
                    allStats: {} as any,
                    matches: [] as any[]
                  }
                  
                  // Record all stats
                  allStats.forEach(key => {
                    playerAnalysis.allStats[key] = espnStats[key]
                  })
                  
                  // Look for value matches
                  if (expected) {
                    if (expected.qs !== undefined) {
                      allStats.forEach(key => {
                        if (Math.abs(espnStats[key] - expected.qs) < 0.1) {
                          const match = { type: 'QS', expectedValue: expected.qs, statId: key, actualValue: espnStats[key] }
                          playerAnalysis.matches.push(match)
                          console.log(`   ⭐ QS MATCH: Stat ID ${key} = ${espnStats[key]} (expected ${expected.qs})`)
                        }
                      })
                    }
                    
                    if (expected.svhd !== undefined) {
                      allStats.forEach(key => {
                        if (Math.abs(espnStats[key] - expected.svhd) < 0.1) {
                          const match = { type: 'SVHD', expectedValue: expected.svhd, statId: key, actualValue: espnStats[key] }
                          playerAnalysis.matches.push(match)
                          console.log(`   ⭐ SVHD MATCH: Stat ID ${key} = ${espnStats[key]} (expected ${expected.svhd})`)
                        }
                      })
                    }
                    
                    if (expected.obp !== undefined) {
                      allStats.forEach(key => {
                        if (Math.abs(espnStats[key] - expected.obp) < 0.05) {
                          const match = { type: 'OBP', expectedValue: expected.obp, statId: key, actualValue: espnStats[key] }
                          playerAnalysis.matches.push(match)
                          console.log(`   ⭐ OBP MATCH: Stat ID ${key} = ${espnStats[key]} (expected ~${expected.obp})`)
                        }
                      })
                    }
                  }
                  
                  analysisResults.push(playerAnalysis)
                }
              }
            }
          }
        }
      }
    }

    console.log('\\n' + '='*80)
    console.log('🎯 ESPN STAT ID DISCOVERY COMPLETE')
    
    return NextResponse.json({
      success: true,
      message: 'ESPN stat analysis complete - check console logs for detailed results',
      analysisResults,
      summary: {
        playersAnalyzed: analysisResults.length,
        totalMatches: analysisResults.reduce((sum, p) => sum + p.matches.length, 0)
      }
    })

  } catch (error) {
    console.error('Error in ESPN debug analysis:', error)
    return NextResponse.json({ 
      error: error instanceof Error ? error.message : 'Failed to analyze ESPN data' 
    }, { status: 500 })
  }
}