// ── Shared category definitions, colors, and formatting for draft pages ──

import type { RankedPlayer } from './valuations-api'
import {
  PITCHER_BENCH_CONTRIBUTION, HITTER_BENCH_CONTRIBUTION, optimizeRoster,
  type RosterResult,
} from './roster-optimizer'

// ── Category definitions ──

export interface CatDef {
  key: string
  label: string
  projKey: string
  inverted: boolean
  rate?: boolean
  weight?: string
}

export const HITTING_CATS: CatDef[] = [
  { key: 'zscore_r', label: 'R', projKey: 'proj_r', inverted: false },
  { key: 'zscore_tb', label: 'TB', projKey: 'proj_tb', inverted: false },
  { key: 'zscore_rbi', label: 'RBI', projKey: 'proj_rbi', inverted: false },
  { key: 'zscore_sb', label: 'SB', projKey: 'proj_sb', inverted: false },
  { key: 'zscore_obp', label: 'OBP', projKey: 'proj_obp', inverted: false, rate: true, weight: 'proj_pa' },
]

export const PITCHING_CATS: CatDef[] = [
  { key: 'zscore_k', label: 'K', projKey: 'proj_k', inverted: false },
  { key: 'zscore_qs', label: 'QS', projKey: 'proj_qs', inverted: false },
  { key: 'zscore_era', label: 'ERA', projKey: 'proj_era', inverted: true, rate: true, weight: 'proj_ip' },
  { key: 'zscore_whip', label: 'WHIP', projKey: 'proj_whip', inverted: true, rate: true, weight: 'proj_ip' },
  { key: 'zscore_svhd', label: 'SVHD', projKey: 'proj_svhd', inverted: false },
]

export const ALL_CATS: CatDef[] = [...HITTING_CATS, ...PITCHING_CATS]

// ── Position badge colors ──

export const posColor: Record<string, string> = {
  C: 'bg-blue-500', '1B': 'bg-amber-500', '2B': 'bg-orange-500', '3B': 'bg-purple-500',
  SS: 'bg-red-500', OF: 'bg-emerald-500', LF: 'bg-emerald-500', CF: 'bg-emerald-500',
  RF: 'bg-emerald-500', DH: 'bg-gray-500', SP: 'bg-sky-500', RP: 'bg-pink-500', P: 'bg-teal-500',
  TWP: 'bg-violet-500', UTIL: 'bg-gray-500',
}

// ── Heatmap color helper ──

export function getHeatColor(rank: number, total: number): string {
  if (total <= 1) return 'rgb(52, 211, 153)' // emerald
  // Map rank 1→green, rank N→red
  const t = (rank - 1) / (total - 1) // 0 = best, 1 = worst
  // Green (52, 211, 153) → Yellow (234, 179, 8) → Red (239, 68, 68)
  if (t <= 0.5) {
    const s = t * 2
    const r = Math.round(52 + (234 - 52) * s)
    const g = Math.round(211 + (179 - 211) * s)
    const b = Math.round(153 + (8 - 153) * s)
    return `rgb(${r}, ${g}, ${b})`
  } else {
    const s = (t - 0.5) * 2
    const r = Math.round(234 + (239 - 234) * s)
    const g = Math.round(179 + (68 - 179) * s)
    const b = Math.round(8 + (68 - 8) * s)
    return `rgb(${r}, ${g}, ${b})`
  }
}

// ── Stat formatting for projected stats ──

export function formatStat(cat: CatDef, value: number): string {
  if (cat.label === 'OBP') return value.toFixed(3)
  if (cat.label === 'ERA' || cat.label === 'WHIP') return value.toFixed(2)
  return Math.round(value).toString()
}

// ── Team category computation (pure function) ──

export interface TeamCategoryRow {
  teamId: number
  teamName: string
  totals: Record<string, number>
  statTotals: Record<string, number>
  totalPA: number
  totalIP: number
  weightedOBP: number
  weightedERA: number
  weightedWHIP: number
  count: number
  total: number
  expectedWins: number
}

export interface TeamCategoriesResult {
  rows: TeamCategoryRow[]
  catRanks: Map<string, Map<number, number>>
  teamCount: number
}

export function computeTeamCategories(
  teamRosters: Map<number, RosterResult>,
  teamNameMap: Map<number, string>,
): TeamCategoriesResult {
  interface TeamData {
    totals: Record<string, number>
    statTotals: Record<string, number>
    totalPA: number
    totalIP: number
    weightedOBP: number
    weightedERA: number
    weightedWHIP: number
    count: number
    total: number
  }
  const teams = new Map<number, TeamData>()

  for (const [teamId, roster] of teamRosters) {
    if (teamId === -1) continue
    const t: TeamData = {
      totals: {}, statTotals: {}, totalPA: 0, totalIP: 0,
      weightedOBP: 0, weightedERA: 0, weightedWHIP: 0,
      count: 0, total: 0,
    }
    teams.set(teamId, t)

    const allPlayers: [RankedPlayer, number][] = [
      ...roster.starters.map(p => [p, 1] as [RankedPlayer, number]),
      ...roster.bench.map(p => [p, p.player_type === 'pitcher' ? PITCHER_BENCH_CONTRIBUTION : HITTER_BENCH_CONTRIBUTION] as [RankedPlayer, number]),
    ]
    for (const [p, weight] of allPlayers) {
      t.count++

      for (const cat of ALL_CATS) {
        const val = (p as unknown as Record<string, number>)[cat.key] ?? 0
        t.totals[cat.key] = (t.totals[cat.key] ?? 0) + val * weight
        t.total += val * weight
      }

      const pd = p as unknown as Record<string, number>
      for (const cat of ALL_CATS) {
        if (!cat.rate) {
          t.statTotals[cat.projKey] = (t.statTotals[cat.projKey] ?? 0) + (pd[cat.projKey] ?? 0) * weight
        }
      }
      t.totalPA += (pd.proj_pa ?? 0) * weight
      t.totalIP += (pd.proj_ip ?? 0) * weight
      t.weightedOBP += (pd.proj_obp ?? 0) * (pd.proj_pa ?? 0) * weight
      t.weightedERA += (pd.proj_era ?? 0) * (pd.proj_ip ?? 0) * weight
      t.weightedWHIP += (pd.proj_whip ?? 0) * (pd.proj_ip ?? 0) * weight
    }
  }

  // Compute final rate stats
  for (const [, t] of teams) {
    t.statTotals['proj_obp'] = t.totalPA > 0 ? t.weightedOBP / t.totalPA : 0
    t.statTotals['proj_era'] = t.totalIP > 0 ? t.weightedERA / t.totalIP : 0
    t.statTotals['proj_whip'] = t.totalIP > 0 ? t.weightedWHIP / t.totalIP : 0
  }

  // Build rows
  const rows: TeamCategoryRow[] = [...teams.entries()]
    .map(([teamId, data]) => ({
      teamId,
      teamName: teamNameMap.get(teamId) ?? `Team ${teamId}`,
      expectedWins: 0,
      ...data,
    }))

  // Compute per-category ranks from projected stats
  const catRanks = new Map<string, Map<number, number>>()
  for (const cat of ALL_CATS) {
    const sorted = [...rows].sort((a, b) => {
      const aVal = a.statTotals[cat.projKey] ?? 0
      const bVal = b.statTotals[cat.projKey] ?? 0
      return cat.inverted ? aVal - bVal : bVal - aVal
    })
    const rankMap = new Map<number, number>()
    sorted.forEach((r, i) => rankMap.set(r.teamId, i + 1))
    catRanks.set(cat.key, rankMap)
  }

  // Compute expected weekly wins
  const numTeams = rows.length
  for (const row of rows) {
    let ew = 0
    for (const cat of ALL_CATS) {
      const rank = catRanks.get(cat.key)?.get(row.teamId) ?? numTeams
      ew += numTeams > 1 ? (numTeams - rank) / (numTeams - 1) : 0
    }
    row.expectedWins = ew
  }

  rows.sort((a, b) => b.expectedWins - a.expectedWins)

  return { rows, catRanks, teamCount: rows.length }
}
