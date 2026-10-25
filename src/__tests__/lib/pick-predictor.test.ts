/**
 * Tests for the pick availability model.
 *
 * The sigma comes from DRAFT_MODEL_CONFIG and was measured against the real
 * 2026 draft (RETROSPECTIVE_2026.md, Layer C). The simulator computes the same
 * thing; draft-scoring-parity.test.ts holds the two implementations together.
 */

import { DRAFT_MODEL_CONFIG } from '@/lib/draft-model-config'
import { availabilitySigma, computeAvailability } from '@/lib/pick-predictor'

describe('computeAvailability', () => {
  it('is near certain well before a player is on the clock', () => {
    // Target pick 10 for a player going around 100th.
    expect(computeAvailability(100, 5, 5)).toBeGreaterThan(0.99)
  })

  it('is near zero well past a player s ADP', () => {
    expect(computeAvailability(10, 50, 10)).toBeLessThan(0.01)
  })

  it('is a coin flip exactly at the player s ADP', () => {
    expect(computeAvailability(50, 25, 25)).toBeCloseTo(0.5, 2)
  })

  it('falls monotonically as the target pick advances', () => {
    const probabilities = [0, 10, 20, 30, 40, 50, 60].map(
      picksSoFar => computeAvailability(40, picksSoFar, 5))
    for (let i = 1; i < probabilities.length; i++) {
      expect(probabilities[i]).toBeLessThanOrEqual(probabilities[i - 1])
    }
  })

  it('always returns a probability', () => {
    for (const adp of [1, 50, 250, 500]) {
      for (const soFar of [0, 100, 400]) {
        const p = computeAvailability(adp, soFar, 12)
        expect(p).toBeGreaterThanOrEqual(0)
        expect(p).toBeLessThanOrEqual(1)
      }
    }
  })

  describe('keeper adjustment', () => {
    it('makes a player likelier to be gone when keepers pull ADP forward', () => {
      const withoutKeepers = computeAvailability(60, 30, 10, 0)
      const withKeepers = computeAvailability(60, 30, 10, 15)
      expect(withKeepers).toBeLessThan(withoutKeepers)
    })

    it('treats the adjustment as a straight shift in effective ADP', () => {
      expect(computeAvailability(60, 30, 10, 15))
        .toBeCloseTo(computeAvailability(45, 30, 10, 0), 9)
    })
  })

  describe('variable sigma', () => {
    it('is more confident about early picks than late ones', () => {
      // Same distance past ADP, but a later pick has a wider sigma, so the
      // probability sits closer to 0.5.
      const early = computeAvailability(20, 26, 4)   // 10 picks past ADP 20
      const late = computeAvailability(200, 206, 4)  // 10 picks past ADP 200
      expect(late).toBeGreaterThan(early)
    })

    it('grows sigma linearly with ADP', () => {
      const { ADP_SIGMA_INTERCEPT, ADP_SIGMA_SLOPE } = DRAFT_MODEL_CONFIG
      for (const adp of [50, 150, 250]) {
        expect(availabilitySigma(adp))
          .toBeCloseTo(ADP_SIGMA_INTERCEPT + ADP_SIGMA_SLOPE * adp, 9)
        // One sigma past ADP is always about 15.9% available.
        const oneSigmaPast = computeAvailability(adp, adp + availabilitySigma(adp), 0)
        expect(oneSigmaPast).toBeCloseTo(0.159, 2)
      }
    })

    it('keeps a mid-round player 20 picks past ADP a real possibility', () => {
      // In the 2026 draft players around ADP 120 went with a spread of ~32
      // picks. The old formula (sigma ~9 here) put this at about 1%.
      expect(computeAvailability(120, 140, 0)).toBeGreaterThan(0.15)
    })
  })
})
