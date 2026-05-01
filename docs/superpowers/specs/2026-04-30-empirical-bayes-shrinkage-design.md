# Empirical Bayes Shrinkage for Playoff Odds Simulator — Design

**Date:** 2026-04-30
**Status:** Approved, ready for implementation plan
**Owner:** John Gibbons

## Problem

The playoff odds simulator (`backend/analysis/playoff_odds.py`) projects each team's
remaining-season weekly category totals from ATC projections (loaded from the
`rankings` table) and runs Monte Carlo H2H matchups around the recently
calibrated `CATEGORY_SIGMA`. Cumulative W/L/T carries forward, but the
rest-of-season projection itself ignores observed performance.

Result: a paper-strong roster that has actually been losing all season still
projects to dominate. Last-place teams routinely score >90% playoff odds because
the simulator trusts ATC over the standings.

## Goal

Apply a per-category empirical Bayes shrinkage to each team's projected weekly
category totals. The posterior blends the ATC-derived projection (prior) with
the team's observed weekly totals (likelihood), with the blend weight
controlled by the calibrated within-team and between-team variance components.

This directly addresses the pathology: a last-place team's *observed* weekly
R/TB/K/etc. will pull their projection down, deflating their playoff odds to
something realistic.

## Scope (v1)

- **In scope:** shrinkage applied inside `compute_playoff_odds_from_request`.
- **Out of scope (deferred):** applying the same shrinkage to the matchup
  endpoint, waiver MCW, trade analysis. The shrinkage module will be reusable
  but only wired up to playoff odds in v1.
- **Out of scope (deferred):** roster-aware reprojection for past observations,
  time-decay weighting of older periods, per-player shrinkage.

## Approach

**Per-category empirical Bayes shrinkage on weekly category totals**, using
the standard conjugate normal-normal posterior.

Why this and not alternatives:
- **Per-category vs per-team aggregate (e.g. shrink wins/week)**: per-category
  preserves the structure of the simulator (which compares cat-by-cat) and
  avoids schedule-strength bias; observed wins/week depends heavily on which
  opponents you played, observed cat totals do not.
- **Per-category vs per-player**: ATC already does player-level Bayesian
  updating. Re-doing it crudely risks competing with their model. Team-level
  shrinkage captures only what ATC *can't* see — lineup choices, hidden injury
  risk, manager skill — which is exactly the gap that produces the pathology.
- **Conjugate normal-normal**: closed-form, no MCMC, and the calibrated
  `CATEGORY_SIGMA` is exactly the per-week noise term the EB formula needs.

### The math

Per (team, category):

- `μ_proj(c)` — projected period total from `project_team_period` (period_weight
  applied).
- `x̄_obs(c)` — team's denominator-weighted mean per period for *c* across `W`
  completed periods, normalized to the current period's day count:
  - Count stats: `(Σ obs_p) / (Σ days_p) × period_days`
  - Rate stats: `(Σ rate_p · denom_p) / (Σ denom_p)` where `denom = PA` for
    `OBP` and `denom = IP` for `ERA`/`WHIP`. Matches how rate stats already
    aggregate elsewhere in the codebase.
- `σ_within(c)` = `CATEGORY_SIGMA[c]` (already calibrated against 2025 data).
- `σ_between(c)` = `CATEGORY_BETWEEN_SIGMA[c]` (new constant, calibrated from
  2025 between-team spread of season-rates).
- `W` — count of fully completed periods for this team at sim time.

Shrinkage weight:

```
w(c) = (σ_between² · W) / (σ_between² · W + σ_within²)
```

Shrunk period total:

```
μ̂(c) = w(c) · x̄_obs(c) + (1 − w(c)) · μ_proj(c)
```

`μ̂(c)` replaces `μ_proj(c)` as the input to `simulate_head_to_head`.

### Calibrating σ_between

Extend `backend/analysis/sigma_calibration.py` with a function that, given the
same 2025 team-period observations already used to compute `CATEGORY_SIGMA`,
returns the variance across teams of season-rate-per-day (count stats) or
season-rate (rate stats). This is an unbiased estimate of "how much do teams'
true production rates differ from each other," assuming ATC is unbiased.

The orchestration script `backend/scripts/calibrate_category_sigma.py` is
extended to also emit `CATEGORY_BETWEEN_SIGMA`. The hardcoded values land in
`backend/analysis/matchup.py` next to the existing `CATEGORY_SIGMA` constant.
The existing 2025 fixture-pinned regression test
(`test_sigma_calibration.py`) is extended to assert on the new constants.

## Architecture

Three components:

1. **Calibration extension** (modify `sigma_calibration.py`,
   `calibrate_category_sigma.py`, add to `matchup.py`): produces and surfaces
   `CATEGORY_BETWEEN_SIGMA`.

2. **Shrinkage math module** (`backend/analysis/shrinkage.py`, new): pure
   functions, no I/O, fully unit-testable. Public API:
   - `compute_shrinkage_weight(W: int, sigma_within: float, sigma_between: float) -> float`
   - `compute_observed_period_value(observations: list[ObservedPeriod], cat: str, kind: str, current_period_days: int) -> tuple[float, int]`
     returns `(observed_mean_in_period_units, n_periods_for_this_cat)`.
   - `apply_shrinkage_to_period(projected_cats: dict[str, float], observations: list[ObservedPeriod], current_period_days: int, sigma_within: dict, sigma_between: dict) -> dict[str, float]`

3. **Endpoint integration**:
   - `src/lib/espn-api.ts`: add `getMatchupHistory(...)` — wraps the same
     `view=mMatchupScore` endpoint already used by `getFullSchedule`,
     returns completed-period cat totals per team. (May share an underlying
     fetch with `getFullSchedule`; refactor opportunistically.)
   - `src/lib/playoff-odds-payload.ts`: add `observed_history` array to the
     payload.
   - `backend/api/playoff_odds_models.py`: add `ObservedPeriod` and
     `observed_history` field to `PlayoffOddsRequest`. Add
     `shrinkage_weight: dict[str, float]` to `TeamOdds` and
     `shrinkage_applied: bool`, `completed_periods_observed: int` meta fields
     to `PlayoffOddsResponse`.
   - `backend/analysis/playoff_odds.py`:
     - `project_team_period` gains an optional `shrinkage_ctx` parameter.
       When present, the per-cat output is replaced by the shrunk value.
     - `compute_playoff_odds_from_request` builds a `ShrinkageContext` per
       team from `observed_history` and threads it through
       `compute_playoff_odds → simulate_one_season → project_team_period`.

The Python `fetch_season_matchup_history` already exists in
`backend/data/espn_history.py` for the calibration pipeline, but the
playoff-odds runtime path runs through Next.js (which already orchestrates
ESPN fetches), so the TS layer fetches the history and passes it through the
payload.

## Data flow

```
User clicks "Run simulation"
        ↓
Next.js /api/playoff-odds route
  ├─ existing: league, teams, rosters, full schedule
  └─ NEW: getMatchupHistory → completed-period cats per team
        ↓
buildPlayoffOddsPayload (extended with observed_history)
        ↓
FastAPI POST /api/playoff-odds
        ↓
compute_playoff_odds_from_request
  ├─ resolve names → mlb_ids → load projections (existing)
  ├─ build rosters per team (existing)
  └─ NEW: build ShrinkageContext per team:
       observed[c] = denominator-weighted mean per period (cached once)
       W = count of completed periods
        ↓
compute_playoff_odds → simulate_one_season → project_team_period(
    roster, period_weight, il, shrinkage_ctx
)
  ├─ raw projection (existing): TeamTotals.category_values()
  └─ NEW if shrinkage_ctx:
       μ̂(c) = w(c) · x̄_obs(c) + (1 − w(c)) · μ_proj(c)
        ↓
Monte Carlo as before
        ↓
Response (extended):
  per team: existing + {shrinkage_weight: dict[cat, w]}
  meta: {shrinkage_applied: bool, completed_periods_observed: int}
```

### Two key design choices baked in

- **Observed mean is computed once per team, not per period.** A team's
  observed *rate* doesn't depend on which future period we're projecting; only
  the period-day rescaling does. We cache the per-team observed dict outside
  the simulate-one-season loop.
- **Shrinkage weight is a function of `W` only**, where `W` is total completed
  periods at simulation start. It does NOT grow during a single trial — we
  don't pretend the simulated future weeks become "observed." This keeps the
  simulator a pure forecast, not an updating filter.

## Error handling & edge cases

| Case | Behavior |
|---|---|
| Zero completed periods (week 1) | `W = 0` → `w = 0` → identical to today's behavior. No special path. |
| `getMatchupHistory` fails (ESPN 5xx, network) | Log + fall back to no shrinkage; response carries `meta.shrinkage_applied: false`. Better than failing the request. |
| Observed period exists but a category is missing (incomplete `scoreByStat`) | Skip that (team, cat, period) cell in the observed mean; reduce `W` *for that cat only*. |
| Team has only 1 completed period | Shrinkage applied normally. Formula is well-defined for `W=1`; gives modest weight. |
| `CATEGORY_BETWEEN_SIGMA[c] = 0.0` (calibration empty) | `w = 0`, skip shrinkage for that cat. Lets new constants ship without coupling. |
| 2025 calibration uses a different format than current league | σ_between would be biased. Document that the calibration script reads cat keys from the league fixture; format mismatches surface as missing cats. |
| Mid-period request (current week partially complete) | Use only fully-completed periods. Existing `parse_matchup_response` already filters by presence of `cumulativeScore.scoreByStat`. |

## Diagnostics

Surfaced on the response so the UI can show shrinkage transparency:
- Per-team `shrinkage_weight: dict[cat, float]` — w applied per category. Cats
  generally share the same `W` (and so vary only via per-cat σ ratios), but
  `W` can be lower for a cat if some periods had a missing `scoreByStat` cell
  for it.
- `meta.completed_periods_observed: int` — most-common `W` across cats and
  teams; for a "shrinkage strength: 4 weeks observed" UI label.
- `meta.shrinkage_applied: bool` — false on fetch failure or when explicitly
  disabled.

The frontend page can render shrinkage info in v1 as plain text in the meta
banner; a richer per-team breakdown is a follow-up.

## Testing

**1. Pure-math unit tests** (`tests/backend/analysis/test_shrinkage.py`, new)
Constructed inputs, no I/O, no fixtures.
- `compute_shrinkage_weight`: `W=0 → 0`, `W → ∞ → 1`, exact value at a
  mid-range case (σ_within=10, σ_between=5, W=4 → w = 100/(100+100) = 0.5).
- `compute_observed_period_value` count stat: per-day-then-rescale arithmetic
  with mixed period_days (7-day weeks + the 14-day All-Star period).
- `compute_observed_period_value` rate stat: denominator-weighted mean (PA for
  OBP, IP for ERA/WHIP).
- `apply_shrinkage_to_period`: end-to-end shrunk values for both count and
  rate cats.
- Edge cases: W=0, σ_between=0, observation missing for one cat (W reduced
  for that cat only).

**2. Calibration regression**
Extend the existing 2025 fixture-pinned regression
(`test_sigma_calibration.py`, commit `3838e33`) to assert on a frozen
`CATEGORY_BETWEEN_SIGMA` block. Catches accidental drift in the calibration
math.

**3. Integration test for `project_team_period` with shrinkage**
(in `tests/backend/analysis/test_playoff_odds.py`)
- Construct a team with a known projected μ for one cat.
- Pass a `shrinkage_ctx` with a known observed mean and `W`.
- Assert returned cat value equals `w·x̄ + (1−w)·μ_proj` (computed by hand for
  the test case).
- One regression test confirming `shrinkage_ctx=None` returns identical output
  to today's behavior, guarding non-shrunk callers (`matchup.py`, etc.) that
  reuse `project_team_period`.

**4. End-to-end smoke test** (manual, like Task 13 in the playoff-odds plan)
Run against the real league. Verify the last-place team's odds drop
substantially. Document before/after numbers in the implementation commit.

## File touch list

**New:**
- `backend/analysis/shrinkage.py` — pure-math module
- `tests/backend/analysis/test_shrinkage.py` — unit tests

**Modified:**
- `backend/analysis/sigma_calibration.py` — add `compute_between_team_sigma`
- `backend/scripts/calibrate_category_sigma.py` — emit `CATEGORY_BETWEEN_SIGMA`
- `backend/analysis/matchup.py` — add `CATEGORY_BETWEEN_SIGMA` constant
- `backend/analysis/playoff_odds.py` — `ShrinkageContext` builder; thread
  through `project_team_period`, `simulate_one_season`, `compute_playoff_odds`,
  `compute_playoff_odds_from_request`
- `backend/api/playoff_odds_models.py` — `ObservedPeriod`, expand
  `PlayoffOddsRequest` and `PlayoffOddsResponse`
- `tests/backend/analysis/test_sigma_calibration.py` — assert on between-sigma
- `tests/backend/analysis/test_playoff_odds.py` — shrinkage integration tests
- `src/lib/espn-api.ts` — `getMatchupHistory`
- `src/lib/playoff-odds-payload.ts` — include `observed_history`
- `src/__tests__/lib/playoff-odds-payload.test.ts` — extend
- `src/app/api/playoff-odds/route.ts` — call `getMatchupHistory`, thread
  through

## Out of scope / future work

- Apply shrinkage to matchup-projection endpoint, waiver MCW, trade analysis.
- Time-decay older periods (exponential decay).
- Roster-aware reprojection of past observations (recompute "what current
  roster would have projected" per past period).
- Per-player Bayesian update of RoS projections from YTD stats (treat as a
  separate effort; ATC's job).
- Surface shrinkage diagnostics in the playoff-odds UI beyond a top-line meta
  banner.
