# Performance ΔTotal Aggregate Score Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a sortable `ΔTotal` column to `/performance` that aggregates per-category projection-vs-actual deltas into a single z-score sum, surfacing the biggest overall outperformers and underperformers in each table.

**Architecture:** Backend (Python) computes per-category z-scores against the ranked-population deltas and attaches them to each player row's `categories[cat]` dict (`delta_volume_z`, `delta_rate_z`). Frontend (TypeScript/React) sums the appropriate z-scores per row based on the active Volume/Rate framing toggle, renders the result as a sortable column, and uses it as the default sort.

**Tech Stack:** Python (backend, no numpy needed for this work — pure stdlib), pytest (tests), TypeScript / React / Next.js (frontend), Tailwind classes for styling.

**Spec:** `docs/superpowers/specs/2026-04-28-performance-aggregate-score-design.md`

---

## File Structure

**Modified:**
- `backend/analysis/performance.py` — add two helpers (`_compute_population_zscores`, `_attach_delta_zscores`) and wire `_attach_delta_zscores` into `compute_performance`.
- `src/app/performance/page.tsx` — extend `CategoryStat` interface, add `ΔTotal` column with sort handler, change default sort, add helper functions for total computation and styling.

**Created:**
- `tests/backend/analysis/test_performance.py` — pytest unit tests for the two new backend helpers.

No file split or restructuring needed. `performance.py` is currently ~440 lines and self-contained; adding ~60 lines of helper code keeps it focused. `page.tsx` is large (~700 lines) but is a single page component with table sub-component — adding one column is consistent with the existing structure.

---

## Task 1: Backend — `_compute_population_zscores` helper

Pure helper that converts a list of (possibly null) floats into z-scores. Cleanly testable, no DB needed.

**Files:**
- Modify: `backend/analysis/performance.py` (add new helper after `_delta`, around line 55)
- Create: `tests/backend/analysis/test_performance.py`

- [ ] **Step 1: Write failing tests**

Create `tests/backend/analysis/test_performance.py` with:

```python
# tests/backend/analysis/test_performance.py

import pytest
from backend.analysis.performance import _compute_population_zscores


class TestComputePopulationZscores:
    def test_basic_zscores(self):
        # [1, 2, 3, 4, 5] → mean=3, population stddev=sqrt(2)
        result = _compute_population_zscores([1.0, 2.0, 3.0, 4.0, 5.0])
        std = 2.0 ** 0.5
        assert result[0] == pytest.approx(-2 / std)
        assert result[2] == pytest.approx(0.0)
        assert result[4] == pytest.approx(2 / std)

    def test_none_passes_through_and_excluded_from_population(self):
        # Population is [1, 3]: mean=2, population stddev=1
        result = _compute_population_zscores([1.0, None, 3.0])
        assert result[0] == pytest.approx(-1.0)
        assert result[1] is None
        assert result[2] == pytest.approx(1.0)

    def test_stddev_zero_returns_zeros(self):
        # All identical → stddev=0 → every non-null returns 0
        assert _compute_population_zscores([5.0, 5.0, 5.0]) == [0.0, 0.0, 0.0]

    def test_single_non_null_returns_zero(self):
        # Population of one → stddev undefined → return 0 for non-null, None for null
        result = _compute_population_zscores([5.0, None, None])
        assert result == [0.0, None, None]

    def test_all_none_returns_all_none(self):
        assert _compute_population_zscores([None, None, None]) == [None, None, None]

    def test_empty_list_returns_empty(self):
        assert _compute_population_zscores([]) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/backend/analysis/test_performance.py -v`
Expected: FAIL — `ImportError: cannot import name '_compute_population_zscores'` or similar.

- [ ] **Step 3: Implement helper**

Open `backend/analysis/performance.py`. Locate the `_delta` function near the top (around line 51-54). Immediately after it, add:

```python
def _compute_population_zscores(values: list[float | None]) -> list[float | None]:
    """Convert a list of values to population z-scores.

    None values pass through as None and are excluded from the
    mean/stddev calculation. If fewer than 2 non-null values exist,
    or if stddev is 0 (all values identical), every non-null entry
    maps to 0.0.

    Uses population stddev (divide by N), not sample stddev (N-1) —
    the ranked player pool *is* the population, not a sample of one.
    """
    non_null = [v for v in values if v is not None]
    if len(non_null) < 2:
        return [None if v is None else 0.0 for v in values]
    mean = sum(non_null) / len(non_null)
    var = sum((v - mean) ** 2 for v in non_null) / len(non_null)
    stddev = var ** 0.5
    if stddev == 0:
        return [None if v is None else 0.0 for v in values]
    return [None if v is None else (v - mean) / stddev for v in values]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/backend/analysis/test_performance.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/backend/analysis/test_performance.py backend/analysis/performance.py
git commit -m "feat(performance): add _compute_population_zscores helper"
```

---

## Task 2: Backend — `_attach_delta_zscores` helper

Mutates a list of player rows to add `delta_volume_z` and `delta_rate_z` fields under each `categories[cat]` dict, with sign-flip for ERA/WHIP.

**Files:**
- Modify: `backend/analysis/performance.py` (add helper after `_compute_population_zscores`)
- Modify: `tests/backend/analysis/test_performance.py` (add new test class)

- [ ] **Step 1: Write failing tests**

Append to `tests/backend/analysis/test_performance.py`:

```python
from backend.analysis.performance import _attach_delta_zscores


class TestAttachDeltaZscores:
    def _hitter_rows(self):
        return [
            {"categories": {
                "r":   {"delta_volume": 5.0,  "delta_rate": 0.01},
                "obp": {"delta_volume": None, "delta_rate": 0.005},
            }},
            {"categories": {
                "r":   {"delta_volume": -5.0, "delta_rate": -0.01},
                "obp": {"delta_volume": None, "delta_rate": -0.005},
            }},
        ]

    def test_attaches_z_fields_under_each_cat(self):
        rows = self._hitter_rows()
        _attach_delta_zscores(rows, ["r", "obp"])
        for row in rows:
            for cat in ("r", "obp"):
                assert "delta_volume_z" in row["categories"][cat]
                assert "delta_rate_z" in row["categories"][cat]

    def test_volume_z_for_two_player_population(self):
        rows = self._hitter_rows()
        _attach_delta_zscores(rows, ["r", "obp"])
        # r.delta_volume = [5, -5] → mean=0, std=5 → zs = [1, -1]
        assert rows[0]["categories"]["r"]["delta_volume_z"] == pytest.approx(1.0)
        assert rows[1]["categories"]["r"]["delta_volume_z"] == pytest.approx(-1.0)

    def test_volume_z_is_none_when_delta_volume_is_none(self):
        rows = self._hitter_rows()
        _attach_delta_zscores(rows, ["r", "obp"])
        # OBP has no volume framing → all delta_volume are None → z stays None
        assert rows[0]["categories"]["obp"]["delta_volume_z"] is None
        assert rows[1]["categories"]["obp"]["delta_volume_z"] is None

    def test_inverted_categories_sign_flipped(self):
        # ERA: lower is better. Pre-flip z for [0.5, -0.5] is [1, -1].
        # After sign flip: [-1, 1] (lower ERA = positive z = good).
        rows = [
            {"categories": {"era": {"delta_volume": None, "delta_rate": 0.5}}},
            {"categories": {"era": {"delta_volume": None, "delta_rate": -0.5}}},
        ]
        _attach_delta_zscores(rows, ["era"])
        assert rows[0]["categories"]["era"]["delta_rate_z"] == pytest.approx(-1.0)
        assert rows[1]["categories"]["era"]["delta_rate_z"] == pytest.approx(1.0)

    def test_whip_inverted_same_as_era(self):
        rows = [
            {"categories": {"whip": {"delta_volume": None, "delta_rate": 0.1}}},
            {"categories": {"whip": {"delta_volume": None, "delta_rate": -0.1}}},
        ]
        _attach_delta_zscores(rows, ["whip"])
        assert rows[0]["categories"]["whip"]["delta_rate_z"] == pytest.approx(-1.0)
        assert rows[1]["categories"]["whip"]["delta_rate_z"] == pytest.approx(1.0)

    def test_non_inverted_category_not_flipped(self):
        # K: higher is better. Pre-flip z for [10, -10] is [1, -1] — no change.
        rows = [
            {"categories": {"k": {"delta_volume": 10.0, "delta_rate": 1.0}}},
            {"categories": {"k": {"delta_volume": -10.0, "delta_rate": -1.0}}},
        ]
        _attach_delta_zscores(rows, ["k"])
        assert rows[0]["categories"]["k"]["delta_volume_z"] == pytest.approx(1.0)
        assert rows[1]["categories"]["k"]["delta_volume_z"] == pytest.approx(-1.0)
        assert rows[0]["categories"]["k"]["delta_rate_z"] == pytest.approx(1.0)
        assert rows[1]["categories"]["k"]["delta_rate_z"] == pytest.approx(-1.0)

    def test_empty_rows(self):
        rows: list[dict] = []
        _attach_delta_zscores(rows, ["r"])
        assert rows == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/backend/analysis/test_performance.py::TestAttachDeltaZscores -v`
Expected: FAIL — `ImportError: cannot import name '_attach_delta_zscores'`.

- [ ] **Step 3: Implement helper**

In `backend/analysis/performance.py`, immediately after `_compute_population_zscores`, add:

```python
# Categories where lower is better — sign-flip the z-score so that
# positive z always means "performed better than expected" everywhere.
_INVERTED_FOR_PERFORMANCE = {"era", "whip"}


def _attach_delta_zscores(rows: list[dict], cats: list[str]) -> None:
    """Mutate each row to add delta_volume_z and delta_rate_z under
    each categories[cat] dict, computed against the population of all
    rows for that cat.

    For inverted categories (ERA, WHIP), z-scores are sign-flipped so
    positive means "better than expected" for every category.
    """
    for cat in cats:
        for delta_field, z_field in (
            ("delta_volume", "delta_volume_z"),
            ("delta_rate",   "delta_rate_z"),
        ):
            values = [row["categories"][cat].get(delta_field) for row in rows]
            zs = _compute_population_zscores(values)
            if cat in _INVERTED_FOR_PERFORMANCE:
                zs = [None if z is None else -z for z in zs]
            for row, z in zip(rows, zs):
                row["categories"][cat][z_field] = z
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/backend/analysis/test_performance.py -v`
Expected: All tests pass (6 from Task 1 + 7 from Task 2 = 13 total).

- [ ] **Step 5: Commit**

```bash
git add tests/backend/analysis/test_performance.py backend/analysis/performance.py
git commit -m "feat(performance): add _attach_delta_zscores helper"
```

---

## Task 3: Backend — wire `_attach_delta_zscores` into `compute_performance`

Hook the helper into the existing `compute_performance` dispatcher so every API response carries the z-scores.

**Files:**
- Modify: `backend/analysis/performance.py` lines 289-296 (the `compute_performance` function)

- [ ] **Step 1: Replace `compute_performance` with z-score-attaching version**

Open `backend/analysis/performance.py`. The current function is:

```python
def compute_performance(
    season: int,
    player_type: Literal["hitter", "pitcher"],
    season_elapsed_fraction: float,
) -> list[dict]:
    if player_type == "hitter":
        return compute_hitter_performance(season, season_elapsed_fraction)
    return compute_pitcher_performance(season, season_elapsed_fraction)
```

Replace with:

```python
_HITTER_CATS_FOR_PERFORMANCE = ["r", "tb", "rbi", "sb", "obp"]
_PITCHER_CATS_FOR_PERFORMANCE = ["k", "qs", "era", "whip", "svhd"]


def compute_performance(
    season: int,
    player_type: Literal["hitter", "pitcher"],
    season_elapsed_fraction: float,
) -> list[dict]:
    if player_type == "hitter":
        rows = compute_hitter_performance(season, season_elapsed_fraction)
        cats = _HITTER_CATS_FOR_PERFORMANCE
    else:
        rows = compute_pitcher_performance(season, season_elapsed_fraction)
        cats = _PITCHER_CATS_FOR_PERFORMANCE
    _attach_delta_zscores(rows, cats)
    return rows
```

- [ ] **Step 2: Manually verify via the dev backend**

Start the backend: `uvicorn backend.api.main:app --reload --port 8000` (in one terminal).

In another terminal, hit the endpoint:

```bash
curl -s -X POST http://localhost:8000/api/performance \
  -H 'Content-Type: application/json' \
  -d '{"season": 2026, "player_type": "hitter", "season_elapsed_fraction": 0.15}' \
  | python -c "import sys,json; d=json.load(sys.stdin); r=d['rows'][0]; print(json.dumps(r['categories']['r'], indent=2))"
```

Expected output: a JSON object with both `delta_volume_z` and `delta_rate_z` keys (numbers, not missing).

Repeat for pitchers (`"player_type": "pitcher"`) and confirm the same.

Stop the backend (Ctrl-C).

- [ ] **Step 3: Re-run the unit tests as a sanity check**

Run: `pytest tests/backend/analysis/test_performance.py -v`
Expected: 13 passed.

- [ ] **Step 4: Commit**

```bash
git add backend/analysis/performance.py
git commit -m "feat(performance): attach delta z-scores in compute_performance"
```

---

## Task 4: Frontend — extend `CategoryStat` and add z-score helpers

Update the TypeScript types and add helper functions for computing the per-row total. No UI yet — just the plumbing.

**Files:**
- Modify: `src/app/performance/page.tsx` lines 20-28 (interface), and around lines 62-83 (constants and helpers)

- [ ] **Step 1: Extend `CategoryStat` interface**

In `src/app/performance/page.tsx`, find the `CategoryStat` interface (around line 20):

```ts
interface CategoryStat {
  proj_total: number | null
  proj_to_date: number | null
  actual: number | null
  delta_volume: number | null
  proj_rate: number | null
  actual_rate: number | null
  delta_rate: number | null
}
```

Replace with:

```ts
interface CategoryStat {
  proj_total: number | null
  proj_to_date: number | null
  actual: number | null
  delta_volume: number | null
  proj_rate: number | null
  actual_rate: number | null
  delta_rate: number | null
  delta_volume_z: number | null
  delta_rate_z: number | null
}
```

- [ ] **Step 2: Add cat-list constants and total-computation helpers**

Find the existing `HITTER_CATS` / `PITCHER_CATS` constants (around line 62):

```ts
const HITTER_CATS = ['r', 'tb', 'rbi', 'sb', 'obp'] as const
const PITCHER_CATS = ['k', 'qs', 'era', 'whip', 'svhd'] as const
```

Immediately after them, add:

```ts
// Categories that contribute to volume framing's ΔTotal (counting cats only —
// rate stats have no meaningful volume dimension so they're excluded).
const HITTER_VOLUME_CATS: readonly string[] = ['r', 'tb', 'rbi', 'sb']
const PITCHER_VOLUME_CATS: readonly string[] = ['k', 'qs', 'svhd']

function totalCatsFor(framing: 'volume' | 'rate', isPitcher: boolean): readonly string[] {
  if (framing === 'volume') return isPitcher ? PITCHER_VOLUME_CATS : HITTER_VOLUME_CATS
  return isPitcher ? PITCHER_CATS : HITTER_CATS
}

function computeDeltaTotal(row: PerfRow, framing: 'volume' | 'rate', isPitcher: boolean): number {
  const cats = totalCatsFor(framing, isPitcher)
  let sum = 0
  for (const cat of cats) {
    const c = row.categories[cat]
    const z = framing === 'volume' ? c?.delta_volume_z : c?.delta_rate_z
    sum += z ?? 0
  }
  return sum
}

function totalColorClass(z: number): string {
  const abs = Math.abs(z)
  if (abs < 0.1) return 'text-gray-500'
  if (z > 0) return abs > 3 ? 'text-emerald-300 font-semibold' : 'text-emerald-400'
  return abs > 3 ? 'text-red-300 font-semibold' : 'text-red-400'
}

function fmtTotal(z: number): string {
  const sign = z > 0 ? '+' : ''
  return `${sign}${z.toFixed(1)}σ`
}

function totalBreakdown(row: PerfRow, framing: 'volume' | 'rate', isPitcher: boolean): string {
  const cats = totalCatsFor(framing, isPitcher)
  return cats.map((cat) => {
    const c = row.categories[cat]
    const z = framing === 'volume' ? c?.delta_volume_z : c?.delta_rate_z
    if (z === null || z === undefined) return `${CAT_LABEL[cat]}: —`
    const s = z > 0 ? '+' : ''
    return `${CAT_LABEL[cat]}: ${s}${z.toFixed(1)}σ`
  }).join(' · ')
}
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add src/app/performance/page.tsx
git commit -m "feat(performance): add ΔTotal helpers and z-score types"
```

---

## Task 5: Frontend — add the `ΔTotal` column to `PerformanceTable`

Wire the helpers into the table: a sortable header column, a body cell with formatting + tooltip, and a sort branch in the existing `useMemo`.

**Files:**
- Modify: `src/app/performance/page.tsx` — the `PerformanceTable` component (lines 140-306)

- [ ] **Step 1: Add the sort branch for `total`**

Find the `sorted` `useMemo` inside `PerformanceTable` (around line 178-198). The current shape:

```ts
const sorted = useMemo(() => {
  const arr = [...filtered]
  if (sortCat === 'rank') {
    arr.sort((a, b) => {
      const ra = a.overall_rank ?? 99999
      const rb = b.overall_rank ?? 99999
      return sortDir === 'asc' ? ra - rb : rb - ra
    })
    return arr
  }
  arr.sort((a, b) => {
    // ... per-category sort
```

Insert a new branch immediately after the `'rank'` branch (before the per-category `arr.sort` block):

```ts
  if (sortCat === 'total') {
    arr.sort((a, b) => {
      const va = computeDeltaTotal(a, framing, isPitcher)
      const vb = computeDeltaTotal(b, framing, isPitcher)
      return sortDir === 'asc' ? va - vb : vb - va
    })
    return arr
  }
```

- [ ] **Step 2: Add the `ΔTotal` column header**

Find the `<thead>` block (around line 210-235). The current header has `#`, Player, Pos, Tm, Rank, PA/IP, then per-cat headers. Insert a new `<th>` after the PA/IP header (the one whose content is `{isPitcher ? 'IP' : 'PA'} (act/exp)`) and before the `cats.map` block:

```tsx
<th
  className="px-2 py-2 text-right font-medium cursor-pointer hover:text-white whitespace-nowrap"
  onClick={() => onSortChange('total')}
  title={`Sort by aggregate Δ across ${framing === 'volume' ? 'counting' : 'all'} cats`}
>
  ΔTotal{arrow('total')}
</th>
```

- [ ] **Step 3: Add the `ΔTotal` body cell**

Find the `<tbody>` row-rendering block (around line 245-296). After the PA/IP cell (the `<td>` with `{Number(paAct).toFixed(...)}`), and before the `cats.map`, insert:

```tsx
<td
  className={`px-2 py-1.5 text-right whitespace-nowrap ${totalColorClass(totalZ)}`}
  title={totalBreakdownStr}
>
  {fmtTotal(totalZ)}
</td>
```

And inside the same `visible.map((row, i) => { ... })` callback, just before the `return` statement, compute the values used by that cell:

```ts
const totalZ = computeDeltaTotal(row, framing, isPitcher)
const totalBreakdownStr = totalBreakdown(row, framing, isPitcher)
```

(Place these next to the existing `paAct` / `paExp` calculations.)

- [ ] **Step 4: Update the empty-state colspan**

Find the empty-state row (around line 240):

```tsx
<td colSpan={6 + cats.length} className="px-2 py-6 text-center text-gray-500">
  No players match your filters.
</td>
```

Change `colSpan={6 + cats.length}` to `colSpan={7 + cats.length}` (we added one column).

- [ ] **Step 5: Verify TypeScript compiles**

Run: `npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 6: Visual smoke test**

Start the dev server: `npm run dev`. Open `http://localhost:3000/performance`. Confirm:

- A `ΔTotal` column header is visible between `PA (act/exp)` and `R` for hitters, and between `IP (act/exp)` and `K` for pitchers.
- Each row shows a value like `+2.4σ` or `-1.1σ` colored emerald/red.
- Clicking the `ΔTotal` header sorts; the `▲`/`▼` arrow appears next to the header.
- Hovering a `ΔTotal` cell shows a tooltip with the per-cat breakdown like `R: +1.2σ · TB: +0.8σ · RBI: -0.3σ · SB: +1.5σ`.
- Toggling the Volume/Rate framing buttons changes `ΔTotal` values and re-sorts.

- [ ] **Step 7: Commit**

```bash
git add src/app/performance/page.tsx
git commit -m "feat(performance): add ΔTotal column with z-score sum"
```

---

## Task 6: Frontend — change default sort to `ΔTotal` desc

The page should open on the most-actionable view: top performers first.

**Files:**
- Modify: `src/app/performance/page.tsx` lines 323-326 (state initialization)

- [ ] **Step 1: Change initial sort state**

Find the sort-state hooks inside the `PerformancePage` component (around line 323-326):

```ts
const [sortCatH, setSortCatH] = useState<string>('r')
const [sortDirH, setSortDirH] = useState<'asc' | 'desc'>('asc')
const [sortCatP, setSortCatP] = useState<string>('era')
const [sortDirP, setSortDirP] = useState<'asc' | 'desc'>('desc')  // most over-performing ERA = lowest delta
```

Replace with:

```ts
const [sortCatH, setSortCatH] = useState<string>('total')
const [sortDirH, setSortDirH] = useState<'asc' | 'desc'>('desc')  // top outperformers first
const [sortCatP, setSortCatP] = useState<string>('total')
const [sortDirP, setSortDirP] = useState<'asc' | 'desc'>('desc')
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Visual verification**

Reload `http://localhost:3000/performance`. Confirm:

- Both tables open already sorted by `ΔTotal` descending — the top row is the biggest outperformer.
- The `▼` arrow is on the `ΔTotal` header for both tables on initial load.

- [ ] **Step 4: Commit**

```bash
git add src/app/performance/page.tsx
git commit -m "feat(performance): default sort to ΔTotal desc"
```

---

## Task 7: Final verification

Spot-check the whole feature end-to-end against the spec.

- [ ] **Step 1: Run all backend tests**

Run: `pytest tests/backend/ -v`
Expected: All tests pass (existing + the 13 new ones from Tasks 1 & 2).

- [ ] **Step 2: TypeScript build check**

Run: `npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Manual UI walkthrough**

With `npm run dev` running, on `http://localhost:3000/performance`:

- Default-load view: both tables sorted ΔTotal desc.
- Toggle Volume → Rate: ΔTotal column values change, table re-sorts.
- Click any per-category header (e.g., R), then click ΔTotal: returns to ΔTotal sort.
- Hover a ΔTotal cell: tooltip shows per-cat breakdown for the active framing.
- Toggle "My team only": ΔTotal values for shown rows are unchanged (because z-scores are computed against the full population, not the filter).
- Click "Refresh actuals": progress message displays; after completion, ΔTotal values update to reflect new actuals.
- A pitcher with no innings yet: in Volume framing shows a strongly negative ΔTotal (correct — he's contributing 0 vs his expected counting stats); in Rate framing shows ΔTotal near 0 (correct — his rate deltas are all null and treated as 0).

- [ ] **Step 4: Confirm no regressions in other parts of the page**

- Per-category columns still show their values and color correctly.
- Position filters still work.
- "Show all" / "Show top 50" toggle still works.
- League / team selectors still drive "my team" highlighting.
