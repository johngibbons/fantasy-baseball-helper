import { NextRequest, NextResponse } from 'next/server'
import { ESPNApi } from '@/lib/espn-api'
import { prisma } from '@/lib/prisma'

function generateTeamName(espnTeam: any): string {
  // Try multiple strategies to get a meaningful team name
  
  // Strategy 1: Use location + nickname
  const locationName = espnTeam.location?.trim()
  const nickname = espnTeam.nickname?.trim()
  
  if (locationName && nickname) {
    return `${locationName} ${nickname}`
  }
  
  // Strategy 2: Use just nickname if it exists
  if (nickname) {
    return nickname
  }
  
  // Strategy 3: Use just location if it exists
  if (locationName) {
    return locationName
  }
  
  // Strategy 4: Use abbreviation if it exists
  if (espnTeam.abbrev?.trim()) {
    return `Team ${espnTeam.abbrev.trim()}`
  }
  
  // Strategy 5: Use team ID as last resort
  if (espnTeam.id) {
    return `Team ${espnTeam.id}`
  }
  
  // Fallback
  return 'Unknown Team'
}

function generateOwnerName(espnTeam: any): string | null {
  // ESPN API sometimes returns owner IDs instead of names
  // Try to extract meaningful owner information
  
  const rawOwner = espnTeam.owners?.[0]
  
  if (!rawOwner) {
    return null
  }
  
  const trimmedOwner = rawOwner.trim()
  
  // Check if it looks like a GUID/ID (common patterns)
  const isGuidPattern = /^[\{\(]?[A-F0-9]{8}[-]?[A-F0-9]{4}[-]?[A-F0-9]{4}[-]?[A-F0-9]{4}[-]?[A-F0-9]{12}[\}\)]?$/i
  const isShortIdPattern = /^[A-Z0-9]{8,}$/i
  
  if (isGuidPattern.test(trimmedOwner) || isShortIdPattern.test(trimmedOwner)) {
    // This looks like an ID, not a readable name
    return null
  }
  
  // Check for other non-readable patterns
  if (trimmedOwner.length < 2 || trimmedOwner.includes('$') || trimmedOwner.includes('#')) {
    return null
  }
  
  // If it passes our checks, assume it's a readable name
  return trimmedOwner
}

export async function POST(request: NextRequest) {
  try {
    console.log('ESPN connect endpoint called')
    
    const body = await request.json()
    console.log('Request body:', { ...body, espn_s2: body.espn_s2 ? '[REDACTED]' : undefined })
    
    const { leagueId, season, swid, espn_s2 } = body

    if (!leagueId || !season || !swid || !espn_s2) {
      console.log('Missing required fields')
      return NextResponse.json({ error: 'Missing required fields' }, { status: 400 })
    }

    const settings = { swid, espn_s2 }

    console.log('Testing ESPN API connection...')
    
    // Test the connection first
    let isConnected: boolean
    try {
      isConnected = await ESPNApi.testConnection(leagueId, season, settings)
    } catch (connectionError) {
      console.error('ESPN API connection error:', connectionError)
      return NextResponse.json({ 
        error: `ESPN API connection failed: ${connectionError instanceof Error ? connectionError.message : 'Unknown error'}` 
      }, { status: 400 })
    }
    
    if (!isConnected) {
      console.log('ESPN connection test failed')
      return NextResponse.json({ 
        error: 'Unable to connect to ESPN league. Please check your credentials and league ID.' 
      }, { status: 400 })
    }

    console.log('ESPN connection test passed')

    // Fetch league data
    console.log('Fetching league data...')
    const espnLeague = await ESPNApi.getLeague(leagueId, season, settings)
    console.log('League data:', JSON.stringify(espnLeague, null, 2))
    
    console.log('Fetching teams data...')
    const teams = await ESPNApi.getTeams(leagueId, season, settings)
    console.log('Teams data:', JSON.stringify(teams, null, 2))
    
    console.log('Fetching rosters data...')
    const rosters = await ESPNApi.getRosters(leagueId, season, settings)
    console.log('Rosters data:', JSON.stringify(rosters, null, 2))

    // Store league in database
    console.log('Storing league in database...')
    console.log('League settings:', espnLeague.settings)
    console.log('League status:', espnLeague.status || 'undefined')
    console.log('League root keys:', Object.keys(espnLeague))
    
    // Debug Prisma client
    console.log('Prisma client available models:', Object.keys(prisma))
    console.log('Prisma league model available:', !!prisma.league)
    
    // Try to find existing league first
    const existingLeague = await prisma.league.findUnique({
      where: {
        platform_externalId_season: {
          platform: 'ESPN',
          externalId: leagueId,
          season
        }
      }
    })

    const leagueData = {
      name: espnLeague.settings?.name || 'Unknown League',
      teamCount: espnLeague.settings?.size || 0,
      lastSyncAt: new Date(),
      settings: {
        currentMatchupPeriod: espnLeague.status?.currentMatchupPeriod || espnLeague.currentMatchupPeriod || 0,
        finalScoringPeriod: espnLeague.status?.finalScoringPeriod || espnLeague.finalScoringPeriod || 0,
        isActive: espnLeague.status?.isActive ?? espnLeague.isActive ?? true,
        latestScoringPeriod: espnLeague.status?.latestScoringPeriod || espnLeague.latestScoringPeriod || 0
      }
    }

    const league = existingLeague 
      ? await prisma.league.update({
          where: { id: existingLeague.id },
          data: leagueData
        })
      : await prisma.league.create({
          data: {
            id: `espn_${leagueId}_${season}`,
            platform: 'ESPN',
            externalId: leagueId,
            season,
            ...leagueData
          }
        })
    
    console.log('League stored successfully:', league.id)

    // Store teams
    console.log('Processing teams...')
    for (const espnTeam of teams || []) {
      console.log('Processing team:', espnTeam.id, espnTeam.location, espnTeam.nickname)
      
      const team = await prisma.team.upsert({
        where: {
          leagueId_externalId: {
            leagueId: league.id,
            externalId: espnTeam.id?.toString() || '0'
          }
        },
        update: {
          name: generateTeamName(espnTeam),
          ownerName: generateOwnerName(espnTeam),
          wins: espnTeam.record?.overall?.wins || 0,
          losses: espnTeam.record?.overall?.losses || 0,
          ties: espnTeam.record?.overall?.ties || 0,
          pointsFor: espnTeam.record?.overall?.pointsFor || 0,
          pointsAgainst: espnTeam.record?.overall?.pointsAgainst || 0
        },
        create: {
          leagueId: league.id,
          externalId: espnTeam.id?.toString() || '0',
          name: generateTeamName(espnTeam),
          ownerName: generateOwnerName(espnTeam),
          wins: espnTeam.record?.overall?.wins || 0,
          losses: espnTeam.record?.overall?.losses || 0,
          ties: espnTeam.record?.overall?.ties || 0,
          pointsFor: espnTeam.record?.overall?.pointsFor || 0,
          pointsAgainst: espnTeam.record?.overall?.pointsAgainst || 0
        }
      })
      
      console.log('Team stored:', team.id)

      // Store roster entries
      const teamRoster = rosters[espnTeam.id]
      console.log(`Processing roster for team ${espnTeam.id}, found ${teamRoster?.length || 0} players`)
      
      if (teamRoster && Array.isArray(teamRoster)) {
        for (const rosterEntry of teamRoster) {
          try {
            // Map lineup slot IDs to position names
            const positionMap: { [key: number]: string } = {
              0: 'C', 1: '1B', 2: '2B', 3: '3B', 4: 'SS', 5: 'OF', 6: 'OF', 7: 'OF',
              8: 'UTIL', 9: 'SP', 10: 'SP', 11: 'RP', 12: 'RP', 13: 'P', 20: 'BENCH'
            }

            const position = positionMap[rosterEntry.lineupSlotId] || 'BENCH'

            await prisma.rosterSlot.upsert({
              where: {
                teamId_playerId_season: {
                  teamId: team.id,
                  playerId: rosterEntry.playerId || 0,
                  season
                }
              },
              update: {
                position,
                acquisitionType: rosterEntry.acquisitionType || 'UNKNOWN',
                acquisitionDate: rosterEntry.acquisitionDate ? new Date(rosterEntry.acquisitionDate) : new Date()
              },
              create: {
                teamId: team.id,
                playerId: rosterEntry.playerId || 0,
                season,
                position,
                acquisitionType: rosterEntry.acquisitionType || 'UNKNOWN',
                acquisitionDate: rosterEntry.acquisitionDate ? new Date(rosterEntry.acquisitionDate) : new Date()
              }
            })
          } catch (rosterError) {
            console.error('Error processing roster entry:', rosterError, rosterEntry)
          }
        }
      }
    }

    return NextResponse.json({ 
      success: true,
      league: {
        id: league.id,
        name: league.name,
        platform: league.platform,
        season: league.season,
        teamCount: league.teamCount
      }
    })

  } catch (error) {
    console.error('Error connecting ESPN league:', error)
    return NextResponse.json({ 
      error: error instanceof Error ? error.message : 'Failed to connect to ESPN league' 
    }, { status: 500 })
  }
}