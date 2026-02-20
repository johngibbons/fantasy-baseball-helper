/**
 * Project final standings from current draft state + remaining value pool.
 *
 * Uses a simple proportional model: each team gets a share of the remaining
 * player pool proportional to their remaining picks.
 */

export interface ProjectedStanding {
  teamId: number
  teamName: string
  currentTotals: Record<string, number>
  projectedTotals: Record<string, number>
  projectedRanks: Record<string, number>
  projectedWins: number
  overallRank: number
}

/**
 * Project final standings for all teams.
 *
 * @param teamRows - Current team category data (from teamCategories.rows)
 * @param availablePlayers - Undrafted players with z-score data
 * @param cats - Category definitions [{key, label}]
 * @param rosterSize - Total roster slots per team (default 25)
 * @param pickSchedule - Flat pick schedule array
 * @param currentPickIndex - Current pick index in the schedule
 */
export function projectStandings(
  teamRows: { teamId: number; teamName: string; totals: Record<string, number>; count: number }[],
  availablePlayers: { mlb_id: number; zscores: Record<string, number> }[],
  cats: { key: string; label: string }[],
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
    // No more picks — projected = current
    return teamRows.map((row, i) => ({
      teamId: row.teamId,
      teamName: row.teamName,
      currentTotals: { ...row.totals },
      projectedTotals: { ...row.totals },
      projectedRanks: {},
      projectedWins: 0,
      overallRank: i + 1,
    }))
  }

  // Sum z-scores of all remaining available players per category (the pool)
  const poolTotals: Record<string, number> = {}
  for (const cat of cats) poolTotals[cat.key] = 0
  for (const p of availablePlayers) {
    for (const cat of cats) {
      poolTotals[cat.key] += (p.zscores[cat.key] ?? 0)
    }
  }

  // Project each team's totals
  const projected: ProjectedStanding[] = teamRows.map(row => {
    const teamRemaining = remainingPicks.get(row.teamId) ?? 0
    const share = teamRemaining / totalRemainingPicks
    const projectedTotals: Record<string, number> = {}

    for (const cat of cats) {
      const currentVal = row.totals[cat.key] ?? 0
      projectedTotals[cat.key] = currentVal + share * poolTotals[cat.key]
    }

    return {
      teamId: row.teamId,
      teamName: row.teamName,
      currentTotals: { ...row.totals },
      projectedTotals,
      projectedRanks: {},
      projectedWins: 0,
      overallRank: 0,
    }
  })

  // Rank teams per category from projected totals
  for (const cat of cats) {
    const sorted = [...projected].sort(
      (a, b) => (b.projectedTotals[cat.key] ?? 0) - (a.projectedTotals[cat.key] ?? 0)
    )
    sorted.forEach((s, i) => {
      s.projectedRanks[cat.key] = i + 1
    })
  }

  // Compute projected weekly wins from category ranks
  const numTeams = projected.length
  for (const standing of projected) {
    let totalWinProb = 0
    for (const cat of cats) {
      const rank = standing.projectedRanks[cat.key] ?? numTeams
      totalWinProb += (numTeams - rank) / (numTeams - 1)
    }
    standing.projectedWins = totalWinProb
  }

  // Compute overall rank from projected wins
  const byWins = [...projected].sort((a, b) => b.projectedWins - a.projectedWins)
  byWins.forEach((s, i) => {
    s.overallRank = i + 1
  })

  return projected
}
