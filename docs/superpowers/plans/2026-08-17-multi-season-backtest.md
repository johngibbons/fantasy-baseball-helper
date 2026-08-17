# Multi-Season Backtest: Extending the Retrospective to 2010–2025

**Status:** planned, not started
**Prerequisite:** the 2026 retrospective, complete — see `RETROSPECTIVE_2026.md`
and `backend/analysis/retro/`

---

## Why

The 2026 retrospective produced one recommendation worth acting on and several
worth ignoring, but nearly all of it rests on a single season:

- **The over-dispersion finding** — the board spreads players ~25% further apart
  than reality — is the only large effect measured, and it comes from one year.
- **The keeper model** was validated on 40 decisions, where the app's
  keep-or-pass signal agreed with the outcome 70% of the time. On n=40 that is
  barely distinguishable from a coin flip.
- **The value-at-pick curve** — which `expectedValueAtRound` in
  `src/app/keepers/page.tsx` depends on, and therefore every keeper surplus the
  app displays — was measured once.

A league spreadsheet covering 2010–2026 makes several of these testable across
many more seasons. Not all of them: see the constraint below.

## What already exists and must be reused

The 2026 retrospective built a working harness. This work extends it rather
than starting over.

| Module | What it does |
|---|---|
| `backend/analysis/retro/expost.py` | Turns realized stats into rows the valuation engine accepts; pace adjustment; pool alignment |
| `backend/analysis/retro/keeper_eval.py` | `keeper_cost`, `value_at_pick_curve`, `evaluate_keepers`, `keeper_accuracy` |
| `backend/analysis/retro/draft_replay.py` | Per-pick regret, board reconstruction, team category totals |
| `backend/analysis/retro/adp_model.py` | Residuals, sigma by band, manager bias |
| `backend/analysis/retro/valuation.py` | Spearman, Kendall, calibration slope, bootstrap CIs |
| `backend/analysis/zscores.py` | `ValuationConfig` — pinned denominators and every tunable, injectable |
| `backend/analysis/snapshots.py` | Snapshot tables, for the going-forward case |

Most of these take plain row dicts and are season-agnostic already. The work is
mostly *feeding them older data*, not writing new analysis.

---

## The hard constraint

**No archived preseason projections exist before 2026.** FanGraphs serves
current projections; historical preseason snapshots are not publicly
retrievable. Only the February 2026 CSVs in `backend/projection_data/` survive.

This splits the work cleanly, and the split should be respected:

**Backtestable with no projections at all** — needs only draft results and
realized stats, so there is nothing to bias:
- keeper outcomes
- the value-at-pick curve
- manager draft behaviour
- SGP denominators from more seasons of standings

**Requires regenerated projections** — possible, but the result measures a
different model:
- whether the valuation engine over-disperses across seasons

For that second group the only option is `generate_projections_from_stats`
(`backend/data/projections.py:857`), the app's own weighted, age-adjusted
three-season average. In 2026 that model scored 0.639 rank correlation for
hitters against THE BAT X's 0.741. So a calibration slope computed from it
measures *our* model's calibration, not THE BAT X's. That is still worth
knowing — it starts to separate "the projections over-disperse" from "the SGP
conversion over-disperses" — but it is not a clean replication of the 2026
result and should never be reported as one.

---

## The data

Source workbook: `2026 Juiced Fantasy Baseball Draft.xlsx`, 72 sheets, 7.5 MB,
currently at `~/Downloads/`. **It is not in the repo and should not be committed
as a binary** — Phase 0 extracts normalized JSON fixtures from it instead.

| Sheet family | Seasons | Shape |
|---|---|---|
| `YYYY Draft` | 2018–2025 | `#`, Owner, Player, Position, MLB Team, Notes; `Round N` marker rows |
| `YYYY Draft` | 2016–2017 | Owner, Player, Position, MLB Team, Notes — no `#` column, pick is positional |
| `YYYY Draft` | 2010–2014 | pick # in col 0, **franchise name** in col 1 (e.g. "London Wankers"), no manager names |
| `YYYY Keepers` | 2015–2026 | Wide: Manager, then (Keeper, Round Forfeited, Seasons Kept) × 4 |
| `ESPN 300 …` | 2017, 2021, 2023, 2024, 2025, 2026 | Rank, Player, Team, Elig. Pos., Pos. Rank, Status |
| Trades, Rosters, Final Rosters, Record Book | most years | not yet surveyed in detail |

**Missing:** 2015 and 2021 drafts; 2021 keepers.

**League stability:** the same ten managers from 2018 through 2025 (Chris Herbst
replaced by Russell Berry for 2026). Pre-2018 uses franchise names and needs a
mapping table before those seasons are usable.

**2026 is different:** its Draft tab is the empty planning template. The real
2026 draft is already captured at
`backend/data/fixtures/retro_2026/draft_state_2026.json`.

**Name resolution** against the local `players` table degrades with age:

| Season | Matched |
|---|---|
| 2025 | 100% |
| 2024 | 99% |
| 2022 | 96% |
| 2020 | 90% |
| 2018 | 69% |

The misses are retired players absent from a table built off current rosters
(Votto, Rizzo, Strasburg). Recoverable through MLB's people-search endpoint —
work, not a blocker.

---

## Phases

### Phase 0 — Extract and freeze the workbook

`backend/scripts/history_import.py`, mirroring `retro_snapshot.py`.

Parse the workbook into committed JSON under
`backend/data/fixtures/league_history/`:

- `drafts_YYYY.json` — `[{pick_number, round, owner, player_name, position, mlb_team, notes}]`
- `keepers_YYYY.json` — `[{manager, player_name, round_cost, seasons_kept}]`
- `rankings_YYYY.json` — the ESPN top-300 sheets, with their snapshot date
- `manifest.json` — per season: rows parsed, layout variant detected, unresolved names

Parse defensively and **report rather than repair**. Three layout eras exist;
detect which applies per sheet instead of assuming. Any row that does not parse
belongs in the manifest, not in a silent `except: continue`.

The workbook stays out of git; the JSON is small, diffable and reviewable.

### Phase 1 — Resolve names to mlb_ids

Extend `backend/data/name_matching.py` with a retired-player lookup against
MLB's people-search endpoint, cached to the `players` table so it runs once.

Emit a per-season resolution report. **Set a floor** — a season resolving below
~90% should be excluded from analysis rather than quietly analysed with a
biased subset, because the players who fail to resolve are systematically the
older ones.

Cross-check against `src/lib/draft-history.ts`, which already holds
hand-curated `KEEPER_HISTORY` and `RECENT_DRAFT_HISTORY`. Disagreements between
the spreadsheet and that file are worth surfacing — one of them is wrong.

### Phase 2 — Backfill realized stats

`batting_stats` and `pitching_stats` currently hold 2024–2026 only. Backfill
every season in scope using `refresh_actuals_for_players`, which already
retries and separates genuine no-stats from fetch failure.

**Derive quality starts** (`include_quality_starts=True`). Without it every
pitcher carries a zero in one of four scored categories — the bug that made the
2026 ex-post pitcher board list no starter in its top five.

### Phase 3 — Keeper outcomes across all seasons ← **start here**

The highest value per unit of risk, and it needs no projections.

For each season with both a draft and a keeper sheet, reuse
`value_at_pick_curve` and `evaluate_keepers` from `keeper_eval.py` unchanged.
Realized value comes from the ex-post SGP path in `expost.py`.

Questions to answer:
- Across ~320 decisions instead of 40, how often does keeping beat what that
  round actually returned?
- Does the app's surplus sign predict the outcome better than the 70% measured
  in 2026?
- Does surplus scale with round cost the way the model assumes?
- Do multi-season keepers (cost dropping five rounds a year) stay worth it in
  years two and three? `KEEPER_HISTORY` shows players kept five seasons.

Artifact: `backend/data/fixtures/league_history/keeper_outcomes.json`.

### Phase 4 — Value-at-pick curve across all seasons

Falls out of the same data. The question that matters: is
`expectedValueAtRound`'s rank-linear assumption stable year to year, or was
2026 unusual? If the curve is stable, it can be replaced with a fitted empirical
curve; if it swings, the keeper model needs to carry uncertainty rather than a
point estimate.

Also worth measuring: whether "only 139 of 1,358 players cleared replacement
while the league rosters 250" is a general property of this league or a 2026
artifact. If general, it is a strategic finding about how early picks should be
valued.

### Phase 5 — Market-consensus baseline

For the six seasons with ESPN top-300 sheets, the ranking is a usable stand-in
for draft-day ADP — and better than ADP in one respect: it is the list the
league actually drafted from.

- Reproduce the 2026 "board versus market" comparison for earlier seasons.
- Re-measure ADP residual spread by band. The 2026 finding was that spread grows
  sixfold from the top of the board to the middle rounds, and that
  `σ = 6.55 + 0.158 × ADP` fits best. Does that hold across years?
- Per-manager reach/wait tendencies over many drafts — a direct upgrade to the
  hand-curated `MANAGER_PROFILES`, and the input the simulator's opponent model
  needs.

### Phase 6 — Regenerated projections (optional, do last)

Only attempt after Phases 3–5 have shown the data is sound.

Regenerate projections for each season with `generate_projections_from_stats`,
scoped strictly to prior seasons, then run the Layer A pipeline
(`retro_valuation.py`) per season.

Report the calibration slope per season and explicitly label it as the *trend
model's* calibration, not THE BAT X's.

---

## Traps

**Lookahead bias is the one that ruins everything.** Regenerating 2022
projections using 2022 statistics produces a spectacular backtest that means
nothing, and the output looks entirely normal. Every regenerated projection must
be scoped to seasons already complete at the time. **Write a test that fails
loudly if the scoping is violated** — this cannot be left to reviewer attention.

**Pre-2026 drafts were not made by the app.** It did not exist. Decision-quality
numbers for those seasons measure the managers, not the software. That is a
useful human baseline, but it is a different question from 2026 and must be
labelled as such.

**Offline drafts.** The league drafts offline, so ESPN's `mDraftDetail` is not a
usable cross-check for pick order. The spreadsheet is the only record.

**SGP denominators shift.** `_compute_sgp_denominators` averages over every
season in `league_season_totals` (currently 2023–2025). Pin them explicitly per
run via `ValuationConfig`, and decide deliberately whether each season should be
valued on its own denominators or a common set. Both are defensible; mixing them
silently is not.

**Replacement level is pool-relative.** Two boards are only comparable over the
same player universe. `align_pool` in `expost.py` enforces this — use it.

**Roster size and league rules may have changed** across 17 seasons. Check
before assuming 25 rounds and 10 teams throughout; the 2010–2014 sheets have
different row counts (174–226 versus 277).

---

## Verification

- Every parsed season asserts the expected pick count and that each manager
  received a full roster — the check that caught the scrambled pick ordering in
  2026.
- Fixture-backed tests in the existing style: store raw inputs alongside
  computed outputs, recompute from raw, assert equality
  (`tests/backend/analysis/test_retro_*.py`).
- A test asserting no regenerated projection uses stats from its own season or
  later.
- Name-resolution rates recorded per season in the manifest, with a hard floor
  below which a season is excluded.
- `python -m pytest tests/backend -q` stays green; it runs in CI now.

## Definition of done

A findings document — `RETROSPECTIVE_MULTISEASON.md` — answering:

1. Does the keeper model work, measured across ~320 decisions rather than 40?
2. Is the value-at-pick curve stable enough to replace the rank-linear
   assumption with a fitted one?
3. Do the 2026 ADP-spread findings replicate?
4. Is the concentration of value above replacement a league constant?
5. If Phase 6 runs: does the valuation engine over-disperse in every season, or
   was 2026 unusual?

Each answer carries its sample size and a confidence interval, and anything
inside the noise is reported as no finding — the discipline
`SCORING_IMPROVEMENTS.md` already applies to simulation sweeps.
