/**
 * TypeScript half of the cross-language draft-scoring parity check.
 *
 * The draft scoring model is implemented twice — src/lib/draft-optimizer.ts
 * drives the live draft board, backend/simulation/scoring_model.py drives the
 * simulator, the Optuna tuner, and the season retrospective. The constants used
 * to be hand-copied between them, so they could drift silently and leave every
 * offline experiment measuring a different model than the one that drafts.
 *
 * The fixture is generated from the Python side; both languages assert against
 * it. See tests/backend/simulation/test_scoring_parity.py for the other half.
 */

import fs from 'fs'
import path from 'path'

import {
  analyzeCategoryStandings,
  computeDesperationBonus,
  computeDraftScore,
  computeMCW,
  detectStrategy,
  standingsConfidence,
  type CategoryAnalysis,
} from '@/lib/draft-optimizer'
import { DRAFT_MODEL_CONFIG } from '@/lib/draft-model-config'

const FIXTURE_PATH = path.join(
  process.cwd(),
  'backend/data/fixtures/draft_scoring_parity.json',
)

type Fixture = {
  config: Record<string, number | boolean | null>
  cases: Record<string, any[]>
}

const fixture: Fixture = JSON.parse(fs.readFileSync(FIXTURE_PATH, 'utf-8'))
const TOLERANCE = 9 // digits for toBeCloseTo

/**
 * The TS entry point takes team rows and filters out my own team, while the
 * Python one takes the other teams' totals directly. Wrap each opponent total
 * in a synthetic team so the two are given identical information.
 */
function teamRowsFrom(otherTeamTotals: Record<string, number[]>, cats: string[]) {
  const teamCount = otherTeamTotals[cats[0]].length
  const rows: { teamId: number; totals: Record<string, number> }[] = []
  for (let i = 0; i < teamCount; i++) {
    const totals: Record<string, number> = {}
    for (const cat of cats) totals[cat] = otherTeamTotals[cat][i]
    rows.push({ teamId: i + 1, totals })
  }
  return rows
}

const MY_TEAM_ID = 999

describe('draft scoring parity with the Python simulator', () => {
  it('the fixture describes the coefficients this code actually uses', () => {
    expect(DRAFT_MODEL_CONFIG.MCW_WEIGHT).toBe(fixture.config.MCW_WEIGHT)
    expect(DRAFT_MODEL_CONFIG.VONA_WEIGHT_MCW).toBe(fixture.config.VONA_WEIGHT_MCW)
    expect(DRAFT_MODEL_CONFIG.URGENCY_WEIGHT_MCW).toBe(fixture.config.URGENCY_WEIGHT_MCW)
    expect(DRAFT_MODEL_CONFIG.VONA_WEIGHT_BPA).toBe(fixture.config.VONA_WEIGHT_BPA)
    expect(DRAFT_MODEL_CONFIG.URGENCY_WEIGHT_BPA).toBe(fixture.config.URGENCY_WEIGHT_BPA)
    expect(DRAFT_MODEL_CONFIG.AVAILABILITY_DISCOUNT).toBe(fixture.config.AVAILABILITY_DISCOUNT)
    expect(DRAFT_MODEL_CONFIG.BENCH_PENALTY_RATE).toBe(fixture.config.BENCH_PENALTY_RATE)
    expect(DRAFT_MODEL_CONFIG.CONFIDENCE_START).toBe(fixture.config.CONFIDENCE_START)
    expect(DRAFT_MODEL_CONFIG.CONFIDENCE_END).toBe(fixture.config.CONFIDENCE_END)
    expect(DRAFT_MODEL_CONFIG.DESPERATION_THRESHOLD).toBe(fixture.config.DESPERATION_THRESHOLD)
    expect(DRAFT_MODEL_CONFIG.DESPERATION_WEIGHT).toBe(fixture.config.DESPERATION_WEIGHT)
    expect(DRAFT_MODEL_CONFIG.DESPERATION_MULTI_CAT).toBe(fixture.config.DESPERATION_MULTI_CAT)
    expect(DRAFT_MODEL_CONFIG.ADP_SIGMA).toBe(fixture.config.ADP_SIGMA)
    expect(DRAFT_MODEL_CONFIG.NUM_TEAMS).toBe(fixture.config.NUM_TEAMS)
    expect(DRAFT_MODEL_CONFIG.PLAYOFF_SPOTS).toBe(fixture.config.PLAYOFF_SPOTS)
  })

  it('standingsConfidence matches', () => {
    for (const testCase of fixture.cases.standings_confidence) {
      expect(standingsConfidence(testCase.total_picks_made))
        .toBeCloseTo(testCase.expected, TOLERANCE)
    }
  })

  it('computeDraftScore matches', () => {
    for (const testCase of fixture.cases.compute_draft_score) {
      const actual = computeDraftScore(
        testCase.mcw, testCase.vona, testCase.urgency,
        testCase.roster_fit, testCase.confidence, testCase.draft_progress,
      )
      expect(actual).toBeCloseTo(testCase.expected, TOLERANCE)
    }
  })

  it('analyzeCategoryStandings + detectStrategy match', () => {
    for (const testCase of fixture.cases.detect_strategy) {
      const catKeys = testCase.cats.map((c: any) => c.key)
      const raw = analyzeCategoryStandings(
        MY_TEAM_ID,
        testCase.my_totals,
        teamRowsFrom(testCase.other_team_totals, catKeys),
        testCase.cats,
        testCase.num_teams,
      )
      const classified: CategoryAnalysis[] = detectStrategy(
        raw, testCase.my_pick_count, testCase.num_teams, testCase.playoff_spots,
      )
      const byKey = new Map(classified.map(s => [s.catKey, s]))

      for (const want of testCase.expected) {
        const got = byKey.get(want.cat_key)!
        expect(got).toBeDefined()
        expect(got.myRank).toBeCloseTo(want.my_rank, TOLERANCE)
        expect(got.winProb).toBeCloseTo(want.win_prob, TOLERANCE)
        expect(got.gapAbove).toBeCloseTo(want.gap_above, TOLERANCE)
        expect(got.gapBelow).toBeCloseTo(want.gap_below, TOLERANCE)
        expect(`${want.cat_key}:${got.strategy}`)
          .toBe(`${want.cat_key}:${want.strategy}`)
      }
    }
  })

  it('computeMCW matches', () => {
    for (const testCase of fixture.cases.compute_mcw) {
      const { mcw } = computeMCW(
        testCase.player_zscores,
        testCase.my_totals,
        testCase.other_team_totals,
        testCase.strategies,
        testCase.cats,
        testCase.num_teams,
      )
      expect(`${testCase.label}:${mcw.toFixed(9)}`)
        .toBe(`${testCase.label}:${testCase.expected.toFixed(9)}`)
    }
  })

  it('computeDesperationBonus matches', () => {
    for (const testCase of fixture.cases.compute_desperation_bonus) {
      // Only catKey, winProb and strategy are read by the function.
      const standings = testCase.standings.map((s: any) => ({
        catKey: s.cat_key,
        label: s.cat_key,
        myTotal: 0,
        myRank: 0,
        winProb: s.win_prob,
        gapAbove: 0,
        gapBelow: 0,
        strategy: s.strategy,
      })) as CategoryAnalysis[]

      const actual = computeDesperationBonus(
        testCase.player_zscores, standings, testCase.threshold,
        testCase.weight, testCase.cap, testCase.multi_cat, testCase.max_bonus,
      )
      expect(`${testCase.label}:${actual.toFixed(9)}`)
        .toBe(`${testCase.label}:${testCase.expected.toFixed(9)}`)
    }
  })
})
