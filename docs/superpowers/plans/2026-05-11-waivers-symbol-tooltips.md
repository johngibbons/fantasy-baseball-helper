# Waivers Page Symbol Tooltips Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add hover tooltips to every symbol on `/waivers` (form badges, sustainability/delta colored badges, score-component icons, NOW/WAIT pills, modal column headers) so users can learn what each symbol means by hovering it.

**Architecture:** A single new `<InfoTip>` component (pure-CSS, group-hover) wraps each existing symbol. All explanation copy lives in one constants file (`waiver-symbol-copy.ts`) keyed by metric and color, with a fallback to the existing derived label for unknown metrics. No new dependencies, no JS state, no positioning library.

**Tech Stack:** Next.js 15, React 19, Tailwind CSS, TypeScript, Jest + React Testing Library (Node 22 via Volta).

**Spec:** `docs/superpowers/specs/2026-05-11-waivers-symbol-tooltips-design.md`

---

## File Map

| Path | Action | Responsibility |
|---|---|---|
| `src/lib/waiver-symbol-copy.ts` | create | All tooltip copy: form levels, metric labels, color suffixes, score components, timing |
| `src/components/InfoTip.tsx` | create | Hover-triggered styled tooltip wrapper |
| `src/__tests__/waiver-symbol-copy.test.ts` | create | Lock down metric × color coverage |
| `src/__tests__/components/InfoTip.test.tsx` | create | Verify tooltip renders content reachable to screen readers |
| `src/components/FormBadge.tsx` | modify | Render badge inside `<InfoTip>` |
| `src/app/waivers/_components/HotTab.tsx` | modify | Wrap sustainability badges in `<InfoTip>` |
| `src/app/waivers/_components/StealthTab.tsx` | modify | Wrap metric-delta badges in `<InfoTip>` |
| `src/app/waivers/_components/ProjectionsTab.tsx` | modify | Convert 4 score-component `<span title=>` to `<InfoTip>` |
| `src/components/ScoreDetailModal.tsx` | modify | Convert 2 column-header `title=` and add tips on NOW/WAIT pills |

---

## Test Runner Note

Jest requires Node ≥18. System default is Node 16 (crashes on `availableParallelism`). All Jest commands in this plan use the volta-installed Node 22 binary path:

```
/Users/jgibbons/.volta/tools/image/node/22.15.0/bin/npx jest <args>
```

If that path doesn't exist on the executor's machine, run `volta install node@22` first.

---

## Task 1: Copy constants file

**Files:**
- Create: `src/lib/waiver-symbol-copy.ts`
- Test: `src/__tests__/waiver-symbol-copy.test.ts`

- [ ] **Step 1: Write the failing test**

Create `src/__tests__/waiver-symbol-copy.test.ts`:

```typescript
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
    // Hot sustainability keys (hitter + pitcher)
    const hotKeys = [
      'xwoba_gap', 'barrel_pct', 'hard_hit_pct', 'sprint_speed',
      'xera_gap', 'whiff_pct', 'csw_pct', 'bb_pct',
    ]
    // Stealth delta keys, post `delta_` strip
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/jgibbons/.volta/tools/image/node/22.15.0/bin/npx jest src/__tests__/waiver-symbol-copy.test.ts`

Expected: FAIL with "Cannot find module '@/lib/waiver-symbol-copy'".

- [ ] **Step 3: Create the constants module**

Create `src/lib/waiver-symbol-copy.ts`:

```typescript
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/jgibbons/.volta/tools/image/node/22.15.0/bin/npx jest src/__tests__/waiver-symbol-copy.test.ts`

Expected: PASS, 9 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/lib/waiver-symbol-copy.ts src/__tests__/waiver-symbol-copy.test.ts
git commit -m "$(/bin/cat <<'EOF'
feat(waivers): symbol copy constants for tooltip layer

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: InfoTip component

**Files:**
- Create: `src/components/InfoTip.tsx`
- Test: `src/__tests__/components/InfoTip.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `src/__tests__/components/InfoTip.test.tsx`:

```typescript
import { render, screen } from '@testing-library/react'
import InfoTip from '@/components/InfoTip'

describe('InfoTip', () => {
  it('renders the trigger child', () => {
    render(<InfoTip content="hello">Trigger</InfoTip>)
    expect(screen.getByText('Trigger')).toBeInTheDocument()
  })

  it('renders the tooltip content in the DOM (so it is hover-discoverable)', () => {
    render(<InfoTip content="hello world">⚡</InfoTip>)
    expect(screen.getByText('hello world')).toBeInTheDocument()
  })

  it('links the trigger to the tooltip via aria-describedby', () => {
    render(<InfoTip content="hello">Trigger</InfoTip>)
    const trigger = screen.getByText('Trigger')
    const describedBy = trigger.getAttribute('aria-describedby')
    expect(describedBy).toBeTruthy()
    const tip = document.getElementById(describedBy!)
    expect(tip).not.toBeNull()
    expect(tip!.textContent).toBe('hello')
  })

  it('accepts ReactNode content (renders a swatch alongside text)', () => {
    render(
      <InfoTip content={<><span data-testid="swatch" />structured</>}>
        ⚡
      </InfoTip>,
    )
    expect(screen.getByTestId('swatch')).toBeInTheDocument()
    expect(screen.getByText('structured')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/jgibbons/.volta/tools/image/node/22.15.0/bin/npx jest src/__tests__/components/InfoTip.test.tsx`

Expected: FAIL with "Cannot find module '@/components/InfoTip'".

- [ ] **Step 3: Create InfoTip**

Create `src/components/InfoTip.tsx`:

```typescript
'use client'

import { useId, type ReactNode } from 'react'

interface InfoTipProps {
  content: string | ReactNode
  children: ReactNode
  className?: string
}

export default function InfoTip({ content, children, className }: InfoTipProps) {
  const tipId = useId()
  return (
    <span className={`relative inline-block group ${className ?? ''}`}>
      <span aria-describedby={tipId}>{children}</span>
      <span
        id={tipId}
        role="tooltip"
        className={[
          'pointer-events-none absolute left-0 top-full mt-1 z-50',
          'opacity-0 group-hover:opacity-100 transition-opacity duration-100',
          'bg-gray-800/95 border border-white/10 rounded-md shadow-xl',
          'px-3 py-2 text-xs text-gray-200 leading-snug',
          'max-w-xs whitespace-normal',
        ].join(' ')}
      >
        {content}
      </span>
    </span>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/jgibbons/.volta/tools/image/node/22.15.0/bin/npx jest src/__tests__/components/InfoTip.test.tsx`

Expected: PASS, 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/components/InfoTip.tsx src/__tests__/components/InfoTip.test.tsx
git commit -m "$(/bin/cat <<'EOF'
feat(ui): InfoTip hover tooltip component

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Wire FormBadge to InfoTip

**Files:**
- Modify: `src/components/FormBadge.tsx`

- [ ] **Step 1: Replace the FormBadge body**

The current file:

```typescript
'use client'

interface Props {
  delta?: number | null
  level?: 'hot' | 'cool' | 'cold' | 'neutral' | null
  tooltip?: string
}

type Level = 'hot' | 'cool' | 'cold' | 'neutral'

function levelFromDelta(d: number): Level {
  if (d >= 0.080) return 'hot'
  if (d >= 0.020) return 'cool'
  if (d <= -0.080) return 'cold'
  return 'neutral'
}

const styles: Record<Level, string> = {
  hot:     'bg-emerald-500/30 text-emerald-300',
  cool:    'bg-emerald-500/15 text-emerald-200',
  neutral: 'bg-gray-500/20 text-gray-300',
  cold:    'bg-red-500/25 text-red-300',
}

const labels: Record<Level, string> = {
  hot:     '🔥',
  cool:    '↗',
  neutral: '→',
  cold:    '❄',
}

export default function FormBadge({ delta, level, tooltip }: Props) {
  const lvl: Level | null =
    level ?? (delta != null ? levelFromDelta(delta) : null)
  if (!lvl) return null
  return (
    <span
      className={`inline-block px-1.5 py-0.5 rounded text-xs ${styles[lvl]}`}
      title={tooltip ?? `recent form: ${lvl}`}
    >
      {labels[lvl]}
    </span>
  )
}
```

Replace with:

```typescript
'use client'

import InfoTip from '@/components/InfoTip'
import { FORM_COPY } from '@/lib/waiver-symbol-copy'

interface Props {
  delta?: number | null
  level?: 'hot' | 'cool' | 'cold' | 'neutral' | null
  tooltip?: string
}

type Level = 'hot' | 'cool' | 'cold' | 'neutral'

function levelFromDelta(d: number): Level {
  if (d >= 0.080) return 'hot'
  if (d >= 0.020) return 'cool'
  if (d <= -0.080) return 'cold'
  return 'neutral'
}

const styles: Record<Level, string> = {
  hot:     'bg-emerald-500/30 text-emerald-300',
  cool:    'bg-emerald-500/15 text-emerald-200',
  neutral: 'bg-gray-500/20 text-gray-300',
  cold:    'bg-red-500/25 text-red-300',
}

const labels: Record<Level, string> = {
  hot:     '🔥',
  cool:    '↗',
  neutral: '→',
  cold:    '❄',
}

export default function FormBadge({ delta, level, tooltip }: Props) {
  const lvl: Level | null =
    level ?? (delta != null ? levelFromDelta(delta) : null)
  if (!lvl) return null
  return (
    <InfoTip content={tooltip ?? FORM_COPY[lvl]}>
      <span className={`inline-block px-1.5 py-0.5 rounded text-xs ${styles[lvl]}`}>
        {labels[lvl]}
      </span>
    </InfoTip>
  )
}
```

- [ ] **Step 2: Verify Next.js build still passes**

Run: `PATH="/Users/jgibbons/.nvm/versions/node/v20.20.0/bin:$PATH" npx tsc --noEmit`

Expected: no TypeScript errors.

- [ ] **Step 3: Commit**

```bash
git add src/components/FormBadge.tsx
git commit -m "$(/bin/cat <<'EOF'
feat(ui): FormBadge uses InfoTip for richer hover copy

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Wire Hot tab sustainability badges

**Files:**
- Modify: `src/app/waivers/_components/HotTab.tsx`

- [ ] **Step 1: Add imports**

At the top of `HotTab.tsx`, add to the existing imports:

```typescript
import InfoTip from '@/components/InfoTip'
import { tipForSustain, type SustainColor } from '@/lib/waiver-symbol-copy'
```

- [ ] **Step 2: Replace the sustainability badge span**

Current code (around line 173-183):

```tsx
<div className="flex flex-wrap gap-1">
  {Object.entries(r.sustainability_badges).map(([metric, color]) => (
    <span
      key={metric}
      className={`px-1.5 py-0.5 rounded text-xs ${badgeColor[color]}`}
      title={`${metric}: ${color}`}
    >
      {metric.replace('_', ' ')}
    </span>
  ))}
</div>
```

Replace with:

```tsx
<div className="flex flex-wrap gap-1">
  {Object.entries(r.sustainability_badges).map(([metric, color]) => (
    <InfoTip key={metric} content={tipForSustain(metric, color as SustainColor)}>
      <span className={`px-1.5 py-0.5 rounded text-xs ${badgeColor[color]}`}>
        {metric.replace('_', ' ')}
      </span>
    </InfoTip>
  ))}
</div>
```

- [ ] **Step 3: Verify TypeScript**

Run: `PATH="/Users/jgibbons/.nvm/versions/node/v20.20.0/bin:$PATH" npx tsc --noEmit`

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add src/app/waivers/_components/HotTab.tsx
git commit -m "$(/bin/cat <<'EOF'
feat(waivers): explain Hot tab sustainability badges on hover

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Wire Stealth tab metric-delta badges

**Files:**
- Modify: `src/app/waivers/_components/StealthTab.tsx`

- [ ] **Step 1: Add imports**

At the top of `StealthTab.tsx`, add to the existing imports:

```typescript
import InfoTip from '@/components/InfoTip'
import { tipForDelta, type DeltaColor } from '@/lib/waiver-symbol-copy'
```

- [ ] **Step 2: Replace the metric-delta badge span**

Current code (around line 159-169):

```tsx
<div className="flex flex-wrap gap-1">
  {Object.entries(r.metric_deltas).map(([k, m]) => (
    <span
      key={k}
      className={`px-1.5 py-0.5 rounded text-xs ${badgeColor[m.badge]}`}
      title={`${k}: ${m.value}`}
    >
      {k.replace('delta_', '')}: {m.value > 0 ? '+' : ''}{m.value}
    </span>
  ))}
</div>
```

Replace with:

```tsx
<div className="flex flex-wrap gap-1">
  {Object.entries(r.metric_deltas).map(([k, m]) => {
    const metricKey = k.replace('delta_', '')
    return (
      <InfoTip key={k} content={tipForDelta(metricKey, m.badge as DeltaColor)}>
        <span className={`px-1.5 py-0.5 rounded text-xs ${badgeColor[m.badge]}`}>
          {metricKey}: {m.value > 0 ? '+' : ''}{m.value}
        </span>
      </InfoTip>
    )
  })}
</div>
```

- [ ] **Step 3: Verify TypeScript**

Run: `PATH="/Users/jgibbons/.nvm/versions/node/v20.20.0/bin:$PATH" npx tsc --noEmit`

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add src/app/waivers/_components/StealthTab.tsx
git commit -m "$(/bin/cat <<'EOF'
feat(waivers): explain Stealth tab metric-delta badges on hover

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Wire Projections tab score-component icons

**Files:**
- Modify: `src/app/waivers/_components/ProjectionsTab.tsx`

- [ ] **Step 1: Add imports**

At the top of `ProjectionsTab.tsx`, add to the existing imports:

```typescript
import InfoTip from '@/components/InfoTip'
import { SCORE_COMPONENT_COPY } from '@/lib/waiver-symbol-copy'
```

- [ ] **Step 2: Replace the four score-component spans**

Current code (around line 469-477):

```tsx
{rec.score_breakdown && (
  <div className="text-[10px] text-gray-400 mt-0.5 font-mono">
    <span title="Projection contribution (ATC RoS)">📊 {rec.score_breakdown.projection_contribution.toFixed(2)}</span>{' '}
    <span title="Recent 30d production (z-score)">🔥 {rec.score_breakdown.production_contribution.toFixed(2)}</span>{' '}
    <span title="Underlying skill (xwOBA vs projected)">🎯 {rec.score_breakdown.xwoba_contribution.toFixed(2)}</span>{' '}
    <span title="Luck adjustment (overperforming xwOBA)" className={rec.score_breakdown.luck_contribution < -0.001 ? 'text-red-400' : ''}>
      🍀 {rec.score_breakdown.luck_contribution.toFixed(2)}
    </span>
  </div>
)}
```

Replace with:

```tsx
{rec.score_breakdown && (
  <div className="text-[10px] text-gray-400 mt-0.5 font-mono">
    <InfoTip content={SCORE_COMPONENT_COPY.projection}>
      <span>📊 {rec.score_breakdown.projection_contribution.toFixed(2)}</span>
    </InfoTip>{' '}
    <InfoTip content={SCORE_COMPONENT_COPY.production}>
      <span>🔥 {rec.score_breakdown.production_contribution.toFixed(2)}</span>
    </InfoTip>{' '}
    <InfoTip content={SCORE_COMPONENT_COPY.xwoba}>
      <span>🎯 {rec.score_breakdown.xwoba_contribution.toFixed(2)}</span>
    </InfoTip>{' '}
    <InfoTip content={SCORE_COMPONENT_COPY.luck}>
      <span className={rec.score_breakdown.luck_contribution < -0.001 ? 'text-red-400' : ''}>
        🍀 {rec.score_breakdown.luck_contribution.toFixed(2)}
      </span>
    </InfoTip>
  </div>
)}
```

- [ ] **Step 3: Verify TypeScript**

Run: `PATH="/Users/jgibbons/.nvm/versions/node/v20.20.0/bin:$PATH" npx tsc --noEmit`

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add src/app/waivers/_components/ProjectionsTab.tsx
git commit -m "$(/bin/cat <<'EOF'
feat(waivers): explain score-component icons on Projections tab

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Wire ScoreDetailModal headers and NOW/WAIT pills

**Files:**
- Modify: `src/components/ScoreDetailModal.tsx`

- [ ] **Step 1: Add imports**

At the top of `ScoreDetailModal.tsx`, add:

```typescript
import InfoTip from '@/components/InfoTip'
import { TIMING_COPY } from '@/lib/waiver-symbol-copy'
```

- [ ] **Step 2: Replace the NOW and WAIT pills**

Current code (around line 221-226):

```tsx
{d.badge === 'NOW' && (
  <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-red-900/60 text-red-300 border border-red-700/50 leading-none">NOW</span>
)}
{d.badge === 'WAIT' && (
  <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-gray-800 text-gray-500 border border-gray-700/50 leading-none">WAIT</span>
)}
```

Replace with:

```tsx
{d.badge === 'NOW' && (
  <InfoTip content={TIMING_COPY.NOW}>
    <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-red-900/60 text-red-300 border border-red-700/50 leading-none">NOW</span>
  </InfoTip>
)}
{d.badge === 'WAIT' && (
  <InfoTip content={TIMING_COPY.WAIT}>
    <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-gray-800 text-gray-500 border border-gray-700/50 leading-none">WAIT</span>
  </InfoTip>
)}
```

- [ ] **Step 3: Replace the two column headers**

Current code (around line 469-475):

```tsx
<span className="text-[10px] text-gray-500 font-bold uppercase tracking-wider" title="Sum of raw SGP z-scores. Shown in the Value column.">Raw Value (SGP)</span>
```

Replace with:

```tsx
<InfoTip content="Sum of raw SGP z-scores. Shown in the Value column.">
  <span className="text-[10px] text-gray-500 font-bold uppercase tracking-wider">Raw Value (SGP)</span>
</InfoTip>
```

And:

```tsx
<span className="text-[10px] text-gray-500 font-bold uppercase tracking-wider" title="Z-scores re-standardized by remaining pool. Used by the Score formula.">Normalized Value</span>
```

Replace with:

```tsx
<InfoTip content="Z-scores re-standardized by remaining pool. Used by the Score formula.">
  <span className="text-[10px] text-gray-500 font-bold uppercase tracking-wider">Normalized Value</span>
</InfoTip>
```

- [ ] **Step 4: Verify TypeScript**

Run: `PATH="/Users/jgibbons/.nvm/versions/node/v20.20.0/bin:$PATH" npx tsc --noEmit`

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add src/components/ScoreDetailModal.tsx
git commit -m "$(/bin/cat <<'EOF'
feat(waivers): explain NOW/WAIT pills and modal column headers

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Full test pass + Next.js build + push to Railway

**Files:** none (verification only)

- [ ] **Step 1: Run the full Jest suite**

Run: `/Users/jgibbons/.volta/tools/image/node/22.15.0/bin/npx jest`

Expected: all tests pass. If pre-existing tests fail unrelated to this work, note them but do not block.

- [ ] **Step 2: Run Next.js build**

Run: `PATH="/Users/jgibbons/.nvm/versions/node/v20.20.0/bin:$PATH" npx next build`

Expected: build succeeds with no type errors.

- [ ] **Step 3: Push to Railway**

```bash
gh auth switch --user johngibbons
git push origin main
gh auth switch --user jgibbons_LinkedIn
```

Expected: push succeeds; both account switches succeed.

- [ ] **Step 4: Verify on Railway prod**

Wait for Railway to redeploy (check `railway logs -n 30 -s fantasy-baseball-helper-frontend -e production` for a fresh build), then open `/waivers` and hover each of these symbol classes on a real recommendation:

  1. A 🔥/↗/→/❄ form badge next to any player name → tooltip explains the OPS threshold.
  2. A colored letter badge on the Hot tab → tooltip names the metric + sustainability meaning.
  3. A colored letter badge on the Stealth tab → tooltip names the metric + delta direction.
  4. 📊 🔥 🎯 🍀 score-component icons on Projections tab → tooltip explains each component.
  5. A score-detail modal "Raw Value (SGP)" / "Normalized Value" header → tooltip explains the column.
  6. A NOW or WAIT pill inside the score detail modal → tooltip explains the recommendation.

Expected: every symbol shows a styled dark tooltip on hover, copy is correct, table layout is not shifted by the absolutely-positioned tooltip.

If anything renders wrong, file the diff in a new task; do not patch silently here.
