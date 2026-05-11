# Waivers "My Roster" row cleanup

**Date:** 2026-05-11
**Scope:** Visual refinement of the My Roster module on `/waivers` (`ProjectionsTab.tsx`). No data changes, no API changes.

## Problem

The current row layout in the My Roster grid (6-column responsive grid, one player per cell) is hard to scan:

1. **Score column floats.** The z-score (`+0.18`, `-3.07`) lands wherever name length pushes it, so values don't line up vertically across rows.
2. **Form/STREAM badges are optional.** Rows with badges look denser than rows without; the right edge of each row shifts horizontally.
3. **Slot label duplicates position tag.** Rows like `1B Jonathan Aranda 1B` and `OF Taylor Ward OF` show the slot AND the eligibility, which often match.
4. **BE/active slot distinction is noise.** It's a daily-lineup league — who starts at each slot rotates day to day. Showing `BE` vs `C`/`1B`/etc. as the leftmost label doesn't carry useful information.

## Design

### Row layout

Each player row becomes a 3-zone flex row:

```
[ELIG-TAG w-14]  [Name flex-1, truncate]  [Badge + Score, right-aligned w-20]  [optional IL chip]
```

- **Leftmost (eligibility tag):** Replaces the current slot label. Shows the player's position eligibility (`C/DH`, `OF`, `2B/SS`, `SP/RP`, etc.) — sourced from `p.position`. Colored by primary position via the existing `posColors`/`primaryPos` helpers. Fixed width so the name column starts at the same x across all rows in a column.
- **Middle (name):** Player name as a link (`/player/[id]`). Truncates with `truncate` (overflow ellipsis) if it would push the right zone. Keeps existing hover behavior.
- **Right (badge + score):** Right-aligned within a fixed-width container. Always renders:
  - Form badge (`<FormBadge level={rv.form} />`) — or a thin spacer placeholder if no badge applies, so the badge column has consistent x.
  - Z-score (`+0.18`, `-3.07`) — or em-dash `—` placeholder when missing.
- **IL chip (conditional):** For IL players, append a small red `IL` chip after the score (e.g. `text-[9px] font-bold text-red-400 bg-red-500/10 px-1 rounded`). Keeps the existing strikethrough on the name. The chip is the explicit IL indicator now that the leftmost slot label is gone.
- **STREAM chip:** Unchanged behavior — still rendered between name and score area when `isStreamSlot` is true.

### Grouping & ordering

Keep the current 6-column grid structure (`grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6`) and the current data ordering from `rosterBySlot`. The starter slots (C, 1B, ..., SP, P) still naturally cluster in the top rows, bench in the middle, IL at the bottom — but without any slot labels. Active vs bench is no longer visually distinguished; in a daily league that's the intent.

### Spacing

- Row vertical gap: `gap-y-0.5` → `gap-y-1`.
- Column horizontal gap: `gap-x-4` → `gap-x-6`.
- Add `px-1` to each row container for breathing room within cells.

### Color & typography

- Eligibility tag: keep the existing position-color palette (`posColors`), `text-[10px]`, mono. Replaces the slot-color palette.
- Name: unchanged (link styling).
- Score: unchanged (`font-mono`, `zColor` from current logic). Em-dash placeholder uses `text-gray-600`.
- IL chip: red, small, consistent with the existing STREAM chip styling.

## Out of scope

- The "Recommendations" table below the roster: untouched.
- The category-strengths bar above the roster: untouched.
- The slot grouping ORDER (which players appear where in the grid): unchanged — same `rosterBySlot` data, same row-major flow.
- Mobile breakpoints: same `grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6` rules; row layout adapts because zones are flex with truncate.

## Implementation notes

All changes are confined to lines ~348–406 of `src/app/waivers/_components/ProjectionsTab.tsx`. No new components, no new helpers — reuse `posColors`, `primaryPos`, `FormBadge`, the existing `rosterValue` map.

## Verification

After deploy, visually compare `/waivers` Projections tab against the original screenshot. Confirm:
1. Z-scores form a clean vertical column along the right edge of each grid cell.
2. Position eligibility tags align on the left edge.
3. Bench players are visually identical to starters (no `BE` label).
4. IL players show strikethrough name + red `IL` chip.
5. Form badges no longer cause rows to shift horizontally.
