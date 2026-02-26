/**
 * Project final standings from current draft state + remaining value pool.
 *
 * Splits undrafted players into hitter and pitcher pools, selects the top
 * players from each proportional to roster slot counts, then distributes
 * them to teams based on each team's remaining hitter/pitcher slots.
 *
 * Projects actual stats (R, TB, OBP, ERA, etc.) rather than z-scores.
 */

import type { CatDef } from './draft-categories'
import { HITTING_CATS, PITCHING_CATS } from './draft-categories'
export type { CatDef }

/** Number of starter roster slots by type */
const HITTER_STARTER_SLOTS = 10 // C, 1B, 2B, 3B, SS, OF×3, UTIL×2
const PITCHER_STARTER_SLOTS = 7 // SP×3, RP×2, P×2

export interface TeamRow {
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
}

export interface ProjectedStanding {
  teamId: number
  teamName: string
  currentTotals: Record<string, number>
  projectedTotals: Record<string, number>
  projectedStatTotals: Record<string, number>
  projectedRanks: Record<string, number>
  projectedWins: number
  overallRank: number
}

interface PoolPlayer {
  mlb_id: number
  player_type: 'hitter' | 'pitcher'
  zscores: Record<string, number>
  stats: Record<string, number>
}

interface PoolTotals {
  statTotals: Record<string, number>
  zscores: Record<string, number>
  pa: number
  ip: number
  weightedOBP: number
  weightedERA: number
  weightedWHIP: number
}

function aggregatePool(players: PoolPlayer[], cats: CatDef[]): PoolTotals {
  const statTotals: Record<string, number> = {}
  const zscores: Record<string, number> = {}
  for (const cat of cats) {
    if (!cat.rate) statTotals[cat.projKey] = 0
    zscores[cat.key] = 0
  }

  let pa = 0, ip = 0, weightedOBP = 0, weightedERA = 0, weightedWHIP = 0

  for (const p of players) {
    for (const cat of cats) {
      if (!cat.rate) statTotals[cat.projKey] += (p.stats[cat.projKey] ?? 0)
      zscores[cat.key] += (p.zscores[cat.key] ?? 0)
    }
    const pPA = p.stats['proj_pa'] ?? 0
    const pIP = p.stats['proj_ip'] ?? 0
    pa += pPA
    ip += pIP
    weightedOBP += (p.stats['proj_obp'] ?? 0) * pPA
    weightedERA += (p.stats['proj_era'] ?? 0) * pIP
    weightedWHIP += (p.stats['proj_whip'] ?? 0) * pIP
  }

  return { statTotals, zscores, pa, ip, weightedOBP, weightedERA, weightedWHIP }
}

/**
 * Project final standings for all teams using projected stats.
 *
 * @param teamRows - Current team data (from teamCategories.rows) with stat totals
 * @param availablePlayers - Undrafted players with projection data and player_type
 * @param cats - Category definitions with projKey, inverted, rate, weight
 * @param remainingStarterSlots - Map of teamId → number of unfilled starter slots
 * @param remainingHitterSlots - Map of teamId → number of unfilled hitter starter slots
 * @param remainingPitcherSlots - Map of teamId → number of unfilled pitcher starter slots
 */
export function projectStandings(
  teamRows: TeamRow[],
  availablePlayers: PoolPlayer[],
  cats: CatDef[],
  remainingStarterSlots: Map<number, number>,
  remainingHitterSlots: Map<number, number>,
  remainingPitcherSlots: Map<number, number>,
): ProjectedStanding[] {
  if (teamRows.length === 0) return []

  // Total remaining slots by type across all teams
  const totalRemainingPicks = [...remainingStarterSlots.values()].reduce((a, b) => a + b, 0)
  const totalRemainingHitter = [...remainingHitterSlots.values()].reduce((a, b) => a + b, 0)
  const totalRemainingPitcher = [...remainingPitcherSlots.values()].reduce((a, b) => a + b, 0)

  if (totalRemainingPicks === 0) {
    const standings: ProjectedStanding[] = teamRows.map(row => ({
      teamId: row.teamId,
      teamName: row.teamName,
      currentTotals: { ...row.totals },
      projectedTotals: { ...row.totals },
      projectedStatTotals: { ...row.statTotals },
      projectedRanks: {},
      projectedWins: 0,
      overallRank: 0,
    }))
    return computeRanksAndWins(standings, cats)
  }

  // Split available players into hitter and pitcher pools, sorted by type-
  // relevant z-score sum, then take the top N of each.
  const hitters = availablePlayers.filter(p => p.player_type === 'hitter')
  const pitchers = availablePlayers.filter(p => p.player_type === 'pitcher')

  const sortByZscoreSum = (players: PoolPlayer[], relevantCats: CatDef[]) =>
    [...players]
      .sort((a, b) => {
        let aTotal = 0, bTotal = 0
        for (const cat of relevantCats) {
          aTotal += (a.zscores[cat.key] ?? 0)
          bTotal += (b.zscores[cat.key] ?? 0)
        }
        return bTotal - aTotal
      })

  const hitterPool = sortByZscoreSum(hitters, HITTING_CATS).slice(0, totalRemainingHitter)
  const pitcherPool = sortByZscoreSum(pitchers, PITCHING_CATS).slice(0, totalRemainingPitcher)

  // Aggregate pool stats separately
  const hitterPoolTotals = aggregatePool(hitterPool, cats)
  const pitcherPoolTotals = aggregatePool(pitcherPool, cats)

  // Project each team's totals
  const projected: ProjectedStanding[] = teamRows.map(row => {
    const hitterShare = totalRemainingHitter > 0
      ? (remainingHitterSlots.get(row.teamId) ?? 0) / totalRemainingHitter
      : 0
    const pitcherShare = totalRemainingPitcher > 0
      ? (remainingPitcherSlots.get(row.teamId) ?? 0) / totalRemainingPitcher
      : 0

    // Z-score projected totals (for MCW model compatibility)
    const projectedTotals: Record<string, number> = {}
    for (const cat of cats) {
      projectedTotals[cat.key] = (row.totals[cat.key] ?? 0)
        + hitterShare * hitterPoolTotals.zscores[cat.key]
        + pitcherShare * pitcherPoolTotals.zscores[cat.key]
    }

    // Stat projected totals (for display)
    const projectedStatTotals: Record<string, number> = {}

    // Counting stats: current + shares of both pools
    for (const cat of cats) {
      if (!cat.rate) {
        projectedStatTotals[cat.projKey] = (row.statTotals[cat.projKey] ?? 0)
          + hitterShare * (hitterPoolTotals.statTotals[cat.projKey] ?? 0)
          + pitcherShare * (pitcherPoolTotals.statTotals[cat.projKey] ?? 0)
      }
    }

    // Rate stats: recompute from combined weighted components
    const projPA = row.totalPA
      + hitterShare * hitterPoolTotals.pa
      + pitcherShare * pitcherPoolTotals.pa
    const projIP = row.totalIP
      + hitterShare * hitterPoolTotals.ip
      + pitcherShare * pitcherPoolTotals.ip

    projectedStatTotals['proj_obp'] = projPA > 0
      ? (row.weightedOBP + hitterShare * hitterPoolTotals.weightedOBP + pitcherShare * pitcherPoolTotals.weightedOBP) / projPA
      : 0
    projectedStatTotals['proj_era'] = projIP > 0
      ? (row.weightedERA + hitterShare * hitterPoolTotals.weightedERA + pitcherShare * pitcherPoolTotals.weightedERA) / projIP
      : 0
    projectedStatTotals['proj_whip'] = projIP > 0
      ? (row.weightedWHIP + hitterShare * hitterPoolTotals.weightedWHIP + pitcherShare * pitcherPoolTotals.weightedWHIP) / projIP
      : 0

    return {
      teamId: row.teamId,
      teamName: row.teamName,
      currentTotals: { ...row.totals },
      projectedTotals,
      projectedStatTotals,
      projectedRanks: {},
      projectedWins: 0,
      overallRank: 0,
    }
  })

  return computeRanksAndWins(projected, cats)
}

/**
 * Compute category ranks, expected weekly wins, and overall rank for standings.
 */
function computeRanksAndWins(standings: ProjectedStanding[], cats: CatDef[]): ProjectedStanding[] {
  // Rank teams per category from projected stat totals
  for (const cat of cats) {
    const sorted = [...standings].sort((a, b) => {
      const aVal = a.projectedStatTotals[cat.projKey] ?? 0
      const bVal = b.projectedStatTotals[cat.projKey] ?? 0
      return cat.inverted ? aVal - bVal : bVal - aVal
    })
    sorted.forEach((s, i) => {
      s.projectedRanks[cat.key] = i + 1
    })
  }

  // Compute projected weekly wins from category ranks
  const numTeams = standings.length
  for (const standing of standings) {
    let totalWinProb = 0
    for (const cat of cats) {
      const rank = standing.projectedRanks[cat.key] ?? numTeams
      totalWinProb += numTeams > 1 ? (numTeams - rank) / (numTeams - 1) : 0
    }
    standing.projectedWins = totalWinProb
  }

  // Compute overall rank from projected wins
  const byWins = [...standings].sort((a, b) => b.projectedWins - a.projectedWins)
  byWins.forEach((s, i) => {
    s.overallRank = i + 1
  })

  return standings
}
