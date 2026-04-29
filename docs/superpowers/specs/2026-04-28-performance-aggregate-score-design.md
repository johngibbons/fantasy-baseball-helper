# Performance Aggregate Score (ΔTotal) — Design

**Date:** 2026-04-28
**Status:** Draft for review
**Surface:** `/performance` page (added in commit `f3dab11`, refined in `6963e69`)

## Problem

The `/performance` page shows projection-vs-actual deltas per category (volume and rate framings). It answers "how is this player doing in K?" but not "who is the biggest overall outperformer / underperformer?" The categories are on different units (R is a count, OBP is a 0–1 rate, ERA is an inverted ratio), so they can't be summed directly.

## Goal

Add a single sortable **ΔTotal** column to the hitter and pitcher tables that aggregates each player's per-category deltas into one comparable score. Make the page open on this view by default so the "who's standing out" question is answered immediately.

## Approach

**Z-score sum across categories.** For each category, standardize each player's delta against the ranked population, then sum the z-scores per player. Sign-flip ERA/WHIP so positive z always means "good." The sum carries both magnitude and direction in unitless stddev space.

Two scores are computed (one per framing), so the column reacts to the existing Volume↔Rate toggle:

- **Volume framing** — sum across counting cats only (R/TB/RBI/SB for hitters, K/QS/SVHD for pitchers). OBP/ERA/WHIP excluded — volume isn't meaningful for rate stats.
- **Rate framing** — sum across all 5 cats per player type. Note: SVHD has no projected rate in the current backend (`performance.py:238`), so its `delta_rate_z` will always be null and contribute 0 — pitcher rate ΔTotal is effectively a sum across K/QS/ERA/WHIP. Consistent with how the existing UI displays SVHD rate (blank).

## Architecture

### Backend (`backend/analysis/performance.py`)

After building the per-row `categories` dict in `compute_hitter_performance` and `compute_pitcher_performance`, add a second pass that:

1. For each category, collects the population of non-null `delta_volume` and `delta_rate` values across all rows.
2. Computes `mean` and `stddev` (population, not sample) per category per framing.
3. For each row + category, sets:
   ```python
   "delta_volume_z": (delta_volume - mean_v) / stddev_v   # None if delta_volume is None
   "delta_rate_z":   (delta_rate   - mean_r) / stddev_r   # None if delta_rate is None
   ```
   Sign-flipped (negated) for `era` and `whip` so positive z = "better than expected" everywhere.

Edge cases:
- `stddev == 0` (e.g., opening day, all deltas equal) → return `z = 0` for every row in that cat.
- Single-population cat (≤1 non-null delta) → same as stddev=0, return `z = 0`.
- Null delta → null z (frontend treats as 0 in the sum).

### Frontend (`src/app/performance/page.tsx`)

The `CategoryStat` TypeScript interface gains two optional fields:

```ts
delta_volume_z: number | null
delta_rate_z:   number | null
```

`PerformanceTable` computes a derived `deltaTotal` per row inside its existing `useMemo` for sorting:

```ts
const cats_for_volume = isPitcher ? ['k','qs','svhd'] : ['r','tb','rbi','sb']
const cats_for_rate   = cats   // all 5
const sumZ = (row, framing) => {
  const fields = framing === 'volume' ? cats_for_volume : cats_for_rate
  return fields.reduce((acc, cat) => {
    const z = framing === 'volume'
      ? row.categories[cat]?.delta_volume_z
      : row.categories[cat]?.delta_rate_z
    return acc + (z ?? 0)
  }, 0)
}
```

Treating `null` as `0` (rather than excluding from sum or showing "—") keeps every player comparable on the same axis. Without this, an unplayed player would have ΔTotal = "—" in rate framing, hiding a signal that volume framing already captures correctly.

## UI

### Column

Header: **ΔTotal**, placed immediately after `PA (act/exp)` / `IP (act/exp)` and before the per-category columns.

Cell:
- Format: `+3.2σ` / `-1.8σ` (one decimal, σ suffix to signal "this is in stddev units").
- Color: same emerald (positive) / red (negative) palette as existing delta cells.
- Bold + brighter shade when `|Σz| > 3` (multi-category outlier threshold).
- Centered alignment, right-aligned numerals.

Tooltip on hover: per-category z breakdown that produced the sum, e.g.:
> R: +1.2σ · TB: +0.8σ · RBI: -0.3σ · SB: +1.5σ

### Sort behavior

- **Default sort on initial page load:** ΔTotal desc, for both hitter and pitcher tables (replaces current `r` / `era`).
- Clicking the ΔTotal header toggles asc/desc as with other sortable columns.
- First-click direction on ΔTotal = desc (top performers first).
- When framing toggles Volume↔Rate, the active sort stays on ΔTotal and re-orders against the new score.

### Filters

- **My team only:** unchanged. Z-scores are always computed against the full ranked population — a player's ΔTotal reflects league-wide standing, not within-roster standing. The filter just hides non-roster rows.
- **Position filter:** unchanged. Same reason — z-scores are not recomputed against the position subset.

## Testing

- **Backend unit test** in `backend/tests/` (or wherever performance tests live):
  - Z-score correctness on a known fixture (mean/stddev hand-computed).
  - Sign flip applied to ERA/WHIP only.
  - Null delta → null z.
  - `stddev == 0` → z = 0 for all.
  - Single-element population → z = 0.
- **Frontend manual verification:**
  - ΔTotal column renders in both tables.
  - Default sort places top performers at the top.
  - Framing toggle re-sorts and updates values.
  - Tooltip shows per-cat breakdown.
  - My-team-only filter does not change z-scores of remaining rows.

## Out of Scope (v1)

The following are interesting but deferred:

- **"Top 5 movers" panel** above the tables. The sortable column already surfaces this — a panel would duplicate the data.
- **Time-windowed deltas** (last 7/30 days vs. season-to-date). Different feature, requires a different actuals snapshot.
- **Position-relative z-scores** (z within SS pool rather than all hitters). Useful for waiver decisions but adds significant complexity and changes the score's meaning.
- **Persisted z-scores in the DB.** Currently recomputed each request — fine at ~1500 rows.
