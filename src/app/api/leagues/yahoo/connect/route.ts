import { NextRequest, NextResponse } from 'next/server'
import { YahooApi } from '@/lib/yahoo-api'
import { prisma } from '@/lib/prisma'

export async function POST(request: NextRequest) {
  try {
    const { accessToken, season = '2024' } = await request.json()

    if (!accessToken) {
      return NextResponse.json({ error: 'Access token is required' }, { status: 400 })
    }

    const tokens = { accessToken }

    // Test the connection first
    const isConnected = await YahooApi.testConnection(tokens)
    if (!isConnected) {
      return NextResponse.json({ 
        error: 'Unable to connect to Yahoo Fantasy. Please check your access token.' 
      }, { status: 400 })
    }

    // Fetch user's leagues
    const yahooLeagues = await YahooApi.getUserLeagues(tokens, season)
    
    if (yahooLeagues.length === 0) {
      return NextResponse.json({ 
        error: 'No fantasy baseball leagues found for the specified season.' 
      }, { status: 404 })
    }

    const connectedLeagues = []

    // Process each league
    for (const yahooLeague of yahooLeagues) {
      // Store league in database
      const league = await prisma.league.upsert({
        where: {
          platform_externalId_season: {
            platform: 'YAHOO',
            externalId: yahooLeague.league_id,
            season: yahooLeague.season
          }
        },
        update: {
          name: yahooLeague.name,
          teamCount: yahooLeague.num_teams,
          lastSyncAt: new Date(),
          settings: {
            game_code: yahooLeague.game_code,
            is_finished: yahooLeague.is_finished,
            url: yahooLeague.url
          }
        },
        create: {
          id: `yahoo_${yahooLeague.league_id}_${yahooLeague.season}`,
          name: yahooLeague.name,
          platform: 'YAHOO',
          externalId: yahooLeague.league_id,
          season: yahooLeague.season,
          teamCount: yahooLeague.num_teams,
          lastSyncAt: new Date(),
          settings: {
            game_code: yahooLeague.game_code,
            is_finished: yahooLeague.is_finished,
            url: yahooLeague.url
          }
        }
      })

      try {
        // Fetch teams for this league
        const teams = await YahooApi.getLeagueTeams(yahooLeague.league_key, tokens)

        // Store teams
        for (const yahooTeam of teams) {
          const team = await prisma.team.upsert({
            where: {
              leagueId_externalId: {
                leagueId: league.id,
                externalId: yahooTeam.team_id
              }
            },
            update: {
              name: yahooTeam.name,
              ownerName: yahooTeam.manager,
              wins: yahooTeam.wins,
              losses: yahooTeam.losses,
              ties: yahooTeam.ties,
              pointsFor: yahooTeam.points_for,
              pointsAgainst: yahooTeam.points_against
            },
            create: {
              leagueId: league.id,
              externalId: yahooTeam.team_id,
              name: yahooTeam.name,
              ownerName: yahooTeam.manager,
              wins: yahooTeam.wins,
              losses: yahooTeam.losses,
              ties: yahooTeam.ties,
              pointsFor: yahooTeam.points_for,
              pointsAgainst: yahooTeam.points_against
            }
          })

          try {
            // Fetch roster for this team
            const roster = await YahooApi.getTeamRoster(yahooTeam.team_key, tokens)

            // Store roster entries
            for (const player of roster) {
              // Extract player ID from player_key (format: "431.p.12345")
              const playerId = parseInt(player.player_id)
              
              if (!isNaN(playerId)) {
                await prisma.rosterSlot.upsert({
                  where: {
                    teamId_playerId_season: {
                      teamId: team.id,
                      playerId: playerId,
                      season: yahooLeague.season
                    }
                  },
                  update: {
                    position: player.selected_position || 'BENCH',
                    acquisitionType: 'UNKNOWN' // Yahoo API doesn't provide this easily
                  },
                  create: {
                    teamId: team.id,
                    playerId: playerId,
                    season: yahooLeague.season,
                    position: player.selected_position || 'BENCH',
                    acquisitionType: 'UNKNOWN'
                  }
                })
              }
            }
          } catch (rosterError) {
            console.warn(`Failed to fetch roster for team ${yahooTeam.team_id}:`, rosterError)
            // Continue with other teams even if one fails
          }
        }
      } catch (teamsError) {
        console.warn(`Failed to fetch teams for league ${yahooLeague.league_id}:`, teamsError)
        // Continue with other leagues even if one fails
      }

      connectedLeagues.push({
        id: league.id,
        name: league.name,
        platform: league.platform,
        season: league.season,
        teamCount: league.teamCount
      })
    }

    return NextResponse.json({ 
      success: true,
      leagues: connectedLeagues
    })

  } catch (error) {
    console.error('Error connecting Yahoo leagues:', error)
    return NextResponse.json({ 
      error: error instanceof Error ? error.message : 'Failed to connect to Yahoo leagues' 
    }, { status: 500 })
  }
}