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
