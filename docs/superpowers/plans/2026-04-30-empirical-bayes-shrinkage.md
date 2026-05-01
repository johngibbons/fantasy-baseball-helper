# Empirical Bayes Shrinkage for Playoff Odds — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply per-category empirical Bayes shrinkage in the playoff odds simulator so that observed weekly performance pulls each team's projected category totals away from the ATC prior, fixing the pathology where last-place teams score 90%+ playoff odds.

**Architecture:** Pure-math shrinkage helper (`backend/analysis/shrinkage.py`) operating in "typical 7-day period" units. Calibration extension produces a per-category `CATEGORY_BETWEEN_SIGMA` constant alongside the existing `CATEGORY_SIGMA`. The Next.js orchestrator additionally fetches season matchup history; FastAPI builds a per-team `ShrinkageContext` once and threads it through `project_team_period` so each per-period projection is replaced by `μ̂(c) = w(c)·x̄_obs(c) + (1−w(c))·μ_proj(c)`.

**Tech Stack:** Python 3, FastAPI, Pydantic v2, NumPy (existing), pytest, Next.js 15, TypeScript, Jest.

**Spec:** `docs/superpowers/specs/2026-04-30-empirical-bayes-shrinkage-design.md`

**v1 simplifications (documented intentionally — do NOT bolt on without follow-up):**
- All matchup periods treated as typical 7-day length for shrinkage math; observed totals normalized to a typical-period basis. Matches the existing simulator's CATEGORY_SIGMA approximation.
- Rate-stat observed means use unweighted average across periods (PA/IP not returned by ESPN's matchup endpoint). Mirrors the calibration's existing rate-stat handling.
- Roster turnover not modeled — every completed period contributes regardless of which roster produced it. (Spec option (i).)

---

## File Structure

**New files:**
- `backend/analysis/shrinkage.py` — pure-math shrinkage module
- `tests/backend/analysis/test_shrinkage.py` — unit tests for the shrinkage math

**Modified files:**
- `backend/analysis/sigma_calibration.py` — add `compute_between_team_sigma`
- `backend/scripts/calibrate_category_sigma.py` — emit `CATEGORY_BETWEEN_SIGMA`, persist to fixture
- `backend/data/fixtures/sigma_calibration_2025.json` — extended with `computed_between_sigma`
- `backend/analysis/matchup.py` — add `CATEGORY_BETWEEN_SIGMA` constant, expose `TYPICAL_PERIOD_DAYS`
- `backend/api/playoff_odds_models.py` — `ObservedPeriod`, `observed_history` field, response shrinkage fields
- `backend/analysis/playoff_odds.py` — `ShrinkageContext`, threading through `project_team_period`, `simulate_one_season`, `compute_playoff_odds`, `compute_playoff_odds_from_request`
- `tests/backend/analysis/test_sigma_calibration.py` — assertions on between-sigma + matchup constants
- `tests/backend/analysis/test_playoff_odds.py` — shrinkage integration tests
- `src/lib/espn-api.ts` — `getMatchupHistory` static method
- `src/__tests__/lib/espn-api.test.ts` — test for `getMatchupHistory`
- `src/lib/playoff-odds-payload.ts` — include `observed_history` in built payload
- `src/__tests__/lib/playoff-odds-payload.test.ts` — extend
- `src/app/api/playoff-odds/route.ts` — fetch history, threaded through; handle fetch failure with fallback meta flag

---

## Task 1: Pure shrinkage math — `compute_shrinkage_weight`

**Files:**
- Create: `backend/analysis/shrinkage.py`
- Create: `tests/backend/analysis/test_shrinkage.py`

The conjugate normal-normal posterior weight: `w = σ_b² · W / (σ_b² · W + σ_w²)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/backend/analysis/test_shrinkage.py`:

```python
"""Tests for empirical Bayes shrinkage math."""

from __future__ import annotations

import math
import pytest

from backend.analysis.shrinkage import compute_shrinkage_weight


class TestComputeShrinkageWeight:
    def test_zero_periods_gives_zero_weight(self):
        assert compute_shrinkage_weight(W=0, sigma_within=10.0, sigma_between=5.0) == 0.0

    def test_zero_between_sigma_gives_zero_weight(self):
        assert compute_shrinkage_weight(W=10, sigma_within=10.0, sigma_between=0.0) == 0.0

    def test_negative_periods_treated_as_zero(self):
        assert compute_shrinkage_weight(W=-1, sigma_within=10.0, sigma_between=5.0) == 0.0

    def test_known_midrange_value(self):
        # σ_w=10, σ_b=5, W=4 → (25 * 4) / (25 * 4 + 100) = 100/200 = 0.5
        assert compute_shrinkage_weight(W=4, sigma_within=10.0, sigma_between=5.0) == pytest.approx(0.5)

    def test_large_W_approaches_one(self):
        w = compute_shrinkage_weight(W=10_000, sigma_within=10.0, sigma_between=5.0)
        assert w > 0.99

    def test_small_between_relative_to_within_gives_small_weight(self):
        # σ_b much smaller than σ_w → prior dominates even with many periods
        w = compute_shrinkage_weight(W=5, sigma_within=10.0, sigma_between=0.5)
        # (0.25 * 5) / (0.25 * 5 + 100) = 1.25 / 101.25 ≈ 0.0123
        assert w == pytest.approx(1.25 / 101.25, rel=1e-6)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/backend/analysis/test_shrinkage.py::TestComputeShrinkageWeight -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.analysis.shrinkage'`.

- [ ] **Step 3: Implement `compute_shrinkage_weight`**

Create `backend/analysis/shrinkage.py`:

```python
"""Empirical Bayes shrinkage for the playoff odds simulator.

Pure-math helpers. No I/O. Operates in typical-period units (~7-day weeks) for
both σ_within (calibrated CATEGORY_SIGMA) and σ_between (calibrated
CATEGORY_BETWEEN_SIGMA), matching the existing simulator's period-length
approximation.
"""

from __future__ import annotations

TYPICAL_PERIOD_DAYS = 7


def compute_shrinkage_weight(
    W: int,
    sigma_within: float,
    sigma_between: float,
) -> float:
    """Conjugate normal-normal posterior weight on the observed mean.

    Args:
        W: Number of completed periods observed for this (team, cat).
        sigma_within: σ for one period's noise around team's true mean (typical-period units).
        sigma_between: σ for spread of teams' true means around the ATC prior (typical-period units).

    Returns:
        Weight in [0, 1]. 0 when no observations or when σ_between == 0.
    """
    if W <= 0 or sigma_between <= 0.0:
        return 0.0
    num = (sigma_between ** 2) * W
    return num / (num + sigma_within ** 2)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/backend/analysis/test_shrinkage.py::TestComputeShrinkageWeight -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/analysis/shrinkage.py tests/backend/analysis/test_shrinkage.py
git commit -m "feat(shrinkage): conjugate normal-normal posterior weight"
```

---

## Task 2: Pure shrinkage math — observed period totals from history

**Files:**
- Modify: `backend/analysis/shrinkage.py`
- Modify: `tests/backend/analysis/test_shrinkage.py`

Two helpers — one for count stats (normalize by total days, scale to typical period), one for rate stats (unweighted average across periods, since ESPN matchup data lacks PA/IP).

A shared `ObservedPeriod` dataclass holds one team-period observation.

- [ ] **Step 1: Write the failing tests**

Append to `tests/backend/analysis/test_shrinkage.py`:

```python
from backend.analysis.shrinkage import (
    ObservedPeriod,
    compute_observed_typical_period_count,
    compute_observed_period_rate,
)


def _obs(period_id: int, days: int, **cats) -> ObservedPeriod:
    return ObservedPeriod(matchup_period_id=period_id, period_days=days, cats=dict(cats))


class TestComputeObservedTypicalPeriodCount:
    def test_seven_day_periods_average_normalizes_to_typical_period(self):
        observations = [
            _obs(1, 7, R=70.0),
            _obs(2, 7, R=84.0),
        ]
        # total=154 over 14 days → 11/day → 77 per typical 7-day period
        mean, n = compute_observed_typical_period_count(observations, "R")
        assert mean == pytest.approx(77.0)
        assert n == 2

    def test_mixed_period_lengths_are_normalized(self):
        # 7-day period: 56 R = 8/day; 14-day period: 154 R = 11/day
        # combined per-day: (56+154)/(7+14) = 210/21 = 10/day → 70 per typical week
        observations = [
            _obs(1, 7, R=56.0),
            _obs(2, 14, R=154.0),
        ]
        mean, n = compute_observed_typical_period_count(observations, "R")
        assert mean == pytest.approx(70.0)
        assert n == 2

    def test_missing_cat_in_some_periods_reduces_n(self):
        # Period 1 has R, period 2 doesn't
        observations = [
            _obs(1, 7, R=70.0),
            _obs(2, 7, TB=200.0),  # no R
        ]
        mean, n = compute_observed_typical_period_count(observations, "R")
        assert mean == pytest.approx(70.0)  # only period 1 counted
        assert n == 1

    def test_no_observations_returns_zero(self):
        mean, n = compute_observed_typical_period_count([], "R")
        assert mean == 0.0
        assert n == 0


class TestComputeObservedPeriodRate:
    def test_unweighted_mean_across_periods(self):
        # ERA values: 3.00, 4.00, 5.00 → avg 4.00
        observations = [
            _obs(1, 7, ERA=3.00),
            _obs(2, 7, ERA=4.00),
            _obs(3, 7, ERA=5.00),
        ]
        mean, n = compute_observed_period_rate(observations, "ERA")
        assert mean == pytest.approx(4.00)
        assert n == 3

    def test_period_length_does_not_affect_rate_mean(self):
        # Rates are not scaled by days
        observations = [
            _obs(1, 7, OBP=0.300),
            _obs(2, 14, OBP=0.400),
        ]
        mean, n = compute_observed_period_rate(observations, "OBP")
        assert mean == pytest.approx(0.350)
        assert n == 2

    def test_no_observations_returns_zero(self):
        mean, n = compute_observed_period_rate([], "OBP")
        assert mean == 0.0
        assert n == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/backend/analysis/test_shrinkage.py::TestComputeObservedTypicalPeriodCount tests/backend/analysis/test_shrinkage.py::TestComputeObservedPeriodRate -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement the helpers**

Append to `backend/analysis/shrinkage.py`:

```python
from dataclasses import dataclass, field


@dataclass
class ObservedPeriod:
    """One completed matchup period's category totals for one team."""
    matchup_period_id: int
    period_days: int
    cats: dict[str, float] = field(default_factory=dict)


def compute_observed_typical_period_count(
    observations: list[ObservedPeriod],
    cat: str,
) -> tuple[float, int]:
    """Mean count for *cat* normalized to a typical 7-day period.

    Combines all periods' observed totals divided by total days, then multiplies
    by TYPICAL_PERIOD_DAYS. Periods missing this cat are skipped (and reduce n).

    Returns:
        (mean_per_typical_period, n_periods_used).
    """
    relevant = [o for o in observations if cat in o.cats]
    if not relevant:
        return 0.0, 0
    total_obs = sum(o.cats[cat] for o in relevant)
    total_days = sum(o.period_days for o in relevant)
    if total_days <= 0:
        return 0.0, len(relevant)
    return (total_obs / total_days) * TYPICAL_PERIOD_DAYS, len(relevant)


def compute_observed_period_rate(
    observations: list[ObservedPeriod],
    cat: str,
) -> tuple[float, int]:
    """Unweighted mean of rate values across periods.

    PA / IP weights are not available in ESPN's matchup response, so we use
    an unweighted mean — same approximation the σ calibration uses.

    Returns:
        (mean_rate, n_periods_used).
    """
    relevant = [o for o in observations if cat in o.cats]
    if not relevant:
        return 0.0, 0
    return sum(o.cats[cat] for o in relevant) / len(relevant), len(relevant)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/backend/analysis/test_shrinkage.py -v`
Expected: PASS (all tests so far).

- [ ] **Step 5: Commit**

```bash
git add backend/analysis/shrinkage.py tests/backend/analysis/test_shrinkage.py
git commit -m "feat(shrinkage): observed-mean helpers (count + rate)"
```

---

## Task 3: Pure shrinkage — `apply_shrinkage_to_period`

**Files:**
- Modify: `backend/analysis/shrinkage.py`
- Modify: `tests/backend/analysis/test_shrinkage.py`

End-to-end helper: given a team's projected category totals for one period, the team's observation history, and the calibrated σ constants, return the shrunk per-category dict.

For count stats: shrink in typical-period units, then convert back to the period's actual day count.
For rate stats: shrink directly (period-length-independent).

- [ ] **Step 1: Write the failing tests**

Append to `tests/backend/analysis/test_shrinkage.py`:

```python
from backend.analysis.shrinkage import apply_shrinkage_to_period


SIGMA_WITHIN = {"R": 5.0, "TB": 15.0, "ERA": 1.0, "OBP": 0.025}
SIGMA_BETWEEN = {"R": 5.0, "TB": 15.0, "ERA": 1.0, "OBP": 0.025}
CAT_KINDS = {"R": "count", "TB": "count", "ERA": "rate", "OBP": "rate"}


class TestApplyShrinkageToPeriod:
    def test_zero_history_returns_projection_unchanged(self):
        projected = {"R": 70.0, "TB": 200.0, "ERA": 3.50, "OBP": 0.330}
        out, weights = apply_shrinkage_to_period(
            projected_period_cats=projected,
            observations=[],
            current_period_days=7,
            sigma_within=SIGMA_WITHIN,
            sigma_between=SIGMA_BETWEEN,
            cat_kinds=CAT_KINDS,
        )
        assert out == projected
        for cat in projected:
            assert weights[cat] == 0.0

    def test_count_stat_shrinks_toward_observed(self):
        # σ_w = σ_b = 5, W = 1 → w = 25 / (25 + 25) = 0.5
        # observed mean per typical period = 100 (well above projected 70)
        observations = [
            _obs(1, 7, R=100.0),
        ]
        out, weights = apply_shrinkage_to_period(
            projected_period_cats={"R": 70.0},
            observations=observations,
            current_period_days=7,
            sigma_within={"R": 5.0},
            sigma_between={"R": 5.0},
            cat_kinds={"R": "count"},
        )
        # shrunk_typical = 0.5 * 100 + 0.5 * 70 = 85; period_days=7 so output = 85
        assert out["R"] == pytest.approx(85.0)
        assert weights["R"] == pytest.approx(0.5)

    def test_count_stat_period_days_rescaling_for_long_periods(self):
        # 14-day period: projected = 140, observed = 100/typical. With w=0.5:
        # shrunk_typical = 0.5*100 + 0.5*(140 / 14 * 7) = 0.5*100 + 0.5*70 = 85
        # back to 14-day period: 85 / 7 * 14 = 170
        observations = [_obs(1, 7, R=100.0)]
        out, _ = apply_shrinkage_to_period(
            projected_period_cats={"R": 140.0},
            observations=observations,
            current_period_days=14,
            sigma_within={"R": 5.0},
            sigma_between={"R": 5.0},
            cat_kinds={"R": "count"},
        )
        assert out["R"] == pytest.approx(170.0)

    def test_rate_stat_shrinks_directly(self):
        # σ_w = σ_b = 1.0, W=1 → w = 0.5; obs ERA = 4.50, projected = 3.50 → shrunk = 4.00
        observations = [_obs(1, 7, ERA=4.50)]
        out, weights = apply_shrinkage_to_period(
            projected_period_cats={"ERA": 3.50},
            observations=observations,
            current_period_days=7,
            sigma_within={"ERA": 1.0},
            sigma_between={"ERA": 1.0},
            cat_kinds={"ERA": "rate"},
        )
        assert out["ERA"] == pytest.approx(4.00)
        assert weights["ERA"] == pytest.approx(0.5)

    def test_missing_cat_in_history_falls_back_to_projection(self):
        # Two periods of TB but no R — R shrinkage uses W=0
        observations = [_obs(1, 7, TB=200.0), _obs(2, 7, TB=210.0)]
        out, weights = apply_shrinkage_to_period(
            projected_period_cats={"R": 70.0, "TB": 250.0},
            observations=observations,
            current_period_days=7,
            sigma_within={"R": 5.0, "TB": 15.0},
            sigma_between={"R": 5.0, "TB": 15.0},
            cat_kinds={"R": "count", "TB": "count"},
        )
        # R: no observations → projection unchanged
        assert out["R"] == pytest.approx(70.0)
        assert weights["R"] == 0.0
        # TB: 2 obs, w = (225*2)/(225*2 + 225) = 450/675 = 2/3
        # observed_typical = 410/14*7 = 205; shrunk = 2/3*205 + 1/3*250 = 220
        assert out["TB"] == pytest.approx(220.0)
        assert weights["TB"] == pytest.approx(2.0/3.0)

    def test_zero_between_sigma_for_one_cat_skips_shrinkage(self):
        observations = [_obs(1, 7, R=100.0)]
        out, weights = apply_shrinkage_to_period(
            projected_period_cats={"R": 70.0},
            observations=observations,
            current_period_days=7,
            sigma_within={"R": 5.0},
            sigma_between={"R": 0.0},  # calibration empty
            cat_kinds={"R": "count"},
        )
        assert out["R"] == pytest.approx(70.0)
        assert weights["R"] == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/backend/analysis/test_shrinkage.py::TestApplyShrinkageToPeriod -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement `apply_shrinkage_to_period`**

Append to `backend/analysis/shrinkage.py`:

```python
def apply_shrinkage_to_period(
    projected_period_cats: dict[str, float],
    observations: list[ObservedPeriod],
    current_period_days: int,
    sigma_within: dict[str, float],
    sigma_between: dict[str, float],
    cat_kinds: dict[str, str],
) -> tuple[dict[str, float], dict[str, float]]:
    """Return shrunk per-cat dict for one period plus the per-cat weights applied.

    For count stats:
        observed_typical = (Σ obs / Σ days) × TYPICAL_PERIOD_DAYS
        projected_typical = projected_period_total / current_period_days × TYPICAL_PERIOD_DAYS
        shrunk_typical = w · observed_typical + (1−w) · projected_typical
        shrunk_period = shrunk_typical / TYPICAL_PERIOD_DAYS × current_period_days

    For rate stats:
        observed = unweighted mean across periods
        shrunk = w · observed + (1−w) · projected_rate
        (no period-length scaling)
    """
    out: dict[str, float] = {}
    weights: dict[str, float] = {}
    for cat, projected in projected_period_cats.items():
        kind = cat_kinds.get(cat, "count")
        sw = sigma_within.get(cat, 0.0)
        sb = sigma_between.get(cat, 0.0)
        if kind == "count":
            observed_typical, n = compute_observed_typical_period_count(observations, cat)
            w = compute_shrinkage_weight(W=n, sigma_within=sw, sigma_between=sb)
            if w == 0.0:
                out[cat] = projected
            else:
                projected_typical = (
                    projected / current_period_days * TYPICAL_PERIOD_DAYS
                    if current_period_days > 0 else projected
                )
                shrunk_typical = w * observed_typical + (1 - w) * projected_typical
                out[cat] = (
                    shrunk_typical / TYPICAL_PERIOD_DAYS * current_period_days
                    if current_period_days > 0 else shrunk_typical
                )
            weights[cat] = w
        else:  # rate
            observed_rate, n = compute_observed_period_rate(observations, cat)
            w = compute_shrinkage_weight(W=n, sigma_within=sw, sigma_between=sb)
            out[cat] = w * observed_rate + (1 - w) * projected if w > 0.0 else projected
            weights[cat] = w
    return out, weights
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/backend/analysis/test_shrinkage.py -v`
Expected: PASS (all shrinkage tests).

- [ ] **Step 5: Commit**

```bash
git add backend/analysis/shrinkage.py tests/backend/analysis/test_shrinkage.py
git commit -m "feat(shrinkage): apply_shrinkage_to_period end-to-end helper"
```

---

## Task 4: Calibration extension — `compute_between_team_sigma`

**Files:**
- Modify: `backend/analysis/sigma_calibration.py`
- Modify: `tests/backend/analysis/test_sigma_calibration.py`

A pure function that, given the per-team season rates the calibration script already computes, returns σ across teams of "average per-typical-period total" for count stats or "season rate" for rate stats.

- [ ] **Step 1: Write the failing test**

Append to `tests/backend/analysis/test_sigma_calibration.py` (above the `TestCalibrationFixtureRegression` class):

```python
class TestComputeBetweenTeamSigma:
    def test_count_stat_uses_per_typical_period_units(self):
        # Three teams with per-day R rates of 9, 10, 11.
        # In typical 7-day periods: 63, 70, 77.
        # Sample stddev of (63, 70, 77) — Python sample variance = 49 → σ = 7.0
        team_rates = {
            1: {"R": 9.0},
            2: {"R": 10.0},
            3: {"R": 11.0},
        }
        from backend.analysis.sigma_calibration import compute_between_team_sigma
        result = compute_between_team_sigma(
            team_rates_per_day=team_rates,
            cat_keys=["R"],
            cat_kinds={"R": "count"},
        )
        assert result["R"] == pytest.approx(7.0, rel=1e-6)

    def test_rate_stat_uses_season_rate_directly(self):
        team_rates = {
            1: {"OBP": 0.300},
            2: {"OBP": 0.330},
            3: {"OBP": 0.360},
        }
        from backend.analysis.sigma_calibration import compute_between_team_sigma
        result = compute_between_team_sigma(
            team_rates_per_day=team_rates,
            cat_keys=["OBP"],
            cat_kinds={"OBP": "rate"},
        )
        # Sample stddev of (0.300, 0.330, 0.360) = 0.030
        assert result["OBP"] == pytest.approx(0.030, rel=1e-6)

    def test_single_team_returns_zero(self):
        from backend.analysis.sigma_calibration import compute_between_team_sigma
        result = compute_between_team_sigma(
            team_rates_per_day={1: {"R": 10.0}},
            cat_keys=["R"],
            cat_kinds={"R": "count"},
        )
        assert result["R"] == 0.0

    def test_handles_multiple_cats(self):
        team_rates = {
            1: {"R": 9.0, "OBP": 0.300},
            2: {"R": 11.0, "OBP": 0.360},
        }
        from backend.analysis.sigma_calibration import compute_between_team_sigma
        result = compute_between_team_sigma(
            team_rates_per_day=team_rates,
            cat_keys=["R", "OBP"],
            cat_kinds={"R": "count", "OBP": "rate"},
        )
        # R: 63, 77 → sample stddev = sqrt((49 + 49)/1) wait
        # sample stddev of (63, 77): mean=70, deviations=±7, var = (49+49)/(2-1) = 98, σ = sqrt(98) ≈ 9.899
        assert result["R"] == pytest.approx(math.sqrt(98.0), rel=1e-6)
        # OBP: sample stddev of (0.300, 0.360) → sqrt((0.0009+0.0009)/1) = sqrt(0.0018) ≈ 0.04243
        assert result["OBP"] == pytest.approx(math.sqrt(0.0018), rel=1e-6)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/backend/analysis/test_sigma_calibration.py::TestComputeBetweenTeamSigma -v`
Expected: FAIL with `ImportError: cannot import name 'compute_between_team_sigma'`.

- [ ] **Step 3: Implement `compute_between_team_sigma`**

Append to `backend/analysis/sigma_calibration.py`:

```python
TYPICAL_PERIOD_DAYS = 7


def compute_between_team_sigma(
    team_rates_per_day: dict[int, dict[str, float]],
    cat_keys: list[str],
    cat_kinds: dict[str, str],
    typical_period_days: int = TYPICAL_PERIOD_DAYS,
) -> dict[str, float]:
    """σ_between per category — spread across teams of typical-period production.

    For count stats: stddev across teams of (per_day_rate × typical_period_days),
    yielding units that match the count-stat CATEGORY_SIGMA (per-typical-period).
    For rate stats: stddev across teams of season_rate, in rate units.

    Returns 0.0 for cats with fewer than 2 teams (no variance signal).
    """
    out: dict[str, float] = {}
    team_ids = list(team_rates_per_day.keys())
    for cat in cat_keys:
        kind = cat_kinds.get(cat, "count")
        if kind == "count":
            values = [
                team_rates_per_day[tid].get(cat, 0.0) * typical_period_days
                for tid in team_ids
            ]
        else:  # rate
            values = [team_rates_per_day[tid].get(cat, 0.0) for tid in team_ids]
        out[cat] = _stddev(values)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/backend/analysis/test_sigma_calibration.py::TestComputeBetweenTeamSigma -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/analysis/sigma_calibration.py tests/backend/analysis/test_sigma_calibration.py
git commit -m "feat(sigma-calibration): per-category between-team sigma"
```

---

## Task 5: Calibration script emits `CATEGORY_BETWEEN_SIGMA` and persists it

**Files:**
- Modify: `backend/scripts/calibrate_category_sigma.py`

The script already computes `team_rates_per_day` for σ_within. We add a parallel call to `compute_between_team_sigma`, print the new constant block, and store it in the fixture JSON.

- [ ] **Step 1: Modify the script's `main()` and `write_fixture()`**

Open `backend/scripts/calibrate_category_sigma.py`. Modify the imports at the top:

```python
from backend.analysis.sigma_calibration import (
    CountStatObservation,
    compute_category_sigma,
    compute_between_team_sigma,
)
```

Modify `write_fixture` signature and body:

```python
def write_fixture(
    fixture_path: Path,
    records: list[MatchupRecord],
    computed_sigma: dict[str, float],
    computed_between_sigma: dict[str, float],
) -> None:
    """Persist raw records + computed σ values for regression testing."""
    payload = {
        "computed_sigma": computed_sigma,
        "computed_between_sigma": computed_between_sigma,
        "records": [
            {
                "team_id": r.team_id,
                "matchup_period_id": r.matchup_period_id,
                "period_days": r.period_days,
                "cats": r.cats,
            }
            for r in records
        ],
    }
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    with fixture_path.open("w") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
```

In `main()`, after the existing `sigma = compute_category_sigma(...)` block, add:

```python
    between_sigma = compute_between_team_sigma(
        team_rates_per_day=rates,
        cat_keys=CAT_KEYS,
        cat_kinds=CAT_KINDS,
    )

    print()
    print("Calibrated CATEGORY_BETWEEN_SIGMA (paste into backend/analysis/matchup.py):")
    print("CATEGORY_BETWEEN_SIGMA: dict[str, float] = {")
    for cat in CAT_KEYS:
        print(f'    "{cat}": {between_sigma[cat]:.4f},')
    print("}")
```

Replace the `write_fixture(fixture_path, filtered, sigma)` call with:

```python
    write_fixture(fixture_path, filtered, sigma, between_sigma)
```

- [ ] **Step 2: Verify the script imports cleanly**

Run: `python -c "import backend.scripts.calibrate_category_sigma; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add backend/scripts/calibrate_category_sigma.py
git commit -m "feat(sigma-calibration): script emits CATEGORY_BETWEEN_SIGMA"
```

---

## Task 6: Recompute against fixture, hardcode constants, extend regression test

**Files:**
- Modify: `backend/data/fixtures/sigma_calibration_2025.json`
- Modify: `backend/analysis/matchup.py`
- Modify: `tests/backend/analysis/test_sigma_calibration.py`

We don't need fresh ESPN credentials for this — the existing 2025 fixture has all the records. Recompute σ_between locally from those records, write the updated fixture, and freeze the values in `matchup.py`.

- [ ] **Step 1: Write a one-off script to update the fixture**

Run inline (no commit):

```bash
python3 - <<'PY'
import json
from pathlib import Path
from backend.scripts.calibrate_category_sigma import (
    CAT_KEYS, CAT_KINDS, compute_team_rates_per_day, records_to_observations,
)
from backend.data.espn_history import MatchupRecord
from backend.analysis.sigma_calibration import (
    compute_category_sigma, compute_between_team_sigma,
)

path = Path("backend/data/fixtures/sigma_calibration_2025.json")
data = json.loads(path.read_text())
records = [
    MatchupRecord(
        team_id=r["team_id"],
        matchup_period_id=r["matchup_period_id"],
        period_days=r["period_days"],
        cats=r["cats"],
    ) for r in data["records"]
]
rates = compute_team_rates_per_day(records)
observations = records_to_observations(records)
sigma = compute_category_sigma(observations, rates, CAT_KEYS, CAT_KINDS)
between = compute_between_team_sigma(rates, CAT_KEYS, CAT_KINDS)

print("CATEGORY_SIGMA (existing — should match):")
for c in CAT_KEYS:
    print(f'    "{c}": {sigma[c]:.5f},')

print("\nCATEGORY_BETWEEN_SIGMA (new — paste into matchup.py):")
for c in CAT_KEYS:
    print(f'    "{c}": {between[c]:.5f},')

data["computed_between_sigma"] = {c: between[c] for c in CAT_KEYS}
path.write_text(json.dumps(data, indent=2, sort_keys=True))
print(f"\nFixture updated at {path}")
PY
```

Capture the printed `CATEGORY_BETWEEN_SIGMA` block — we use it in Step 2.

- [ ] **Step 2: Hardcode constants in matchup.py**

Open `backend/analysis/matchup.py`. Locate the existing `CATEGORY_SIGMA` block (around line 48). Immediately after the closing `}`, add:

```python
# σ_between: spread of teams' typical-period totals around the league mean.
# Calibrated from 2025 historical league fixture. Used by empirical Bayes
# shrinkage in the playoff odds simulator.
CATEGORY_BETWEEN_SIGMA: dict[str, float] = {
    # PASTE the values printed by the Step 1 script here (5-decimal precision).
    "R":     <value>,
    "TB":    <value>,
    "RBI":   <value>,
    "SB":    <value>,
    "OBP":   <value>,
    "K":     <value>,
    "QS":    <value>,
    "ERA":   <value>,
    "WHIP":  <value>,
    "SVHD":  <value>,
}
```

(The literal `<value>` placeholders MUST be replaced with the script output — without that the test in Step 3 fails. The values aren't pre-known because they're derived from the live fixture.)

- [ ] **Step 3: Extend the regression test**

In `tests/backend/analysis/test_sigma_calibration.py`, in `TestCalibrationFixtureRegression`:

Change `test_fixture_exists_and_has_expected_shape` to also assert on `computed_between_sigma`:

```python
    def test_fixture_exists_and_has_expected_shape(self):
        fixture = self._load_fixture()
        assert "computed_sigma" in fixture
        assert "computed_between_sigma" in fixture
        assert "records" in fixture
        assert set(fixture["computed_sigma"].keys()) == set(CAT_KEYS)
        assert set(fixture["computed_between_sigma"].keys()) == set(CAT_KEYS)
        assert len(fixture["records"]) > 100
```

Add a new method to recompute and assert on σ_between:

```python
    def test_recomputing_between_sigma_from_fixture_records_matches_stored(self):
        fixture = self._load_fixture()
        records = [
            MatchupRecord(
                team_id=r["team_id"],
                matchup_period_id=r["matchup_period_id"],
                period_days=r["period_days"],
                cats=r["cats"],
            )
            for r in fixture["records"]
        ]
        rates = compute_team_rates_per_day(records)
        from backend.analysis.sigma_calibration import compute_between_team_sigma
        recomputed = compute_between_team_sigma(
            team_rates_per_day=rates,
            cat_keys=CAT_KEYS,
            cat_kinds=CAT_KINDS,
        )
        for cat in CAT_KEYS:
            stored = fixture["computed_between_sigma"][cat]
            assert recomputed[cat] == pytest.approx(stored, rel=1e-6), (
                f"Drift in σ_between_{cat}: stored={stored}, recomputed={recomputed[cat]}"
            )
```

Add a method asserting `matchup.py` matches:

```python
    def test_matchup_between_sigma_constants_match_fixture(self):
        from backend.analysis.matchup import CATEGORY_BETWEEN_SIGMA
        fixture = self._load_fixture()
        for cat in CAT_KEYS:
            assert CATEGORY_BETWEEN_SIGMA[cat] == pytest.approx(
                fixture["computed_between_sigma"][cat], rel=1e-3
            ), (
                f"matchup.py CATEGORY_BETWEEN_SIGMA['{cat}'] = {CATEGORY_BETWEEN_SIGMA[cat]} "
                f"but fixture has {fixture['computed_between_sigma'][cat]}. "
                f"Re-run backend/scripts/calibrate_category_sigma.py and update."
            )
```

- [ ] **Step 4: Run all sigma calibration tests**

Run: `pytest tests/backend/analysis/test_sigma_calibration.py -v`
Expected: PASS (existing + 3 new).

- [ ] **Step 5: Commit**

```bash
git add backend/data/fixtures/sigma_calibration_2025.json backend/analysis/matchup.py tests/backend/analysis/test_sigma_calibration.py
git commit -m "feat(sigma-calibration): freeze 2025 CATEGORY_BETWEEN_SIGMA"
```

---

## Task 7: Pydantic models — observation history + response shrinkage fields

**Files:**
- Modify: `backend/api/playoff_odds_models.py`

Add `ObservedPeriod`, the per-team observation list on `PlayoffOddsRequest`, and the shrinkage-diagnostic fields on `TeamOdds` / `PlayoffOddsResponse`.

- [ ] **Step 1: Modify the models file**

Open `backend/api/playoff_odds_models.py`.

After `MatchupPair`, add:

```python
class ObservedPeriodPayload(BaseModel):
    """One completed matchup period's category totals for one team."""
    team_id: int
    matchup_period_id: int
    period_days: int
    cats: dict[str, float]
```

Modify `PlayoffOddsRequest` to add an optional `observed_history` field at the bottom:

```python
class PlayoffOddsRequest(BaseModel):
    season: int
    teams: list[TeamPayload]
    remaining_schedule: list[MatchupPair]
    period_weights: dict[int, float]
    playoff_slots: int = 6
    n_trials: int = 5000
    seed: Optional[int] = None
    observed_history: list[ObservedPeriodPayload] = []
```

Modify `TeamOdds` to add a per-cat shrinkage-weight dict:

```python
class TeamOdds(BaseModel):
    team_id: int
    team_name: str
    current_wins: int
    current_losses: int
    current_ties: int
    playoff_odds: float
    avg_final_wins: float
    avg_final_losses: float
    avg_final_ties: float
    avg_final_rank: float
    shrinkage_weight: dict[str, float] = {}
```

Modify `PlayoffOddsResponse`:

```python
class PlayoffOddsResponse(BaseModel):
    teams: list[TeamOdds]
    n_trials: int
    matched_player_count: int
    unmatched_player_names: list[str]
    shrinkage_applied: bool = True
    completed_periods_observed: int = 0
```

- [ ] **Step 2: Verify the models import cleanly**

Run:
```bash
python -c "from backend.api.playoff_odds_models import (
    PlayoffOddsRequest, PlayoffOddsResponse, ObservedPeriodPayload, TeamOdds
); print('ok')"
```
Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add backend/api/playoff_odds_models.py
git commit -m "feat(playoff-odds): add observed_history + shrinkage response fields"
```

---

## Task 8: Engine wiring — `ShrinkageContext` and `project_team_period`

**Files:**
- Modify: `backend/analysis/playoff_odds.py`
- Modify: `tests/backend/analysis/test_playoff_odds.py`

A `ShrinkageContext` holds one team's observation list. `project_team_period` gains an optional `shrinkage_ctx` parameter; when present, the per-cat output is the shrunk value. When absent, behavior is unchanged (so other callers of `project_team_period` aren't affected).

- [ ] **Step 1: Write the failing tests**

Append to `tests/backend/analysis/test_playoff_odds.py`:

```python
from backend.analysis.playoff_odds import ShrinkageContext, project_team_period
from backend.analysis.shrinkage import ObservedPeriod


# Match cat kinds the simulator will be using
SHRINK_CAT_KINDS = {
    "R": "count", "TB": "count", "RBI": "count", "SB": "count", "OBP": "rate",
    "K": "count", "QS": "count", "ERA": "rate", "WHIP": "rate", "SVHD": "count",
}


class TestProjectTeamPeriodWithShrinkage:
    def test_shrinkage_ctx_none_gives_identical_output_to_today(self):
        roster = [_hitter(i, f"H{i}") for i in range(1, 8)]
        baseline = project_team_period(roster, period_weight=1.0)
        with_none = project_team_period(roster, period_weight=1.0, shrinkage_ctx=None)
        assert baseline == with_none

    def test_shrinkage_ctx_pulls_count_cat_toward_observed(self):
        # 7 hitters projecting 90 R each → 5 starters * 90 + 2 bench * 90 * 0.25 = 495 R per "full RoS"
        # period_weight=1.0 → 495 R for the period.
        # observation: 100 R over 7 days → typical period total = 100.
        # σ_within = σ_between = 100 (huge), W = 1 → w = 0.5
        # shrunk = 0.5 * 100 + 0.5 * 495 = 297.5
        roster = [_hitter(i, f"H{i}") for i in range(1, 8)]
        ctx = ShrinkageContext(
            observations=[ObservedPeriod(matchup_period_id=1, period_days=7, cats={"R": 100.0})],
            sigma_within={"R": 100.0},
            sigma_between={"R": 100.0},
            cat_kinds=SHRINK_CAT_KINDS,
        )
        result = project_team_period(roster, period_weight=1.0, shrinkage_ctx=ctx)
        assert result["R"] == pytest.approx(297.5)

    def test_shrinkage_ctx_period_days_uses_period_weight_basis(self):
        # period_weight=0.5 maps to a 7-day reference where total_remaining_days assumed.
        # Convention used here: current_period_days = round(period_weight * 14) for a 2-period RoS,
        # but since project_team_period doesn't know period_days, we let the caller pass it.
        # The caller (simulate_one_season) passes period_days explicitly.
        roster = [_hitter(1, "A")]  # 90 R per RoS; period_weight=1.0 → 90 R
        ctx = ShrinkageContext(
            observations=[ObservedPeriod(matchup_period_id=1, period_days=7, cats={"R": 0.0})],
            sigma_within={"R": 1.0},
            sigma_between={"R": 1.0},
            cat_kinds=SHRINK_CAT_KINDS,
        )
        # σ_w = σ_b = 1, W=1 → w = 0.5; observed_typical = 0
        # current_period_days defaults to TYPICAL_PERIOD_DAYS = 7 if not passed
        # projected_typical = 90 / 7 * 7 = 90; shrunk_typical = 0.5*0 + 0.5*90 = 45
        # output back-converted to 7-day period = 45
        result = project_team_period(
            roster, period_weight=1.0, shrinkage_ctx=ctx, current_period_days=7,
        )
        assert result["R"] == pytest.approx(45.0)

    def test_observations_with_no_data_for_a_cat_keep_projection(self):
        roster = [_hitter(1, "A")]
        ctx = ShrinkageContext(
            observations=[ObservedPeriod(matchup_period_id=1, period_days=7, cats={"TB": 50.0})],
            sigma_within={"R": 5.0, "TB": 15.0},
            sigma_between={"R": 5.0, "TB": 15.0},
            cat_kinds=SHRINK_CAT_KINDS,
        )
        result_no_shrink = project_team_period(roster, period_weight=1.0)
        result_with_ctx = project_team_period(
            roster, period_weight=1.0, shrinkage_ctx=ctx, current_period_days=7,
        )
        # R: no observation → unchanged
        assert result_with_ctx["R"] == pytest.approx(result_no_shrink["R"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/backend/analysis/test_playoff_odds.py::TestProjectTeamPeriodWithShrinkage -v`
Expected: FAIL with `ImportError: cannot import name 'ShrinkageContext'`.

- [ ] **Step 3: Implement `ShrinkageContext` + extend `project_team_period`**

Open `backend/analysis/playoff_odds.py`. Add after the existing imports:

```python
from dataclasses import dataclass

from backend.analysis.shrinkage import (
    ObservedPeriod,
    TYPICAL_PERIOD_DAYS,
    apply_shrinkage_to_period,
)


@dataclass
class ShrinkageContext:
    """Per-team shrinkage inputs, built once per simulation request."""
    observations: list[ObservedPeriod]
    sigma_within: dict[str, float]
    sigma_between: dict[str, float]
    cat_kinds: dict[str, str]
    last_weights: dict[str, float] = None  # populated on the most recent apply call

    def __post_init__(self):
        if self.last_weights is None:
            self.last_weights = {}
```

Modify `project_team_period`'s signature and body:

```python
def project_team_period(
    roster: list[PlayerProjection],
    period_weight: float,
    il_mlb_ids: Optional[dict[int, bool]] = None,
    shrinkage_ctx: Optional["ShrinkageContext"] = None,
    current_period_days: int = TYPICAL_PERIOD_DAYS,
) -> dict[str, float]:
    """Project a team's category totals for one matchup period.

    When `shrinkage_ctx` is provided, the per-cat result is replaced by the
    empirical-Bayes-shrunk value blending observed history with the projection.
    """
    il = il_mlb_ids or {}
    active = [p for p in roster if not il.get(p.mlb_id, False)]

    as_dicts = [
        {
            "mlb_id": p.mlb_id,
            "position": p.position,
            "player_type": p.player_type,
            "eligible_positions": p.eligible_positions or p.position,
        }
        for p in active
    ]
    lineup = optimize_daily_lineup(as_dicts)
    starter_ids = {d["mlb_id"] for d in lineup["starters"]}

    totals = TeamTotals()
    for p in active:
        weight = period_weight if p.mlb_id in starter_ids else period_weight * _bench_weight(p)
        totals.add_player(p, weight=weight)

    projected = totals.category_values()
    if shrinkage_ctx is None:
        return projected

    shrunk, weights = apply_shrinkage_to_period(
        projected_period_cats=projected,
        observations=shrinkage_ctx.observations,
        current_period_days=current_period_days,
        sigma_within=shrinkage_ctx.sigma_within,
        sigma_between=shrinkage_ctx.sigma_between,
        cat_kinds=shrinkage_ctx.cat_kinds,
    )
    shrinkage_ctx.last_weights = weights
    return shrunk
```

Note: keep the existing `from typing import Optional` import.

- [ ] **Step 4: Run the tests to verify they pass**

Run:
```bash
pytest tests/backend/analysis/test_playoff_odds.py::TestProjectTeamPeriod \
       tests/backend/analysis/test_playoff_odds.py::TestProjectTeamPeriodWithShrinkage -v
```
Expected: PASS (existing project_team_period tests still pass + new tests pass).

- [ ] **Step 5: Commit**

```bash
git add backend/analysis/playoff_odds.py tests/backend/analysis/test_playoff_odds.py
git commit -m "feat(playoff-odds): ShrinkageContext + project_team_period integration"
```

---

## Task 9: Engine wiring — thread shrinkage through the sim + adapter

**Files:**
- Modify: `backend/analysis/playoff_odds.py`
- Modify: `tests/backend/analysis/test_playoff_odds.py`

`simulate_one_season`, `compute_playoff_odds`, and `compute_playoff_odds_from_request` need to:
1. Accept the per-team shrinkage contexts.
2. Pass `current_period_days` (looked up from a `period_days` map or derived from `period_weights`) to `project_team_period`.
3. Capture the per-team final shrinkage weights for the response.
4. Build per-team `ShrinkageContext` from the request's `observed_history` and the calibrated constants.
5. Surface `shrinkage_applied` and `completed_periods_observed` in the result.

We derive `current_period_days` per period from `period_weights` × `total_remaining_days`. Since we don't have explicit per-period day counts in the existing payload, infer them: `total_remaining_days = sum_of_all_period_weights · 7 / mean_period_weight`. Cleaner: pass `period_days_by_id: dict[int, int]` through the pipeline derived from `period_weights` × an inferred total. To avoid this guesswork, **add an explicit `period_days_by_id` to the payload** in this task; the TS payload builder already has it locally and just needs to surface it.

- [ ] **Step 1: Add `period_days_by_id` to the request model**

Open `backend/api/playoff_odds_models.py`. Modify `PlayoffOddsRequest`:

```python
class PlayoffOddsRequest(BaseModel):
    season: int
    teams: list[TeamPayload]
    remaining_schedule: list[MatchupPair]
    period_weights: dict[int, float]
    period_days_by_id: dict[int, int] = {}  # period_id → days; falls back to TYPICAL_PERIOD_DAYS
    playoff_slots: int = 6
    n_trials: int = 5000
    seed: Optional[int] = None
    observed_history: list[ObservedPeriodPayload] = []
```

- [ ] **Step 2: Write the failing test**

Append to `tests/backend/analysis/test_playoff_odds.py`:

```python
class TestComputePlayoffOddsFromRequestWithShrinkage:
    def test_shrinkage_pulls_overprojected_team_down(self):
        # Mock projections: team 1 has stud projections, team 2 has weak projections.
        # observed_history makes team 1 actually look weak, team 2 actually look stud.
        # With shrinkage, team 1 odds should be << 100% even with playoff_slots=1.
        from unittest.mock import patch
        fake_projections = {
            1001: PlayerProjection(
                mlb_id=1001, name="A", position="OF", player_type="hitter",
                pa=600, r=200, tb=400, rbi=200, sb=20, obp=0.420,
                eligible_positions="OF/UTIL",
            ),
            1002: PlayerProjection(
                mlb_id=1002, name="B", position="OF", player_type="hitter",
                pa=600, r=20, tb=80, rbi=20, sb=2, obp=0.250,
                eligible_positions="OF/UTIL",
            ),
            1003: PlayerProjection(
                mlb_id=1003, name="C", position="SP", player_type="pitcher",
                ip=180, k=200, qs=18, era=2.50, whip=1.00,
                eligible_positions="SP/P",
            ),
            1004: PlayerProjection(
                mlb_id=1004, name="D", position="SP", player_type="pitcher",
                ip=180, k=80, qs=8, era=5.00, whip=1.50,
                eligible_positions="SP/P",
            ),
        }
        with patch("backend.analysis.playoff_odds.resolve_espn_names_to_mlbid") as resolve, \
             patch("backend.analysis.playoff_odds._load_projections") as load_proj:
            # Mock returns name → mlb_id with original casing (matches recent
            # commit 1119971 — lookup is by original ESPN string).
            resolve.return_value = {"A": 1001, "B": 1002, "C": 1003, "D": 1004}
            load_proj.return_value = fake_projections

            # Run twice — once with observed_history, once without — and assert
            # that shrinkage flips the head-to-head odds. This is more robust
            # than asserting an absolute threshold against tuned σ values.
            base_payload = {
                "season": 2026,
                "teams": [
                    {
                        "team_id": 1, "team_name": "T1",
                        "roster": [
                            {"name": "A", "position": "OF", "player_type": "hitter",
                             "lineup_slot_id": 5, "eligible_positions": "OF/UTIL"},
                            {"name": "C", "position": "SP", "player_type": "pitcher",
                             "lineup_slot_id": 14, "eligible_positions": "SP/P"},
                        ],
                        "current_wins": 0, "current_losses": 0, "current_ties": 0,
                    },
                    {
                        "team_id": 2, "team_name": "T2",
                        "roster": [
                            {"name": "B", "position": "OF", "player_type": "hitter",
                             "lineup_slot_id": 5, "eligible_positions": "OF/UTIL"},
                            {"name": "D", "position": "SP", "player_type": "pitcher",
                             "lineup_slot_id": 14, "eligible_positions": "SP/P"},
                        ],
                        "current_wins": 0, "current_losses": 0, "current_ties": 0,
                    },
                ],
                # 4 head-to-head matchups, evenly weighted
                "remaining_schedule": [
                    {"matchup_period_id": p, "home_team_id": 1, "away_team_id": 2}
                    for p in range(1, 5)
                ],
                "period_weights": {1: 0.25, 2: 0.25, 3: 0.25, 4: 0.25},
                "period_days_by_id": {1: 7, 2: 7, 3: 7, 4: 7},
                "playoff_slots": 1,
                "n_trials": 400,
                "seed": 0,
            }

            # Without observation history → team 1 dominates ATC-wise
            result_no_shrink = compute_playoff_odds_from_request({
                **base_payload, "observed_history": []
            })
            t1_no_shrink = next(t for t in result_no_shrink["teams"] if t["team_id"] == 1)

            # With observation history flipping observed strengths
            result_shrunk = compute_playoff_odds_from_request({
                **base_payload,
                "observed_history": [
                    # Team 1 has been WEAK across 5 prior periods
                    *({"team_id": 1, "matchup_period_id": p, "period_days": 7,
                       "cats": {"R": 30, "TB": 80, "RBI": 30, "SB": 2, "OBP": 0.250,
                                "K": 60, "QS": 4, "ERA": 5.50, "WHIP": 1.55, "SVHD": 4}}
                      for p in range(1, 6)),
                    # Team 2 has been STRONG
                    *({"team_id": 2, "matchup_period_id": p, "period_days": 7,
                       "cats": {"R": 110, "TB": 280, "RBI": 110, "SB": 12, "OBP": 0.380,
                                "K": 120, "QS": 12, "ERA": 2.80, "WHIP": 1.05, "SVHD": 8}}
                      for p in range(1, 6)),
                ],
            })
            t1_shrunk = next(t for t in result_shrunk["teams"] if t["team_id"] == 1)

            # Shrinkage must move team 1's odds substantially DOWN — exact threshold
            # depends on calibrated σ ratios, but a 0.20-pt drop is the floor we
            # require to call shrinkage "working."
            assert t1_no_shrink["playoff_odds"] - t1_shrunk["playoff_odds"] > 0.20, (
                f"Expected shrinkage to drop team 1 by ≥0.20 but got "
                f"{t1_no_shrink['playoff_odds']} → {t1_shrunk['playoff_odds']}"
            )
            assert result_shrunk["shrinkage_applied"] is True
            assert result_shrunk["completed_periods_observed"] == 5
            assert result_no_shrink["shrinkage_applied"] is False
            assert result_no_shrink["completed_periods_observed"] == 0
            assert "R" in t1_shrunk["shrinkage_weight"]
            assert t1_shrunk["shrinkage_weight"]["R"] > 0.0

    def test_no_observed_history_keeps_projection_unchanged(self):
        from unittest.mock import patch
        fake_projections = {
            1001: PlayerProjection(
                mlb_id=1001, name="A", position="OF", player_type="hitter",
                pa=600, r=90, tb=270, rbi=80, sb=10, obp=0.330,
                eligible_positions="OF/UTIL",
            ),
        }
        with patch("backend.analysis.playoff_odds.resolve_espn_names_to_mlbid") as resolve, \
             patch("backend.analysis.playoff_odds._load_projections") as load_proj:
            resolve.return_value = {"A": 1001}
            load_proj.return_value = fake_projections

            payload = {
                "season": 2026,
                "teams": [
                    {"team_id": 1, "team_name": "T1",
                     "roster": [{"name": "A", "position": "OF", "player_type": "hitter",
                                 "lineup_slot_id": 5, "eligible_positions": "OF/UTIL"}],
                     "current_wins": 0, "current_losses": 0, "current_ties": 0},
                    {"team_id": 2, "team_name": "T2",
                     "roster": [{"name": "A", "position": "OF", "player_type": "hitter",
                                 "lineup_slot_id": 5, "eligible_positions": "OF/UTIL"}],
                     "current_wins": 0, "current_losses": 0, "current_ties": 0},
                ],
                "remaining_schedule": [
                    {"matchup_period_id": 1, "home_team_id": 1, "away_team_id": 2},
                ],
                "period_weights": {1: 1.0},
                "period_days_by_id": {1: 7},
                "playoff_slots": 1,
                "n_trials": 50,
                "seed": 1,
                "observed_history": [],
            }
            result = compute_playoff_odds_from_request(payload)
            assert result["shrinkage_applied"] is False
            assert result["completed_periods_observed"] == 0
            for t in result["teams"]:
                assert all(w == 0.0 for w in t["shrinkage_weight"].values())
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `pytest tests/backend/analysis/test_playoff_odds.py::TestComputePlayoffOddsFromRequestWithShrinkage -v`
Expected: FAIL — payload extra fields rejected, or `shrinkage_applied` key missing.

- [ ] **Step 4: Wire shrinkage through the sim**

Open `backend/analysis/playoff_odds.py`.

Add to existing imports near the top:

```python
from backend.analysis.matchup import (
    CATEGORY_SIGMA,
    CATEGORY_BETWEEN_SIGMA,
    optimize_daily_lineup,
    _load_projections,
)
```

Define a module-level cat-kinds map (at file top, after imports):

```python
CAT_KINDS: dict[str, str] = {
    "R": "count", "TB": "count", "RBI": "count", "SB": "count", "OBP": "rate",
    "K": "count", "QS": "count", "ERA": "rate", "WHIP": "rate", "SVHD": "count",
}
```

Modify `simulate_one_season`'s signature and body to accept and use shrinkage contexts and per-period day counts:

```python
def simulate_one_season(
    rosters: dict[int, list[PlayerProjection]],
    current_records: dict[int, tuple[int, int, int]],
    remaining_schedule: list[tuple[int, int, int]],
    period_weights: dict[int, float],
    rng: np.random.Generator,
    il_by_team: Optional[dict[int, dict[int, bool]]] = None,
    shrinkage_by_team: Optional[dict[int, "ShrinkageContext"]] = None,
    period_days_by_id: Optional[dict[int, int]] = None,
) -> dict[int, tuple[int, int, int]]:
    il_by_team = il_by_team or {}
    shrinkage_by_team = shrinkage_by_team or {}
    period_days_by_id = period_days_by_id or {}
    final = {tid: list(rec) for tid, rec in current_records.items()}

    period_projections: dict[tuple[int, int], dict[str, float]] = {}

    for period_id, home_id, away_id in remaining_schedule:
        weight = period_weights[period_id]
        days = period_days_by_id.get(period_id, TYPICAL_PERIOD_DAYS)
        for team_id in (home_id, away_id):
            key = (team_id, period_id)
            if key not in period_projections:
                period_projections[key] = project_team_period(
                    roster=rosters[team_id],
                    period_weight=weight,
                    il_mlb_ids=il_by_team.get(team_id),
                    shrinkage_ctx=shrinkage_by_team.get(team_id),
                    current_period_days=days,
                )
        a_cats = period_projections[(home_id, period_id)]
        b_cats = period_projections[(away_id, period_id)]
        a_w, a_l, a_t = simulate_head_to_head(a_cats, b_cats, rng)
        final[home_id][0] += a_w
        final[home_id][1] += a_l
        final[home_id][2] += a_t
        final[away_id][0] += a_l
        final[away_id][1] += a_w
        final[away_id][2] += a_t

    return {tid: tuple(rec) for tid, rec in final.items()}
```

Modify `compute_playoff_odds`'s signature, body, and the per-team result dict:

```python
def compute_playoff_odds(
    rosters: dict[int, list[PlayerProjection]],
    current_records: dict[int, tuple[int, int, int]],
    remaining_schedule: list[tuple[int, int, int]],
    period_weights: dict[int, float],
    playoff_slots: int = 6,
    n_trials: int = 5000,
    seed: Optional[int] = None,
    il_by_team: Optional[dict[int, dict[int, bool]]] = None,
    team_names: Optional[dict[int, str]] = None,
    shrinkage_by_team: Optional[dict[int, "ShrinkageContext"]] = None,
    period_days_by_id: Optional[dict[int, int]] = None,
) -> list[dict]:
    team_ids = list(rosters.keys())
    team_names = team_names or {tid: f"Team {tid}" for tid in team_ids}
    shrinkage_by_team = shrinkage_by_team or {}

    playoff_count = {tid: 0 for tid in team_ids}
    sum_wins = {tid: 0.0 for tid in team_ids}
    sum_losses = {tid: 0.0 for tid in team_ids}
    sum_ties = {tid: 0.0 for tid in team_ids}
    sum_rank = {tid: 0.0 for tid in team_ids}

    rng = np.random.default_rng(seed)

    for _ in range(n_trials):
        finals = simulate_one_season(
            rosters=rosters,
            current_records=current_records,
            remaining_schedule=remaining_schedule,
            period_weights=period_weights,
            rng=rng,
            il_by_team=il_by_team,
            shrinkage_by_team=shrinkage_by_team,
            period_days_by_id=period_days_by_id,
        )
        shuffled = list(team_ids)
        rng.shuffle(shuffled)
        ranked = sorted(
            shuffled,
            key=lambda tid: (-finals[tid][0], -finals[tid][2]),
        )
        for rank, tid in enumerate(ranked, start=1):
            sum_rank[tid] += rank
            if rank <= playoff_slots:
                playoff_count[tid] += 1
            w, l, t = finals[tid]
            sum_wins[tid] += w
            sum_losses[tid] += l
            sum_ties[tid] += t

    out: list[dict] = []
    for tid in team_ids:
        cur_w, cur_l, cur_t = current_records[tid]
        ctx = shrinkage_by_team.get(tid)
        weights = dict(ctx.last_weights) if ctx and ctx.last_weights else {}
        out.append({
            "team_id": tid,
            "team_name": team_names[tid],
            "current_wins": cur_w,
            "current_losses": cur_l,
            "current_ties": cur_t,
            "playoff_odds": playoff_count[tid] / n_trials,
            "avg_final_wins": sum_wins[tid] / n_trials,
            "avg_final_losses": sum_losses[tid] / n_trials,
            "avg_final_ties": sum_ties[tid] / n_trials,
            "avg_final_rank": sum_rank[tid] / n_trials,
            "shrinkage_weight": weights,
        })
    out.sort(key=lambda r: -r["playoff_odds"])
    return out
```

Modify `compute_playoff_odds_from_request` to build `ShrinkageContext` per team and surface diagnostics:

```python
def compute_playoff_odds_from_request(payload: dict) -> dict:
    season = payload["season"]
    teams = payload["teams"]
    observed_history = payload.get("observed_history", []) or []

    all_roster_dicts: list[dict] = []
    for t in teams:
        for p in t["roster"]:
            all_roster_dicts.append({
                "name": p["name"],
                "player_type": p.get("player_type", "hitter"),
            })

    name_to_id = resolve_espn_names_to_mlbid(all_roster_dicts, season=season)
    matched_ids = list(set(name_to_id.values()))
    projections = _load_projections(matched_ids, season=season)

    rosters: dict[int, list[PlayerProjection]] = {}
    il_by_team: dict[int, dict[int, bool]] = {}
    current_records: dict[int, tuple[int, int, int]] = {}
    team_names: dict[int, str] = {}
    unmatched_names: set[str] = set()
    matched_count = 0

    for t in teams:
        tid = t["team_id"]
        team_names[tid] = t["team_name"]
        current_records[tid] = (
            t.get("current_wins", 0),
            t.get("current_losses", 0),
            t.get("current_ties", 0),
        )
        rosters[tid] = []
        il_by_team[tid] = {}
        for p in t["roster"]:
            mlb_id = name_to_id.get(p["name"])
            if mlb_id is None or mlb_id not in projections:
                unmatched_names.add(p["name"])
                continue
            proj = projections[mlb_id]
            proj_with_elig = PlayerProjection(
                mlb_id=proj.mlb_id, name=proj.name, position=proj.position,
                player_type=proj.player_type,
                pa=proj.pa, r=proj.r, tb=proj.tb, rbi=proj.rbi, sb=proj.sb,
                obp=proj.obp, ip=proj.ip, k=proj.k, qs=proj.qs, era=proj.era,
                whip=proj.whip, svhd=proj.svhd,
                eligible_positions=p.get("eligible_positions") or proj.eligible_positions or proj.position,
                overall_rank=proj.overall_rank,
            )
            rosters[tid].append(proj_with_elig)
            matched_count += 1
            if p.get("lineup_slot_id", 0) >= IL_LINEUP_SLOT_MIN:
                il_by_team[tid][mlb_id] = True

    schedule = [
        (m["matchup_period_id"], m["home_team_id"], m["away_team_id"])
        for m in payload["remaining_schedule"]
    ]
    period_weights = {int(k): float(v) for k, v in payload["period_weights"].items()}
    period_days_by_id = {
        int(k): int(v) for k, v in (payload.get("period_days_by_id") or {}).items()
    }

    # Build per-team ShrinkageContext from observed_history
    obs_by_team: dict[int, list[ObservedPeriod]] = {tid: [] for tid in rosters}
    for o in observed_history:
        tid = o["team_id"]
        if tid not in obs_by_team:
            continue
        obs_by_team[tid].append(ObservedPeriod(
            matchup_period_id=o["matchup_period_id"],
            period_days=o["period_days"],
            cats=dict(o["cats"]),
        ))

    shrinkage_applied = any(len(v) > 0 for v in obs_by_team.values())
    shrinkage_by_team: dict[int, ShrinkageContext] = {}
    for tid, obs in obs_by_team.items():
        shrinkage_by_team[tid] = ShrinkageContext(
            observations=obs,
            sigma_within=dict(CATEGORY_SIGMA),
            sigma_between=dict(CATEGORY_BETWEEN_SIGMA),
            cat_kinds=dict(CAT_KINDS),
        )

    completed_periods_observed = max(
        (len(v) for v in obs_by_team.values()), default=0,
    )

    teams_out = compute_playoff_odds(
        rosters=rosters,
        current_records=current_records,
        remaining_schedule=schedule,
        period_weights=period_weights,
        playoff_slots=payload.get("playoff_slots", 6),
        n_trials=payload.get("n_trials", 5000),
        seed=payload.get("seed"),
        il_by_team=il_by_team,
        team_names=team_names,
        shrinkage_by_team=shrinkage_by_team,
        period_days_by_id=period_days_by_id,
    )

    return {
        "teams": teams_out,
        "n_trials": payload.get("n_trials", 5000),
        "matched_player_count": matched_count,
        "unmatched_player_names": sorted(unmatched_names),
        "shrinkage_applied": shrinkage_applied,
        "completed_periods_observed": completed_periods_observed,
    }
```

- [ ] **Step 5: Run all playoff_odds tests**

Run: `pytest tests/backend/analysis/test_playoff_odds.py -v`
Expected: PASS (existing + new shrinkage tests).

- [ ] **Step 6: Commit**

```bash
git add backend/analysis/playoff_odds.py tests/backend/analysis/test_playoff_odds.py backend/api/playoff_odds_models.py
git commit -m "feat(playoff-odds): empirical Bayes shrinkage in the sim engine"
```

---

## Task 10: TS — `getMatchupHistory` in `espn-api.ts`

**Files:**
- Modify: `src/lib/espn-api.ts`
- Modify: `src/__tests__/lib/espn-api.test.ts`

A new static method on `ESPNApi` that hits the same `view=mMatchup` endpoint the Python history fetcher uses, returning per-team per-period cat totals only for completed periods (i.e. those whose `cumulativeScore.scoreByStat` is populated).

The ESPN stat-id → cat mapping mirrors `backend/data/espn_history.py`.

- [ ] **Step 1: Write the failing test**

Append to `src/__tests__/lib/espn-api.test.ts`:

```typescript
describe('ESPNApi.getMatchupHistory', () => {
  it('returns one record per team per completed period', async () => {
    const fakeResponse = {
      schedule: [
        {
          matchupPeriodId: 1,
          home: {
            teamId: 1,
            cumulativeScore: { scoreByStat: { '20': { score: 70 }, '8': { score: 200 } } },
            pointsByScoringPeriod: { '1': 10, '2': 15, '3': 12, '4': 8, '5': 11, '6': 7, '7': 9 },
          },
          away: {
            teamId: 2,
            cumulativeScore: { scoreByStat: { '20': { score: 60 }, '8': { score: 180 } } },
            pointsByScoringPeriod: { '1': 8, '2': 9, '3': 10, '4': 7, '5': 11, '6': 8, '7': 7 },
          },
        },
        {
          matchupPeriodId: 2,
          home: {
            teamId: 1,
            // No cumulativeScore.scoreByStat → in-progress, skip
            pointsByScoringPeriod: {},
          },
          away: {
            teamId: 2,
            pointsByScoringPeriod: {},
          },
        },
      ],
    }
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => fakeResponse,
    }) as any

    const result = await ESPNApi.getMatchupHistory('77166', '2026', {
      swid: 'S', espn_s2: 'E',
    })

    expect(result).toHaveLength(2)
    const t1 = result.find(r => r.team_id === 1 && r.matchup_period_id === 1)!
    expect(t1.period_days).toBe(7)
    expect(t1.cats.R).toBe(70)
    expect(t1.cats.TB).toBe(200)
    const t2 = result.find(r => r.team_id === 2)!
    expect(t2.cats.R).toBe(60)
  })

  it('skips matchups missing scoreByStat', async () => {
    const fakeResponse = {
      schedule: [
        {
          matchupPeriodId: 5,
          home: { teamId: 1, pointsByScoringPeriod: {} },
          away: { teamId: 2, pointsByScoringPeriod: {} },
        },
      ],
    }
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => fakeResponse,
    }) as any

    const result = await ESPNApi.getMatchupHistory('77166', '2026', {
      swid: 'S', espn_s2: 'E',
    })
    expect(result).toHaveLength(0)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx jest src/__tests__/lib/espn-api.test.ts -t getMatchupHistory`
Expected: FAIL with "ESPNApi.getMatchupHistory is not a function".

- [ ] **Step 3: Implement `getMatchupHistory`**

Open `src/lib/espn-api.ts`. Add to the `ESPNApi` class, after `getFullSchedule`:

```typescript
  /**
   * Fetch all completed matchup periods' category totals per team. Used for
   * empirical Bayes shrinkage in the playoff odds simulator. Skips any matchup
   * that lacks `cumulativeScore.scoreByStat` (future or in-progress).
   */
  static async getMatchupHistory(
    leagueId: string,
    season: string,
    settings: ESPNLeagueSettings,
  ): Promise<Array<{
    team_id: number
    matchup_period_id: number
    period_days: number
    cats: Record<string, number>
  }>> {
    const url = `https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb/seasons/${season}/segments/0/leagues/${leagueId}?view=mMatchup&scoringPeriodId=7`

    const response = await fetch(url, { headers: this.getHeaders(settings) })
    if (!response.ok) {
      throw new Error(`ESPN API error: ${response.status} - ${response.statusText}`)
    }

    const data = await response.json()
    const ESPN_STAT_ID_TO_CAT: Record<string, string> = {
      '20': 'R', '8': 'TB', '21': 'RBI', '23': 'SB', '17': 'OBP',
      '48': 'K', '63': 'QS', '47': 'ERA', '41': 'WHIP', '83': 'SVHD',
    }

    const out: Array<{
      team_id: number
      matchup_period_id: number
      period_days: number
      cats: Record<string, number>
    }> = []

    for (const m of data.schedule || []) {
      const periodId = m.matchupPeriodId
      if (periodId == null) continue
      for (const sideKey of ['home', 'away'] as const) {
        const side = m[sideKey]
        if (!side) continue
        const scoreByStat = side.cumulativeScore?.scoreByStat
        if (!scoreByStat) continue
        const cats: Record<string, number> = {}
        for (const [statId, catName] of Object.entries(ESPN_STAT_ID_TO_CAT)) {
          const obj = scoreByStat[statId]
          if (obj && typeof obj.score === 'number') {
            cats[catName] = obj.score
          }
        }
        const periodDays = Object.keys(side.pointsByScoringPeriod || {}).length
        out.push({
          team_id: side.teamId,
          matchup_period_id: periodId,
          period_days: periodDays,
          cats,
        })
      }
    }
    return out
  }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx jest src/__tests__/lib/espn-api.test.ts -t getMatchupHistory`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/lib/espn-api.ts src/__tests__/lib/espn-api.test.ts
git commit -m "feat(playoff-odds): ESPN matchup history fetcher"
```

---

## Task 11: TS — payload builder includes `observed_history` and `period_days_by_id`

**Files:**
- Modify: `src/lib/playoff-odds-payload.ts`
- Modify: `src/__tests__/lib/playoff-odds-payload.test.ts`

`buildPlayoffOddsPayload` accepts `observedHistory` (returned by `getMatchupHistory`) and `matchupSchedule` (already accepted) and emits both `observed_history` and `period_days_by_id` in the payload.

- [ ] **Step 1: Write the failing test**

Append to `src/__tests__/lib/playoff-odds-payload.test.ts`, inside the existing `describe('buildPlayoffOddsPayload', ...)` block (or a new describe block):

```typescript
describe('buildPlayoffOddsPayload with observed history', () => {
  const teams = [
    { id: 1, name: 'T1', record: { overall: { wins: 10, losses: 5, ties: 0 } } },
    { id: 2, name: 'T2', record: { overall: { wins: 5, losses: 10, ties: 0 } } },
  ] as any
  const rosters = { 1: [], 2: [] } as any
  const fullSchedule = [
    { matchupPeriodId: 2, home: { teamId: 1 }, away: { teamId: 2 } },
    { matchupPeriodId: 3, home: { teamId: 2 }, away: { teamId: 1 } },
  ]

  it('emits observed_history filtered to completed periods preceding currentMatchupPeriod', () => {
    const observedHistory = [
      { team_id: 1, matchup_period_id: 1, period_days: 7,
        cats: { R: 70, TB: 200, RBI: 70, SB: 5, OBP: 0.330,
                K: 60, QS: 6, ERA: 3.50, WHIP: 1.20, SVHD: 5 } },
      { team_id: 2, matchup_period_id: 1, period_days: 7,
        cats: { R: 50, TB: 150, RBI: 50, SB: 3, OBP: 0.300,
                K: 40, QS: 4, ERA: 4.20, WHIP: 1.35, SVHD: 3 } },
      // matchup_period_id 2 is the CURRENT period — should NOT be in observed_history
      { team_id: 1, matchup_period_id: 2, period_days: 7,
        cats: { R: 30, TB: 70 } },
    ]

    const payload = buildPlayoffOddsPayload({
      season: 2026,
      currentMatchupPeriod: 2,
      finalRegularSeasonPeriod: 3,
      teams,
      rosters,
      fullSchedule,
      matchupSchedule: {
        2: ['2026-04-06', '2026-04-12'],
        3: ['2026-04-13', '2026-04-19'],
      },
      observedHistory,
      playoffSlots: 1,
      nTrials: 100,
    })

    expect(payload.observed_history).toHaveLength(2)
    const ids = payload.observed_history.map((o: any) => o.matchup_period_id)
    expect(ids).toEqual([1, 1])
    expect(payload.period_days_by_id).toEqual({ '2': 7, '3': 7 })
  })

  it('omits observed_history entirely when none provided', () => {
    const payload = buildPlayoffOddsPayload({
      season: 2026,
      currentMatchupPeriod: 2,
      finalRegularSeasonPeriod: 3,
      teams,
      rosters,
      fullSchedule,
      matchupSchedule: { 2: ['2026-04-06', '2026-04-12'], 3: ['2026-04-13', '2026-04-19'] },
      playoffSlots: 1,
      nTrials: 100,
    })
    expect(payload.observed_history).toEqual([])
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx jest src/__tests__/lib/playoff-odds-payload.test.ts -t observed`
Expected: FAIL — `observed_history` undefined or builder rejects extra args.

- [ ] **Step 3: Modify `buildPlayoffOddsPayload`**

Open `src/lib/playoff-odds-payload.ts`. Add an export and an interface field:

```typescript
export interface ObservedPeriodPayload {
  team_id: number
  matchup_period_id: number
  period_days: number
  cats: Record<string, number>
}

interface BuildArgs {
  season: number
  currentMatchupPeriod: number
  finalRegularSeasonPeriod: number
  teams: ESPNTeam[]
  rosters: Record<number, ESPNRosterEntry[]>
  fullSchedule: Array<{
    matchupPeriodId: number
    home: { teamId: number }
    away: { teamId: number }
  }>
  matchupSchedule: Record<number, [string, string]>
  observedHistory?: ObservedPeriodPayload[]
  playoffSlots: number
  nTrials: number
  seed?: number
}
```

Modify the body to (a) filter observed history to periods strictly before `currentMatchupPeriod` and (b) emit `period_days_by_id`. Replace the existing `return { ... }` block:

```typescript
  // Filter observed history to fully-completed prior periods only
  const completedHistory = (args.observedHistory || []).filter(
    o => o.matchup_period_id < args.currentMatchupPeriod,
  )

  // Build period_days_by_id from matchupSchedule for the remaining periods
  const period_days_by_id: Record<number, number> = {}
  for (const id of periodIds) {
    const range = args.matchupSchedule[id]
    if (range) {
      period_days_by_id[id] = daysBetweenInclusive(range[0], range[1])
    }
  }

  return {
    season: args.season,
    teams: teamsOut,
    remaining_schedule: remaining.map(m => ({
      matchup_period_id: m.matchupPeriodId,
      home_team_id: m.home.teamId,
      away_team_id: m.away.teamId,
    })),
    period_weights: Object.fromEntries(
      Object.entries(period_weights).map(([k, v]) => [String(k), v]),
    ),
    period_days_by_id: Object.fromEntries(
      Object.entries(period_days_by_id).map(([k, v]) => [String(k), v]),
    ),
    observed_history: completedHistory,
    playoff_slots: args.playoffSlots,
    n_trials: args.nTrials,
    seed: args.seed,
  }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx jest src/__tests__/lib/playoff-odds-payload.test.ts`
Expected: PASS (existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add src/lib/playoff-odds-payload.ts src/__tests__/lib/playoff-odds-payload.test.ts
git commit -m "feat(playoff-odds): payload includes observed_history + period_days_by_id"
```

---

## Task 12: Next.js route fetches history with fallback

**Files:**
- Modify: `src/app/api/playoff-odds/route.ts`

Add `getMatchupHistory` to the parallel fetch. On failure (network error, ESPN 5xx), log + proceed with empty `observedHistory` and surface `meta.shrinkage_applied: false`. On success, pass the history through; preserve existing `meta` fields and merge backend-provided `shrinkage_applied` / `completed_periods_observed`.

- [ ] **Step 1: Modify the route**

Open `src/app/api/playoff-odds/route.ts`. Replace the `Promise.all([...])` block and the body that follows it through the `NextResponse.json({ ...result, meta: ... })` return:

```typescript
    const fetches = await Promise.allSettled([
      ESPNApi.getLeague(league.externalId, season, espnSettings),
      ESPNApi.getLeagueTeamsAndFaab(league.externalId, season, espnSettings),
      ESPNApi.getRosters(league.externalId, season, espnSettings),
      ESPNApi.getFullSchedule(league.externalId, season, espnSettings),
      ESPNApi.getMatchupHistory(league.externalId, season, espnSettings),
    ])

    // Required fetches (the first four) — bail if any failed
    const [leagueRes, teamsRes, rostersRes, fullScheduleRes, historyRes] = fetches
    if (leagueRes.status !== 'fulfilled' || teamsRes.status !== 'fulfilled'
        || rostersRes.status !== 'fulfilled' || fullScheduleRes.status !== 'fulfilled') {
      const failed = [leagueRes, teamsRes, rostersRes, fullScheduleRes]
        .find(r => r.status === 'rejected') as PromiseRejectedResult | undefined
      throw failed?.reason ?? new Error('Failed to fetch ESPN league data')
    }
    const leagueData = leagueRes.value
    const teamsAndFaab = teamsRes.value
    const rosters = rostersRes.value
    const fullSchedule = fullScheduleRes.value

    // Optional fetch — degrade gracefully if it fails
    let observedHistory: Awaited<ReturnType<typeof ESPNApi.getMatchupHistory>> = []
    let historyFetchOk = true
    if (historyRes.status === 'fulfilled') {
      observedHistory = historyRes.value
    } else {
      historyFetchOk = false
      console.warn('Playoff-odds: matchup history fetch failed, proceeding without shrinkage:', historyRes.reason)
    }

    const currentMatchupPeriod = leagueData.status?.currentMatchupPeriod
      || leagueData.currentMatchupPeriod
      || 1
    const finalRegularSeasonPeriod =
      (leagueData as any).settings?.scheduleSettings?.matchupPeriodCount
      ?? settingsBlob?.scheduleSettings?.matchupPeriodCount
      ?? 18

    const payload = buildPlayoffOddsPayload({
      season: parseInt(season),
      currentMatchupPeriod,
      finalRegularSeasonPeriod,
      teams: teamsAndFaab.teams,
      rosters,
      fullSchedule,
      matchupSchedule: MATCHUP_SCHEDULE,
      observedHistory,
      playoffSlots,
      nTrials,
      seed,
    })

    const backendResponse = await fetch(`${BACKEND_URL}/api/playoff-odds`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (!backendResponse.ok) {
      const errorText = await backendResponse.text()
      console.error('Playoff-odds backend error:', errorText)
      return NextResponse.json(
        { error: `Backend error: ${backendResponse.status}` },
        { status: 502 },
      )
    }
    const result = await backendResponse.json()
    return NextResponse.json({
      ...result,
      // If our TS-side fetch failed, override the backend's shrinkage_applied=false
      // anyway. If it succeeded but backend reports false (e.g. zero observations),
      // pass that through.
      shrinkage_applied: historyFetchOk && (result.shrinkage_applied ?? false),
      meta: {
        current_matchup_period: currentMatchupPeriod,
        final_regular_season_period: finalRegularSeasonPeriod,
        playoff_slots: playoffSlots,
        n_trials: nTrials,
        shrinkage_applied: historyFetchOk && (result.shrinkage_applied ?? false),
        completed_periods_observed: result.completed_periods_observed ?? 0,
        history_fetch_ok: historyFetchOk,
      },
    })
```

- [ ] **Step 2: Verify the route compiles**

Run: `npx tsc --noEmit -p tsconfig.json`
Expected: no errors related to `src/app/api/playoff-odds/route.ts` (pre-existing errors elsewhere acceptable).

- [ ] **Step 3: Commit**

```bash
git add src/app/api/playoff-odds/route.ts
git commit -m "feat(playoff-odds): fetch matchup history with graceful fallback"
```

---

## Task 13: End-to-end smoke test

**Files:** none (manual verification)

- [ ] **Step 1: Start backend and frontend**

In two terminals:
```bash
# Terminal 1
cd backend && uvicorn api.main:app --reload --port 8000
# Terminal 2
npm run dev
```

- [ ] **Step 2: Run the simulator pre-shrinkage state for comparison**

If you can, save a snapshot of the previous run's playoff odds (the pathological one). If not, note the relative team rankings you remember.

- [ ] **Step 3: Visit `/playoff-odds` and run a 1000-trial simulation**

Open `http://localhost:3000/playoff-odds`. Click Run.

Expected behavior:
- Last-place team's playoff odds should drop substantially compared to the pre-shrinkage run (this is the whole point — quantitative target depends on how badly the team has been performing).
- Top-team odds should also moderate somewhat (top teams overperforming ATC will be pulled down too).
- The response (visible via DevTools Network tab) should include `shrinkage_applied: true` and `completed_periods_observed` matching the number of completed matchup periods.
- Each team should have non-zero `shrinkage_weight` for at least the count cats (R, TB, RBI, SB, K, QS, SVHD). For early-season runs with W=4 and the calibrated σ ratios, expect weights in roughly the 0.1–0.6 range.

- [ ] **Step 4: Verify the fallback path**

Temporarily break the history fetch by modifying the URL in `getMatchupHistory` to a 404-producing path. Re-run the simulation. Expected:
- Request succeeds.
- Response shows `shrinkage_applied: false`, `completed_periods_observed: 0`.
- Each team's `shrinkage_weight` dict is empty or all zeros.
- Standings match pre-shrinkage behavior (the pathological numbers).

Revert the URL change.

- [ ] **Step 5: Re-run with 5000 trials to confirm consistency**

The shrunk odds should not change by more than ~1pt vs the 1000-trial run. If they do, variance assumption violated → investigate.

- [ ] **Step 6: Capture before/after numbers in the final commit**

If any final fix was needed during smoke-testing, commit it with the before/after team-by-team odds in the body (no code changes? no commit needed). Otherwise we're done.

---

## Self-Review Notes

**Spec coverage check:**
- σ_within reuse → Task 8 (CATEGORY_SIGMA imported in compute_playoff_odds_from_request)
- σ_between calibration → Tasks 4, 5, 6
- Pure shrinkage math → Tasks 1, 2, 3
- Observed-mean computation (count + rate) → Tasks 2, 3
- Engine integration (project_team_period, simulate_one_season, compute_playoff_odds, _from_request) → Tasks 8, 9
- Pydantic models (ObservedPeriod, response fields) → Tasks 7, 9
- TS history fetch → Task 10
- Payload builder extension → Task 11
- Next.js route + fallback → Task 12
- Diagnostics surfaced (shrinkage_weight, completed_periods_observed, shrinkage_applied) → Tasks 7, 9, 12
- End-to-end verification → Task 13

**Type consistency check:**
- `ShrinkageContext` defined in playoff_odds.py (Task 8); used by `simulate_one_season` and `compute_playoff_odds` (Task 9). Consistent.
- `ObservedPeriod` (Python dataclass in shrinkage.py, Task 2) ↔ `ObservedPeriodPayload` (Pydantic in playoff_odds_models.py, Task 7) ↔ `ObservedPeriodPayload` (TS interface in playoff-odds-payload.ts, Task 11) all share the same field names: `team_id` (skipped on the dataclass since it's grouped per-team there), `matchup_period_id`, `period_days`, `cats`. Adapter in Task 9 handles the team grouping.
- `apply_shrinkage_to_period` returns `(dict, dict)` — used in Task 8 to populate `ctx.last_weights`. Consistent.
- `period_days_by_id` is `dict[int, int]` Python and `Record<string, number>` TS; conversion done in Task 9 adapter via `int(k)`.
- `CATEGORY_BETWEEN_SIGMA` (Task 6) imported in Task 9. Spelling consistent throughout.

**Placeholder scan:** Task 6 Step 2 contains literal `<value>` placeholders. This is intentional and the only one — values come from running the script in Step 1 and pasting into the constants block. The plan explicitly notes this; the test in Step 3 will fail if the user forgets to replace the placeholders.
