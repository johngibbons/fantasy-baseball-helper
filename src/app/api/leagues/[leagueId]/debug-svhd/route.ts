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

    const league = await prisma.league.findUnique({
      where: { id: leagueId }
    })

    if (!league) {
      return NextResponse.json({ 
        error: 'League not found' 
      }, { status: 404 })
    }

    console.log('🔍 SVHD DISCOVERY: Looking for Saves + Holds stat IDs')
    console.log('='*80)

    const settings = { swid, espn_s2 }
    const rosters = await ESPNApi.getRosters(league.externalId, league.season, settings)
    
    // Target relief pitchers with known SV + HD values
    const targetPitchers = {
      'Tyler Rogers': { expectedSV: 1, expectedHD: 19, expectedSVHD: 20 },
      'Ronny Henriquez': { expectedSV: 5, expectedHD: 13, expectedSVHD: 18 },
      'Randy Rodriguez': { expectedSV: 0, expectedHD: 14, expectedSVHD: 14 },
      'Kris Bubic': { expectedSV: 1, expectedHD: 0, expectedSVHD: 1 } // Mixed SP/RP
    }

    const results: any[] = []

    for (const [teamId, teamRoster] of Object.entries(rosters)) {
      if (Array.isArray(teamRoster)) {
        for (const rosterEntry of teamRoster) {
          if (rosterEntry.player) {
            const espnPlayer = rosterEntry.player
            
            const targetInfo = Object.entries(targetPitchers).find(([name]) => 
              espnPlayer.fullName.includes(name)
            )?.[1]

            if (targetInfo) {
              console.log(`\\n🎯 ANALYZING: ${espnPlayer.fullName}`)
              console.log(`   Expected: SV=${targetInfo.expectedSV} + HD=${targetInfo.expectedHD} = SVHD=${targetInfo.expectedSVHD}`)
              
              if (espnPlayer.stats && espnPlayer.stats.length > 0) {
                const statPeriod = espnPlayer.stats[0]
                if (statPeriod && statPeriod.stats) {
                  const espnStats = statPeriod.stats
                  const allStats = Object.keys(espnStats).sort((a,b) => parseInt(a) - parseInt(b))
                  
                  // Look for Saves matches
                  const savesMatches: any[] = []
                  allStats.forEach(key => {
                    if (Math.abs(espnStats[key] - targetInfo.expectedSV) < 0.1) {
                      savesMatches.push({ statId: key, value: espnStats[key] })
                      console.log(`   ⭐ SAVES MATCH: Stat ID ${key} = ${espnStats[key]} (expected SV=${targetInfo.expectedSV})`)
                    }
                  })
                  
                  // Look for Holds matches  
                  const holdsMatches: any[] = []
                  allStats.forEach(key => {
                    if (Math.abs(espnStats[key] - targetInfo.expectedHD) < 0.1) {
                      holdsMatches.push({ statId: key, value: espnStats[key] })
                      console.log(`   ⭐ HOLDS MATCH: Stat ID ${key} = ${espnStats[key]} (expected HD=${targetInfo.expectedHD})`)
                    }
                  })
                  
                  // Look for direct SVHD matches (just in case ESPN has it)
                  const svhdMatches: any[] = []
                  allStats.forEach(key => {
                    if (Math.abs(espnStats[key] - targetInfo.expectedSVHD) < 0.1) {
                      svhdMatches.push({ statId: key, value: espnStats[key] })
                      console.log(`   ⭐ SVHD DIRECT MATCH: Stat ID ${key} = ${espnStats[key]} (expected SVHD=${targetInfo.expectedSVHD})`)
                    }
                  })
                  
                  // Check for combination possibilities
                  console.log(`   🧮 Checking all SV + HD combinations:`)
                  for (const svMatch of savesMatches) {
                    for (const hdMatch of holdsMatches) {
                      const calculated = svMatch.value + hdMatch.value
                      if (Math.abs(calculated - targetInfo.expectedSVHD) < 0.1) {
                        console.log(`   🎯 PERFECT COMBO: Stat ${svMatch.statId} (${svMatch.value}) + Stat ${hdMatch.statId} (${hdMatch.value}) = ${calculated}`)
                      }
                    }
                  }
                  
                  results.push({
                    player: espnPlayer.fullName,
                    expected: targetInfo,
                    savesMatches,
                    holdsMatches,
                    svhdMatches,
                    allStatCount: allStats.length
                  })
                  
                  // Show some high-value stats that might be relevant
                  console.log(`   📊 High-value stats (might be SV/HD/SVHD):`)
                  allStats.forEach(key => {
                    const value = espnStats[key]
                    if (value > 0 && value <= 50) { // Reasonable range for saves/holds
                      console.log(`      Stat ${key}: ${value}`)
                    }
                  })
                }
              }
            }
          }
        }
      }
    }

    console.log('\\n' + '='*80)
    console.log('🎯 SVHD DISCOVERY COMPLETE')
    
    return NextResponse.json({
      success: true,
      message: 'SVHD analysis complete - check console for SV/HD stat ID matches',
      results,
      summary: {
        pitchersAnalyzed: results.length,
        totalMatches: results.reduce((sum, p) => sum + p.savesMatches.length + p.holdsMatches.length, 0)
      }
    })

  } catch (error) {
    console.error('Error in SVHD analysis:', error)
    return NextResponse.json({ 
      error: error instanceof Error ? error.message : 'Failed to analyze SVHD data' 
    }, { status: 500 })
  }
}