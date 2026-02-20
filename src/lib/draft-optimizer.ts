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
 *
 * Thresholds adapt to league format via playoffSpots:
 *   - More forgiving playoffs (e.g. 6/10) → higher punt gap requirement
 *     (punting is riskier when you only need to be average) and wider
 *     target zone (more middle ranks worth improving).
 *   - Strict playoffs (e.g. 4/10) → lower punt gap (punting is a viable
 *     concentration strategy) and narrower target zone.
 */
export function detectStrategy(
  standings: CategoryAnalysis[],
  myPickCount: number,
  numTeams: number,
  playoffSpots: number = 6
): CategoryAnalysis[] {
  if (myPickCount < 6) {
    return standings.map(s => ({ ...s, strategy: 'neutral' as const }))
  }

  // Playoff ratio drives threshold scaling.
  // ratio = 0.6 (6/10) → forgiving; ratio = 0.4 (4/10) → strict.
  const playoffRatio = playoffSpots / numTeams

  // Punt gap: higher when playoffs are forgiving (giving up a cat hurts more).
  // Base 3.0 at ratio 0.4, scales up to ~4.5 at ratio 0.6.
  const puntGap = 3.0 + (playoffRatio - 0.4) * 7.5  // 0.4→3.0, 0.5→3.75, 0.6→4.5

  // Punt rank threshold: bottom N ranks.  With forgiving playoffs, only
  // the very worst rank is punt-eligible (harder to justify).
  const puntRankFloor = playoffRatio >= 0.55
    ? numTeams          // must be dead last
    : numTeams - 1      // bottom 2

  // Target zone: ranks where marginal improvement yields the most wins.
  // Wider when playoffs are forgiving (more ranks matter).
  const targetLow = playoffRatio >= 0.55 ? 3 : 4
  const targetHigh = playoffRatio >= 0.55 ? 8 : 7

  const classified = standings.map(s => {
    let strategy: CategoryAnalysis['strategy'] = 'neutral'

    if (s.myRank <= 2 && s.gapBelow >= 1.0) {
      strategy = 'lock'
    } else if (s.myRank >= puntRankFloor && s.gapAbove >= puntGap) {
      strategy = 'punt'
    } else if (s.myRank >= targetLow && s.myRank <= targetHigh) {
      strategy = 'target'
    }

    return { ...s, strategy }
  })

  // Enforce max 2 punts (keep the 2 worst-ranked ones as punts, rest become neutral)
  const puntCats = classified
    .filter(c => c.strategy === 'punt')
    .sort((a, b) => b.myRank - a.myRank)

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

    // Fractional credit: if we closed a gap without fully overtaking.
    // Uses a convex curve (gapClosed^1.5) so that closing 80% of a gap
    // is worth much more than closing 20% — the closer you get, the more
    // likely weekly variance will complete the overtake in H2H matchups.
    if (marginalWin === 0 && playerVal > 0) {
      const teamsAboveBefore = otherVals.filter(v => v > myVal)
      const teamsAboveAfter = otherVals.filter(v => v > newVal)
      if (teamsAboveBefore.length > 0 && teamsAboveAfter.length === teamsAboveBefore.length) {
        const closestAboveBefore = teamsAboveBefore[teamsAboveBefore.length - 1]
        const gapBefore = closestAboveBefore - myVal
        const gapAfter = closestAboveBefore - newVal
        if (gapBefore > 0) {
          const gapClosed = (gapBefore - gapAfter) / gapBefore
          marginalWin = Math.pow(gapClosed, 1.5) * 0.55 / (numTeams - 1)
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

  if (vona >= 2.0) {
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
