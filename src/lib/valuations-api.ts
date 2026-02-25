/**
 * Client for the FastAPI valuations backend.
 * Routes are proxied through Next.js: /api/v2/* -> FastAPI localhost:8000/api/*
 */

const BASE = '/api/v2'

export interface RankedPlayer {
  mlb_id: number
  full_name: string
  primary_position: string
  team: string
  player_type: 'hitter' | 'pitcher'
  overall_rank: number
  position_rank: number
  total_zscore: number
  // Hitter z-scores
  zscore_r?: number
  zscore_tb?: number
  zscore_rbi?: number
  zscore_sb?: number
  zscore_obp?: number
  // Pitcher z-scores
  zscore_k?: number
  zscore_qs?: number
  zscore_era?: number
  zscore_whip?: number
  zscore_svhd?: number
  // Blended projected stats
  proj_pa?: number
  proj_r?: number
  proj_tb?: number
  proj_rbi?: number
  proj_sb?: number
  proj_obp?: number
  proj_ip?: number
  proj_k?: number
  proj_qs?: number
  proj_era?: number
  proj_whip?: number
  proj_svhd?: number
  // Multi-position eligibility
  eligible_positions?: string
  // ADP
  espn_adp?: number
  adp_diff?: number
}

export interface PlayerDetail {
  mlb_id: number
  full_name: string
  first_name: string
  last_name: string
  primary_position: string
  team: string
  player_type: string
  bats: string
  throws: string
  birth_date: string
  ranking: {
    overall_rank: number
    position_rank: number
    total_zscore: number
    zscore_r: number
    zscore_tb: number
    zscore_rbi: number
    zscore_sb: number
    zscore_obp: number
    zscore_k: number
    zscore_qs: number
    zscore_era: number
    zscore_whip: number
    zscore_svhd: number
  } | null
  projection: Record<string, number> | null
  batting_history: Record<string, number>[]
  pitching_history: Record<string, number>[]
}

export interface StatsSummary {
  total_players: number
  total_hitters: number
  total_pitchers: number
  top_5: {
    mlb_id: number
    full_name: string
    primary_position: string
    team: string
    overall_rank: number
    total_zscore: number
    player_type: string
  }[]
}

async function fetchApi<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = new URL(`${BASE}${path}`, window.location.origin)
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') {
        url.searchParams.set(k, v)
      }
    })
  }
  const res = await fetch(url.toString())
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`)
  }
  return res.json()
}

export async function getPlayers(opts?: {
  season?: number
  playerType?: string
  position?: string
  search?: string
  limit?: number
  offset?: number
}): Promise<{ players: RankedPlayer[]; total: number }> {
  return fetchApi('/players', {
    season: String(opts?.season ?? 2026),
    player_type: opts?.playerType ?? '',
    position: opts?.position ?? '',
    search: opts?.search ?? '',
    limit: String(opts?.limit ?? 300),
    offset: String(opts?.offset ?? 0),
  })
}

export async function getPlayerDetail(
  mlbId: number,
  season: number = 2026
): Promise<PlayerDetail> {
  return fetchApi(`/players/${mlbId}`, { season: String(season) })
}

export async function getRankings(opts?: {
  season?: number
  playerType?: string
  position?: string
  sortBy?: string
  limit?: number
}): Promise<{ rankings: RankedPlayer[] }> {
  return fetchApi('/rankings', {
    season: String(opts?.season ?? 2026),
    player_type: opts?.playerType ?? '',
    position: opts?.position ?? '',
    sort_by: opts?.sortBy ?? '',
    limit: String(opts?.limit ?? 300),
  })
}

export async function getPositionRankings(
  season: number = 2026
): Promise<Record<string, RankedPlayer[]>> {
  return fetchApi('/rankings/positions', { season: String(season) })
}

export async function getDraftBoard(
  season: number = 2026
): Promise<{ players: RankedPlayer[]; total: number }> {
  return fetchApi('/draft/board', { season: String(season) })
}

export async function getDraftValue(
  season: number = 2026
): Promise<{ players: RankedPlayer[]; note?: string }> {
  return fetchApi('/draft/value', { season: String(season) })
}

export async function recalculateDraftValues(
  excludedIds: number[],
  season: number = 2026
): Promise<{ players: RankedPlayer[] }> {
  const url = `${BASE}/draft/recalculate`
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ excluded_ids: excludedIds, season }),
  })
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`)
  }
  return res.json()
}

export interface StatcastData {
  mlb_id: number
  season: number
  player_type?: 'hitter' | 'pitcher'
  data: {
    // Hitter fields
    xwoba?: number
    xba?: number
    xslg?: number
    barrel_pct?: number
    hard_hit_pct?: number
    avg_exit_velocity?: number
    max_exit_velocity?: number
    sprint_speed?: number
    sweet_spot_pct?: number
    launch_angle?: number
    woba?: number
    // Pitcher fields
    xera?: number
    xwoba_against?: number
    xba_against?: number
    barrel_pct_against?: number
    hard_hit_pct_against?: number
    whiff_pct?: number
    k_pct?: number
    bb_pct?: number
    avg_exit_velocity_against?: number
    chase_rate?: number
    csw_pct?: number
  } | null
}

export async function getPlayerStatcast(
  mlbId: number,
  season: number = 2025
): Promise<StatcastData> {
  return fetchApi(`/players/${mlbId}/statcast`, { season: String(season) })
}

export async function getStatsSummary(
  season: number = 2026
): Promise<StatsSummary> {
  return fetchApi('/stats/summary', { season: String(season) })
}

// === Keeper Types ===

export interface KeeperCandidate {
  name: string
  draft_round: number | null
  keeper_season: number
}

export interface ResolvedKeeper {
  name: string
  mlb_id: number
  matched_name: string
  match_confidence: number
  draft_round: number | null
  keeper_season: number
  overall_rank: number | null
  total_zscore: number | null
  primary_position: string
  team: string
  player_type: 'hitter' | 'pitcher'
  eligible_positions?: string
  zscore_r?: number
  zscore_tb?: number
  zscore_rbi?: number
  zscore_sb?: number
  zscore_obp?: number
  zscore_k?: number
  zscore_qs?: number
  zscore_era?: number
  zscore_whip?: number
  zscore_svhd?: number
}

export interface UnmatchedPlayer {
  name: string
  draft_round: number | null
  keeper_season: number
}

export interface KeeperResolveResponse {
  resolved: ResolvedKeeper[]
  unmatched: UnmatchedPlayer[]
}

export async function resolveKeepers(
  players: KeeperCandidate[],
  season: number = 2026
): Promise<KeeperResolveResponse> {
  const url = `${BASE}/keepers/resolve`
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ players, season }),
  })
  if (!res.ok) throw new Error(`API error: ${res.status} ${res.statusText}`)
  return res.json()
}

// === In-Season Types ===

export interface InseasonFreeAgent {
  mlb_id: number
  full_name: string
  primary_position: string
  team: string
  player_type: string
  total_zscore: number
  mcw: number
  category_impact: Record<string, number>
  eligible_positions?: string
  proj_pa?: number
  proj_ip?: number
}

export interface SwapRecommendation {
  add_player: {
    mlb_id: number
    full_name: string
    primary_position: string
    team: string
    player_type: string
    mcw: number
  }
  drop_player: {
    mlb_id: number
    full_name: string
    primary_position: string
    team: string
    player_type: string
  }
  net_mcw: number
  category_impact: Record<string, number>
  horizon: string
}

export interface TradeEvalResult {
  give_players: { mlb_id: number; full_name: string }[]
  receive_players: { mlb_id: number; full_name: string }[]
  my_mcw_change: number
  partner_mcw_change: number
  my_category_impact: Record<string, number>
  partner_category_impact: Record<string, number>
  is_positive_sum: boolean
}

export interface TradeProposal {
  give_player: { mlb_id: number; full_name: string; primary_position: string; team: string }
  receive_player: { mlb_id: number; full_name: string; primary_position: string; team: string }
  partner_team_id: number
  my_mcw_gain: number
  partner_mcw_gain: number
}

export interface MatchupCategory {
  category: string
  my_value: number
  opp_value: number
  margin: number
  threshold: number
  status: 'winning' | 'losing' | 'swing'
}

export interface MatchupAnalysis {
  matchup_period: number
  my_team_id: number
  opp_team_id: number
  categories: MatchupCategory[]
  projected_result: string
  wins: number
  losses: number
  ties: number
  error?: string
}

export interface CategoryStrategy {
  category: string
  cat_key: string
  my_total: number
  rank: number
  win_prob: number
  gap_above: number
  gap_below: number
  strategy: 'lock' | 'target' | 'punt' | 'neutral'
}

export interface SeasonStrategy {
  my_team_id: number
  num_teams: number
  expected_category_wins: number
  categories: CategoryStrategy[]
  target_categories: string[]
  lock_categories: string[]
  punt_categories: string[]
  error?: string
}

export interface RosterSignal {
  mlb_id: number
  full_name: string
  primary_position: string
  team: string
  player_type: string
  signal_type: 'drop_candidate' | 'add_target' | 'underperformer'
  severity: 'high' | 'medium' | 'low'
  mcw: number
  action: string
  description: string
}

// === In-Season API Functions ===

export async function triggerInseasonSync(season: number = 2026): Promise<{ ok: boolean; last_ros_update?: string }> {
  const url = `${BASE}/inseason/sync?season=${season}`
  const res = await fetch(url, { method: 'POST' })
  if (!res.ok) throw new Error(`API error: ${res.status} ${res.statusText}`)
  return res.json()
}

export async function getFreeAgentRankings(opts: {
  leagueId: string
  season?: number
  myTeamId: number
  numTeams?: number
  position?: string
  limit?: number
}): Promise<{ free_agents: InseasonFreeAgent[] }> {
  return fetchApi('/inseason/free-agents', {
    league_id: opts.leagueId,
    season: String(opts.season ?? 2026),
    my_team_id: String(opts.myTeamId),
    num_teams: String(opts.numTeams ?? 10),
    position: opts.position ?? '',
    limit: String(opts.limit ?? 50),
  })
}

export async function getAddDropRecommendations(opts: {
  leagueId: string
  season?: number
  myTeamId: number
  numTeams?: number
  horizon?: 'ros' | 'week'
  limit?: number
}): Promise<{ recommendations: SwapRecommendation[] }> {
  return fetchApi('/inseason/recommendations', {
    league_id: opts.leagueId,
    season: String(opts.season ?? 2026),
    my_team_id: String(opts.myTeamId),
    num_teams: String(opts.numTeams ?? 10),
    horizon: opts.horizon ?? 'ros',
    limit: String(opts.limit ?? 20),
  })
}

export async function evaluateTrade(opts: {
  leagueId: string
  season?: number
  myTeamId: number
  partnerTeamId: number
  giveIds: number[]
  receiveIds: number[]
  numTeams?: number
}): Promise<TradeEvalResult> {
  const url = `${BASE}/inseason/trade-eval`
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      league_id: opts.leagueId,
      season: opts.season ?? 2026,
      my_team_id: opts.myTeamId,
      partner_team_id: opts.partnerTeamId,
      give_ids: opts.giveIds,
      receive_ids: opts.receiveIds,
      num_teams: opts.numTeams ?? 10,
    }),
  })
  if (!res.ok) throw new Error(`API error: ${res.status} ${res.statusText}`)
  return res.json()
}

export async function findTrades(opts: {
  leagueId: string
  season?: number
  myTeamId: number
  numTeams?: number
  limit?: number
}): Promise<{ trades: TradeProposal[] }> {
  return fetchApi('/inseason/trade-finder', {
    league_id: opts.leagueId,
    season: String(opts.season ?? 2026),
    my_team_id: String(opts.myTeamId),
    num_teams: String(opts.numTeams ?? 10),
    limit: String(opts.limit ?? 20),
  })
}

export async function getMatchupAnalysis(opts: {
  leagueId: string
  season?: number
  matchupPeriod: number
  myTeamId: number
}): Promise<MatchupAnalysis> {
  return fetchApi('/inseason/matchup', {
    league_id: opts.leagueId,
    season: String(opts.season ?? 2026),
    matchup_period: String(opts.matchupPeriod),
    my_team_id: String(opts.myTeamId),
  })
}

export async function getSeasonStrategy(opts: {
  leagueId: string
  season?: number
  myTeamId: number
  numTeams?: number
}): Promise<SeasonStrategy> {
  return fetchApi('/inseason/strategy', {
    league_id: opts.leagueId,
    season: String(opts.season ?? 2026),
    my_team_id: String(opts.myTeamId),
    num_teams: String(opts.numTeams ?? 10),
  })
}

export async function getRosterSignals(opts: {
  leagueId: string
  season?: number
  myTeamId: number
  numTeams?: number
  limit?: number
}): Promise<{ signals: RosterSignal[] }> {
  return fetchApi('/inseason/signals', {
    league_id: opts.leagueId,
    season: String(opts.season ?? 2026),
    my_team_id: String(opts.myTeamId),
    num_teams: String(opts.numTeams ?? 10),
    limit: String(opts.limit ?? 30),
  })
}
