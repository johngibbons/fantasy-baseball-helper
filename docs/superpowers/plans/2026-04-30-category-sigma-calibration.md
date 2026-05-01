# Category Sigma Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the eyeballed `CATEGORY_SIGMA` constants in `backend/analysis/matchup.py` with values backtested against the league's complete 2025 weekly H2H season — improving win-probability accuracy in both the matchup projections page and the playoff odds simulator.

**Architecture:** A one-shot Python calibration script pulls every 2025 matchup period from ESPN, computes per-team weekly category residuals against each team's season-average rate, and produces calibrated `σ` values. Results are persisted as a JSON fixture for reproducibility, and `CATEGORY_SIGMA` is updated with provenance comments. A unit test pins the math against the fixture so future drift is caught.

**Tech Stack:** Python 3.9+, pytest, `requests` (or `urllib`), the existing `backend/database.py` connection abstraction.

**Spec:** This plan; no separate spec doc.

**Why this matters (read before implementing):**
- `CATEGORY_SIGMA` is used in two production paths:
  - `backend/analysis/matchup.py::compute_win_probability` — sigmoid for the current week's per-cat win probability (matchup projections page)
  - `backend/analysis/playoff_odds.py::simulate_head_to_head` — Gaussian noise added to each team's projection in the Monte Carlo simulator (playoff odds page)
- Current values were eyeballed, never validated. They're likely too tight, which makes both features overconfident. Recent observation: the playoff odds page reports >97% confidence for an early-season last-place team to make playoffs — the σ being too tight is one of three likely contributors.

---

## v1 Scope (intentional simplifications, do NOT auto-expand)

- **Single league, single season.** The 2025 ESPN league `77166` has 21 matchup periods × ~5 matchups × 10 teams = ~210 team-weeks per cat. That's small but tractable for a single calibrated number per cat.
- **Pool σ across all teams.** v1 uses one σ per cat for all teams. Real teams have heteroskedastic noise (high-mean teams have higher absolute σ); if we want to address that, it's a v2 follow-up via a multiplicative scale.
- **Filter to typical-length matchup periods.** The 2025 season had period 1 ≈ 12 days and period 15 ≈ 14 days (All-Star). Variance scales with sample size, so mixing periods of different lengths inflates σ. v1: filter to periods of 5–9 days inclusive.
- **Treat team season rate as the "projection" for residuals.** We don't have historical ATC RoS DC snapshots from mid-2025. The cleanest proxy is to assume a team's true skill = its full-season-realized rate, and measure noise as deviations from that. This systematically underestimates noise (because some weekly variance reflects skill-vs-projection error, which we're folding into "skill") but it's the right proxy given our data.
- **Don't refresh CATEGORY_SIGMA in CI.** The fixture is committed; calibration runs on demand via the script, not automatically.

---

## File Structure

**New files:**
- `backend/analysis/sigma_calibration.py` — pure math: `compute_category_sigma(team_period_observations, team_season_rates, cat_keys) -> dict[str, float]`
- `backend/scripts/__init__.py` — empty, to make `backend/scripts/` a package
- `backend/scripts/calibrate_category_sigma.py` — orchestrator: fetch ESPN data, call calibration, print results, write fixture
- `backend/data/fixtures/__init__.py` — empty
- `backend/data/fixtures/sigma_calibration_2025.json` — committed fixture: raw team-period observations + computed σ values
- `tests/backend/analysis/test_sigma_calibration.py` — unit tests (synthetic data) + fixture-pinned regression test

**Modified files:**
- `backend/analysis/matchup.py:42-45` — replace `CATEGORY_SIGMA` constants, add provenance comment

---

## Task 1: Pure math function (synthetic-data TDD)

**Files:**
- Create: `backend/analysis/sigma_calibration.py`
- Test: `tests/backend/analysis/test_sigma_calibration.py`

The math is: given a list of `(team_id, period_id, period_days, observed_value)` tuples per cat, plus a `team_season_rate_per_day[team_id][cat]` map (units per day), compute residuals as `observed - rate * period_days` and return `σ_cat = stddev(residuals)` for count stats. For rate stats (OBP, ERA, WHIP), `season_rate` IS the per-day rate (rates don't scale with time), so residual = `observed_rate - season_rate`, and `σ = stddev(residuals)`.

Caller decides count-vs-rate per cat and passes appropriate `season_rates`.

- [ ] **Step 1: Write the failing test**

Create `tests/backend/analysis/test_sigma_calibration.py`:

```python
"""Tests for category sigma calibration math."""

from __future__ import annotations

import math
import random
import pytest

from backend.analysis.sigma_calibration import (
    compute_category_sigma,
    CountStatObservation,
)


class TestComputeCategorySigma:
    def test_recovers_known_sigma_for_count_stat(self):
        """Generate synthetic data with a known σ; verify it's recovered within tolerance."""
        rng = random.Random(42)
        true_sigma = 5.0
        team_rate_per_day = {1: {"R": 10.0}, 2: {"R": 8.0}}
        observations = []
        for team_id in (1, 2):
            for period_id in range(1, 21):
                period_days = 7
                expected = team_rate_per_day[team_id]["R"] * period_days
                observed = expected + rng.gauss(0.0, true_sigma)
                observations.append(CountStatObservation(
                    team_id=team_id, period_id=period_id, period_days=period_days,
                    cat="R", observed=observed,
                ))

        result = compute_category_sigma(
            observations=observations,
            team_rates_per_day=team_rate_per_day,
            cat_keys=["R"],
            cat_kinds={"R": "count"},
        )

        # With 40 samples and N(0, 5) noise, sample stddev should be within ~25% of 5.0
        assert math.isclose(result["R"], true_sigma, rel_tol=0.25)

    def test_rate_stat_residual_is_observed_minus_rate(self):
        """For rate stats (OBP), residual is observed_rate - season_rate (no period_days scaling)."""
        rng = random.Random(7)
        true_sigma = 0.020
        team_rate_per_day = {1: {"OBP": 0.330}, 2: {"OBP": 0.300}}
        observations = []
        for team_id in (1, 2):
            for period_id in range(1, 21):
                expected = team_rate_per_day[team_id]["OBP"]
                observed = expected + rng.gauss(0.0, true_sigma)
                observations.append(CountStatObservation(
                    team_id=team_id, period_id=period_id, period_days=7,
                    cat="OBP", observed=observed,
                ))

        result = compute_category_sigma(
            observations=observations,
            team_rates_per_day=team_rate_per_day,
            cat_keys=["OBP"],
            cat_kinds={"OBP": "rate"},
        )
        assert math.isclose(result["OBP"], true_sigma, rel_tol=0.30)

    def test_returns_zero_for_cat_with_no_observations(self):
        result = compute_category_sigma(
            observations=[],
            team_rates_per_day={},
            cat_keys=["R", "TB"],
            cat_kinds={"R": "count", "TB": "count"},
        )
        assert result == {"R": 0.0, "TB": 0.0}

    def test_handles_multiple_cats_independently(self):
        """Different cats should produce different σ values when noise differs."""
        rng = random.Random(99)
        team_rates = {1: {"R": 10.0, "TB": 30.0}}
        observations = []
        for period_id in range(1, 41):
            observations.append(CountStatObservation(
                team_id=1, period_id=period_id, period_days=7, cat="R",
                observed=10.0 * 7 + rng.gauss(0.0, 5.0),
            ))
            observations.append(CountStatObservation(
                team_id=1, period_id=period_id, period_days=7, cat="TB",
                observed=30.0 * 7 + rng.gauss(0.0, 15.0),
            ))

        result = compute_category_sigma(
            observations=observations,
            team_rates_per_day=team_rates,
            cat_keys=["R", "TB"],
            cat_kinds={"R": "count", "TB": "count"},
        )
        # σ_TB should be ~3x σ_R (15 vs 5)
        assert result["TB"] / result["R"] > 2.0
        assert result["TB"] / result["R"] < 4.0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/jgibbons/code/fantasy-baseball-helper && python3 -m pytest tests/backend/analysis/test_sigma_calibration.py::TestComputeCategorySigma -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.analysis.sigma_calibration'`.

- [ ] **Step 3: Implement `compute_category_sigma`**

Create `backend/analysis/sigma_calibration.py`:

```python
"""Category sigma calibration: pure math.

Computes per-category σ values from historical team-period observations.
For count stats (R, TB, K, etc): σ is the stddev of (observed - rate * period_days).
For rate stats (OBP, ERA, WHIP): σ is the stddev of (observed - season_rate).
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class CountStatObservation:
    """One team's observed value for one category over one matchup period."""
    team_id: int
    period_id: int
    period_days: int
    cat: str
    observed: float


def _stddev(values: list[float]) -> float:
    """Sample standard deviation. Returns 0.0 for fewer than 2 values."""
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return math.sqrt(var)


def compute_category_sigma(
    observations: list[CountStatObservation],
    team_rates_per_day: dict[int, dict[str, float]],
    cat_keys: list[str],
    cat_kinds: dict[str, str],
) -> dict[str, float]:
    """Compute calibrated σ per category.

    Args:
        observations: All team-period observations (across teams, periods, cats).
        team_rates_per_day: team_id → cat → per-day rate. For count stats this is
            (season_total / total_season_days). For rate stats this is the season rate.
        cat_keys: Categories to calibrate (e.g. ["R", "TB", "OBP", ...]).
        cat_kinds: cat → "count" or "rate". Determines residual formula.

    Returns:
        cat → σ. Cats with no observations get 0.0.
    """
    residuals_by_cat: dict[str, list[float]] = {cat: [] for cat in cat_keys}

    for obs in observations:
        if obs.cat not in residuals_by_cat:
            continue
        rate = team_rates_per_day.get(obs.team_id, {}).get(obs.cat, 0.0)
        kind = cat_kinds.get(obs.cat, "count")
        if kind == "count":
            expected = rate * obs.period_days
        else:  # rate
            expected = rate
        residuals_by_cat[obs.cat].append(obs.observed - expected)

    return {cat: _stddev(residuals_by_cat[cat]) for cat in cat_keys}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /Users/jgibbons/code/fantasy-baseball-helper && python3 -m pytest tests/backend/analysis/test_sigma_calibration.py::TestComputeCategorySigma -v`
Expected: PASS (all 4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/analysis/sigma_calibration.py tests/backend/analysis/test_sigma_calibration.py
git commit -m "feat(sigma-calibration): pure math for per-category sigma from team-period observations"
```

---

## Task 2: ESPN season-history fetcher

**Files:**
- Create: `backend/data/espn_history.py`
- Test: `tests/backend/data/__init__.py` (empty if missing) and `tests/backend/data/test_espn_history.py`

A small module that hits ESPN's `view=mMatchup&scoringPeriodId=X` endpoint once and returns a structured list of `MatchupRecord` per matchup period × team-side. The endpoint returns the entire season's schedule with `cumulativeScore.scoreByStat` populated for completed periods (verified empirically on 2025 league 77166 — any positive `scoringPeriodId` returns the full season).

ESPN stat ID → cat name mapping (from the existing `src/app/api/matchup/projections/route.ts:15-18`):
- 20=R, 8=TB, 21=RBI, 23=SB, 17=OBP, 48=K, 63=QS, 47=ERA, 41=WHIP, 83=SVHD

Period length: derived from `len(team['cumulativeScore']['statBySlot'])` is unreliable; use `len(home['pointsByScoringPeriod'])` which is reliable — it's the count of scoring periods (= days) included in the matchup.

- [ ] **Step 1: Write the failing test**

Create `tests/backend/data/__init__.py` if missing (empty file). Create `tests/backend/data/test_espn_history.py`:

```python
"""Tests for ESPN historical season fetcher."""

from __future__ import annotations

from unittest.mock import patch, MagicMock
from backend.data.espn_history import (
    fetch_season_matchup_history,
    parse_matchup_response,
    MatchupRecord,
    ESPN_STAT_ID_TO_CAT,
)


class TestParseMatchupResponse:
    def test_extracts_records_per_team_side(self):
        """Each home/away pair becomes two MatchupRecord rows."""
        fake_response = {
            "schedule": [
                {
                    "matchupPeriodId": 5,
                    "home": {
                        "teamId": 10,
                        "cumulativeScore": {
                            "scoreByStat": {
                                "20": {"score": 28.0},  # R
                                "8": {"score": 92.0},   # TB
                                "21": {"score": 31.0},  # RBI
                                "23": {"score": 3.0},   # SB
                                "17": {"score": 0.350}, # OBP
                                "48": {"score": 54.0},  # K
                                "63": {"score": 4.0},   # QS
                                "47": {"score": 3.277}, # ERA
                                "41": {"score": 1.266}, # WHIP
                                "83": {"score": 5.0},   # SVHD
                            },
                        },
                        "pointsByScoringPeriod": {"30": 1, "31": 1, "32": 1, "33": 1, "34": 1, "35": 1, "36": 1},
                    },
                    "away": {
                        "teamId": 7,
                        "cumulativeScore": {
                            "scoreByStat": {
                                "20": {"score": 33.0},
                                "8": {"score": 105.0},
                                "21": {"score": 28.0},
                                "23": {"score": 7.0},
                                "17": {"score": 0.335},
                                "48": {"score": 79.0},
                                "63": {"score": 5.0},
                                "47": {"score": 5.326},
                                "41": {"score": 1.500},
                                "83": {"score": 3.0},
                            },
                        },
                        "pointsByScoringPeriod": {"30": 1, "31": 1, "32": 1, "33": 1, "34": 1, "35": 1, "36": 1},
                    },
                },
            ],
        }
        records = parse_matchup_response(fake_response)
        assert len(records) == 2  # one home, one away
        home = next(r for r in records if r.team_id == 10)
        assert home.matchup_period_id == 5
        assert home.period_days == 7
        assert home.cats["R"] == 28.0
        assert home.cats["OBP"] == 0.350
        assert home.cats["ERA"] == 3.277

    def test_skips_matchups_with_empty_score_by_stat(self):
        """Future/in-progress matchups have no scoreByStat — skip them."""
        fake_response = {
            "schedule": [
                {
                    "matchupPeriodId": 1,
                    "home": {"teamId": 1, "cumulativeScore": {"scoreByStat": {}}, "pointsByScoringPeriod": {}},
                    "away": {"teamId": 2, "cumulativeScore": {"scoreByStat": {}}, "pointsByScoringPeriod": {}},
                },
            ],
        }
        records = parse_matchup_response(fake_response)
        assert records == []


class TestFetchSeasonMatchupHistory:
    def test_calls_espn_with_correct_url_and_returns_parsed_records(self):
        fake_response_json = {
            "schedule": [
                {
                    "matchupPeriodId": 1,
                    "home": {
                        "teamId": 1,
                        "cumulativeScore": {
                            "scoreByStat": {"20": {"score": 50.0}},
                        },
                        "pointsByScoringPeriod": {str(d): 1 for d in range(1, 8)},
                    },
                    "away": {
                        "teamId": 2,
                        "cumulativeScore": {
                            "scoreByStat": {"20": {"score": 45.0}},
                        },
                        "pointsByScoringPeriod": {str(d): 1 for d in range(1, 8)},
                    },
                },
            ],
        }
        with patch("backend.data.espn_history.urllib.request.urlopen") as urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b'{"schedule": [{"matchupPeriodId": 1, "home": {"teamId": 1, "cumulativeScore": {"scoreByStat": {"20": {"score": 50.0}}}, "pointsByScoringPeriod": {"1": 1, "2": 1, "3": 1, "4": 1, "5": 1, "6": 1, "7": 1}}, "away": {"teamId": 2, "cumulativeScore": {"scoreByStat": {"20": {"score": 45.0}}}, "pointsByScoringPeriod": {"1": 1, "2": 1, "3": 1, "4": 1, "5": 1, "6": 1, "7": 1}}}]}'
            urlopen.return_value.__enter__.return_value = mock_resp

            records = fetch_season_matchup_history(
                league_id="77166", season=2025, swid="X", espn_s2="Y",
            )

            urlopen.assert_called_once()
            req = urlopen.call_args[0][0]
            url = req.full_url if hasattr(req, "full_url") else req
            assert "seasons/2025" in url
            assert "leagues/77166" in url
            assert "view=mMatchup" in url
            assert "scoringPeriodId=" in url
            cookie = req.get_header("Cookie")
            assert "swid=X" in cookie
            assert "espn_s2=Y" in cookie
            assert len(records) == 2  # one home, one away
            assert records[0].cats["R"] == 50.0


def test_espn_stat_id_map_covers_all_ten_cats():
    """ESPN_STAT_ID_TO_CAT must include all 10 H2H cats."""
    assert set(ESPN_STAT_ID_TO_CAT.values()) == {
        "R", "TB", "RBI", "SB", "OBP",
        "K", "QS", "ERA", "WHIP", "SVHD",
    }
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/jgibbons/code/fantasy-baseball-helper && python3 -m pytest tests/backend/data/test_espn_history.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.data.espn_history'`.

- [ ] **Step 3: Implement the fetcher**

Create `tests/backend/data/__init__.py` (empty file) if it doesn't exist.

Create `backend/data/espn_history.py`:

```python
"""Fetch historical ESPN H2H category league weekly results.

Used by the σ calibration script to gather every team-week's category totals
for variance estimation.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass, field


ESPN_STAT_ID_TO_CAT: dict[str, str] = {
    "20": "R",  "8": "TB", "21": "RBI", "23": "SB", "17": "OBP",
    "48": "K",  "63": "QS", "47": "ERA", "41": "WHIP", "83": "SVHD",
}


@dataclass
class MatchupRecord:
    """One team-side observation for one matchup period."""
    team_id: int
    matchup_period_id: int
    period_days: int
    cats: dict[str, float] = field(default_factory=dict)


def parse_matchup_response(response: dict) -> list[MatchupRecord]:
    """Extract MatchupRecord per home/away side from an ESPN mMatchup response."""
    out: list[MatchupRecord] = []
    for m in response.get("schedule", []):
        period_id = m.get("matchupPeriodId")
        if period_id is None:
            continue
        for side_key in ("home", "away"):
            side = m.get(side_key)
            if not side:
                continue
            cum = side.get("cumulativeScore") or {}
            score_by_stat = cum.get("scoreByStat") or {}
            if not score_by_stat:
                continue  # future or in-progress matchup
            cats: dict[str, float] = {}
            for stat_id, cat_name in ESPN_STAT_ID_TO_CAT.items():
                score_obj = score_by_stat.get(stat_id) or {}
                cats[cat_name] = float(score_obj.get("score", 0.0))
            period_days = len(side.get("pointsByScoringPeriod") or {})
            out.append(MatchupRecord(
                team_id=side["teamId"],
                matchup_period_id=period_id,
                period_days=period_days,
                cats=cats,
            ))
    return out


def fetch_season_matchup_history(
    league_id: str,
    season: int,
    swid: str,
    espn_s2: str,
) -> list[MatchupRecord]:
    """Fetch all completed matchups for one season's H2H league.

    A single ESPN call with `view=mMatchup&scoringPeriodId=N` returns the
    complete season schedule with `cumulativeScore.scoreByStat` populated
    for every completed matchup period (any positive scoringPeriodId works
    once the season has data).
    """
    # scoringPeriodId=7 is arbitrary — empirically ESPN returns full season data
    # regardless of which scoring period is requested, as long as data exists.
    url = (
        f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb/seasons/"
        f"{season}/segments/0/leagues/{league_id}?view=mMatchup&scoringPeriodId=7"
    )
    req = urllib.request.Request(
        url,
        headers={
            "Cookie": f"swid={swid}; espn_s2={espn_s2}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
    return parse_matchup_response(data)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /Users/jgibbons/code/fantasy-baseball-helper && python3 -m pytest tests/backend/data/test_espn_history.py -v`
Expected: PASS (all 4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/data/espn_history.py tests/backend/data/__init__.py tests/backend/data/test_espn_history.py
git commit -m "feat(sigma-calibration): ESPN historical matchup fetcher"
```

---

## Task 3: Orchestration script + smoke run + persist fixture

**Files:**
- Create: `backend/scripts/__init__.py` (empty)
- Create: `backend/scripts/calibrate_category_sigma.py`
- Create: `backend/data/fixtures/__init__.py` (empty)
- Create: `backend/data/fixtures/sigma_calibration_2025.json` (output of running the script — committed to git)

The script:
1. Loads ESPN credentials from the production `leagues.settings.credentials` row for `espn_77166_2025` (via `prisma`-equivalent SQL using the existing `backend/database.py` connection — but note that's the analytics DB, not the Prisma DB). **Easier: read credentials from CLI args / env vars** — the script is interactive, run by a developer with access.
2. Calls `fetch_season_matchup_history` to get all team-week records.
3. Filters records to typical-length periods (5 ≤ period_days ≤ 9) — drops period 1 (12 days, opening fortnight) and period 15 (14 days, All-Star break).
4. Computes per-team season totals from the filtered records.
5. Derives `team_rates_per_day` for each team and cat:
   - Count stats: `season_total / total_filtered_season_days`
   - Rate stats: PA/IP-weighted average of period rates → simplified to unweighted mean since we don't have PA/IP per period from ESPN's response
6. Calls `compute_category_sigma` to get σ per cat.
7. Prints results in a copy-pasteable Python literal format.
8. Writes the fixture JSON: `{records: [...], computed_sigma: {...}}` so the regression test can replay the math without hitting ESPN.

- [ ] **Step 1: Create the script**

Create `backend/scripts/__init__.py` (empty file).

Create `backend/scripts/calibrate_category_sigma.py`:

```python
"""Calibrate CATEGORY_SIGMA values from a completed H2H season.

Usage:
    python3 -m backend.scripts.calibrate_category_sigma \\
        --league-id 77166 --season 2025 \\
        --swid '{...}' --espn-s2 '...'

Prints calibrated σ values and writes a fixture JSON to
backend/data/fixtures/sigma_calibration_<season>.json for regression testing.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from backend.analysis.sigma_calibration import (
    CountStatObservation,
    compute_category_sigma,
)
from backend.data.espn_history import (
    ESPN_STAT_ID_TO_CAT,
    MatchupRecord,
    fetch_season_matchup_history,
)

# Mirrors the cat list in matchup.py's CATEGORY_SIGMA
CAT_KEYS = ["R", "TB", "RBI", "SB", "OBP", "K", "QS", "ERA", "WHIP", "SVHD"]
CAT_KINDS: dict[str, str] = {
    "R": "count", "TB": "count", "RBI": "count", "SB": "count", "OBP": "rate",
    "K": "count", "QS": "count", "ERA": "rate", "WHIP": "rate", "SVHD": "count",
}

# v1 filter: include only typical-length matchup periods (5–9 days inclusive)
MIN_PERIOD_DAYS = 5
MAX_PERIOD_DAYS = 9


def filter_records(records: list[MatchupRecord]) -> list[MatchupRecord]:
    """Drop matchup periods outside typical 7-day length to avoid period-length confound."""
    return [r for r in records if MIN_PERIOD_DAYS <= r.period_days <= MAX_PERIOD_DAYS]


def compute_team_rates_per_day(
    records: list[MatchupRecord],
) -> dict[int, dict[str, float]]:
    """For each team, compute season-rate per day per cat.

    Count stats: total_observed / total_filtered_days.
    Rate stats: unweighted mean across periods (no PA/IP weights available
    from ESPN's matchup response). Acceptable for v1 calibration.
    """
    by_team: dict[int, list[MatchupRecord]] = defaultdict(list)
    for r in records:
        by_team[r.team_id].append(r)

    rates: dict[int, dict[str, float]] = {}
    for team_id, team_records in by_team.items():
        total_days = sum(r.period_days for r in team_records)
        cat_rates: dict[str, float] = {}
        for cat in CAT_KEYS:
            kind = CAT_KINDS[cat]
            if kind == "count":
                total = sum(r.cats.get(cat, 0.0) for r in team_records)
                cat_rates[cat] = (total / total_days) if total_days > 0 else 0.0
            else:  # rate
                values = [r.cats.get(cat, 0.0) for r in team_records]
                cat_rates[cat] = (sum(values) / len(values)) if values else 0.0
        rates[team_id] = cat_rates
    return rates


def records_to_observations(records: list[MatchupRecord]) -> list[CountStatObservation]:
    """Flatten MatchupRecords into per-cat observations for the calibrator."""
    out: list[CountStatObservation] = []
    for r in records:
        for cat in CAT_KEYS:
            if cat not in r.cats:
                continue
            out.append(CountStatObservation(
                team_id=r.team_id,
                period_id=r.matchup_period_id,
                period_days=r.period_days,
                cat=cat,
                observed=r.cats[cat],
            ))
    return out


def write_fixture(
    fixture_path: Path,
    records: list[MatchupRecord],
    computed_sigma: dict[str, float],
) -> None:
    """Persist raw records + computed σ for regression testing."""
    payload = {
        "computed_sigma": computed_sigma,
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league-id", required=True)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--swid", required=True)
    parser.add_argument("--espn-s2", required=True)
    parser.add_argument(
        "--fixture",
        type=Path,
        default=None,
        help="Output fixture path (default: backend/data/fixtures/sigma_calibration_<season>.json)",
    )
    args = parser.parse_args()

    print(f"Fetching {args.season} matchup history for league {args.league_id}...")
    records = fetch_season_matchup_history(
        league_id=args.league_id,
        season=args.season,
        swid=args.swid,
        espn_s2=args.espn_s2,
    )
    print(f"  Retrieved {len(records)} team-week records.")

    filtered = filter_records(records)
    dropped = len(records) - len(filtered)
    print(f"  Filtered to {len(filtered)} typical-length team-weeks ({dropped} dropped).")

    period_lengths = sorted(set(r.period_days for r in filtered))
    print(f"  Period lengths in calibration set: {period_lengths}")

    rates = compute_team_rates_per_day(filtered)
    observations = records_to_observations(filtered)
    sigma = compute_category_sigma(
        observations=observations,
        team_rates_per_day=rates,
        cat_keys=CAT_KEYS,
        cat_kinds=CAT_KINDS,
    )

    print()
    print("Calibrated CATEGORY_SIGMA (paste into backend/analysis/matchup.py):")
    print("CATEGORY_SIGMA: dict[str, float] = {")
    for cat in CAT_KEYS:
        print(f'    "{cat}": {sigma[cat]:.4f},')
    print("}")

    fixture_path = args.fixture or (
        Path(__file__).resolve().parent.parent
        / "data" / "fixtures" / f"sigma_calibration_{args.season}.json"
    )
    write_fixture(fixture_path, filtered, sigma)
    print(f"\nFixture written: {fixture_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Smoke-test the script imports cleanly**

Run: `cd /Users/jgibbons/code/fantasy-baseball-helper && python3 -m backend.scripts.calibrate_category_sigma --help`
Expected: prints help text without import errors.

- [ ] **Step 3: Run the calibration against the 2025 league and inspect output**

Get credentials from the production `espn_77166_2025` league row. Either:

- **Option A (recommended): query Postgres directly** if you have access to `psql`:
  ```bash
  /opt/homebrew/opt/libpq/bin/psql "$(railway variables --service Postgres | grep DATABASE_PUBLIC_URL | awk '{print $4}')" \
    -t -c "SELECT settings->>'credentials' FROM leagues WHERE id = 'espn_77166_2025';"
  ```
  Then extract `swid` and `espn_s2` fields from the returned JSON.

- **Option B: ESPN cookie copy** — open the user's ESPN league in a browser, copy `SWID` and `espn_s2` cookies from devtools. Same values that worked for the playoff-odds smoke test on 2026-04-30.

Run the script:
```bash
cd /Users/jgibbons/code/fantasy-baseball-helper && \
python3 -m backend.scripts.calibrate_category_sigma \
  --league-id 77166 --season 2025 \
  --swid '{EAADB9D2-A316-4C1F-B64A-D3B9AEE937D0}' \
  --espn-s2 '<paste-from-credentials>'
```

Expected output (approximate; exact values are what we're calibrating):
- `Retrieved ~210 team-week records.` (21 periods × 10 teams × 2 sides ÷ 2 because each matchup is 1 home + 1 away — actual count ~210)
- `Filtered to ~190 typical-length team-weeks.` (drops period 1 and 15)
- `Period lengths in calibration set: [7]` (or similar — should not include 12 or 14)
- A `CATEGORY_SIGMA` dict literal printed
- `Fixture written: backend/data/fixtures/sigma_calibration_2025.json`

**Sanity-check the printed σ values before continuing.** They should be:
- σ_R, σ_TB, σ_RBI, σ_SB, σ_K, σ_QS, σ_SVHD — positive, on the order of typical 7-day cat counting stats
- σ_OBP — small (likely 0.005–0.030)
- σ_ERA, σ_WHIP — moderate (likely 0.5–2.0 for ERA, 0.05–0.25 for WHIP)
- σ_TB > σ_R (TB includes 1B+2*2B+3*3B+4*HR, more variance than R)

If any value looks wildly off (e.g., σ_R > 50, σ_OBP > 0.1), STOP and report — there's likely a data-shape bug. Don't update CATEGORY_SIGMA from broken calibration.

- [ ] **Step 4: Verify the fixture file exists and has reasonable size**

Run: `ls -l backend/data/fixtures/sigma_calibration_2025.json && head -30 backend/data/fixtures/sigma_calibration_2025.json`
Expected: file exists, ~30–80 KB, JSON starts with `{"computed_sigma": {...`.

- [ ] **Step 5: Commit script + fixture**

```bash
git add backend/scripts/__init__.py backend/scripts/calibrate_category_sigma.py \
        backend/data/fixtures/__init__.py backend/data/fixtures/sigma_calibration_2025.json
git commit -m "feat(sigma-calibration): orchestration script + 2025 league fixture"
```

---

## Task 4: Update CATEGORY_SIGMA + verify all existing tests still pass

**Files:**
- Modify: `backend/analysis/matchup.py:42-45`

The existing tests in `tests/backend/analysis/test_matchup.py` and `tests/backend/analysis/test_playoff_odds.py` use `CATEGORY_SIGMA` directly. They use tolerance-based assertions (e.g., `assert a_w >= 9` for a dominant team), so reasonable σ changes shouldn't break them. But we verify.

- [ ] **Step 1: Read the printed CATEGORY_SIGMA literal from Task 3 Step 3**

You should have it from the smoke run, e.g.:
```python
CATEGORY_SIGMA: dict[str, float] = {
    "R": 7.2345,
    "TB": 14.8123,
    # ...
}
```

If not, re-run the script from Task 3 Step 3 to get the literal.

- [ ] **Step 2: Replace the constants in `backend/analysis/matchup.py`**

Find the existing block (around line 41–45):

```python
# Weekly variance sigma values per category (for win probability sigmoid)
CATEGORY_SIGMA: dict[str, float] = {
    "R": 5.0, "TB": 10.0, "RBI": 5.0, "SB": 2.0, "OBP": 0.015,
    "K": 8.0, "QS": 1.5, "ERA": 1.0, "WHIP": 0.15, "SVHD": 2.0,
}
```

Replace with the calibrated literal AND a provenance comment. Example shape (substitute your real numbers):

```python
# Weekly variance sigma values per category. Calibrated against the 2025
# season of ESPN league 77166 (10 teams, 21 H2H matchup periods, filtered
# to 5–9 day periods). See backend/scripts/calibrate_category_sigma.py and
# backend/data/fixtures/sigma_calibration_2025.json for provenance.
# Used by:
#   - matchup.py::compute_win_probability  (per-cat win-prob sigmoid)
#   - playoff_odds.py::simulate_head_to_head (Monte Carlo noise term)
CATEGORY_SIGMA: dict[str, float] = {
    "R":    7.2345,
    "TB":  14.8123,
    "RBI":  6.7891,
    "SB":   2.4012,
    "OBP":  0.0182,
    "K":   12.4500,
    "QS":   1.7800,
    "ERA":  1.2300,
    "WHIP": 0.1850,
    "SVHD": 2.6700,
}
```

**Substitute the actual values from your calibration run** — the literals above are illustrative.

- [ ] **Step 3: Run the full Python test suite**

Run: `cd /Users/jgibbons/code/fantasy-baseball-helper && python3 -m pytest tests/backend/ -v`
Expected: all tests pass. The relevant suites:
- `test_matchup.py` — exercises `compute_win_probability` and matchup projection logic
- `test_playoff_odds.py` — 12 tests including Monte Carlo with `CATEGORY_SIGMA`
- `test_sigma_calibration.py` — Task 1 + Task 5 tests
- `test_espn_history.py` — Task 2 tests

If any test fails:
- If failure is a tolerance threshold (e.g., `assert wins/200 >= 5.0`), inspect whether the calibrated σ legitimately changes the expected behavior. Adjust the test tolerance only if the new behavior is correct under realistic σ.
- If failure is structural (assertion about output shape, not values), STOP and report — likely a bug.

- [ ] **Step 4: Commit constants update**

```bash
git add backend/analysis/matchup.py
git commit -m "feat(sigma-calibration): replace eyeballed CATEGORY_SIGMA with 2025-calibrated values"
```

---

## Task 5: Fixture-pinned regression test

**Files:**
- Modify: `tests/backend/analysis/test_sigma_calibration.py` (append new test class)

A regression test that loads the committed fixture, re-runs the calibration math, and asserts the output matches the fixture's `computed_sigma`. This catches:
- Future code changes that accidentally change the calibration math
- Future fixture updates (you re-run the script with new data, the test re-pins to the new values)

The test does NOT hit ESPN — it loads from `backend/data/fixtures/sigma_calibration_2025.json`.

- [ ] **Step 1: Write the failing regression test**

Append to `tests/backend/analysis/test_sigma_calibration.py`:

```python
import json
from pathlib import Path

from backend.scripts.calibrate_category_sigma import (
    CAT_KEYS,
    CAT_KINDS,
    compute_team_rates_per_day,
    records_to_observations,
)
from backend.data.espn_history import MatchupRecord


FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "backend" / "data" / "fixtures" / "sigma_calibration_2025.json"
)


class TestCalibrationFixtureRegression:
    """Pin the 2025 σ calibration to the committed fixture data."""

    def _load_fixture(self) -> dict:
        with FIXTURE_PATH.open() as f:
            return json.load(f)

    def test_fixture_exists_and_has_expected_shape(self):
        fixture = self._load_fixture()
        assert "computed_sigma" in fixture
        assert "records" in fixture
        assert set(fixture["computed_sigma"].keys()) == set(CAT_KEYS)
        assert len(fixture["records"]) > 100  # ~190 expected after filtering

    def test_recomputing_sigma_from_fixture_records_matches_stored_sigma(self):
        """Math regression: reconstructing σ from fixture records should reproduce the stored values."""
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
        observations = records_to_observations(records)

        from backend.analysis.sigma_calibration import compute_category_sigma
        recomputed = compute_category_sigma(
            observations=observations,
            team_rates_per_day=rates,
            cat_keys=CAT_KEYS,
            cat_kinds=CAT_KINDS,
        )

        for cat in CAT_KEYS:
            stored = fixture["computed_sigma"][cat]
            assert recomputed[cat] == pytest.approx(stored, rel=1e-6), (
                f"Drift in σ_{cat}: stored={stored}, recomputed={recomputed[cat]}"
            )

    def test_matchup_constants_match_fixture(self):
        """The CATEGORY_SIGMA constants in matchup.py should match the fixture."""
        from backend.analysis.matchup import CATEGORY_SIGMA
        fixture = self._load_fixture()
        for cat in CAT_KEYS:
            assert CATEGORY_SIGMA[cat] == pytest.approx(
                fixture["computed_sigma"][cat], rel=1e-3
            ), (
                f"matchup.py CATEGORY_SIGMA['{cat}'] = {CATEGORY_SIGMA[cat]} "
                f"but fixture has {fixture['computed_sigma'][cat]}. "
                f"Re-run backend/scripts/calibrate_category_sigma.py and update."
            )
```

- [ ] **Step 2: Run the new tests to verify they pass**

Run: `cd /Users/jgibbons/code/fantasy-baseball-helper && python3 -m pytest tests/backend/analysis/test_sigma_calibration.py::TestCalibrationFixtureRegression -v`
Expected: all 3 tests pass.

If `test_matchup_constants_match_fixture` fails, it means the values in `matchup.py` don't match the fixture — go back to Task 4 Step 2 and verify you used the correct numbers.

- [ ] **Step 3: Run the full Python suite to confirm no regressions**

Run: `cd /Users/jgibbons/code/fantasy-baseball-helper && python3 -m pytest tests/backend/ -v 2>&1 | tail -20`
Expected: all tests pass (Task 1's 4 tests + Task 2's 4 tests + Task 5's 3 tests + everything pre-existing in `test_matchup.py`, `test_playoff_odds.py`, `test_waivers.py`, `test_trades.py`, `test_lineup_optimizer.py`, `test_bench_contributions.py`, `test_performance.py`, `test_pitcherlist.py`, `test_start_sit.py`).

- [ ] **Step 4: Commit**

```bash
git add tests/backend/analysis/test_sigma_calibration.py
git commit -m "test(sigma-calibration): fixture-pinned regression for 2025 calibration"
```

---

## Self-Review Notes

**Spec coverage check:**
- Pure math function for computing σ from observations → Task 1
- ESPN historical fetcher → Task 2
- Orchestration + smoke run + fixture → Task 3
- Update CATEGORY_SIGMA constants → Task 4
- Regression test pinning to fixture → Task 5

**Type consistency check:**
- `MatchupRecord` defined in Task 2 (`backend/data/espn_history.py`), reused in Tasks 3 + 5.
- `CountStatObservation` defined in Task 1 (`backend/analysis/sigma_calibration.py`), reused in Tasks 3 + 5.
- `CAT_KEYS` and `CAT_KINDS` defined in Task 3 (`backend/scripts/calibrate_category_sigma.py`); Task 5 imports them from there.
- ESPN stat ID → cat name map (`ESPN_STAT_ID_TO_CAT`) defined in Task 2; not reused (Tasks 3/5 don't need it directly since they consume the parsed `MatchupRecord.cats`).

**Acceptance criteria for "done":**
1. `python3 -m backend.scripts.calibrate_category_sigma --league-id 77166 --season 2025 --swid X --espn-s2 Y` runs cleanly and prints a `CATEGORY_SIGMA` literal.
2. `backend/data/fixtures/sigma_calibration_2025.json` is committed.
3. `backend/analysis/matchup.py` has the calibrated `CATEGORY_SIGMA` values with a provenance comment.
4. All `tests/backend/` tests pass with `python3 -m pytest tests/backend/ -v`.
5. The regression test `test_matchup_constants_match_fixture` confirms the fixture and `matchup.py` are in sync.

**Out of scope (explicit follow-ups, do NOT attempt in this plan):**
- Per-team heteroskedastic σ (high-mean teams have larger absolute σ).
- Recalibrating with multiple seasons (2024, 2023) — would require ESPN historical access for those years.
- Recalibrating against ATC RoS DC projection residuals instead of season-rate residuals — needs historical ATC snapshots we don't have.
- The "empirical Bayes shrinkage" (blend observed cat-win rate with projection-implied rate) — this is a separate plan; addressing variance ≠ addressing the projection-vs-observed-skill tension.
