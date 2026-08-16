/**
 * Characterization tests for the draft optimizer.
 *
 * Cross-language agreement is covered by draft-scoring-parity.test.ts. This
 * file pins the behaviour that only exists on the TypeScript side — the
 * per-category gain breakdown the board renders, the caps and multipliers on
 * the desperation bonus, and the explanation text — so the season
 * retrospective can retune constants without silently changing the UI.
 */

import {
  analyzeCategoryStandings,
  computeDesperationBonus,
  computeDraftScore,
  computeMCW,
  detectStrategy,
  expectedWeeklyWins,
  generateExplanation,
  standingsConfidence,
  type CategoryAnalysis,
} from '@/lib/draft-optimizer'
import { DRAFT_MODEL_CONFIG } from '@/lib/draft-model-config'

const CATS = [
  { key: 'zscore_r', label: 'R' },
  { key: 'zscore_sb', label: 'SB' },
  { key: 'zscore_k', label: 'K' },
]

function standing(over: Partial<CategoryAnalysis> = {}): CategoryAnalysis {
  return {
    catKey: 'zscore_r',
    label: 'R',
    myTotal: 0,
    myRank: 5,
    winProb: 0.5,
    gapAbove: 0,
    gapBelow: 0,
    strategy: 'neutral',
    ...over,
  }
}

describe('analyzeCategoryStandings', () => {
  const teamRows = [
    { teamId: 1, totals: { zscore_r: 10 } },
    { teamId: 2, totals: { zscore_r: 6 } },
    { teamId: 3, totals: { zscore_r: 2 } },
    { teamId: 99, totals: { zscore_r: 4 } },
  ]

  it('excludes my own team from the comparison field', () => {
    const [cat] = analyzeCategoryStandings(
      99, { zscore_r: 4 }, teamRows, [CATS[0]], 4)
    // Two teams above me (10, 6), so rank 3 of 4.
    expect(cat.myRank).toBe(3)
    expect(cat.winProb).toBeCloseTo((4 - 3) / 3, 6)
  })

  it('reports gaps to the nearest team above and below', () => {
    const [cat] = analyzeCategoryStandings(
      99, { zscore_r: 4 }, teamRows, [CATS[0]], 4)
    expect(cat.gapAbove).toBe(2)  // 6 - 4
    expect(cat.gapBelow).toBe(2)  // 4 - 2
  })

  it('treats a missing category total as zero', () => {
    const [cat] = analyzeCategoryStandings(99, {}, teamRows, [CATS[0]], 4)
    expect(cat.myTotal).toBe(0)
    expect(cat.myRank).toBe(4)
  })

  it('splits ties down the middle', () => {
    const rows = [
      { teamId: 1, totals: { zscore_r: 5 } },
      { teamId: 2, totals: { zscore_r: 5 } },
      { teamId: 99, totals: { zscore_r: 5 } },
    ]
    const [cat] = analyzeCategoryStandings(99, { zscore_r: 5 }, rows, [CATS[0]], 3)
    expect(cat.myRank).toBe(2) // 0 above + 1 + 2/2
  })
})

describe('detectStrategy', () => {
  it('stays neutral until the strategy has enough picks to be meaningful', () => {
    const standings = [standing({ myRank: 10, gapAbove: 9 })]
    const result = detectStrategy(standings, 5, 10, 6)
    expect(result[0].strategy).toBe('neutral')
  })

  it('locks a top-two category that has a real cushion', () => {
    const result = detectStrategy(
      [standing({ myRank: 1, gapBelow: 2.0 })], 8, 10, 6)
    expect(result[0].strategy).toBe('lock')
  })

  it('does not lock a top-two category that is barely ahead', () => {
    const result = detectStrategy(
      [standing({ myRank: 2, gapBelow: 0.4 })], 8, 10, 6)
    expect(result[0].strategy).not.toBe('lock')
  })

  it('caps punts at two, keeping the worst-ranked categories', () => {
    const standings = [
      standing({ catKey: 'a', myRank: 10, gapAbove: 9 }),
      standing({ catKey: 'b', myRank: 10, gapAbove: 9 }),
      standing({ catKey: 'c', myRank: 10, gapAbove: 9 }),
    ]
    const result = detectStrategy(standings, 8, 10, 6)
    expect(result.filter(s => s.strategy === 'punt')).toHaveLength(2)
    expect(result.filter(s => s.strategy !== 'punt')).toHaveLength(1)
  })

  it('requires a bigger hole to punt when playoffs are forgiving', () => {
    // puntGap = 3.0 + (ratio - 0.4) * 7.5 → 4.5 at 6/10, 3.0 at 4/10.
    const nearMiss = () => standing({ myRank: 10, gapAbove: 4.0 })
    expect(detectStrategy([nearMiss()], 8, 10, 6)[0].strategy).not.toBe('punt')
    expect(detectStrategy([nearMiss()], 8, 10, 4)[0].strategy).toBe('punt')
  })

  it('does not mutate the standings it is given', () => {
    const standings = [standing({ myRank: 1, gapBelow: 2.0 })]
    detectStrategy(standings, 8, 10, 6)
    expect(standings[0].strategy).toBe('neutral')
  })
})

describe('computeMCW', () => {
  const myTotals = { zscore_r: 5, zscore_sb: 5, zscore_k: 5 }
  const otherTotals = {
    zscore_r: [9, 7, 3, 1],
    zscore_sb: [9, 7, 3, 1],
    zscore_k: [9, 7, 3, 1],
  }
  const neutral = { zscore_r: 'neutral', zscore_sb: 'neutral', zscore_k: 'neutral' } as const

  it('reports a gain entry for every category, including untouched ones', () => {
    const { categoryGains } = computeMCW(
      { zscore_r: 3 }, myTotals, otherTotals, neutral, CATS, 5)
    expect(categoryGains.map(g => g.catKey))
      .toEqual(['zscore_r', 'zscore_sb', 'zscore_k'])
  })

  it('credits a category the player actually overtakes', () => {
    const { mcw, categoryGains } = computeMCW(
      { zscore_r: 3 }, myTotals, otherTotals, neutral, CATS, 5)
    const r = categoryGains.find(g => g.catKey === 'zscore_r')!
    expect(r.winProbAfter).toBeGreaterThan(r.winProbBefore)
    expect(mcw).toBeGreaterThan(0)
  })

  it('gives punted categories zero credit and zeroed gains', () => {
    const punted = { ...neutral, zscore_r: 'punt' } as const
    const { mcw, categoryGains } = computeMCW(
      { zscore_r: 3 }, myTotals, otherTotals, punted, CATS, 5)
    expect(mcw).toBe(0)
    const r = categoryGains.find(g => g.catKey === 'zscore_r')!
    expect(r.winProbBefore).toBe(0)
    expect(r.winProbAfter).toBe(0)
  })

  it('awards partial credit for closing a gap without overtaking', () => {
    const { mcw } = computeMCW(
      { zscore_r: 1 }, myTotals, otherTotals, neutral, CATS, 5)
    expect(mcw).toBeGreaterThan(0)
    expect(mcw).toBeLessThan(1 / 4)
  })

  it('rewards closing most of a gap far more than a little of it', () => {
    const near = computeMCW({ zscore_r: 1.8 }, myTotals, otherTotals, neutral, CATS, 5).mcw
    const far = computeMCW({ zscore_r: 0.4 }, myTotals, otherTotals, neutral, CATS, 5).mcw
    // Convex (gapClosed ^ 1.5): 4.5x the gap closed should buy more than 4.5x credit.
    expect(near / far).toBeGreaterThan(4.5)
  })

  it('is zero for a player who contributes nothing', () => {
    const { mcw } = computeMCW({}, myTotals, otherTotals, neutral, CATS, 5)
    expect(mcw).toBe(0)
  })
})

describe('standingsConfidence', () => {
  it('ramps linearly between the configured pick counts', () => {
    const { CONFIDENCE_START: start, CONFIDENCE_END: end } = DRAFT_MODEL_CONFIG
    expect(standingsConfidence(start)).toBe(0)
    expect(standingsConfidence(end)).toBe(1)
    expect(standingsConfidence((start + end) / 2)).toBeCloseTo(0.5, 6)
  })

  it('clamps outside the ramp', () => {
    expect(standingsConfidence(0)).toBe(0)
    expect(standingsConfidence(10_000)).toBe(1)
  })
})

describe('computeDesperationBonus', () => {
  const desperate = [
    standing({ catKey: 'zscore_r', winProb: 0.1 }),
    standing({ catKey: 'zscore_sb', winProb: 0.1 }),
  ]

  it('is zero when the weight is off', () => {
    expect(computeDesperationBonus({ zscore_r: 2 }, desperate, 0.35, 0)).toBe(0)
  })

  it('ignores categories that are already healthy', () => {
    const healthy = [standing({ catKey: 'zscore_r', winProb: 0.9 })]
    expect(computeDesperationBonus({ zscore_r: 2 }, healthy)).toBe(0)
  })

  it('ignores punted categories even when they are desperate', () => {
    const punted = [standing({ catKey: 'zscore_r', winProb: 0.1, strategy: 'punt' })]
    expect(computeDesperationBonus({ zscore_r: 2 }, punted)).toBe(0)
  })

  it('ignores players who do not help the desperate category', () => {
    expect(computeDesperationBonus({ zscore_r: -1 }, desperate)).toBe(0)
  })

  it('multiplies the bonus when several desperate categories are helped', () => {
    const single = computeDesperationBonus({ zscore_r: 1 }, desperate)
    const double = computeDesperationBonus({ zscore_r: 1, zscore_sb: 1 }, desperate)
    // Two cats helped → (1 + (2-1) * 0.25) = 1.25x on top of twice the base.
    expect(double).toBeCloseTo(single * 2 * 1.25, 6)
  })

  it('caps per-category z-score credit when a cap is set', () => {
    const uncapped = computeDesperationBonus({ zscore_r: 5 }, desperate, 0.35, 6, 0)
    const capped = computeDesperationBonus({ zscore_r: 5 }, desperate, 0.35, 6, 2)
    expect(capped).toBeLessThan(uncapped)
    expect(capped).toBeCloseTo(
      computeDesperationBonus({ zscore_r: 2 }, desperate, 0.35, 6, 2), 6)
  })

  it('applies the absolute maximum last', () => {
    const bonus = computeDesperationBonus(
      { zscore_r: 5, zscore_sb: 5 }, desperate, 0.35, 6, 0, 0.25, 3)
    expect(bonus).toBe(3)
  })
})

describe('computeDraftScore', () => {
  it('is a weighted sum of its four components', () => {
    const { MCW_WEIGHT, VONA_WEIGHT_MCW, URGENCY_WEIGHT_MCW } = DRAFT_MODEL_CONFIG
    expect(computeDraftScore(0.5, 2, 10, 1, 0.8, 0.5)).toBeCloseTo(
      0.5 * MCW_WEIGHT * 0.8 + 2 * VONA_WEIGHT_MCW + 10 * URGENCY_WEIGHT_MCW + 1 * 0.5,
      9,
    )
  })

  it('discards MCW entirely at zero confidence', () => {
    expect(computeDraftScore(99, 0, 0, 0, 0, 0)).toBe(0)
  })

  it('phases roster fit in with draft progress', () => {
    expect(computeDraftScore(0, 0, 0, 1, 1, 0)).toBe(0)
    expect(computeDraftScore(0, 0, 0, 1, 1, 1)).toBe(1)
  })
})

describe('expectedWeeklyWins', () => {
  it('sums win probabilities across non-punted categories', () => {
    const standings = [
      standing({ winProb: 0.6 }),
      standing({ winProb: 0.4 }),
      standing({ winProb: 0.9, strategy: 'punt' }),
    ]
    expect(expectedWeeklyWins(standings)).toBeCloseTo(1.0, 9)
  })
})

describe('generateExplanation', () => {
  const player = { fullName: 'Test Player', position: 'OF' }

  it('leads with the biggest win-probability swing', () => {
    const gains = [
      { catKey: 'zscore_r', label: 'R', winProbBefore: 0.3, winProbAfter: 0.5 },
      { catKey: 'zscore_sb', label: 'SB', winProbBefore: 0.4, winProbAfter: 0.45 },
    ]
    const text = generateExplanation(player, gains, 0, 0, 0, {})
    expect(text).toContain('Boosts R win rate from 30% to 50%')
    expect(text).toContain('also helps SB')
  })

  it('falls back to best-available wording when nothing moves', () => {
    const text = generateExplanation(player, [], 0, 0, 0, {})
    expect(text).toBe('Test Player is the best available value at OF.')
  })

  it('calls out scarcity, urgency and roster need above their thresholds', () => {
    const text = generateExplanation(player, [], 2.5, 12, 1, {})
    expect(text).toContain('high positional scarcity')
    expect(text).toContain('likely gone before your next pick')
    expect(text).toContain('fills a roster need')
  })
})
