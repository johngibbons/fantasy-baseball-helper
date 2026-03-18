/**
 * Project final standings via deterministic greedy draft simulation.
 *
 * Simulates remaining draft picks pick-by-pick, assigning players to teams
 * based on ADP + positional scarcity + category need bonuses. This replaces
 * the old proportional-share model that didn't account for team needs.
 */

import type { CatDef } from './draft-categories'
import { HITTING_CATS, PITCHING_CATS } from './draft-categories'
import { ROSTER_SLOTS, POSITION_TO_SLOTS, benchContribution } from './roster-optimizer'
export type { CatDef }

// ── Simulation config (matches Python opponent model) ──
const BENCH_ADP_PENALTY = 15
const SCARCITY_BONUS = 15
const CAT_NEED_BONUS = 4

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

export interface PoolPlayer {
  mlb_id: number
  player_type: 'hitter' | 'pitcher'
  zscores: Record<string, number>
  stats: Record<string, number>
  blended_adp: number
  eligible_slots: string[] // roster slots this player can fill (from POSITION_TO_SLOTS)
}

/** Per-team draft state during simulation */
interface TeamDraftState {
  teamId: number
  capacity: Record<string, number> // remaining slot capacity
  zscoreTotals: Record<string, number>
  statTotals: Record<string, number>
  totalPA: number
  totalIP: number
  weightedOBP: number
  weightedERA: number
  weightedWHIP: number
}

// ── Roster helpers (mirror Python RosterState) ──

function hasStartingNeed(slots: string[], capacity: Record<string, number>): boolean {
  for (const slot of slots) {
    if (slot !== 'BE' && (capacity[slot] ?? 0) > 0) return true
  }
  return false
}

function slotScarcity(slots: string[], capacity: Record<string, number>): number {
  let minCap = 0
  for (const slot of slots) {
    if (slot === 'BE') continue
    const cap = capacity[slot] ?? 0
    if (cap > 0 && (minCap === 0 || cap < minCap)) {
      minCap = cap
    }
  }
  return minCap > 0 ? 1.0 / minCap : 0.0
}

function assignToSlot(slots: string[], capacity: Record<string, number>): string | null {
  for (const slot of slots) {
    if ((capacity[slot] ?? 0) > 0) {
      capacity[slot]--
      return slot
    }
  }
  return null
}

function categoryNeedBonus(
  player: PoolPlayer,
  zscoreTotals: Record<string, number>,
): number {
  const cats = player.player_type === 'pitcher' ? PITCHING_CATS : HITTING_CATS
  const catVals = cats.map(c => ({ key: c.key, value: zscoreTotals[c.key] ?? 0 }))
  catVals.sort((a, b) => a.value - b.value)
  const weakCats = new Set(catVals.slice(0, 2).map(c => c.key))

  let bonus = 0
  for (const catKey of weakCats) {
    if ((player.zscores[catKey] ?? 0) > 0.5) {
      bonus += CAT_NEED_BONUS
    }
  }
  return bonus
}

/**
 * Project final standings using a deterministic greedy draft simulation.
 *
 * For each remaining pick in the schedule, scores available players for the
 * picking team using ADP + positional scarcity + category need bonuses,
 * then assigns the best player.
 */
export function projectStandings(
  teamRows: TeamRow[],
  availablePlayers: PoolPlayer[],
  cats: CatDef[],
  remainingPickSchedule: number[], // teamId for each remaining pick
  teamCapacities: Map<number, Record<string, number>>, // per-team remaining slot capacity
): ProjectedStanding[] {
  if (teamRows.length === 0) return []

  // Initialize per-team draft state
  const teamStateMap = new Map<number, TeamDraftState>()
  for (const row of teamRows) {
    const capacity = teamCapacities.get(row.teamId)
    teamStateMap.set(row.teamId, {
      teamId: row.teamId,
      capacity: capacity ? { ...capacity } : { ...ROSTER_SLOTS },
      zscoreTotals: { ...row.totals },
      statTotals: { ...row.statTotals },
      totalPA: row.totalPA,
      totalIP: row.totalIP,
      weightedOBP: row.weightedOBP,
      weightedERA: row.weightedERA,
      weightedWHIP: row.weightedWHIP,
    })
  }

  if (remainingPickSchedule.length === 0) {
    return computeRanksAndWins(teamRows.map(row => ({
      teamId: row.teamId,
      teamName: row.teamName,
      currentTotals: { ...row.totals },
      projectedTotals: { ...row.totals },
      projectedStatTotals: { ...row.statTotals },
      projectedRanks: {},
      projectedWins: 0,
      overallRank: 0,
    })), cats)
  }

  // Sort available players by ADP for efficient iteration
  const pool = [...availablePlayers].sort((a, b) => a.blended_adp - b.blended_adp)
  const drafted = new Set<number>()

  // Run the greedy simulation pick-by-pick
  for (const pickTeamId of remainingPickSchedule) {
    const ts = teamStateMap.get(pickTeamId)
    if (!ts) continue

    // Score each available player for this team
    let bestScore = Infinity
    let bestPlayer: PoolPlayer | null = null

    for (const p of pool) {
      if (drafted.has(p.mlb_id)) continue

      let effectiveAdp = p.blended_adp

      if (!hasStartingNeed(p.eligible_slots, ts.capacity)) {
        effectiveAdp += BENCH_ADP_PENALTY
      } else {
        const scarcity = slotScarcity(p.eligible_slots, ts.capacity)
        effectiveAdp -= scarcity * SCARCITY_BONUS
        effectiveAdp -= categoryNeedBonus(p, ts.zscoreTotals)
      }

      if (effectiveAdp < bestScore) {
        bestScore = effectiveAdp
        bestPlayer = p
      }
    }

    if (!bestPlayer) continue

    // Assign player to team
    drafted.add(bestPlayer.mlb_id)
    const assignedSlot = assignToSlot(bestPlayer.eligible_slots, ts.capacity)
    const weight = assignedSlot === 'BE' ? benchContribution(bestPlayer) : 1

    for (const cat of cats) {
      ts.zscoreTotals[cat.key] = (ts.zscoreTotals[cat.key] ?? 0) + (bestPlayer.zscores[cat.key] ?? 0) * weight
      if (!cat.rate) {
        ts.statTotals[cat.projKey] = (ts.statTotals[cat.projKey] ?? 0) + (bestPlayer.stats[cat.projKey] ?? 0) * weight
      }
    }
    const pa = (bestPlayer.stats['proj_pa'] ?? 0) * weight
    const ip = (bestPlayer.stats['proj_ip'] ?? 0) * weight
    ts.totalPA += pa
    ts.totalIP += ip
    ts.weightedOBP += (bestPlayer.stats['proj_obp'] ?? 0) * pa
    ts.weightedERA += (bestPlayer.stats['proj_era'] ?? 0) * ip
    ts.weightedWHIP += (bestPlayer.stats['proj_whip'] ?? 0) * ip
  }

  // Build projected standings from simulation results
  const projected: ProjectedStanding[] = teamRows.map(row => {
    const ts = teamStateMap.get(row.teamId)!
    const projectedStatTotals: Record<string, number> = {}

    for (const cat of cats) {
      if (!cat.rate) {
        projectedStatTotals[cat.projKey] = ts.statTotals[cat.projKey] ?? 0
      }
    }

    // Rate stats from weighted components
    projectedStatTotals['proj_obp'] = ts.totalPA > 0 ? ts.weightedOBP / ts.totalPA : 0
    projectedStatTotals['proj_era'] = ts.totalIP > 0 ? ts.weightedERA / ts.totalIP : 0
    projectedStatTotals['proj_whip'] = ts.totalIP > 0 ? ts.weightedWHIP / ts.totalIP : 0

    return {
      teamId: row.teamId,
      teamName: row.teamName,
      currentTotals: { ...row.totals },
      projectedTotals: { ...ts.zscoreTotals },
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
