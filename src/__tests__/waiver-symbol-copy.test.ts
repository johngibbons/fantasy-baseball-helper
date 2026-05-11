import {
  FORM_COPY,
  METRIC_LABELS,
  SUSTAIN_COPY,
  DELTA_COPY,
  SCORE_COMPONENT_COPY,
  TIMING_COPY,
  tipForSustain,
  tipForDelta,
} from '@/lib/waiver-symbol-copy'

describe('waiver-symbol-copy', () => {
  it('covers all four form levels', () => {
    for (const lvl of ['hot', 'cool', 'neutral', 'cold'] as const) {
      expect(FORM_COPY[lvl]).toMatch(/OPS/)
    }
  })

  it('covers all sustainability colors', () => {
    for (const c of ['green', 'yellow', 'red', 'gray'] as const) {
      expect(SUSTAIN_COPY[c]).toBeTruthy()
    }
  })

  it('covers all delta colors', () => {
    for (const c of ['green', 'yellow', 'red', 'gray'] as const) {
      expect(DELTA_COPY[c]).toBeTruthy()
    }
  })

  it('labels every metric emitted by the breakouts backend', () => {
    const hotKeys = [
      'xwoba_gap', 'barrel_pct', 'hard_hit_pct', 'sprint_speed',
      'xera_gap', 'whiff_pct', 'csw_pct', 'bb_pct',
    ]
    const stealthKeys = [
      'xwoba', 'barrel_pct', 'hard_hit_pct', 'sprint_speed',
      'xera', 'whiff_pct', 'k_pct', 'bb_pct', 'chase_rate',
    ]
    for (const k of [...hotKeys, ...stealthKeys]) {
      expect(METRIC_LABELS[k]).toBeTruthy()
    }
  })

  it('covers all score components', () => {
    for (const k of ['projection', 'production', 'xwoba', 'luck'] as const) {
      expect(SCORE_COMPONENT_COPY[k]).toBeTruthy()
    }
  })

  it('covers NOW and WAIT', () => {
    expect(TIMING_COPY.NOW).toBeTruthy()
    expect(TIMING_COPY.WAIT).toBeTruthy()
  })

  it('tipForSustain combines metric label + color copy', () => {
    const tip = tipForSustain('barrel_pct', 'green')
    expect(tip).toContain('Barrel')
    expect(tip).toContain('support')
  })

  it('tipForDelta combines metric label + color copy', () => {
    const tip = tipForDelta('xwoba', 'red')
    expect(tip).toContain('xwOBA')
  })

  it('tipForSustain falls back gracefully for unknown metrics', () => {
    const tip = tipForSustain('unknown_metric', 'green')
    expect(tip).toContain('unknown metric')
  })
})
