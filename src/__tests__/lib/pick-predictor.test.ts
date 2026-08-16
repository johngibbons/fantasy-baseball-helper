/**
 * Characterization tests for the pick availability model.
 *
 * This is the sigma the season retrospective will check against the real 2026
 * draft: the board uses a variable sigma (6 + adp/250 * 6) while
 * backend/simulation/config.py ships USE_VARIABLE_SIGMA = False and a flat
 * ADP_SIGMA of 18. The two disagree, and neither has ever been measured against
 * an actual draft — see Phase 5 of the retrospective plan. These tests pin
 * today's behaviour so that comparison starts from a known baseline.
 */

import { computeAvailability } from '@/lib/pick-predictor'

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
      // sigma = 6 + adp/250 * 6, so one sigma past ADP is always ~15.9% available.
      for (const adp of [50, 150, 250]) {
        const sigma = 6 + (adp / 250) * 6
        const oneSigmaPast = computeAvailability(adp, Math.round(adp + sigma), 0)
        expect(oneSigmaPast).toBeCloseTo(0.159, 1)
      }
    })
  })
})
