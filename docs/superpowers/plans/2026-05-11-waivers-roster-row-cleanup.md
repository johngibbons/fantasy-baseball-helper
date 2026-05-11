# Waivers My Roster Row Cleanup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the per-row slot label in the My Roster grid with position eligibility, lock the badge+score zone to a fixed-width right-aligned column, and bump grid spacing.

**Architecture:** Single-file edit in `src/app/waivers/_components/ProjectionsTab.tsx`, lines ~348–406 (the `{/* My Roster */}` block). Reuses existing helpers `posColors`, `primaryPos`, `FormBadge`, and the `rosterValue` map. No new components, no new files, no data model changes. Tests are not added because the existing component has no test coverage and the change is purely presentational — verification is visual on Railway prod (per user's standing preference).

**Tech Stack:** Next.js (App Router), React, TailwindCSS, TypeScript.

**Spec:** `docs/superpowers/specs/2026-05-11-waivers-roster-row-cleanup-design.md`

---

### Task 1: Replace roster row layout

**Files:**
- Modify: `src/app/waivers/_components/ProjectionsTab.tsx:348-406`

- [ ] **Step 1: Read the current My Roster block to confirm line numbers**

Run: open `src/app/waivers/_components/ProjectionsTab.tsx` and locate the `{/* My Roster */}` comment near line 348. The block ends at the closing `</div>` near line 406. The current row JSX renders:
1. Slot `<span>` (leftmost, `w-6 text-right font-mono font-bold`, slot-colored)
2. Player name as `<Link>` (or `<span>` if no `mlb_id`), with IL strikethrough and stream-slot dimming
3. Position eligibility `<span>` (small `text-[10px]`, position-colored)
4. STREAM chip (conditional)
5. FormBadge (conditional)
6. Z-score `<span>` (conditional)

- [ ] **Step 2: Update the outer grid container spacing**

Find this line (currently ~358):

```jsx
<div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-x-4 gap-y-0.5 text-xs">
```

Replace with:

```jsx
<div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-x-6 gap-y-1 text-xs">
```

- [ ] **Step 3: Replace the row body with the new 3-zone layout**

Find the entire inner row return (currently ~372–402):

```jsx
return (
  <div key={`${slot}-${i}`} className="flex items-center gap-1.5 py-0.5">
    <span className={`w-6 text-right font-mono font-bold ${slotColors[slot] || 'text-gray-500'}`}>{slot}</span>
    {p.mlb_id ? (
      <Link
        href={`/player/${p.mlb_id}`}
        className={`hover:underline ${
          slot === 'IL'
            ? 'text-gray-600 line-through'
            : isStreamSlot
              ? 'text-gray-500 hover:text-white'
              : 'text-gray-300 hover:text-white'
        }`}
      >
        {p.name}
      </Link>
    ) : (
      <span className={slot === 'IL' ? 'text-gray-600 line-through' : 'text-gray-300'}>{p.name}</span>
    )}
    <span className={`text-[10px] ${posColors[primaryPos(p.position)] || 'text-gray-500'}`}>{p.position}</span>
    {isStreamSlot && (
      <span className="text-[9px] font-bold text-orange-400 bg-orange-500/10 px-1 rounded">STREAM</span>
    )}
    {rv && <FormBadge level={rv.form} />}
    {rv && (
      <span className={`text-[10px] font-mono ${zColor}`}>
        {rv.z > 0 ? `+${rv.z.toFixed(2)}` : rv.z.toFixed(2)}
      </span>
    )}
  </div>
)
```

Replace with:

```jsx
return (
  <div key={`${slot}-${i}`} className="flex items-center gap-2 px-1 py-0.5">
    <span className={`w-14 shrink-0 text-[10px] font-mono ${posColors[primaryPos(p.position)] || 'text-gray-500'}`}>
      {p.position}
    </span>
    <div className="flex-1 min-w-0 flex items-center gap-1.5">
      {p.mlb_id ? (
        <Link
          href={`/player/${p.mlb_id}`}
          className={`truncate hover:underline ${
            slot === 'IL'
              ? 'text-gray-600 line-through'
              : isStreamSlot
                ? 'text-gray-500 hover:text-white'
                : 'text-gray-300 hover:text-white'
          }`}
        >
          {p.name}
        </Link>
      ) : (
        <span className={`truncate ${slot === 'IL' ? 'text-gray-600 line-through' : 'text-gray-300'}`}>{p.name}</span>
      )}
      {isStreamSlot && (
        <span className="text-[9px] font-bold text-orange-400 bg-orange-500/10 px-1 rounded shrink-0">STREAM</span>
      )}
    </div>
    <div className="flex items-center gap-1 w-16 shrink-0 justify-end">
      <span className="w-4 flex justify-center">
        {rv ? <FormBadge level={rv.form} /> : null}
      </span>
      <span className={`text-[10px] font-mono tabular-nums w-10 text-right ${rv ? zColor : 'text-gray-700'}`}>
        {rv ? (rv.z > 0 ? `+${rv.z.toFixed(2)}` : rv.z.toFixed(2)) : '—'}
      </span>
    </div>
    {slot === 'IL' && (
      <span className="text-[9px] font-bold text-red-400 bg-red-500/10 px-1 rounded shrink-0">IL</span>
    )}
  </div>
)
```

Notes about this replacement:
- The leftmost zone is now `w-14 shrink-0` showing `p.position` (eligibility) in position color, replacing the slot label.
- The middle zone is a flex sub-container with `flex-1 min-w-0` so the name can truncate. STREAM chip stays inside the name zone (immediately after name) so it visually attaches to the player it labels.
- The right zone is `w-16 shrink-0 justify-end` containing the FormBadge (in a fixed `w-4` slot so it doesn't horizontally jitter when absent) and the z-score (`w-10 text-right tabular-nums` so digit columns align).
- Em-dash `—` placeholder renders when `rv` is undefined; uses `text-gray-700` to recede.
- The IL chip is appended after the right zone, outside the score column, so it doesn't disturb score alignment.
- `tabular-nums` ensures `-3.07` and `+0.18` have the same digit width.

- [ ] **Step 4: TypeScript check**

Run: `cd /Users/jgibbons/code/fantasy-baseball-helper && npx tsc --noEmit 2>&1 | tail -20`

Expected: no new errors in `ProjectionsTab.tsx`. Pre-existing errors elsewhere in the repo (if any) are OK as long as nothing new appears for this file.

- [ ] **Step 5: Lint check**

Run: `cd /Users/jgibbons/code/fantasy-baseball-helper && npx next lint --file src/app/waivers/_components/ProjectionsTab.tsx 2>&1 | tail -20`

Expected: no new lint errors for this file.

- [ ] **Step 6: Commit**

```bash
git add src/app/waivers/_components/ProjectionsTab.tsx
git commit -F- <<'EOF'
feat(waivers): clean up My Roster row layout

- Replace slot label with position eligibility as leftmost tag
- Lock badge+z-score into fixed-width right-aligned zone with em-dash placeholder
- Drop BE/active distinction (daily league — slot-today is noise)
- Add small red IL chip for injured players, keep strikethrough
- Bump grid gap-y, gap-x, add per-row px

Spec: docs/superpowers/specs/2026-05-11-waivers-roster-row-cleanup-design.md
EOF
```

---

### Task 2: Push to Railway and visually verify

**Files:** none (deploy + verify only)

- [ ] **Step 1: Push to prod**

Run:
```bash
gh auth switch --user johngibbons
git push origin main
gh auth switch --user jgibbons_LinkedIn
```

Expected: push succeeds; Railway auto-deploys.

- [ ] **Step 2: Wait for Railway deploy, then load /waivers on prod**

Open the Railway URL `/waivers` page in a browser. Wait ~60 seconds for deploy to propagate if needed.

- [ ] **Step 3: Visual checklist**

Compare against the original screenshot. Confirm all of:
- [ ] Z-scores form a clean vertical column at the right edge of each grid cell (digits align across rows in each column).
- [ ] Position eligibility tags (`C/DH`, `OF`, `2B/SS`, `SP/RP`, etc.) align on the left edge of each cell, replacing the old slot labels.
- [ ] Bench players are visually identical to starters — no `BE` label anywhere.
- [ ] IL players show strikethrough name + red `IL` chip on the right edge.
- [ ] Form badges (`🔥`/`→`/`❄`/`📈`) no longer cause rows to shift horizontally. Rows without a badge have a spacer where the badge would go.
- [ ] STREAM chip (if visible for any player) renders adjacent to the name, not in the score column.
- [ ] No regression on the Hot tab or Stealth tab (they share helpers).

If any checklist item fails, file a follow-up rather than rolling back.

---

## Self-Review

**1. Spec coverage** — checked against the spec:
- Row 3-zone layout ✓ Task 1 Step 3
- Eligibility tag replaces slot ✓ Task 1 Step 3
- Fixed-width right zone + em-dash placeholder ✓ Task 1 Step 3
- IL chip ✓ Task 1 Step 3
- Bench/active distinction dropped ✓ implicit in Step 3 (no slot label rendered)
- Spacing bumps ✓ Task 1 Step 2 (`gap-x-6`, `gap-y-1`, `px-1`)
- Grid order unchanged ✓ same `rosterBySlot.map(...)` driver
- Verification ✓ Task 2 covers visual checklist

**2. Placeholder scan** — none.

**3. Type consistency** — `p.position` is `string` (from `RosterPlayer.position` at line 41), `rv` is `{ z: number; form: ... } | undefined`, `FormBadge` accepts `level` prop. All references match the existing code.
