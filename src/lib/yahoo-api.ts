interface YahooTokens {
  accessToken: string
  refreshToken?: string
}

export interface YahooLeague {
  league_key: string
  league_id: string
  name: string
  url: string
  num_teams: number
  season: string
  game_code: string
  is_finished: boolean
}

export interface YahooTeam {
  team_key: string
  team_id: string
  name: string
  manager: string
  wins: number
  losses: number
  ties: number
  points_for: number
  points_against: number
}

export interface YahooPlayer {
  player_key: string
  player_id: string
  name: {
    full: string
    first: string
    last: string
  }
  eligible_positions: string[]
  selected_position: string
}

export class YahooApi {
  private static getHeaders(tokens: YahooTokens) {
    return {
      'Authorization': `Bearer ${tokens.accessToken}`,
      'Content-Type': 'application/json'
    }
  }

  static async getUserLeagues(tokens: YahooTokens, season: string = '2024'): Promise<YahooLeague[]> {
    // Baseball game key for 2025 season is 458, 2024 is 431
    const gameKey = season === '2024' ? '431' : '458'
    const url = `https://fantasysports.yahooapis.com/fantasy/v2/users;use_login=1/games;game_keys=${gameKey}/leagues?format=json`
    
    const response = await fetch(url, {
      headers: this.getHeaders(tokens)
    })

    if (!response.ok) {
      throw new Error(`Yahoo API error: ${response.status} - ${response.statusText}`)
    }

    const data = await response.json()
    const leagues: YahooLeague[] = []
    
    if (data.fantasy_content?.users?.[0]?.user?.[1]?.games) {
      const games = data.fantasy_content.users[0].user[1].games
      Object.values(games).forEach((game: any) => {
        if (game.leagues) {
          Object.values(game.leagues).forEach((league: any) => {
            if (league.league) {
              const leagueData = league.league[0]
              leagues.push({
                league_key: leagueData.league_key,
                league_id: leagueData.league_id,
                name: leagueData.name,
                url: leagueData.url,
                num_teams: parseInt(leagueData.num_teams),
                season: leagueData.season,
                game_code: leagueData.game_code,
                is_finished: leagueData.is_finished === '1'
              })
            }
          })
        }
      })
    }
    
    return leagues
  }

  static async getLeagueTeams(leagueKey: string, tokens: YahooTokens): Promise<YahooTeam[]> {
    const url = `https://fantasysports.yahooapis.com/fantasy/v2/league/${leagueKey}/teams?format=json`
    
    const response = await fetch(url, {
      headers: this.getHeaders(tokens)
    })

    if (!response.ok) {
      throw new Error(`Yahoo API error: ${response.status} - ${response.statusText}`)
    }

    const data = await response.json()
    const teams: YahooTeam[] = []
    
    if (data.fantasy_content?.league?.[1]?.teams) {
      const teamsData = data.fantasy_content.league[1].teams
      Object.values(teamsData).forEach((team: any) => {
        if (team.team) {
          const teamData = team.team[0]
          const standings = team.team[1]?.team_standings || {}
          teams.push({
            team_key: teamData.team_key,
            team_id: teamData.team_id,
            name: teamData.name,
            manager: teamData.managers?.[0]?.manager?.nickname || 'Unknown',
            wins: parseInt(standings.wins || '0'),
            losses: parseInt(standings.losses || '0'),
            ties: parseInt(standings.ties || '0'),
            points_for: parseFloat(standings.points_for || '0'),
            points_against: parseFloat(standings.points_against || '0')
          })
        }
      })
    }
    
    return teams
  }

  static async getTeamRoster(teamKey: string, tokens: YahooTokens): Promise<YahooPlayer[]> {
    const url = `https://fantasysports.yahooapis.com/fantasy/v2/team/${teamKey}/roster?format=json`
    
    const response = await fetch(url, {
      headers: this.getHeaders(tokens)
    })

    if (!response.ok) {
      throw new Error(`Yahoo API error: ${response.status} - ${response.statusText}`)
    }

    const data = await response.json()
    const players: YahooPlayer[] = []
    
    if (data.fantasy_content?.team?.[1]?.roster?.[0]?.players) {
      const playersData = data.fantasy_content.team[1].roster[0].players
      Object.values(playersData).forEach((player: any) => {
        if (player.player) {
          const playerData = player.player[0]
          const playerInfo = player.player[1]
          players.push({
            player_key: playerData.player_key,
            player_id: playerData.player_id,
            name: {
              full: playerData.name?.full || '',
              first: playerData.name?.first || '',
              last: playerData.name?.last || ''
            },
            eligible_positions: playerInfo?.eligible_positions?.position || [],
            selected_position: playerInfo?.selected_position?.position || ''
          })
        }
      })
    }
    
    return players
  }

  static async testConnection(tokens: YahooTokens): Promise<boolean> {
    try {
      await this.getUserLeagues(tokens)
      return true
    } catch (error) {
      console.error('Yahoo connection test failed:', error)
      return false
    }
  }
}