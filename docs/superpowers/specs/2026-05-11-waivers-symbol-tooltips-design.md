# Waivers Page Symbol Tooltips — Design

**Date:** 2026-05-11
**Status:** Approved, pending implementation

## Problem

The `/waivers` page surfaces five distinct visual vocabularies — form badges, sustainability dot badges, metric-delta dot badges, score-component icons, and NOW/WAIT pills — without a discoverable explanation. A few symbols already carry native `title=` attributes, but those are tiny, delayed, browser-styled, and easy to miss. Result: the user cannot tell what most symbols mean.

## Goal

Make every symbol on the waivers page self-explanatory on hover, without adding a legend strip, a glossary modal, or a touch/mobile flow.

## Out of Scope

- Persistent legend strips, help-icon glossary modals.
- Touch/mobile tooltip behavior (desktop only, matches rest of app).
- Animation library, positioning library, or any new dependency.
- Any change to scoring math, projections, or backend.

## Symbols Covered

| Location | Symbol | Meaning |
|---|---|---|
| Player rows (Projections, Hot, Stealth, sidebar) | 🔥 ↗ → ❄ | Form: 14d OPS vs season OPS (thresholds ±0.080 hot/cold, ±0.020 warming/cooling). |
| Hot tab row | Colored letter badges (xBA, xwOBA, ISO, K%, BB%, hard-hit %, etc.) | Per-metric sustainability of the hot streak. green=supports, yellow=mixed, red=contradicts, gray=insufficient data. |
| Stealth tab row | Colored letter badges (same metrics) | Per-metric delta magnitude vs season. green=large positive, yellow=small positive, red=negative, gray=noise. |
| Projections tab "score breakdown" | 📊 🔥 🎯 🍀 | Score components: projection contribution, 30d production z, xwOBA skill, luck/regression risk. |
| Score detail modal column headers | "Raw Value (SGP)", "Normalized Value" | Already have native `title=` — upgrade text and switch to `<InfoTip>`. |
| Score detail modal | NOW / WAIT pills | Acquisition timing recommendation. |

## Component: `<InfoTip>`

New file: `src/components/InfoTip.tsx`. Single client component.

**API:**

```tsx
interface InfoTipProps {
  content: string | React.ReactNode  // tooltip body
  children: React.ReactNode           // trigger
  className?: string                  // optional wrapper class
}
```

**Behavior:**

- Wraps `children` in an inline span with Tailwind's `group` class.
- A second span (the tooltip) is `position: absolute`, hidden by default, becomes visible via `group-hover:opacity-100`.
- Anchored below the trigger, left-aligned, `top-full mt-1 left-0`.
- Styled to match the dark theme: `bg-gray-800/95 border border-white/10 rounded-md px-3 py-2 text-xs text-gray-200 shadow-xl max-w-xs whitespace-normal leading-snug pointer-events-none`.
- `pointer-events-none` keeps it from blocking row clicks; the user does not need to enter the tooltip.
- `z-50` to render above table content and modal layers it shares space with.
- `aria-describedby` linking trigger to tooltip id, generated with `useId()`.

**Why pure CSS over a JS-controlled popover:**

- Tooltip content is short (1–3 lines text) and read-only — no need for the cursor to enter it.
- No positioning library means no new dependency, no SSR pitfalls, no portal/z-index gymnastics.
- Matches the existing "vanilla Tailwind, minimal client state" style of the codebase.

**Edge cases handled:**

- Long content: `max-w-xs` + `whitespace-normal` wraps gracefully.
- Trigger near right edge of viewport: acceptable to clip — the affected rows are inside a 1-column-per-row table, content never reaches the page right edge. If this turns out to be wrong in implementation, switch the offending tooltip to `right-0` anchoring; do not add full collision detection.

## Content Strategy

Each tooltip explains *its own meaning*, not the full legend. A user hovering the green xBA dot learns what green xBA means, not what red K% means.

**Form badges** (auto-generated from level if no custom prop passed):

| Level | Tooltip body |
|---|---|
| hot 🔥 | "Hot streak — 14-day OPS at least 0.080 above season OPS." |
| cool ↗ | "Warming — 14-day OPS 0.020 to 0.080 above season." |
| neutral → | "Steady — 14-day OPS within ±0.020 of season." |
| cold ❄ | "Cold — 14-day OPS at least 0.080 below season." |

**Sustainability badges (Hot tab)** — keyed by `(metric, color)`:

Per-metric short copy. Examples:

- xwOBA + green: "xwOBA — expected wOBA. Underlying contact quality supports the hot streak."
- xwOBA + red: "xwOBA — expected wOBA. Contact quality lags the hot results; likely unsustainable."
- K% + green: "Strikeout rate. K% is down vs season — supports the hot streak."

Metric → human-name map lives in a single const (`METRIC_LABELS`) in a new file `src/lib/waiver-symbol-copy.ts`, shared between Hot and Stealth tabs. Color → suffix map (`SUSTAIN_COPY`, `DELTA_COPY`) also lives there.

**Stealth metric-delta badges** — same metric labels, different color suffixes:

- green: "Large positive shift vs season — strong underlying improvement."
- yellow: "Modest positive shift — directionally encouraging."
- red: "Negative shift — underlying signal is moving the wrong way."
- gray: "Insufficient signal or noise — discount this metric."

**Score components (Projections tab):**

- 📊 projection_contribution: "Rest-of-season projection delta (ATC). Higher = projections favor the add."
- 🔥 production_contribution: "30-day production z-score. Higher = recent box-score output stands out vs replacement."
- 🎯 xwoba_contribution: "Underlying skill signal — Statcast xwOBA vs projected wOBA. Higher = scouting metrics agree with the rec."
- 🍀 luck_contribution: "Regression risk. Negative means the player is overperforming xwOBA and may cool off."

**NOW / WAIT pills:**

- NOW: "Acquire now — the signal is strong enough that delay costs expected value."
- WAIT: "Hold — evidence is mixed or thin; wait another window before claiming."

## Wiring

| File | Change |
|---|---|
| `src/components/InfoTip.tsx` | New component (see API above). |
| `src/lib/waiver-symbol-copy.ts` | New file. Exports `METRIC_LABELS`, `SUSTAIN_COPY`, `DELTA_COPY`, `FORM_COPY`, `SCORE_COMPONENT_COPY`, `TIMING_COPY` constants. |
| `src/components/FormBadge.tsx` | Replace native `title=` with `<InfoTip>` wrapper. Default content from `FORM_COPY[level]` when no `tooltip` prop is passed. Keep `tooltip` prop as override. |
| `src/app/waivers/_components/HotTab.tsx` | Wrap each sustainability badge in `<InfoTip>`. Look up copy from `METRIC_LABELS[metric] + SUSTAIN_COPY[color]`. |
| `src/app/waivers/_components/StealthTab.tsx` | Wrap each delta badge in `<InfoTip>`. Look up copy from `METRIC_LABELS[metric] + DELTA_COPY[badge]`. |
| `src/app/waivers/_components/ProjectionsTab.tsx` | Replace 4 native `title=` spans with `<InfoTip>` wrappers using `SCORE_COMPONENT_COPY`. |
| `src/components/ScoreDetailModal.tsx` | Replace 2 native `title=` column headers with `<InfoTip>`. Add `<InfoTip>` around NOW/WAIT pills using `TIMING_COPY`. |

## Testing

- Manual verification on the Railway prod deployment: visit `/waivers`, hover each symbol class on each tab, confirm tooltip appears, copy is correct, no layout shift, tooltip clears on mouse-out.
- No unit tests added — this is presentation-only and the copy lives in a single constants file that is trivial to inspect.

## Risks

- **Tooltip clipping at table right edge**: mitigated by left-anchoring + the table's column structure; fallback is per-call `right-0` override.
- **Accessibility**: `aria-describedby` exposes the tooltip text to screen readers even though triggers are not focusable. Not full WCAG conformance — no role="tooltip" semantics, no keyboard hover equivalent, no Escape-to-dismiss — but better than the current native `title=`.
- **Pre-existing `title=` left in place** on non-waiver pages: out of scope; do not touch.
