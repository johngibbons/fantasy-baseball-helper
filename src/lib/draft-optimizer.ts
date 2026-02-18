// ── Draft Optimizer: Marginal Category Wins Model for H2H Categories ──
// Pure math functions, no React dependencies.

// ── Types ──

export interface CategoryAnalysis {
  catKey: string
  label: string
  myTotal: number
  myRank: number           // 1=best, 10=worst
  winProb: number          // 0.0-1.0, probability of winning vs random opponent
  gapAbove: number         // z-score gap to next team above (0 if rank 1)
  gapBelow: number         // z-score gap to next team below (0 if last)
  strategy: 'target' | 'neutral' | 'punt' | 'lock'
}

export interface CategoryGain {
  catKey: string
  label: string
  winProbBefore: number
  winProbAfter: number
}

export interface PlayerDraftScore {
  mlbId: number
  score: number
  mcw: number              // marginal category wins
  vona: number
  urgency: number
  badge: 'NOW' | 'WAIT' | null
  categoryGains: CategoryGain[]
}

export interface DraftRecommendation {
  primary: PlayerDraftScore & { fullName: string; position: string }
  explanation: string
  runnersUp: (PlayerDraftScore & { fullName: string; position: string })[]
}

// ── Core functions ──

/**
 * Compute win probability from rank.
 * Rank 1 = best = beats everyone. Rank N = worst = beats no one.
 * Ties count as 0.5 win / 0.5 loss.
 */
function winProbFromRank(rank: number, numTeams: number): number {
  if (numTeams <= 1) return 0.5
  // Teams I'm strictly better than = numTeams - rank
  return (numTeams - rank) / (numTeams - 1)
}

/**
 * Compute fractional rank for a value within a sorted descending array of other team totals.
 * Returns a rank from 1 (best) to numTeams (worst).
 * Handles ties by averaging positions.
 */
function computeRank(myValue: number, otherTotals: number[]): number {
  // otherTotals is sorted descending (best first)
  let teamsAbove = 0
  let tiedTeams = 0
  for (const t of otherTotals) {
    if (t > myValue) teamsAbove++
    else if (t === myValue) tiedTeams++
  }
  // My rank: 1-indexed, with tied teams sharing the middle of tied positions
  // rank = teamsAbove + 1 + tiedTeams/2 (average of tied range)
  return teamsAbove + 1 + tiedTeams / 2
}

/**
 * Compute per-category standings analysis for my team.
 */
export function analyzeCategoryStandings(
  myTeamId: number,
  myTotals: Record<string, number>,
  teamRows: { teamId: number; totals: Record<string, number> }[],
  cats: { key: string; label: string }[],
  numTeams: number
): CategoryAnalysis[] {
  const otherRows = teamRows.filter(r => r.teamId !== myTeamId)

  return cats.map(cat => {
    const myVal = myTotals[cat.key] ?? 0

    // Get other teams' values sorted descending
    const otherVals = otherRows
      .map(r => r.totals[cat.key] ?? 0)
      .sort((a, b) => b - a)

    const rank = computeRank(myVal, otherVals)
    const winProb = winProbFromRank(rank, numTeams)

    // Gap to team directly above (lower rank number = better)
    let gapAbove = 0
    const teamsAboveMe = otherVals.filter(v => v > myVal)
    if (teamsAboveMe.length > 0) {
      gapAbove = teamsAboveMe[teamsAboveMe.length - 1] - myVal // closest team above
    }

    // Gap to team directly below
    let gapBelow = 0
    const teamsBelowMe = otherVals.filter(v => v < myVal)
    if (teamsBelowMe.length > 0) {
      gapBelow = myVal - teamsBelowMe[0] // closest team below
    }

    return {
      catKey: cat.key,
      label: cat.label,
      myTotal: myVal,
      myRank: rank,
      winProb,
      gapAbove,
      gapBelow,
      strategy: 'neutral' as const,
    }
  })
}

/**
 * Detect punt/target/lock/neutral strategy per category.
 * Only activates after enough picks (6+).
 * Hard cap: max 2 punts.
 */
export function detectStrategy(
  standings: CategoryAnalysis[],
  myPickCount: number,
  numTeams: number
): CategoryAnalysis[] {
  if (myPickCount < 6) {
    // Not enough data — everything neutral
    return standings.map(s => ({ ...s, strategy: 'neutral' as const }))
  }

  // First pass: classify each category
  const classified = standings.map(s => {
    let strategy: CategoryAnalysis['strategy'] = 'neutral'

    if (s.myRank <= 2 && s.gapBelow >= 1.0) {
      // Top 2 with solid lead
      strategy = 'lock'
    } else if (s.myRank >= numTeams - 1 && s.gapAbove >= 3.0) {
      // Bottom 2 with huge gap to middle
      strategy = 'punt'
    } else if (s.myRank >= 4 && s.myRank <= 7) {
      // Near median — biggest marginal gains here
      strategy = 'target'
    }

    return { ...s, strategy }
  })

  // Enforce max 2 punts (keep the 2 worst-ranked ones as punts, rest become neutral)
  const puntCats = classified
    .filter(c => c.strategy === 'punt')
    .sort((a, b) => b.myRank - a.myRank) // worst rank first

  if (puntCats.length > 2) {
    const keepPunts = new Set(puntCats.slice(0, 2).map(c => c.catKey))
    return classified.map(c =>
      c.strategy === 'punt' && !keepPunts.has(c.catKey)
        ? { ...c, strategy: 'neutral' as const }
        : c
    )
  }

  return classified
}

/**
 * Compute marginal category wins for one player.
 *
 * For each category, computes how adding the player shifts win probability.
 * Punted categories get 0 weight.
 * Includes fractional credit for closing gaps without fully overtaking.
 */
export function computeMCW(
  playerZscores: Record<string, number>,
  myTotals: Record<string, number>,
  otherTeamTotals: Record<string, number[]>, // catKey → sorted desc array of other team totals
  strategies: Record<string, CategoryAnalysis['strategy']>,
  cats: { key: string; label: string }[],
  numTeams: number
): { mcw: number; categoryGains: CategoryGain[] } {
  let mcw = 0
  const categoryGains: CategoryGain[] = []

  for (const cat of cats) {
    const strategy = strategies[cat.key]

    // Skip punted categories entirely
    if (strategy === 'punt') {
      categoryGains.push({
        catKey: cat.key,
        label: cat.label,
        winProbBefore: 0,
        winProbAfter: 0,
      })
      continue
    }

    const myVal = myTotals[cat.key] ?? 0
    const playerVal = playerZscores[cat.key] ?? 0

    if (playerVal === 0) {
      // Player contributes nothing to this category
      const otherVals = otherTeamTotals[cat.key] ?? []
      const rankBefore = computeRank(myVal, otherVals)
      const winProbBefore = winProbFromRank(rankBefore, numTeams)
      categoryGains.push({
        catKey: cat.key,
        label: cat.label,
        winProbBefore,
        winProbAfter: winProbBefore,
      })
      continue
    }

    const newVal = myVal + playerVal
    const otherVals = otherTeamTotals[cat.key] ?? []

    const rankBefore = computeRank(myVal, otherVals)
    const rankAfter = computeRank(newVal, otherVals)

    const winProbBefore = winProbFromRank(rankBefore, numTeams)
    const winProbAfter = winProbFromRank(rankAfter, numTeams)

    let marginalWin = winProbAfter - winProbBefore

    // Fractional credit: if we closed a gap without fully overtaking
    if (marginalWin === 0 && playerVal > 0) {
      // Check if we closed a gap to someone above us
      const teamsAboveBefore = otherVals.filter(v => v > myVal)
      const teamsAboveAfter = otherVals.filter(v => v > newVal)
      if (teamsAboveBefore.length > 0 && teamsAboveAfter.length === teamsAboveBefore.length) {
        // Didn't overtake, but closed gap
        const closestAboveBefore = teamsAboveBefore[teamsAboveBefore.length - 1]
        const gapBefore = closestAboveBefore - myVal
        const gapAfter = closestAboveBefore - newVal
        if (gapBefore > 0) {
          const gapClosed = (gapBefore - gapAfter) / gapBefore
          marginalWin = gapClosed * 0.3 / (numTeams - 1) // small fractional credit
        }
      }
    }

    mcw += marginalWin
    categoryGains.push({
      catKey: cat.key,
      label: cat.label,
      winProbBefore,
      winProbAfter: winProbBefore + marginalWin,
    })
  }

  return { mcw, categoryGains }
}

/**
 * Compute standings confidence based on draft progress.
 * Ramps from 0 at pick 30 (round 3 in 10-team) to 1.0 at pick 100 (round 10).
 */
export function standingsConfidence(
  totalPicksMade: number
): number {
  return Math.max(0, Math.min(1, (totalPicksMade - 30) / 70))
}

/**
 * Compute full draft score combining MCW + VONA + urgency + roster fit.
 */
export function computeDraftScore(
  mcw: number,
  vona: number,
  urgency: number,
  rosterFit: number,
  confidence: number,
  draftProgress: number
): number {
  return mcw * 12.0 * confidence
    + vona * 1.5
    + urgency * 0.8
    + rosterFit * draftProgress
}

/**
 * Generate plain-English explanation for the recommendation.
 */
export function generateExplanation(
  player: { fullName: string; position: string },
  categoryGains: CategoryGain[],
  vona: number,
  urgency: number,
  rosterFit: number,
  strategies: Record<string, CategoryAnalysis['strategy']>
): string {
  const parts: string[] = []

  // Find the biggest win probability shift
  const significantGains = categoryGains
    .filter(g => g.winProbAfter - g.winProbBefore > 0.02)
    .sort((a, b) => (b.winProbAfter - b.winProbBefore) - (a.winProbAfter - a.winProbBefore))

  if (significantGains.length > 0) {
    const top = significantGains[0]
    const pctBefore = Math.round(top.winProbBefore * 100)
    const pctAfter = Math.round(top.winProbAfter * 100)
    parts.push(`Boosts ${top.label} win rate from ${pctBefore}% to ${pctAfter}%`)

    if (significantGains.length > 1) {
      const other = significantGains.slice(1, 3).map(g => g.label).join(', ')
      parts.push(`also helps ${other}`)
    }
  }

  if (vona >= 3.0) {
    parts.push(`high positional scarcity (VONA ${vona.toFixed(1)})`)
  }

  if (urgency >= 10) {
    parts.push(`likely gone before your next pick`)
  }

  if (rosterFit > 0) {
    parts.push(`fills a roster need`)
  }

  // Mention punted categories
  const punts = Object.entries(strategies).filter(([, s]) => s === 'punt')
  if (punts.length > 0) {
    // Check if player's value came from punted cats — if so, mention it doesn't
    const puntedGains = categoryGains.filter(g =>
      strategies[g.catKey] === 'punt' && g.winProbAfter !== g.winProbBefore
    )
    if (puntedGains.length === 0 && significantGains.length > 0) {
      // Good — player's value comes from non-punted categories
    }
  }

  if (parts.length === 0) {
    return `${player.fullName} is the best available value at ${player.position}.`
  }

  return `${player.fullName}: ${parts.join('. ')}.`
}

/**
 * Compute expected weekly wins from category win probabilities.
 */
export function expectedWeeklyWins(standings: CategoryAnalysis[]): number {
  return standings.reduce((sum, s) => {
    if (s.strategy === 'punt') return sum // punt = expected loss
    return sum + s.winProb
  }, 0)
}
