import { NextRequest, NextResponse } from 'next/server'
import { ESPNApi } from '@/lib/espn-api'

export async function POST(request: NextRequest) {
  try {
    const { swid, espn_s2, leagueId = '77166', season = '2025' } = await request.json()

    if (!swid || !espn_s2) {
      return NextResponse.json({ 
        error: 'ESPN credentials required' 
      }, { status: 400 })
    }

    console.log('🔍 Debugging ESPN position data')
    console.log('=' * 80)

    const settings = { swid, espn_s2 }
    const rosters = await ESPNApi.getRosters(leagueId, season, settings)
    
    const problemPlayers = ['Juan Soto', 'Seiya Suzuki', 'Marcus Semien', 'Lawrence Butler']
    const results: any[] = []

    for (const [teamId, teamRoster] of Object.entries(rosters)) {
      if (Array.isArray(teamRoster)) {
        for (const rosterEntry of teamRoster) {
          if (rosterEntry.player) {
            const espnPlayer = rosterEntry.player
            
            // Check if this is one of our problem players
            const isProblemPlayer = problemPlayers.some(name => 
              espnPlayer.fullName?.includes(name.split(' ')[1]) // Check by last name
            )
            
            if (isProblemPlayer) {
              console.log(`\n🎯 FOUND: ${espnPlayer.fullName}`)
              console.log(`   ESPN defaultPositionId: ${espnPlayer.defaultPositionId}`)
              console.log(`   ESPN eligibleSlots: ${JSON.stringify(espnPlayer.eligibleSlots)}`)
              console.log(`   Roster lineupSlotId: ${rosterEntry.lineupSlotId}`)
              
              // Apply our position logic
              const positionIdMap: { [key: number]: string } = {
                0: 'C', 1: '1B', 2: '2B', 3: '3B', 4: 'SS', 5: 'OF', 
                6: 'OF', 7: 'OF', 8: 'DH', 9: 'SP', 10: 'RP', 11: 'P'
              }
              
              let primaryPosition = positionIdMap[espnPlayer.defaultPositionId] || 'UTIL'
              
              // Enhanced position detection using eligibleSlots
              if (espnPlayer.eligibleSlots && espnPlayer.eligibleSlots.length > 0) {
                const hasPitcherSlots = espnPlayer.eligibleSlots.some(slot => slot >= 9 && slot <= 11)
                const hasPositionSlots = espnPlayer.eligibleSlots.some(slot => slot < 9)
                
                console.log(`   hasPitcherSlots: ${hasPitcherSlots}`)
                console.log(`   hasPositionSlots: ${hasPositionSlots}`)
                
                if (hasPitcherSlots && !hasPositionSlots) {
                  // Pure pitcher
                  if (espnPlayer.eligibleSlots.includes(9)) primaryPosition = 'SP'
                  else if (espnPlayer.eligibleSlots.includes(10)) primaryPosition = 'RP'
                  else primaryPosition = 'P'
                } else if (hasPositionSlots && !hasPitcherSlots) {
                  // Pure position player
                  const positionSlot = espnPlayer.eligibleSlots.find(slot => slot < 9)
                  if (positionSlot !== undefined) {
                    primaryPosition = positionIdMap[positionSlot] || primaryPosition
                  }
                }
              }
              
              console.log(`   Final primaryPosition: ${primaryPosition}`)
              console.log(`   Should be pitcher: ${primaryPosition === 'SP' || primaryPosition === 'RP' || primaryPosition === 'P'}`)
              
              results.push({
                player: espnPlayer.fullName,
                espnId: espnPlayer.id,
                defaultPositionId: espnPlayer.defaultPositionId,
                eligibleSlots: espnPlayer.eligibleSlots,
                lineupSlotId: rosterEntry.lineupSlotId,
                calculatedPosition: primaryPosition,
                shouldBePitcher: primaryPosition === 'SP' || primaryPosition === 'RP' || primaryPosition === 'P'
              })
            }
          }
        }
      }
    }

    console.log('\n' + '=' * 80)
    console.log('🎯 ESPN POSITION DEBUG COMPLETE')

    return NextResponse.json({
      success: true,
      message: 'ESPN position debug complete',
      results,
      summary: {
        playersAnalyzed: results.length,
        incorrectlyClassifiedAsPitchers: results.filter(p => p.shouldBePitcher && 
          ['Juan Soto', 'Seiya Suzuki', 'Marcus Semien', 'Lawrence Butler'].some(name => 
            p.player.includes(name.split(' ')[1])
          )
        ).length
      }
    })

  } catch (error) {
    console.error('Error debugging ESPN positions:', error)
    return NextResponse.json({ 
      error: error instanceof Error ? error.message : 'Failed to debug ESPN positions' 
    }, { status: 500 })
  }
}