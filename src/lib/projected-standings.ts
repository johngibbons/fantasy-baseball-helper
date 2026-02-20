/**
 * Project final standings from current draft state + remaining value pool.
 *
 * Uses a simple proportional model: each team gets a share of the remaining
 * player pool proportional to their remaining picks.
 *
 * Projects actual stats (R, TB, OBP, ERA, etc.) rather than z-scores.
 */

export interface CatDef {
  key: string
  label: string
  projKey: string
  inverted: boolean
  rate?: boolean
  weight?: string
}

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

/**
 * Project final standings for all teams using projected stats.
 *
 * @param teamRows - Current team data (from teamCategories.rows) with stat totals
 * @param availablePlayers - Undrafted players with projection data
 * @param cats - Category definitions with projKey, inverted, rate, weight
 * @param rosterSize - Total roster slots per team
 * @param pickSchedule - Flat pick schedule array
 * @param currentPickIndex - Current pick index in the schedule
 */
export function projectStandings(
  teamRows: TeamRow[],
  availablePlayers: { mlb_id: number; zscores: Record<string, number>; stats: Record<string, number> }[],
  cats: CatDef[],
  rosterSize: number,
  pickSchedule: number[],
  currentPickIndex: number
): ProjectedStanding[] {
  if (teamRows.length === 0) return []

  // Count remaining picks per team from the schedule
  const remainingPicks = new Map<number, number>()
  for (let i = currentPickIndex; i < pickSchedule.length; i++) {
    const tid = pickSchedule[i]
    remainingPicks.set(tid, (remainingPicks.get(tid) ?? 0) + 1)
  }

  // Total remaining picks across all teams
  const totalRemainingPicks = [...remainingPicks.values()].reduce((a, b) => a + b, 0)
  if (totalRemainingPicks === 0) {
    // No more picks — projected = current, but still compute ranks and wins
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

  // Compute pool totals for counting stats and rate stat components
  let poolPA = 0
  let poolIP = 0
  let poolWeightedOBP = 0
  let poolWeightedERA = 0
  let poolWeightedWHIP = 0
  const poolStatTotals: Record<string, number> = {}
  for (const cat of cats) {
    if (!cat.rate) poolStatTotals[cat.projKey] = 0
  }

  for (const p of availablePlayers) {
    // Counting stats
    for (const cat of cats) {
      if (!cat.rate) {
        poolStatTotals[cat.projKey] += (p.stats[cat.projKey] ?? 0)
      }
    }
    // Rate stat components
    const pa = p.stats['proj_pa'] ?? 0
    const ip = p.stats['proj_ip'] ?? 0
    poolPA += pa
    poolIP += ip
    poolWeightedOBP += (p.stats['proj_obp'] ?? 0) * pa
    poolWeightedERA += (p.stats['proj_era'] ?? 0) * ip
    poolWeightedWHIP += (p.stats['proj_whip'] ?? 0) * ip
  }

  // Also sum z-score pool for projectedTotals (used by MCW model downstream)
  const poolZscores: Record<string, number> = {}
  for (const cat of cats) poolZscores[cat.key] = 0
  for (const p of availablePlayers) {
    for (const cat of cats) {
      poolZscores[cat.key] += (p.zscores[cat.key] ?? 0)
    }
  }

  // Project each team's totals
  const projected: ProjectedStanding[] = teamRows.map(row => {
    const teamRemaining = remainingPicks.get(row.teamId) ?? 0
    const share = teamRemaining / totalRemainingPicks

    // Z-score projected totals (for MCW model compatibility)
    const projectedTotals: Record<string, number> = {}
    for (const cat of cats) {
      projectedTotals[cat.key] = (row.totals[cat.key] ?? 0) + share * poolZscores[cat.key]
    }

    // Stat projected totals (for display)
    const projectedStatTotals: Record<string, number> = {}

    // Counting stats: current + share of pool
    for (const cat of cats) {
      if (!cat.rate) {
        projectedStatTotals[cat.projKey] = (row.statTotals[cat.projKey] ?? 0) + share * poolStatTotals[cat.projKey]
      }
    }

    // Rate stats: recompute from combined weighted components
    const projPA = row.totalPA + share * poolPA
    const projIP = row.totalIP + share * poolIP
    projectedStatTotals['proj_obp'] = projPA > 0
      ? (row.weightedOBP + share * poolWeightedOBP) / projPA
      : 0
    projectedStatTotals['proj_era'] = projIP > 0
      ? (row.weightedERA + share * poolWeightedERA) / projIP
      : 0
    projectedStatTotals['proj_whip'] = projIP > 0
      ? (row.weightedWHIP + share * poolWeightedWHIP) / projIP
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
