# Playoff Odds Simulator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a `/playoff-odds` page that runs a Monte Carlo simulation of the remaining H2H regular season and reports the percent chance each team makes the playoffs (top‑6 of 10).

**Architecture:** Three-tier, mirroring the existing `matchup` and `waivers` features.
React page → Next.js API route (orchestrates ESPN fetch + payload build) → FastAPI backend (`backend/analysis/playoff_odds.py` runs the sim). The Python engine reuses `PlayerProjection`, `TeamTotals`, `_load_projections`, `resolve_espn_names_to_mlbid` from `backend/analysis/waivers.py` and `CATEGORY_SIGMA`, `optimize_daily_lineup` from `backend/analysis/matchup.py`.

**Tech Stack:** Next.js 15, React 19, TailwindCSS, FastAPI, Pydantic v2, NumPy, ESPN Fantasy API, SQLite (rankings table).

**Spec:** This plan; no separate spec doc.

**v1 simplifications (documented intentionally — do NOT bolt on without follow‑up):**
- Static rosters from "today" — no waiver/trade drift across remaining periods.
- Equal weight per remaining matchup period (period_days / sum_remaining_period_days). All‑Star period (period 15 in this league) is 14 days vs 7 for other periods, so the date ratio handles it.
- Pitcher start caps not modeled (this league has no GS cap).
- Variance reuses `CATEGORY_SIGMA` from `matchup.py` — empirically tuned for weekly H2H. Not re‑calibrated.

---

## File Structure

**New files:**
- `backend/analysis/playoff_odds.py` — sim engine
- `backend/api/playoff_odds_models.py` — Pydantic request/response models
- `tests/backend/analysis/test_playoff_odds.py` — Python unit tests
- `src/lib/playoff-odds-payload.ts` — payload builder pure helper
- `src/app/api/playoff-odds/route.ts` — Next.js API orchestrator
- `src/app/playoff-odds/page.tsx` — frontend page
- `src/__tests__/lib/playoff-odds-payload.test.ts` — payload builder tests

**Modified files:**
- `src/lib/espn-api.ts` — add `getFullSchedule()` returning all matchup periods
- `backend/api/routes.py` — register playoff-odds endpoint
- `src/components/Navigation.tsx` — add nav link (look up actual file in step 1 of Task 11)

---

## Task 1: ESPN full-season schedule fetch

**Files:**
- Modify: `src/lib/espn-api.ts` (add new static method on `ESPNApi`)
- Test: `src/__tests__/lib/espn-api.test.ts` (extend existing file)

ESPN's `view=mMatchupScore` returns the entire season's schedule (every matchup pairing for every period) in `data.schedule`. Existing `getMatchupScoreboard` filters to a single period. This task adds a second method that returns the full schedule.

- [ ] **Step 1: Write the failing test**

Append to `src/__tests__/lib/espn-api.test.ts`:

```typescript
describe('ESPNApi.getFullSchedule', () => {
  it('returns every matchup across every period', async () => {
    const fakeResponse = {
      schedule: [
        { matchupPeriodId: 1, home: { teamId: 1 }, away: { teamId: 2 } },
        { matchupPeriodId: 1, home: { teamId: 3 }, away: { teamId: 4 } },
        { matchupPeriodId: 2, home: { teamId: 1 }, away: { teamId: 3 } },
      ],
    }
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => fakeResponse,
    }) as any

    const result = await ESPNApi.getFullSchedule('77166', '2026', {
      swid: 'S', espn_s2: 'E',
    })

    expect(result).toHaveLength(3)
    expect(result[0].matchupPeriodId).toBe(1)
    expect(result[2].matchupPeriodId).toBe(2)
    expect(result[2].home.teamId).toBe(1)
    expect(result[2].away.teamId).toBe(3)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx jest src/__tests__/lib/espn-api.test.ts -t getFullSchedule`
Expected: FAIL with "ESPNApi.getFullSchedule is not a function".

- [ ] **Step 3: Implement `getFullSchedule`**

Add to `src/lib/espn-api.ts` inside class `ESPNApi`, after `getMatchupScoreboard`:

```typescript
  static async getFullSchedule(
    leagueId: string,
    season: string,
    settings: ESPNLeagueSettings,
  ): Promise<Array<{
    matchupPeriodId: number
    home: { teamId: number }
    away: { teamId: number }
  }>> {
    const url = `https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb/seasons/${season}/segments/0/leagues/${leagueId}?view=mMatchupScore`

    const response = await fetch(url, { headers: this.getHeaders(settings) })
    if (!response.ok) {
      throw new Error(`ESPN API error: ${response.status} - ${response.statusText}`)
    }

    const data = await response.json()
    return (data.schedule || []).map((m: any) => ({
      matchupPeriodId: m.matchupPeriodId,
      home: { teamId: m.home.teamId },
      away: { teamId: m.away.teamId },
    }))
  }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx jest src/__tests__/lib/espn-api.test.ts -t getFullSchedule`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lib/espn-api.ts src/__tests__/lib/espn-api.test.ts
git commit -m "feat(playoff-odds): add ESPN full-season schedule fetch"
```

---

## Task 2: Python — Pydantic request/response models

**Files:**
- Create: `backend/api/playoff_odds_models.py`

The endpoint accepts: each team's roster (from ESPN), current cumulative W/L/T per team, remaining matchup schedule (period → home/away team IDs), period date ranges, and config (n_trials, playoff_slots). It returns: per-team playoff odds + summary stats.

- [ ] **Step 1: Create the models file**

```python
# backend/api/playoff_odds_models.py
"""Pydantic models for the playoff odds endpoint."""

from __future__ import annotations

from pydantic import BaseModel
from typing import Optional


class RosterPlayer(BaseModel):
    """A single roster entry as sent from the TS layer."""
    name: str
    position: str  # ESPN default position abbrev (e.g. "OF", "SP")
    player_type: str  # "hitter" or "pitcher"
    lineup_slot_id: int  # 0-15 active, 16 BE, 17+ IL
    eligible_positions: str  # slash-separated, e.g. "OF/UTIL"
    injury_status: str = "ACTIVE"


class TeamPayload(BaseModel):
    team_id: int
    team_name: str
    roster: list[RosterPlayer]
    current_wins: int = 0
    current_losses: int = 0
    current_ties: int = 0


class MatchupPair(BaseModel):
    matchup_period_id: int
    home_team_id: int
    away_team_id: int


class PlayoffOddsRequest(BaseModel):
    season: int
    teams: list[TeamPayload]
    remaining_schedule: list[MatchupPair]
    # Per-period weight (period_days / sum_remaining_days). Same length and order
    # as remaining_schedule's distinct period IDs (smallest first).
    period_weights: dict[int, float]
    playoff_slots: int = 6
    n_trials: int = 5000
    seed: Optional[int] = None


class TeamOdds(BaseModel):
    team_id: int
    team_name: str
    current_wins: int
    current_losses: int
    current_ties: int
    playoff_odds: float  # 0.0–1.0
    avg_final_wins: float
    avg_final_losses: float
    avg_final_ties: float
    avg_final_rank: float


class PlayoffOddsResponse(BaseModel):
    teams: list[TeamOdds]  # sorted by playoff_odds desc
    n_trials: int
    matched_player_count: int
    unmatched_player_names: list[str]
```

- [ ] **Step 2: Verify the file imports cleanly**

Run: `python -c "from backend.api.playoff_odds_models import PlayoffOddsRequest, PlayoffOddsResponse; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add backend/api/playoff_odds_models.py
git commit -m "feat(playoff-odds): add Pydantic request/response models"
```

---

## Task 3: Python — weekly team projection

**Files:**
- Create: `backend/analysis/playoff_odds.py`
- Test: `tests/backend/analysis/test_playoff_odds.py`

For one team in one matchup period, compute the projected category values. Approach:
1. Decompose each rostered player's RoS projection into a per-period share by multiplying by `period_weight` (period_days / sum_remaining_period_days).
2. Run `optimize_daily_lineup` on active players to identify starters; bench/IL get bench/IL weights.
3. Aggregate using `TeamTotals.add_player(player, weight)`.
4. Return the 10 category values via `TeamTotals.category_values()`.

- [ ] **Step 1: Write the failing test for `project_team_period`**

```python
# tests/backend/analysis/test_playoff_odds.py
"""Tests for the playoff odds simulator engine."""

from __future__ import annotations

import pytest
from backend.analysis.waivers import PlayerProjection
from backend.analysis.playoff_odds import project_team_period


def _hitter(mlb_id: int, name: str, **stats) -> PlayerProjection:
    base = dict(pa=600, r=90, tb=270, rbi=80, sb=10, obp=0.340)
    base.update(stats)
    return PlayerProjection(
        mlb_id=mlb_id, name=name, position="OF", player_type="hitter",
        eligible_positions="OF/UTIL", **base,
    )


def _sp(mlb_id: int, name: str, **stats) -> PlayerProjection:
    base = dict(ip=180.0, k=200, qs=18, era=3.50, whip=1.15)
    base.update(stats)
    return PlayerProjection(
        mlb_id=mlb_id, name=name, position="SP", player_type="pitcher",
        eligible_positions="SP/P", **base,
    )


class TestProjectTeamPeriod:
    def test_period_weight_scales_count_stats_linearly(self):
        roster = [_hitter(1, "A"), _hitter(2, "B"), _hitter(3, "C")]
        full = project_team_period(roster, period_weight=1.0)
        half = project_team_period(roster, period_weight=0.5)
        # Count stats must scale by period_weight
        assert half["R"] == pytest.approx(full["R"] / 2, rel=1e-6)
        assert half["TB"] == pytest.approx(full["TB"] / 2, rel=1e-6)
        # Rate stats stay constant
        assert half["OBP"] == pytest.approx(full["OBP"], rel=1e-6)

    def test_starters_and_bench_weighted_correctly(self):
        # 4 OF on roster; only 3 OF starting slots + 2 UTIL = 5 total hitter slots
        # With 4 hitters, all start (slots not exceeded). Add a 5th to test bench.
        roster = [_hitter(i, f"H{i}") for i in range(1, 8)]  # 7 hitters
        result = project_team_period(roster, period_weight=1.0)
        # Starting hitters: 1C+1@1B+1@2B+1@3B+1SS+3OF+2UTIL = 10 → only 7 of those slots
        # match. With 7 OF-eligible hitters and 3 OF + 2 UTIL = 5 slots, 2 will be bench.
        # Total R = 5 starters * 90 + 2 bench * 90 * 0.25
        expected_r = 5 * 90 + 2 * 90 * 0.25
        assert result["R"] == pytest.approx(expected_r, rel=1e-6)

    def test_pitcher_rate_stats_use_ip_weighted_average(self):
        roster = [
            _sp(1, "Ace", ip=200.0, era=2.50, whip=1.00, k=240, qs=22),
            _sp(2, "Mid", ip=160.0, era=4.00, whip=1.30, k=140, qs=12),
        ]
        result = project_team_period(roster, period_weight=1.0)
        # Both start (3 SP + 2 P = 5 slots, 2 SPs)
        weighted_era = (2.50 * 200 + 4.00 * 160) / (200 + 160)
        assert result["ERA"] == pytest.approx(weighted_era, rel=1e-3)

    def test_il_player_zero_weight(self):
        # Hitter with lineup_slot_id=17 (IL) contributes nothing
        from backend.analysis.playoff_odds import IL_LINEUP_SLOT_MIN
        injured = _hitter(99, "Injured")
        # Marker: we'll express IL via a separate parameter list
        result = project_team_period(
            roster=[_hitter(1, "A")],
            period_weight=1.0,
            il_mlb_ids={99: True},  # injured player would be in roster but IL-flagged
        )
        # Only 1 hitter; all slots empty for others
        assert result["R"] == pytest.approx(90, rel=1e-6)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/backend/analysis/test_playoff_odds.py::TestProjectTeamPeriod -v`
Expected: FAIL with "ModuleNotFoundError" or "cannot import name 'project_team_period'".

- [ ] **Step 3: Implement `project_team_period`**

Create `backend/analysis/playoff_odds.py`:

```python
# backend/analysis/playoff_odds.py
"""Playoff odds Monte Carlo simulator.

Given each team's roster, current cumulative W/L/T, and the remaining matchup
schedule, runs N trials of the rest of the season and reports each team's
probability of finishing in the top K (playoff slots).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np

from backend.analysis.matchup import (
    CATEGORY_SIGMA,
    optimize_daily_lineup,
)
from backend.analysis.waivers import (
    ALL_CATS,
    HITTER_BENCH_WEIGHT,
    INVERTED_CATS,
    PlayerProjection,
    TeamTotals,
)

logger = logging.getLogger(__name__)

IL_LINEUP_SLOT_MIN = 17  # ESPN lineupSlotId 17+ are IL slots
BENCH_LINEUP_SLOT = 16
PITCHER_BENCH_WEIGHT_SP = 0.95
PITCHER_BENCH_WEIGHT_RP = 0.95


def _bench_weight(player: PlayerProjection) -> float:
    """Bench contribution weight matching roster-optimizer.ts."""
    if player.player_type == "hitter":
        return HITTER_BENCH_WEIGHT
    # SP and RP both use ~0.95 per memory and roster-optimizer.ts
    return PITCHER_BENCH_WEIGHT_SP if player.qs > 0 else PITCHER_BENCH_WEIGHT_RP


def project_team_period(
    roster: list[PlayerProjection],
    period_weight: float,
    il_mlb_ids: Optional[dict[int, bool]] = None,
) -> dict[str, float]:
    """Project a team's category totals for one matchup period.

    Args:
        roster: All non-IL players on the team for this period.
        period_weight: Fraction of full RoS this period represents (e.g. 7/91).
        il_mlb_ids: Mapping of mlb_id → True for IL players. IL players
            contribute 0. Pass None or empty dict for no IL.

    Returns:
        Dict with the 10 H2H category keys (R, TB, RBI, SB, OBP, K, QS,
        ERA, WHIP, SVHD).
    """
    il = il_mlb_ids or {}
    active = [p for p in roster if not il.get(p.mlb_id, False)]

    # Run greedy lineup optimizer on the active roster to identify starters.
    # `optimize_daily_lineup` accepts a list of dicts; convert.
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

    # Build a TeamTotals scaled by period_weight
    totals = TeamTotals()
    for p in active:
        weight = period_weight if p.mlb_id in starter_ids else period_weight * _bench_weight(p)
        totals.add_player(p, weight=weight)

    return totals.category_values()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/backend/analysis/test_playoff_odds.py::TestProjectTeamPeriod -v`
Expected: PASS (all 4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/analysis/playoff_odds.py tests/backend/analysis/test_playoff_odds.py
git commit -m "feat(playoff-odds): per-team weekly projection helper"
```

---

## Task 4: Python — simulate one head-to-head matchup

**Files:**
- Modify: `backend/analysis/playoff_odds.py`
- Modify: `tests/backend/analysis/test_playoff_odds.py`

For one matchup pair (team A's projected categories vs team B's), draw a noisy outcome for each of the 10 categories. Higher value wins (lower wins for ERA/WHIP). Tied values count as a tie (T) for both teams.

- [ ] **Step 1: Write the failing test**

Append to `tests/backend/analysis/test_playoff_odds.py`:

```python
from backend.analysis.playoff_odds import simulate_head_to_head


class TestSimulateHeadToHead:
    def test_dominant_team_wins_most_cats(self):
        # Team A is much better at every cat
        a = {"R": 100, "TB": 300, "RBI": 100, "SB": 20, "OBP": 0.380,
             "K": 100, "QS": 8, "ERA": 3.00, "WHIP": 1.05, "SVHD": 10}
        b = {"R": 50, "TB": 150, "RBI": 50, "SB": 5, "OBP": 0.300,
             "K": 50, "QS": 3, "ERA": 5.00, "WHIP": 1.40, "SVHD": 4}
        rng = np.random.default_rng(seed=42)
        a_w, a_l, a_t = simulate_head_to_head(a, b, rng)
        # A should win nearly all 10
        assert a_w >= 9
        assert a_w + a_l + a_t == 10

    def test_tie_means_zero_margin(self):
        same = {"R": 80, "TB": 240, "RBI": 80, "SB": 10, "OBP": 0.330,
                "K": 80, "QS": 6, "ERA": 3.50, "WHIP": 1.20, "SVHD": 6}
        rng = np.random.default_rng(seed=42)
        # Run many trials; with sigma > 0, ties from noise should be near 0
        ties = 0
        for _ in range(100):
            _, _, t = simulate_head_to_head(same, same.copy(), rng)
            ties += t
        # With continuous gaussian noise, exact equality is essentially never;
        # pure ties (~0%) are rare. Win/loss should split ~50/50 across runs.
        assert ties == 0  # gaussians never tie

    def test_inverted_cats_lower_wins(self):
        # Team A has lower ERA — should win ERA/WHIP categories more often
        a = {"R": 80, "TB": 240, "RBI": 80, "SB": 10, "OBP": 0.330,
             "K": 80, "QS": 6, "ERA": 2.50, "WHIP": 1.00, "SVHD": 6}
        b = {"R": 80, "TB": 240, "RBI": 80, "SB": 10, "OBP": 0.330,
             "K": 80, "QS": 6, "ERA": 5.00, "WHIP": 1.50, "SVHD": 6}
        rng = np.random.default_rng(seed=42)
        wins = 0
        for _ in range(200):
            a_w, _, _ = simulate_head_to_head(a, b, rng)
            wins += a_w
        # A wins ERA + WHIP almost always (~2 cats), splits the 8 equal cats
        # ~50/50. Average around 2 + 4 = 6.
        avg = wins / 200
        assert 5.0 <= avg <= 7.0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/backend/analysis/test_playoff_odds.py::TestSimulateHeadToHead -v`
Expected: FAIL with `ImportError: cannot import name 'simulate_head_to_head'`.

- [ ] **Step 3: Implement `simulate_head_to_head`**

Append to `backend/analysis/playoff_odds.py`:

```python
def simulate_head_to_head(
    team_a_cats: dict[str, float],
    team_b_cats: dict[str, float],
    rng: np.random.Generator,
) -> tuple[int, int, int]:
    """Simulate one matchup. Returns team_a's (wins, losses, ties) over 10 cats.

    For each category, draw a normal noise term scaled by CATEGORY_SIGMA from
    matchup.py and add to each team's projected value. Compare and tally W/L/T.
    """
    wins = losses = ties = 0
    for cat in ALL_CATS:
        sigma = CATEGORY_SIGMA[cat]
        a_draw = team_a_cats[cat] + rng.normal(0.0, sigma)
        b_draw = team_b_cats[cat] + rng.normal(0.0, sigma)
        if cat in INVERTED_CATS:
            # Lower wins
            if a_draw < b_draw:
                wins += 1
            elif a_draw > b_draw:
                losses += 1
            else:
                ties += 1
        else:
            if a_draw > b_draw:
                wins += 1
            elif a_draw < b_draw:
                losses += 1
            else:
                ties += 1
    return wins, losses, ties
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/backend/analysis/test_playoff_odds.py::TestSimulateHeadToHead -v`
Expected: PASS (all 3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/analysis/playoff_odds.py tests/backend/analysis/test_playoff_odds.py
git commit -m "feat(playoff-odds): simulate one head-to-head matchup"
```

---

## Task 5: Python — simulate one full remaining season

**Files:**
- Modify: `backend/analysis/playoff_odds.py`
- Modify: `tests/backend/analysis/test_playoff_odds.py`

For each remaining matchup period: project each team's cats for that period, then for each pairing in that period, simulate the matchup and accumulate W/L/T to each team's running total. Returns final cumulative W/L/T per team.

- [ ] **Step 1: Write the failing test**

Append to `tests/backend/analysis/test_playoff_odds.py`:

```python
from backend.analysis.playoff_odds import simulate_one_season


class TestSimulateOneSeason:
    def _make_rosters(self) -> dict[int, list[PlayerProjection]]:
        # Two teams of identical strength
        return {
            1: [_hitter(i, f"T1_H{i}") for i in range(1, 11)] + [_sp(i, f"T1_P{i}") for i in range(20, 25)],
            2: [_hitter(i + 100, f"T2_H{i}") for i in range(1, 11)] + [_sp(i + 100, f"T2_P{i}") for i in range(20, 25)],
        }

    def test_two_team_two_period_balanced(self):
        rosters = self._make_rosters()
        current = {1: (0, 0, 0), 2: (0, 0, 0)}
        schedule = [(1, 1, 2), (2, 1, 2)]  # 2 periods, both same matchup
        period_weights = {1: 0.5, 2: 0.5}
        rng = np.random.default_rng(seed=123)

        result = simulate_one_season(
            rosters=rosters,
            current_records=current,
            remaining_schedule=schedule,
            period_weights=period_weights,
            rng=rng,
        )

        # Each team played 2 matchups × 10 cats = 20 cat-decisions
        for team_id in (1, 2):
            w, l, t = result[team_id]
            assert w + l + t == 20

    def test_current_records_carry_forward(self):
        rosters = self._make_rosters()
        current = {1: (50, 30, 0), 2: (10, 70, 0)}  # team 1 has huge lead
        schedule = [(1, 1, 2)]
        period_weights = {1: 1.0}
        rng = np.random.default_rng(seed=42)

        result = simulate_one_season(
            rosters=rosters,
            current_records=current,
            remaining_schedule=schedule,
            period_weights=period_weights,
            rng=rng,
        )

        w1, l1, t1 = result[1]
        # Team 1 should still have far more wins than team 2 after 1 period
        w2, _, _ = result[2]
        assert w1 > w2
        assert w1 >= 50  # carried forward at minimum
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/backend/analysis/test_playoff_odds.py::TestSimulateOneSeason -v`
Expected: FAIL with `ImportError: cannot import name 'simulate_one_season'`.

- [ ] **Step 3: Implement `simulate_one_season`**

Append to `backend/analysis/playoff_odds.py`:

```python
def simulate_one_season(
    rosters: dict[int, list[PlayerProjection]],
    current_records: dict[int, tuple[int, int, int]],
    remaining_schedule: list[tuple[int, int, int]],
    period_weights: dict[int, float],
    rng: np.random.Generator,
    il_by_team: Optional[dict[int, dict[int, bool]]] = None,
) -> dict[int, tuple[int, int, int]]:
    """Run one full simulation of the rest of the regular season.

    Args:
        rosters: team_id → list of PlayerProjection.
        current_records: team_id → (wins, losses, ties) at start of sim.
        remaining_schedule: list of (matchup_period_id, home_team_id, away_team_id).
        period_weights: matchup_period_id → fraction-of-RoS this period covers.
        rng: numpy Generator for noise draws.
        il_by_team: team_id → {mlb_id: True} for IL players. Optional.

    Returns:
        team_id → final cumulative (wins, losses, ties).
    """
    il_by_team = il_by_team or {}
    final = {tid: list(rec) for tid, rec in current_records.items()}

    # Group periods so we project once per (team, period) pair (caching).
    periods_seen: set[int] = set()
    period_projections: dict[tuple[int, int], dict[str, float]] = {}

    for period_id, home_id, away_id in remaining_schedule:
        weight = period_weights[period_id]
        # Project each team for this period (cache to avoid recomputation)
        for team_id in (home_id, away_id):
            key = (team_id, period_id)
            if key not in period_projections:
                period_projections[key] = project_team_period(
                    roster=rosters[team_id],
                    period_weight=weight,
                    il_mlb_ids=il_by_team.get(team_id),
                )
        a_cats = period_projections[(home_id, period_id)]
        b_cats = period_projections[(away_id, period_id)]
        a_w, a_l, a_t = simulate_head_to_head(a_cats, b_cats, rng)
        # Home gets a_w/a_l/a_t; away is the inverse (a_l wins, a_w losses, a_t ties)
        final[home_id][0] += a_w
        final[home_id][1] += a_l
        final[home_id][2] += a_t
        final[away_id][0] += a_l
        final[away_id][1] += a_w
        final[away_id][2] += a_t
        periods_seen.add(period_id)

    return {tid: tuple(rec) for tid, rec in final.items()}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/backend/analysis/test_playoff_odds.py::TestSimulateOneSeason -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add backend/analysis/playoff_odds.py tests/backend/analysis/test_playoff_odds.py
git commit -m "feat(playoff-odds): full-season single-trial simulator"
```

---

## Task 6: Python — Monte Carlo `compute_playoff_odds`

**Files:**
- Modify: `backend/analysis/playoff_odds.py`
- Modify: `tests/backend/analysis/test_playoff_odds.py`

Run N trials. After each trial, sort teams by wins (tiebreak: ties; then random tiebreaker, since this league uses head-to-head category wins as the tiebreaker which we approximate by total wins). Count top-K finishes per team. Also accumulate sum of (wins, losses, ties) and sum-of-final-rank per team for averages.

- [ ] **Step 1: Write the failing test**

Append:

```python
from backend.analysis.playoff_odds import compute_playoff_odds


class TestComputePlayoffOdds:
    def test_dominant_team_has_high_odds(self):
        # Team 1 has a huge lead; team 2 has none
        rosters = {
            1: [_hitter(i, f"T1_H{i}", r=120, tb=350, rbi=110) for i in range(1, 11)] + [_sp(i, f"T1_P{i}", k=240, qs=22, era=2.50, whip=1.00) for i in range(20, 25)],
            2: [_hitter(i + 100, f"T2_H{i}", r=50, tb=150, rbi=50) for i in range(1, 11)] + [_sp(i + 100, f"T2_P{i}", k=120, qs=10, era=4.50, whip=1.40) for i in range(20, 25)],
        }
        result = compute_playoff_odds(
            rosters=rosters,
            current_records={1: (50, 0, 0), 2: (0, 50, 0)},
            remaining_schedule=[(1, 1, 2), (2, 1, 2)],
            period_weights={1: 0.5, 2: 0.5},
            playoff_slots=1,  # only the top team makes playoffs
            n_trials=200,
            seed=42,
        )
        team1 = next(t for t in result if t["team_id"] == 1)
        team2 = next(t for t in result if t["team_id"] == 2)
        assert team1["playoff_odds"] >= 0.95
        assert team2["playoff_odds"] <= 0.05

    def test_balanced_two_team_one_slot_is_fifty_fifty(self):
        rosters = {
            1: [_hitter(i, f"T1_H{i}") for i in range(1, 11)] + [_sp(i, f"T1_P{i}") for i in range(20, 25)],
            2: [_hitter(i + 100, f"T2_H{i}") for i in range(1, 11)] + [_sp(i + 100, f"T2_P{i}") for i in range(20, 25)],
        }
        result = compute_playoff_odds(
            rosters=rosters,
            current_records={1: (10, 10, 0), 2: (10, 10, 0)},
            remaining_schedule=[(1, 1, 2), (2, 1, 2), (3, 1, 2)],
            period_weights={1: 1/3, 2: 1/3, 3: 1/3},
            playoff_slots=1,
            n_trials=400,
            seed=7,
        )
        team1 = next(t for t in result if t["team_id"] == 1)
        team2 = next(t for t in result if t["team_id"] == 2)
        # Each should be ~50%; allow ±10% sampling tolerance
        assert abs(team1["playoff_odds"] - 0.5) < 0.15
        assert abs(team1["playoff_odds"] + team2["playoff_odds"] - 1.0) < 0.05
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/backend/analysis/test_playoff_odds.py::TestComputePlayoffOdds -v`
Expected: FAIL with `ImportError: cannot import name 'compute_playoff_odds'`.

- [ ] **Step 3: Implement `compute_playoff_odds`**

Append to `backend/analysis/playoff_odds.py`:

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
) -> list[dict]:
    """Run Monte Carlo and return per-team playoff odds.

    Tiebreaker for top-K cut: total wins, then ties (more ties = tied teams
    treated as ahead of fewer-ties), then random. Approximates ESPN cat-format
    tiebreakers, which compare head-to-head record then total points-for.
    """
    team_ids = list(rosters.keys())
    n_teams = len(team_ids)
    team_names = team_names or {tid: f"Team {tid}" for tid in team_ids}

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
        )
        # Rank teams: more wins is better, more ties as secondary, random tiebreak.
        # Use a stable shuffle then sort to break exact ties uniformly.
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
        })
    out.sort(key=lambda r: -r["playoff_odds"])
    return out
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/backend/analysis/test_playoff_odds.py::TestComputePlayoffOdds -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add backend/analysis/playoff_odds.py tests/backend/analysis/test_playoff_odds.py
git commit -m "feat(playoff-odds): Monte Carlo playoff odds engine"
```

---

## Task 7: Python — payload-to-engine adapter

**Files:**
- Modify: `backend/analysis/playoff_odds.py`
- Modify: `tests/backend/analysis/test_playoff_odds.py`

The endpoint receives the raw `PlayoffOddsRequest` payload (rosters with names, no projections). This task adds a function `compute_playoff_odds_from_request` that:
1. Resolves ESPN names → mlb_ids via `resolve_espn_names_to_mlbid`.
2. Loads `PlayerProjection` rows from the rankings table via `_load_projections`.
3. Builds `rosters: dict[int, list[PlayerProjection]]` and `il_by_team`.
4. Calls `compute_playoff_odds`.
5. Returns the response dict + `matched_player_count` + `unmatched_player_names`.

- [ ] **Step 1: Write the failing test**

Append:

```python
from unittest.mock import patch
from backend.analysis.playoff_odds import compute_playoff_odds_from_request


class TestComputePlayoffOddsFromRequest:
    def test_resolves_names_and_returns_unmatched(self):
        # Mock the projection loader and name resolver
        fake_projections = {
            1001: PlayerProjection(mlb_id=1001, name="A", position="OF",
                                   player_type="hitter", pa=600, r=90, tb=270,
                                   rbi=80, sb=10, obp=0.330,
                                   eligible_positions="OF/UTIL"),
            1002: PlayerProjection(mlb_id=1002, name="B", position="SP",
                                   player_type="pitcher", ip=180, k=200, qs=18,
                                   era=3.50, whip=1.15,
                                   eligible_positions="SP/P"),
        }
        with patch("backend.analysis.playoff_odds.resolve_espn_names_to_mlbid") as resolve, \
             patch("backend.analysis.playoff_odds._load_projections") as load_proj:
            resolve.return_value = {"a": 1001, "b": 1002}  # "missing" not in map
            load_proj.return_value = fake_projections

            payload = {
                "season": 2026,
                "teams": [
                    {
                        "team_id": 1, "team_name": "T1",
                        "roster": [
                            {"name": "A", "position": "OF", "player_type": "hitter",
                             "lineup_slot_id": 5, "eligible_positions": "OF/UTIL"},
                            {"name": "Missing", "position": "1B",
                             "player_type": "hitter", "lineup_slot_id": 1,
                             "eligible_positions": "1B/UTIL"},
                        ],
                        "current_wins": 10, "current_losses": 5, "current_ties": 0,
                    },
                    {
                        "team_id": 2, "team_name": "T2",
                        "roster": [
                            {"name": "B", "position": "SP", "player_type": "pitcher",
                             "lineup_slot_id": 14, "eligible_positions": "SP/P"},
                        ],
                        "current_wins": 5, "current_losses": 10, "current_ties": 0,
                    },
                ],
                "remaining_schedule": [
                    {"matchup_period_id": 1, "home_team_id": 1, "away_team_id": 2},
                ],
                "period_weights": {1: 1.0},
                "playoff_slots": 1,
                "n_trials": 50,
                "seed": 0,
            }

            result = compute_playoff_odds_from_request(payload)

            assert result["matched_player_count"] == 2
            assert "Missing" in result["unmatched_player_names"]
            assert len(result["teams"]) == 2
            for t in result["teams"]:
                assert 0.0 <= t["playoff_odds"] <= 1.0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/backend/analysis/test_playoff_odds.py::TestComputePlayoffOddsFromRequest -v`
Expected: FAIL with `ImportError: cannot import name 'compute_playoff_odds_from_request'`.

- [ ] **Step 3: Implement adapter**

Append to `backend/analysis/playoff_odds.py`:

```python
from backend.analysis.waivers import resolve_espn_names_to_mlbid
from backend.analysis.matchup import _load_projections


def _normalize_name(name: str) -> str:
    """Match the normalization used by resolve_espn_names_to_mlbid."""
    import unicodedata
    return "".join(
        c for c in unicodedata.normalize("NFD", name)
        if unicodedata.category(c) != "Mn"
    ).lower()


def compute_playoff_odds_from_request(payload: dict) -> dict:
    """Resolve names → mlb_ids, load projections, run sim, return response dict."""
    season = payload["season"]
    teams = payload["teams"]

    # Flatten all roster players for name resolution
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

    # Build per-team PlayerProjection lists; track IL and unmatched
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
            mlb_id = name_to_id.get(_normalize_name(p["name"]))
            if mlb_id is None or mlb_id not in projections:
                unmatched_names.add(p["name"])
                continue
            proj = projections[mlb_id]
            # Override position with ESPN-derived eligible_positions for lineup opt
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

    # Build remaining_schedule as tuples
    schedule = [
        (m["matchup_period_id"], m["home_team_id"], m["away_team_id"])
        for m in payload["remaining_schedule"]
    ]
    # period_weights keys may be strings via JSON
    period_weights = {int(k): float(v) for k, v in payload["period_weights"].items()}

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
    )

    return {
        "teams": teams_out,
        "n_trials": payload.get("n_trials", 5000),
        "matched_player_count": matched_count,
        "unmatched_player_names": sorted(unmatched_names),
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/backend/analysis/test_playoff_odds.py::TestComputePlayoffOddsFromRequest -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/analysis/playoff_odds.py tests/backend/analysis/test_playoff_odds.py
git commit -m "feat(playoff-odds): payload-to-engine adapter"
```

---

## Task 8: FastAPI route

**Files:**
- Modify: `backend/api/routes.py`

Register `POST /api/playoff-odds` that calls `compute_playoff_odds_from_request`.

- [ ] **Step 1: Add the import and the route**

Open `backend/api/routes.py`. After the existing imports, add:

```python
from backend.analysis.playoff_odds import compute_playoff_odds_from_request
from backend.api.playoff_odds_models import PlayoffOddsRequest, PlayoffOddsResponse
```

At the bottom of the file, add:

```python
@router.post("/playoff-odds", response_model=PlayoffOddsResponse)
def playoff_odds(req: PlayoffOddsRequest) -> PlayoffOddsResponse:
    """Run Monte Carlo simulation of remaining season → playoff odds per team."""
    payload = req.model_dump()
    result = compute_playoff_odds_from_request(payload)
    return PlayoffOddsResponse(**result)
```

- [ ] **Step 2: Smoke-test the import**

Run: `python -c "from backend.api.routes import router; print([r.path for r in router.routes if hasattr(r, 'path')])"`
Expected: prints a list that includes `/playoff-odds`.

- [ ] **Step 3: Commit**

```bash
git add backend/api/routes.py
git commit -m "feat(playoff-odds): register FastAPI endpoint"
```

---

## Task 9: TS — payload builder

**Files:**
- Create: `src/lib/playoff-odds-payload.ts`
- Test: `src/__tests__/lib/playoff-odds-payload.test.ts`

A pure helper that assembles the Python-bound payload from ESPN data: teams + records, remaining schedule, period weights computed from `MATCHUP_SCHEDULE`.

- [ ] **Step 1: Write the failing test**

```typescript
// src/__tests__/lib/playoff-odds-payload.test.ts
import {
  buildPlayoffOddsPayload,
  computePeriodWeights,
} from '@/lib/playoff-odds-payload'

describe('computePeriodWeights', () => {
  it('weights each period by its day count proportionally', () => {
    const weights = computePeriodWeights([1, 2], {
      1: ['2026-05-04', '2026-05-10'],   // 7 days
      2: ['2026-05-11', '2026-05-24'],   // 14 days
    })
    expect(weights[1]).toBeCloseTo(7 / 21, 5)
    expect(weights[2]).toBeCloseTo(14 / 21, 5)
  })

  it('returns equal weights when ranges have the same length', () => {
    const weights = computePeriodWeights([1, 2, 3], {
      1: ['2026-05-04', '2026-05-10'],
      2: ['2026-05-11', '2026-05-17'],
      3: ['2026-05-18', '2026-05-24'],
    })
    expect(weights[1]).toBeCloseTo(1 / 3, 5)
    expect(weights[2]).toBeCloseTo(1 / 3, 5)
    expect(weights[3]).toBeCloseTo(1 / 3, 5)
  })
})

describe('buildPlayoffOddsPayload', () => {
  const teams = [
    { id: 1, name: 'T1', record: { overall: { wins: 10, losses: 5, ties: 0 } } },
    { id: 2, name: 'T2', record: { overall: { wins: 5, losses: 10, ties: 0 } } },
  ] as any

  const rosters = {
    1: [
      { player: { fullName: 'A', defaultPositionId: 7,
                  eligibleSlots: [5, 12, 16], injuryStatus: 'ACTIVE' },
        lineupSlotId: 5 },
    ],
    2: [
      { player: { fullName: 'B', defaultPositionId: 1,
                  eligibleSlots: [14, 13, 16], injuryStatus: 'ACTIVE' },
        lineupSlotId: 14 },
    ],
  } as any

  const fullSchedule = [
    { matchupPeriodId: 1, home: { teamId: 1 }, away: { teamId: 2 } },
    { matchupPeriodId: 2, home: { teamId: 2 }, away: { teamId: 1 } },
    { matchupPeriodId: 3, home: { teamId: 1 }, away: { teamId: 2 } },
  ]

  it('emits remaining schedule from currentMatchupPeriod onward', () => {
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
      playoffSlots: 1,
      nTrials: 100,
    })

    expect(payload.remaining_schedule).toHaveLength(2)
    expect(payload.remaining_schedule[0].matchup_period_id).toBe(2)
    expect(payload.period_weights['2']).toBeCloseTo(0.5, 5)
    expect(payload.teams).toHaveLength(2)
    expect(payload.teams[0].current_wins).toBe(10)
    expect(payload.teams[0].roster[0].name).toBe('A')
    expect(payload.teams[0].roster[0].eligible_positions).toBe('OF/UTIL')
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npx jest src/__tests__/lib/playoff-odds-payload.test.ts`
Expected: FAIL with "Cannot find module '@/lib/playoff-odds-payload'".

- [ ] **Step 3: Implement the payload builder**

Create `src/lib/playoff-odds-payload.ts`:

```typescript
// src/lib/playoff-odds-payload.ts
//
// Pure helper: shape ESPN data into the Python /playoff-odds payload.

import type { ESPNTeam, ESPNRosterEntry } from '@/lib/espn-api'

const ESPN_POSITION_MAP: Record<number, string> = {
  1: 'SP', 2: 'C', 3: '1B', 4: '2B', 5: '3B', 6: 'SS',
  7: 'LF', 8: 'CF', 9: 'RF', 10: 'DH', 11: 'RP',
}

const ESPN_LINEUP_SLOT_MAP: Record<number, string> = {
  0: 'C', 1: '1B', 2: '2B', 3: '3B', 4: 'SS', 5: 'OF',
  6: 'OF', 7: 'OF', 10: 'DH', 12: 'UTIL', 13: 'P', 14: 'SP', 15: 'RP',
}

function daysBetweenInclusive(start: string, end: string): number {
  const s = new Date(start + 'T00:00:00').getTime()
  const e = new Date(end + 'T00:00:00').getTime()
  return Math.round((e - s) / (1000 * 60 * 60 * 24)) + 1
}

export function computePeriodWeights(
  periodIds: number[],
  matchupSchedule: Record<number, [string, string]>,
): Record<number, number> {
  const days: Record<number, number> = {}
  let total = 0
  for (const id of periodIds) {
    const range = matchupSchedule[id]
    if (!range) continue
    const d = daysBetweenInclusive(range[0], range[1])
    days[id] = d
    total += d
  }
  const weights: Record<number, number> = {}
  for (const id of periodIds) {
    weights[id] = total > 0 ? (days[id] || 0) / total : 0
  }
  return weights
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
  playoffSlots: number
  nTrials: number
  seed?: number
}

export function buildPlayoffOddsPayload(args: BuildArgs) {
  const remaining = args.fullSchedule.filter(
    m => m.matchupPeriodId >= args.currentMatchupPeriod
        && m.matchupPeriodId <= args.finalRegularSeasonPeriod,
  )
  const periodIds = Array.from(
    new Set(remaining.map(m => m.matchupPeriodId)),
  ).sort((a, b) => a - b)

  const period_weights = computePeriodWeights(periodIds, args.matchupSchedule)

  const teamsOut = args.teams.map(t => {
    const entries = args.rosters[t.id] || []
    return {
      team_id: t.id,
      team_name: [t.location, t.nickname].filter(Boolean).join(' ').trim()
                || `Team ${t.id}`,
      current_wins: t.record?.overall?.wins ?? 0,
      current_losses: t.record?.overall?.losses ?? 0,
      current_ties: t.record?.overall?.ties ?? 0,
      roster: entries.map(e => {
        const p = e.player
        const posId = p?.defaultPositionId ?? 0
        const position = ESPN_POSITION_MAP[posId] || ''
        const playerType = posId === 1 || posId === 11 ? 'pitcher' : 'hitter'
        const eligible = (p?.eligibleSlots || [])
          .map((s: number) => ESPN_LINEUP_SLOT_MAP[s])
          .filter(Boolean)
          .join('/')
        return {
          name: p?.fullName || `Player ${e.playerId}`,
          position,
          player_type: playerType,
          lineup_slot_id: e.lineupSlotId,
          eligible_positions: eligible,
          injury_status: p?.injuryStatus || 'ACTIVE',
        }
      }),
    }
  })

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
    playoff_slots: args.playoffSlots,
    n_trials: args.nTrials,
    seed: args.seed,
  }
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `npx jest src/__tests__/lib/playoff-odds-payload.test.ts`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/lib/playoff-odds-payload.ts src/__tests__/lib/playoff-odds-payload.test.ts
git commit -m "feat(playoff-odds): TS payload builder"
```

---

## Task 10: Next.js API route

**Files:**
- Create: `src/app/api/playoff-odds/route.ts`

Orchestrator: fetch league, teams, rosters, full schedule from ESPN; call payload builder; POST to Python backend; return result.

- [ ] **Step 1: Create the route file**

```typescript
// src/app/api/playoff-odds/route.ts
import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { ESPNApi } from '@/lib/espn-api'
import { MATCHUP_SCHEDULE } from '@/lib/matchup-schedule'
import { buildPlayoffOddsPayload } from '@/lib/playoff-odds-payload'

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000'

export async function POST(request: NextRequest) {
  try {
    const body = await request.json()
    const {
      leagueId,
      season = '2026',
      playoffSlots = 6,
      nTrials = 5000,
      seed,
    } = body

    if (!leagueId) {
      return NextResponse.json(
        { error: 'Missing required field: leagueId' },
        { status: 400 },
      )
    }

    const league = await prisma.league.findUnique({ where: { id: leagueId } })
    if (!league) {
      return NextResponse.json({ error: 'League not found' }, { status: 404 })
    }
    const settingsBlob = league.settings as any
    const credentials = settingsBlob?.credentials
    if (!credentials?.swid || !credentials?.espn_s2) {
      return NextResponse.json(
        { error: 'ESPN credentials not configured. Set them up in Settings.' },
        { status: 400 },
      )
    }
    const espnSettings = { swid: credentials.swid, espn_s2: credentials.espn_s2 }

    const [leagueData, teamsAndFaab, rosters, fullSchedule] = await Promise.all([
      ESPNApi.getLeague(league.externalId, season, espnSettings),
      ESPNApi.getLeagueTeamsAndFaab(league.externalId, season, espnSettings),
      ESPNApi.getRosters(league.externalId, season, espnSettings),
      ESPNApi.getFullSchedule(league.externalId, season, espnSettings),
    ])

    const currentMatchupPeriod = leagueData.status?.currentMatchupPeriod
      || leagueData.currentMatchupPeriod
      || 1
    // Pull regular-season length from settings (matchupPeriodCount).
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
      meta: {
        current_matchup_period: currentMatchupPeriod,
        final_regular_season_period: finalRegularSeasonPeriod,
        playoff_slots: playoffSlots,
        n_trials: nTrials,
      },
    })
  } catch (error: any) {
    console.error('Playoff odds error:', error)
    return NextResponse.json(
      { error: error.message || 'Failed to compute playoff odds' },
      { status: 500 },
    )
  }
}
```

- [ ] **Step 2: Verify the route compiles**

Run: `npx tsc --noEmit -p tsconfig.json`
Expected: no errors related to `src/app/api/playoff-odds/route.ts`. (Pre-existing errors in other files are acceptable; only check this file.)

- [ ] **Step 3: Commit**

```bash
git add src/app/api/playoff-odds/route.ts
git commit -m "feat(playoff-odds): Next.js API orchestrator"
```

---

## Task 11: Frontend page

**Files:**
- Create: `src/app/playoff-odds/page.tsx`

Show a table of teams sorted by playoff odds. Each row: rank, team name (highlight your team), current W-L-T, projected final W-L-T, playoff odds %. Form has fields for n_trials and run button.

- [ ] **Step 1: Find the leagueId/teamId pattern used by other pages**

Look at how `src/app/waivers/page.tsx` reads credentials/league from localStorage. The new page should follow the same pattern. Quick check:

```bash
grep -n "localStorage" src/app/waivers/page.tsx | head -5
```

You should see lines reading `localStorage.getItem('selectedLeagueId')` and `'selectedTeamId'`. Use the same keys.

- [ ] **Step 2: Create the page**

```tsx
// src/app/playoff-odds/page.tsx
'use client'

import { useEffect, useState } from 'react'

interface TeamOdds {
  team_id: number
  team_name: string
  current_wins: number
  current_losses: number
  current_ties: number
  playoff_odds: number
  avg_final_wins: number
  avg_final_losses: number
  avg_final_ties: number
  avg_final_rank: number
}

interface Response {
  teams: TeamOdds[]
  n_trials: number
  matched_player_count: number
  unmatched_player_names: string[]
  meta: {
    current_matchup_period: number
    final_regular_season_period: number
    playoff_slots: number
    n_trials: number
  }
}

export default function PlayoffOddsPage() {
  const [leagueId, setLeagueId] = useState<string | null>(null)
  const [myTeamId, setMyTeamId] = useState<number | null>(null)
  const [nTrials, setNTrials] = useState(5000)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [data, setData] = useState<Response | null>(null)

  useEffect(() => {
    setLeagueId(localStorage.getItem('selectedLeagueId'))
    const tid = localStorage.getItem('selectedTeamId')
    setMyTeamId(tid ? parseInt(tid) : null)
  }, [])

  const run = async () => {
    if (!leagueId) {
      setError('Select a league in Settings first.')
      return
    }
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/playoff-odds', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ leagueId, nTrials }),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.error || `HTTP ${res.status}`)
      }
      const json = (await res.json()) as Response
      setData(json)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-5xl mx-auto p-6">
      <h1 className="text-2xl font-bold mb-2">Playoff Odds</h1>
      <p className="text-gray-600 mb-4">
        Monte Carlo simulation of the remaining regular season. Top{' '}
        {data?.meta?.playoff_slots ?? 6} teams make the playoffs.
      </p>

      <div className="flex items-center gap-3 mb-6">
        <label className="text-sm">Trials:</label>
        <input
          type="number"
          value={nTrials}
          onChange={e => setNTrials(parseInt(e.target.value) || 1000)}
          min={100}
          max={50000}
          step={500}
          className="border rounded px-2 py-1 w-24"
        />
        <button
          onClick={run}
          disabled={loading}
          className="bg-blue-600 text-white px-4 py-1 rounded disabled:opacity-50"
        >
          {loading ? 'Simulating…' : 'Run simulation'}
        </button>
      </div>

      {error && <div className="text-red-600 mb-4">{error}</div>}

      {data && (
        <>
          <div className="text-sm text-gray-500 mb-3">
            {data.n_trials} trials · {data.matched_player_count} players matched
            {data.unmatched_player_names.length > 0 &&
              ` · ${data.unmatched_player_names.length} unmatched`}
          </div>
          <table className="w-full text-sm">
            <thead className="bg-gray-100">
              <tr>
                <th className="text-left px-3 py-2">#</th>
                <th className="text-left px-3 py-2">Team</th>
                <th className="text-right px-3 py-2">Current</th>
                <th className="text-right px-3 py-2">Proj. Final</th>
                <th className="text-right px-3 py-2">Avg Rank</th>
                <th className="text-right px-3 py-2">Playoff %</th>
              </tr>
            </thead>
            <tbody>
              {data.teams.map((t, i) => {
                const isMe = t.team_id === myTeamId
                const inPlayoffs = i < (data.meta?.playoff_slots ?? 6)
                return (
                  <tr
                    key={t.team_id}
                    className={`border-b ${isMe ? 'bg-yellow-50 font-semibold' : ''}`}
                  >
                    <td className="px-3 py-2">{i + 1}</td>
                    <td className="px-3 py-2">
                      {t.team_name}
                      {isMe && ' (you)'}
                    </td>
                    <td className="text-right px-3 py-2">
                      {t.current_wins}-{t.current_losses}-{t.current_ties}
                    </td>
                    <td className="text-right px-3 py-2">
                      {t.avg_final_wins.toFixed(1)}-
                      {t.avg_final_losses.toFixed(1)}-
                      {t.avg_final_ties.toFixed(1)}
                    </td>
                    <td className="text-right px-3 py-2">
                      {t.avg_final_rank.toFixed(2)}
                    </td>
                    <td
                      className={`text-right px-3 py-2 ${
                        inPlayoffs ? 'text-green-600' : 'text-gray-500'
                      }`}
                    >
                      {(t.playoff_odds * 100).toFixed(1)}%
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </>
      )}
    </div>
  )
}
```

- [ ] **Step 3: Verify the page compiles**

Run: `npx tsc --noEmit -p tsconfig.json`
Expected: no errors related to `src/app/playoff-odds/page.tsx`.

- [ ] **Step 4: Commit**

```bash
git add src/app/playoff-odds/page.tsx
git commit -m "feat(playoff-odds): UI page with team odds table"
```

---

## Task 12: Add nav link

**Files:**
- Modify: `src/components/Navigation.tsx` (path may differ; locate first)

- [ ] **Step 1: Locate the navigation component**

Run:
```bash
grep -rn "href=\"/waivers\"" src/components src/app --include="*.tsx" | head -3
```

You'll find the file that lists nav links. Open it.

- [ ] **Step 2: Add a `Playoff Odds` link**

Insert next to the existing waivers / matchup nav links. Example pattern (adjust to match the file's existing JSX):

```tsx
<Link href="/playoff-odds" className="...">Playoff Odds</Link>
```

Match the styling of adjacent links exactly.

- [ ] **Step 3: Verify the page is reachable**

Start the dev server in another shell: `npm run dev`. Visit `http://localhost:3000` and confirm the new "Playoff Odds" link appears in the nav and routes to `/playoff-odds`.

- [ ] **Step 4: Commit**

```bash
git add src/components/Navigation.tsx
git commit -m "feat(playoff-odds): add nav link"
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

- [ ] **Step 2: Visit `/playoff-odds`**

Open `http://localhost:3000/playoff-odds`. With your real ESPN credentials configured (per the existing `selectedLeagueId` localStorage entry pointing at `espn_77166_2026` — note this league row may need to be created first via the existing leagues sync flow if the DB still only has the 2025 row).

- [ ] **Step 3: Run a simulation with 1000 trials and confirm the result**

- The current matchup period should be displayed (~5).
- Top team's playoff odds should be > 95% (Rikers Island and Last Place Champs are clear leaders).
- Your team (The Notorious G.I.B.) should appear with a low single-digit %.
- `unmatched_player_names` should be empty or near-empty (any players not in the rankings table will appear here).

- [ ] **Step 4: Run with 5000 trials and confirm consistency**

Re-run; top-team % should not change by more than ~1pt, validating the variance assumption.

- [ ] **Step 5: Commit any final polish (only if changes were needed)**

If the smoke test exposed bugs, fix them with TDD per the affected task and commit. If it passed clean, no commit needed.

---

## Self-Review Notes

Spec coverage check:
- ESPN data fetch (schedule + standings + rosters) → Tasks 1, 10
- Per-team weekly projection → Task 3
- Per-matchup simulation → Task 4
- Full-season simulation → Task 5
- Monte Carlo aggregation → Task 6
- Name resolution + projection loading → Task 7
- API surface (FastAPI + Next.js) → Tasks 8, 10
- UI → Task 11
- Discoverability → Task 12
- Verification → Task 13

Type consistency check:
- `PlayerProjection` fields used identically across all Python tasks (Tasks 3–7).
- `simulate_head_to_head` returns `(wins, losses, ties)` for team A; `simulate_one_season` correctly inverts for team B.
- TS `team_name` from ESPN combines `location` + `nickname`; Python preserves it through `team_names` map.
- `period_weights` is `Record<number, number>` in TS and `dict[int, float]` in Python. JSON keys arrive as strings; Task 7's adapter explicitly does `int(k)`.
