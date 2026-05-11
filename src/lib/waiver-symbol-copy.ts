export type FormLevel = 'hot' | 'cool' | 'neutral' | 'cold'
export type SustainColor = 'green' | 'yellow' | 'red' | 'gray'
export type DeltaColor = 'green' | 'yellow' | 'red' | 'gray'

export const FORM_COPY: Record<FormLevel, string> = {
  hot:     'Hot streak — 14-day OPS at least 0.080 above season OPS.',
  cool:    'Warming — 14-day OPS 0.020 to 0.080 above season.',
  neutral: 'Steady — 14-day OPS within ±0.020 of season.',
  cold:    'Cold — 14-day OPS at least 0.080 below season.',
}

export const METRIC_LABELS: Record<string, string> = {
  xwoba_gap:     'xwOBA − wOBA (skill vs outcomes)',
  xwoba:         'xwOBA (expected wOBA)',
  barrel_pct:    'Barrel %',
  hard_hit_pct:  'Hard-hit % (95+ mph)',
  sprint_speed:  'Sprint speed',
  xera_gap:      'ERA − xERA (luck vs skill)',
  xera:          'xERA (expected ERA)',
  whiff_pct:     'Whiff %',
  csw_pct:       'CSW % (called strikes + whiffs)',
  bb_pct:        'Walk %',
  k_pct:         'Strikeout %',
  chase_rate:    'Chase rate (out-of-zone swings)',
}

export const SUSTAIN_COPY: Record<SustainColor, string> = {
  green:  'supports the hot streak; underlying skill agrees.',
  yellow: 'mixed signal; partly supports the hot run.',
  red:    'contradicts the hot streak; likely unsustainable.',
  gray:   'insufficient data to judge sustainability.',
}

export const DELTA_COPY: Record<DeltaColor, string> = {
  green:  'large positive shift vs season; strong underlying improvement.',
  yellow: 'modest positive shift; directionally encouraging.',
  red:    'negative shift; underlying signal moving the wrong way.',
  gray:   'insufficient signal or noise; discount this metric.',
}

export const SCORE_COMPONENT_COPY = {
  projection: '📊 Projection contribution — rest-of-season projection delta (ATC). Higher = projections favor the add.',
  production: '🔥 Recent production — 30-day box-score z-score vs replacement. Higher = standout recent output.',
  xwoba:      '🎯 Underlying skill — Statcast xwOBA vs projected wOBA. Higher = scouting metrics agree with the rec.',
  luck:       '🍀 Regression risk — negative means the player is overperforming xwOBA and may cool off.',
} as const

export const TIMING_COPY = {
  NOW:  'Acquire now — the signal is strong enough that delay costs expected value.',
  WAIT: 'Hold — evidence is mixed or thin; wait another window before claiming.',
} as const

function labelFor(metricKey: string): string {
  return METRIC_LABELS[metricKey] ?? metricKey.replace(/_/g, ' ')
}

export function tipForSustain(metricKey: string, color: SustainColor): string {
  return `${labelFor(metricKey)} — ${SUSTAIN_COPY[color]}`
}

export function tipForDelta(metricKey: string, color: DeltaColor): string {
  return `${labelFor(metricKey)} — ${DELTA_COPY[color]}`
}
