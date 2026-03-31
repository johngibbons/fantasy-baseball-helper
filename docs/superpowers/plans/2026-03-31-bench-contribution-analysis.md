# Bench Contribution Rate Analysis — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Monte Carlo simulation that calculates empirical bench player contribution rates by simulating optimal daily lineups across a full MLB season.

**Architecture:** A Python CLI script (`sweep_bench_contributions.py`) calls a core engine module (`backend/analysis/bench_contributions.py`). The engine fetches the MLB season schedule, loads the user's ESPN roster + projections, and runs N iterations of day-by-day lineup optimization to measure how often each bench player actually starts. A sweep mode tests different bench hitter/pitcher compositions.

**Tech Stack:** Python 3.12, httpx (MLB Stats API), sqlite3 (rankings DB), existing `optimize_daily_lineup` from `matchup.py`, pytest.

---

## File Structure

| File | Responsibility |
|------|---------------|
| `backend/analysis/bench_contributions.py` | Core simulation: schedule fetching, availability model, Monte Carlo daily lineup sim, contribution rate aggregation, sweep logic |
| `sweep_bench_contributions.py` | CLI entry point: arg parsing, ESPN roster fetch, calls engine, prints results |
| `tests/backend/analysis/test_bench_contributions.py` | Unit tests for availability model, SP start distribution, daily simulation, and contribution rate calculation |

---

### Task 1: MLB Schedule Fetcher

**Files:**
- Create: `tests/backend/analysis/test_bench_contributions.py`
- Create: `backend/analysis/bench_contributions.py`

- [ ] **Step 1: Write failing test for schedule parsing**

```python
# tests/backend/analysis/test_bench_contributions.py

import pytest
from unittest.mock import patch, MagicMock
from backend.analysis.bench_contributions import parse_schedule_response


class TestScheduleParsing:
    def test_parses_dates_and_teams(self):
        """parse_schedule_response extracts date -> set of team abbrevs."""
        fake_response = {
            "dates": [
                {
                    "date": "2026-04-01",
                    "games": [
                        {
                            "gameType": "R",
                            "status": {"abstractGameCode": "S"},
                            "teams": {
                                "home": {"team": {"id": 147}},  # NYY
                                "away": {"team": {"id": 111}},  # BOS
                            },
                        },
                    ],
                },
                {
                    "date": "2026-04-02",
                    "games": [
                        {
                            "gameType": "R",
                            "status": {"abstractGameCode": "S"},
                            "teams": {
                                "home": {"team": {"id": 119}},  # LAD
                                "away": {"team": {"id": 137}},  # SF
                            },
                        },
                    ],
                },
            ]
        }
        schedule = parse_schedule_response(fake_response)
        assert schedule["2026-04-01"] == {"NYY", "BOS"}
        assert schedule["2026-04-02"] == {"LAD", "SF"}

    def test_skips_non_regular_season_games(self):
        fake_response = {
            "dates": [
                {
                    "date": "2026-04-01",
                    "games": [
                        {
                            "gameType": "E",  # Exhibition
                            "status": {"abstractGameCode": "S"},
                            "teams": {
                                "home": {"team": {"id": 147}},
                                "away": {"team": {"id": 111}},
                            },
                        },
                    ],
                },
            ]
        }
        schedule = parse_schedule_response(fake_response)
        assert schedule.get("2026-04-01", set()) == set()

    def test_skips_finished_games(self):
        fake_response = {
            "dates": [
                {
                    "date": "2026-04-01",
                    "games": [
                        {
                            "gameType": "R",
                            "status": {"abstractGameCode": "F"},
                            "teams": {
                                "home": {"team": {"id": 147}},
                                "away": {"team": {"id": 111}},
                            },
                        },
                    ],
                },
            ]
        }
        schedule = parse_schedule_response(fake_response)
        assert schedule.get("2026-04-01", set()) == set()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/backend/analysis/test_bench_contributions.py::TestScheduleParsing -v`
Expected: FAIL — `cannot import name 'parse_schedule_response'`

- [ ] **Step 3: Implement schedule parser**

```python
# backend/analysis/bench_contributions.py

"""Bench contribution rate analysis via full-season daily lineup simulation.

Calculates empirical bench player contribution rates by simulating optimal
daily lineups across a full MLB season using Monte Carlo methods.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

MLB_API_BASE = "https://statsapi.mlb.com/api/v1"

# MLB team ID -> abbreviation (matches mlb-schedule.ts)
MLB_TEAM_ABBREVS: dict[int, str] = {
    108: "LAA", 109: "ARI", 110: "BAL", 111: "BOS", 112: "CHC",
    113: "CIN", 114: "CLE", 115: "COL", 116: "DET", 117: "HOU",
    118: "KC", 119: "LAD", 120: "WSH", 121: "NYM", 133: "OAK",
    134: "PIT", 135: "SD", 136: "SEA", 137: "SF", 138: "STL",
    139: "TB", 140: "TEX", 141: "TOR", 142: "MIN", 143: "PHI",
    144: "ATL", 145: "CWS", 146: "MIA", 147: "NYY", 158: "MIL",
}

IP_PER_START = 5.5  # Modern MLB average innings per start


def parse_schedule_response(data: dict) -> dict[str, set[str]]:
    """Parse MLB Stats API schedule response into date -> set of team abbrevs.

    Only includes regular-season games that haven't finished yet.
    """
    schedule: dict[str, set[str]] = {}
    for date_entry in data.get("dates", []):
        date = date_entry["date"]
        teams_today: set[str] = set()
        for game in date_entry.get("games", []):
            if game.get("gameType") != "R":
                continue
            if game.get("status", {}).get("abstractGameCode") == "F":
                continue
            home_id = game.get("teams", {}).get("home", {}).get("team", {}).get("id")
            away_id = game.get("teams", {}).get("away", {}).get("team", {}).get("id")
            if home_id and home_id in MLB_TEAM_ABBREVS:
                teams_today.add(MLB_TEAM_ABBREVS[home_id])
            if away_id and away_id in MLB_TEAM_ABBREVS:
                teams_today.add(MLB_TEAM_ABBREVS[away_id])
        if teams_today:
            schedule[date] = teams_today
    return schedule


def fetch_season_schedule(start_date: str, end_date: str) -> dict[str, set[str]]:
    """Fetch full-season MLB schedule from Stats API."""
    url = f"{MLB_API_BASE}/schedule"
    resp = httpx.get(url, params={"sportId": 1, "startDate": start_date, "endDate": end_date})
    resp.raise_for_status()
    return parse_schedule_response(resp.json())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/backend/analysis/test_bench_contributions.py::TestScheduleParsing -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/analysis/bench_contributions.py tests/backend/analysis/test_bench_contributions.py
git commit -m "feat(bench): add MLB schedule fetcher and parser"
```

---

### Task 2: Player Availability Model

**Files:**
- Modify: `tests/backend/analysis/test_bench_contributions.py`
- Modify: `backend/analysis/bench_contributions.py`

- [ ] **Step 1: Write failing test for hitter availability**

```python
# Add to tests/backend/analysis/test_bench_contributions.py

from backend.analysis.bench_contributions import (
    parse_schedule_response,
    RosterPlayer,
    compute_availability_rate,
)


class TestAvailabilityModel:
    def test_fulltime_hitter_availability(self):
        """Full-time hitter (600 PA, 162 team games) -> ~0.93 availability."""
        player = RosterPlayer(
            mlb_id=1, name="Juan Soto", position="OF", player_type="hitter",
            eligible_positions="OF/DH", team="NYY",
            proj_pa=600, proj_ip=0.0, overall_rank=5,
        )
        rate = compute_availability_rate(player, team_season_games=162)
        assert rate == pytest.approx(600 / 4.0 / 162, abs=0.01)  # ~0.926

    def test_platoon_hitter_availability(self):
        """Platoon player (350 PA) -> ~0.54 availability."""
        player = RosterPlayer(
            mlb_id=2, name="Platoon Guy", position="OF", player_type="hitter",
            eligible_positions="OF", team="NYY",
            proj_pa=350, proj_ip=0.0, overall_rank=200,
        )
        rate = compute_availability_rate(player, team_season_games=162)
        assert rate == pytest.approx(350 / 4.0 / 162, abs=0.01)  # ~0.540

    def test_hitter_availability_capped_at_1(self):
        """Very high PA player should be capped at 1.0."""
        player = RosterPlayer(
            mlb_id=3, name="Iron Man", position="SS", player_type="hitter",
            eligible_positions="SS", team="NYY",
            proj_pa=700, proj_ip=0.0, overall_rank=1,
        )
        rate = compute_availability_rate(player, team_season_games=162)
        assert rate == 1.0

    def test_sp_projected_starts(self):
        """SP projected starts = proj_ip / 5.5."""
        player = RosterPlayer(
            mlb_id=10, name="Corbin Burnes", position="SP", player_type="pitcher",
            eligible_positions="SP", team="BAL",
            proj_pa=0, proj_ip=180.0, overall_rank=20,
        )
        rate = compute_availability_rate(player, team_season_games=162)
        # For SPs, return projected_starts / team_games (used for scheduling, not daily roll)
        expected = round(180.0 / 5.5) / 162
        assert rate == pytest.approx(expected, abs=0.01)

    def test_rp_always_available(self):
        """RPs are always available when their team plays."""
        player = RosterPlayer(
            mlb_id=20, name="Edwin Diaz", position="RP", player_type="pitcher",
            eligible_positions="RP", team="NYM",
            proj_pa=0, proj_ip=60.0, overall_rank=80,
        )
        rate = compute_availability_rate(player, team_season_games=162)
        assert rate == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/backend/analysis/test_bench_contributions.py::TestAvailabilityModel -v`
Expected: FAIL — `cannot import name 'RosterPlayer'`

- [ ] **Step 3: Implement RosterPlayer and availability model**

Add to `backend/analysis/bench_contributions.py`:

```python
@dataclass
class RosterPlayer:
    """Player on a fantasy roster with projection data for simulation."""
    mlb_id: int
    name: str
    position: str           # Primary position (SP, RP, OF, C, etc.)
    player_type: str        # "hitter" or "pitcher"
    eligible_positions: str  # Slash-separated (e.g. "SS/2B")
    team: str               # MLB team abbreviation
    proj_pa: int = 0
    proj_ip: float = 0.0
    overall_rank: int = 9999
    # Full projection stats for stat impact calculation
    proj_r: int = 0
    proj_tb: int = 0
    proj_rbi: int = 0
    proj_sb: int = 0
    proj_obp: float = 0.0
    proj_k: int = 0
    proj_qs: int = 0
    proj_era: float = 0.0
    proj_whip: float = 0.0
    proj_svhd: int = 0


def _is_sp(player: RosterPlayer) -> bool:
    """Determine if a pitcher is an SP (vs RP)."""
    if player.player_type != "pitcher":
        return False
    if "SP" in player.eligible_positions.split("/"):
        return True
    # Fallback: high IP = starter
    return player.proj_ip >= 80


def compute_availability_rate(player: RosterPlayer, team_season_games: int) -> float:
    """Compute how often a player is available to play on days their team has a game.

    Returns:
        Float 0-1. For hitters: fraction of team games they play in.
        For SPs: projected_starts / team_games (used for start distribution).
        For RPs: 1.0 (available every day their team plays).
    """
    if team_season_games <= 0:
        return 0.0

    if player.player_type == "hitter":
        games_played = player.proj_pa / 4.0
        return min(1.0, games_played / team_season_games)

    if _is_sp(player):
        projected_starts = round(player.proj_ip / IP_PER_START)
        return projected_starts / team_season_games

    # RP: available whenever team plays
    return 1.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/backend/analysis/test_bench_contributions.py::TestAvailabilityModel -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/analysis/bench_contributions.py tests/backend/analysis/test_bench_contributions.py
git commit -m "feat(bench): add player availability model"
```

---

### Task 3: SP Start Distribution

**Files:**
- Modify: `tests/backend/analysis/test_bench_contributions.py`
- Modify: `backend/analysis/bench_contributions.py`

- [ ] **Step 1: Write failing test for SP start scheduling**

```python
# Add to tests/backend/analysis/test_bench_contributions.py

import random

from backend.analysis.bench_contributions import (
    parse_schedule_response,
    RosterPlayer,
    compute_availability_rate,
    distribute_sp_starts,
)


class TestSPStartDistribution:
    def test_correct_number_of_starts(self):
        """distribute_sp_starts returns exactly projected_starts dates."""
        team_game_dates = [f"2026-04-{d:02d}" for d in range(1, 31)]  # 30 game dates
        rng = random.Random(42)
        starts = distribute_sp_starts(
            projected_starts=6,
            team_game_dates=team_game_dates,
            rng=rng,
        )
        assert len(starts) == 6
        # All start dates must be valid team game dates
        for d in starts:
            assert d in team_game_dates

    def test_starts_are_unique(self):
        """No duplicate start dates."""
        team_game_dates = [f"2026-04-{d:02d}" for d in range(1, 31)]
        rng = random.Random(42)
        starts = distribute_sp_starts(
            projected_starts=6,
            team_game_dates=team_game_dates,
            rng=rng,
        )
        assert len(starts) == len(set(starts))

    def test_starts_roughly_evenly_spaced(self):
        """Starts should be spread across the schedule, not clustered."""
        team_game_dates = [f"2026-04-{d:02d}" for d in range(1, 31)]
        rng = random.Random(42)
        starts = distribute_sp_starts(
            projected_starts=6,
            team_game_dates=team_game_dates,
            rng=rng,
        )
        indices = sorted(team_game_dates.index(d) for d in starts)
        gaps = [indices[i + 1] - indices[i] for i in range(len(indices) - 1)]
        # With 6 starts in 30 games, ideal gap is 5. Allow 2-8 range with jitter.
        for gap in gaps:
            assert 1 <= gap <= 10

    def test_more_starts_than_games_caps(self):
        """If projected_starts > team_game_dates, return all dates."""
        team_game_dates = ["2026-04-01", "2026-04-02", "2026-04-03"]
        rng = random.Random(42)
        starts = distribute_sp_starts(
            projected_starts=10,
            team_game_dates=team_game_dates,
            rng=rng,
        )
        assert len(starts) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/backend/analysis/test_bench_contributions.py::TestSPStartDistribution -v`
Expected: FAIL — `cannot import name 'distribute_sp_starts'`

- [ ] **Step 3: Implement SP start distribution**

Add to `backend/analysis/bench_contributions.py`:

```python
def distribute_sp_starts(
    projected_starts: int,
    team_game_dates: list[str],
    rng: random.Random,
) -> set[str]:
    """Distribute an SP's projected starts evenly across their team's schedule with jitter.

    Places starts at regular intervals (every Nth game), then applies +/-1 game
    of random jitter to simulate real rotation variability.

    Returns set of date strings when the SP is scheduled to start.
    """
    num_games = len(team_game_dates)
    if num_games == 0 or projected_starts <= 0:
        return set()
    if projected_starts >= num_games:
        return set(team_game_dates)

    # Place starts at evenly-spaced intervals
    interval = num_games / projected_starts
    ideal_indices = [round(i * interval) for i in range(projected_starts)]

    # Apply jitter: shift each by -1, 0, or +1, then clamp and deduplicate
    jittered: list[int] = []
    for idx in ideal_indices:
        shift = rng.choice([-1, 0, 1])
        new_idx = max(0, min(num_games - 1, idx + shift))
        jittered.append(new_idx)

    # Deduplicate: if two starts land on the same date, shift the second forward
    used: set[int] = set()
    final_indices: list[int] = []
    for idx in sorted(jittered):
        while idx in used and idx < num_games - 1:
            idx += 1
        if idx not in used:
            used.add(idx)
            final_indices.append(idx)

    return {team_game_dates[i] for i in final_indices}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/backend/analysis/test_bench_contributions.py::TestSPStartDistribution -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/analysis/bench_contributions.py tests/backend/analysis/test_bench_contributions.py
git commit -m "feat(bench): add SP start distribution with jitter"
```

---

### Task 4: Monte Carlo Daily Lineup Simulation

**Files:**
- Modify: `tests/backend/analysis/test_bench_contributions.py`
- Modify: `backend/analysis/bench_contributions.py`

- [ ] **Step 1: Write failing test for single-day simulation**

```python
# Add to tests/backend/analysis/test_bench_contributions.py

from backend.analysis.bench_contributions import (
    parse_schedule_response,
    RosterPlayer,
    compute_availability_rate,
    distribute_sp_starts,
    SimulationResult,
    simulate_season,
)


def _make_hitter(mlb_id: int, name: str, pos: str, team: str, pa: int = 600, rank: int = 50) -> RosterPlayer:
    return RosterPlayer(
        mlb_id=mlb_id, name=name, position=pos, player_type="hitter",
        eligible_positions=pos, team=team, proj_pa=pa, overall_rank=rank,
    )


def _make_pitcher(mlb_id: int, name: str, pos: str, team: str, ip: float = 180.0, rank: int = 50) -> RosterPlayer:
    return RosterPlayer(
        mlb_id=mlb_id, name=name, position=pos, player_type="pitcher",
        eligible_positions=pos, team=team, proj_ip=ip, overall_rank=rank,
    )


class TestSimulateSeason:
    def test_starter_contributes_more_than_bench(self):
        """A starting-caliber C should have higher contribution than a bench OF."""
        # 10 hitter starters + 2 bench hitters, all on same team
        roster = [
            _make_hitter(1, "C1", "C", "NYY", rank=10),
            _make_hitter(2, "1B1", "1B", "NYY", rank=11),
            _make_hitter(3, "2B1", "2B", "NYY", rank=12),
            _make_hitter(4, "3B1", "3B", "NYY", rank=13),
            _make_hitter(5, "SS1", "SS", "NYY", rank=14),
            _make_hitter(6, "OF1", "OF", "NYY", rank=15),
            _make_hitter(7, "OF2", "OF", "NYY", rank=16),
            _make_hitter(8, "OF3", "OF", "NYY", rank=17),
            _make_hitter(9, "UTIL1", "1B/DH", "NYY", rank=18),
            _make_hitter(10, "UTIL2", "OF/DH", "NYY", rank=19),
            # Bench hitters
            _make_hitter(11, "BenchH1", "OF", "NYY", rank=100),
            _make_hitter(12, "BenchH2", "1B", "NYY", rank=120),
        ]
        # Simple schedule: NYY plays every day for 10 days
        schedule = {f"2026-04-{d:02d}": {"NYY"} for d in range(1, 11)}

        result = simulate_season(roster, schedule, team_season_games={"NYY": 162}, num_sims=50, seed=42)

        # Starters should have ~0.9+ contribution rate
        starter_rate = result.player_contribution_rates[1]  # C1
        assert starter_rate > 0.8

        # Bench hitters should have lower rate (they only play on off days)
        bench_rate = result.player_contribution_rates[11]  # BenchH1
        assert bench_rate < starter_rate
        assert bench_rate > 0.0  # But they do get some starts

    def test_sp_only_contributes_on_start_days(self):
        """Bench SP contribution rate should reflect start frequency, not every day."""
        roster = [
            # Fill pitching starters
            _make_pitcher(20, "SP1", "SP", "NYY", ip=180.0, rank=10),
            _make_pitcher(21, "SP2", "SP", "NYY", ip=180.0, rank=11),
            _make_pitcher(22, "SP3", "SP", "NYY", ip=180.0, rank=12),
            _make_pitcher(23, "RP1", "RP", "NYY", ip=60.0, rank=30),
            _make_pitcher(24, "RP2", "RP", "NYY", ip=60.0, rank=31),
            _make_pitcher(25, "P1", "SP", "NYY", ip=170.0, rank=20),
            _make_pitcher(26, "P2", "RP", "NYY", ip=55.0, rank=40),
            # Bench SP
            _make_pitcher(27, "BenchSP", "SP", "NYY", ip=150.0, rank=60),
            # Need some hitters too (fill starter slots)
            _make_hitter(1, "C1", "C", "NYY", rank=10),
            _make_hitter(2, "1B1", "1B", "NYY", rank=11),
            _make_hitter(3, "2B1", "2B", "NYY", rank=12),
            _make_hitter(4, "3B1", "3B", "NYY", rank=13),
            _make_hitter(5, "SS1", "SS", "NYY", rank=14),
            _make_hitter(6, "OF1", "OF", "NYY", rank=15),
            _make_hitter(7, "OF2", "OF", "NYY", rank=16),
            _make_hitter(8, "OF3", "OF", "NYY", rank=17),
            _make_hitter(9, "UTIL1", "DH", "NYY", rank=18),
            _make_hitter(10, "UTIL2", "DH", "NYY", rank=19),
        ]
        schedule = {f"2026-04-{d:02d}": {"NYY"} for d in range(1, 31)}

        result = simulate_season(roster, schedule, team_season_games={"NYY": 162}, num_sims=50, seed=42)

        bench_sp_rate = result.player_contribution_rates[27]
        # Bench SP should have moderate contribution (starts some days, benched others)
        # With 7 pitcher slots and 8 pitchers, the bench SP starts when scheduled
        # but can't start on days another SP has priority
        assert 0.0 < bench_sp_rate < 0.8
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/backend/analysis/test_bench_contributions.py::TestSimulateSeason -v`
Expected: FAIL — `cannot import name 'SimulationResult'`

- [ ] **Step 3: Implement Monte Carlo simulation engine**

Add to `backend/analysis/bench_contributions.py`:

```python
from backend.analysis.matchup import optimize_daily_lineup


@dataclass
class SimulationResult:
    """Results from a full-season Monte Carlo lineup simulation."""
    player_contribution_rates: dict[int, float]   # mlb_id -> fraction of team games started
    player_days_started: dict[int, float]          # mlb_id -> avg days started across sims
    player_days_available: dict[int, float]        # mlb_id -> avg days team played


def simulate_season(
    roster: list[RosterPlayer],
    schedule: dict[str, set[str]],
    team_season_games: dict[str, int],
    num_sims: int = 200,
    seed: int | None = None,
) -> SimulationResult:
    """Run Monte Carlo daily lineup simulation across a full MLB season.

    For each iteration:
    1. Distribute each SP's projected starts across their team's schedule (with jitter)
    2. For each day, determine which players are available
    3. Run the lineup optimizer on available players
    4. Track starts vs bench

    Returns aggregated contribution rates averaged across all iterations.
    """
    rng = random.Random(seed)
    sorted_dates = sorted(schedule.keys())

    # Pre-compute team game dates
    team_game_dates: dict[str, list[str]] = {}
    for date in sorted_dates:
        for team in schedule[date]:
            team_game_dates.setdefault(team, []).append(date)

    # Pre-compute availability rates for hitters
    availability_rates: dict[int, float] = {}
    for p in roster:
        games = team_season_games.get(p.team, 162)
        availability_rates[p.mlb_id] = compute_availability_rate(p, games)

    # Track starts across all simulations
    total_starts: dict[int, int] = {p.mlb_id: 0 for p in roster}
    total_team_days: dict[int, int] = {p.mlb_id: 0 for p in roster}

    # Player lookup
    player_by_id = {p.mlb_id: p for p in roster}

    for _sim in range(num_sims):
        # Distribute SP starts for this iteration
        sp_start_dates: dict[int, set[str]] = {}
        for p in roster:
            if _is_sp(p):
                projected_starts = round(p.proj_ip / IP_PER_START)
                dates = team_game_dates.get(p.team, [])
                sp_start_dates[p.mlb_id] = distribute_sp_starts(projected_starts, dates, rng)

        # Simulate each day
        for date in sorted_dates:
            teams_playing = schedule[date]
            available_today: list[dict] = []

            for p in roster:
                if p.team not in teams_playing:
                    continue

                total_team_days[p.mlb_id] += 1

                if p.player_type == "hitter":
                    # Roll against availability rate
                    if rng.random() > availability_rates[p.mlb_id]:
                        continue
                elif _is_sp(p):
                    # SP only available on start days
                    if date not in sp_start_dates.get(p.mlb_id, set()):
                        continue
                # else RP: always available when team plays

                available_today.append({
                    "mlb_id": p.mlb_id,
                    "position": p.position,
                    "player_type": p.player_type,
                    "eligible_positions": p.eligible_positions,
                })

            # Run lineup optimizer
            lineup = optimize_daily_lineup(available_today)
            starting_ids = {pl["mlb_id"] for pl in lineup["starters"]}

            for mid in starting_ids:
                total_starts[mid] += 1

    # Compute averaged contribution rates
    contribution_rates: dict[int, float] = {}
    avg_starts: dict[int, float] = {}
    avg_available: dict[int, float] = {}

    for p in roster:
        mid = p.mlb_id
        team_days = total_team_days[mid]
        avg_available[mid] = team_days / num_sims
        avg_starts[mid] = total_starts[mid] / num_sims
        contribution_rates[mid] = total_starts[mid] / team_days if team_days > 0 else 0.0

    return SimulationResult(
        player_contribution_rates=contribution_rates,
        player_days_started=avg_starts,
        player_days_available=avg_available,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/backend/analysis/test_bench_contributions.py::TestSimulateSeason -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/analysis/bench_contributions.py tests/backend/analysis/test_bench_contributions.py
git commit -m "feat(bench): add Monte Carlo daily lineup simulation engine"
```

---

### Task 5: Contribution Rate Aggregation & Reporting

**Files:**
- Modify: `tests/backend/analysis/test_bench_contributions.py`
- Modify: `backend/analysis/bench_contributions.py`

- [ ] **Step 1: Write failing test for role-based aggregation**

```python
# Add to tests/backend/analysis/test_bench_contributions.py

from backend.analysis.bench_contributions import (
    parse_schedule_response,
    RosterPlayer,
    compute_availability_rate,
    distribute_sp_starts,
    SimulationResult,
    simulate_season,
    aggregate_by_role,
    RoleAggregation,
)


class TestAggregation:
    def test_aggregate_separates_starters_from_bench(self):
        """Players with >0.8 contribution rate are starters; others are bench."""
        rates = {1: 0.93, 2: 0.91, 3: 0.15, 4: 0.88, 5: 0.20}
        players = [
            _make_hitter(1, "H1", "C", "NYY", rank=10),
            _make_hitter(2, "H2", "1B", "NYY", rank=11),
            _make_hitter(3, "BenchH", "OF", "NYY", rank=100),
            _make_pitcher(4, "SP1", "SP", "NYY", ip=180.0, rank=20),
            _make_pitcher(5, "BenchRP", "RP", "NYY", ip=60.0, rank=90),
        ]
        result = aggregate_by_role(rates, players)
        assert len(result.bench_hitters) == 1
        assert result.bench_hitters[0].mlb_id == 3
        assert result.avg_bench_hitter_rate == pytest.approx(0.15, abs=0.01)

    def test_aggregate_bench_pitcher_sp_vs_rp(self):
        """Bench pitchers are split into SP and RP categories."""
        rates = {10: 0.30, 20: 0.12}
        players = [
            _make_pitcher(10, "BenchSP", "SP", "NYY", ip=150.0, rank=60),
            _make_pitcher(20, "BenchRP", "RP", "NYY", ip=55.0, rank=90),
        ]
        result = aggregate_by_role(rates, players)
        assert result.avg_bench_sp_rate == pytest.approx(0.30, abs=0.01)
        assert result.avg_bench_rp_rate == pytest.approx(0.12, abs=0.01)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/backend/analysis/test_bench_contributions.py::TestAggregation -v`
Expected: FAIL — `cannot import name 'aggregate_by_role'`

- [ ] **Step 3: Implement aggregation**

Add to `backend/analysis/bench_contributions.py`:

```python
# Threshold: players starting more than this fraction are considered "starters"
STARTER_THRESHOLD = 0.75


@dataclass
class RoleAggregation:
    """Aggregated contribution rates by player role."""
    bench_hitters: list[RosterPlayer]
    bench_sps: list[RosterPlayer]
    bench_rps: list[RosterPlayer]
    starter_hitters: list[RosterPlayer]
    starter_pitchers: list[RosterPlayer]
    avg_bench_hitter_rate: float
    avg_bench_sp_rate: float
    avg_bench_rp_rate: float


def aggregate_by_role(
    contribution_rates: dict[int, float],
    roster: list[RosterPlayer],
) -> RoleAggregation:
    """Classify players as starter/bench and compute per-role average contribution rates."""
    bench_hitters: list[RosterPlayer] = []
    bench_sps: list[RosterPlayer] = []
    bench_rps: list[RosterPlayer] = []
    starter_hitters: list[RosterPlayer] = []
    starter_pitchers: list[RosterPlayer] = []

    for p in roster:
        rate = contribution_rates.get(p.mlb_id, 0.0)
        if p.player_type == "hitter":
            if rate >= STARTER_THRESHOLD:
                starter_hitters.append(p)
            else:
                bench_hitters.append(p)
        else:
            if rate >= STARTER_THRESHOLD:
                starter_pitchers.append(p)
            elif _is_sp(p):
                bench_sps.append(p)
            else:
                bench_rps.append(p)

    def _avg_rate(players: list[RosterPlayer]) -> float:
        if not players:
            return 0.0
        return sum(contribution_rates.get(p.mlb_id, 0.0) for p in players) / len(players)

    # Sort bench players by rank (best first)
    bench_hitters.sort(key=lambda p: p.overall_rank)
    bench_sps.sort(key=lambda p: p.overall_rank)
    bench_rps.sort(key=lambda p: p.overall_rank)

    return RoleAggregation(
        bench_hitters=bench_hitters,
        bench_sps=bench_sps,
        bench_rps=bench_rps,
        starter_hitters=starter_hitters,
        starter_pitchers=starter_pitchers,
        avg_bench_hitter_rate=_avg_rate(bench_hitters),
        avg_bench_sp_rate=_avg_rate(bench_sps),
        avg_bench_rp_rate=_avg_rate(bench_rps),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/backend/analysis/test_bench_contributions.py::TestAggregation -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/analysis/bench_contributions.py tests/backend/analysis/test_bench_contributions.py
git commit -m "feat(bench): add contribution rate aggregation by role"
```

---

### Task 6: Stat Impact Calculation

**Files:**
- Modify: `tests/backend/analysis/test_bench_contributions.py`
- Modify: `backend/analysis/bench_contributions.py`

- [ ] **Step 1: Write failing test for stat impact**

```python
# Add to tests/backend/analysis/test_bench_contributions.py

from backend.analysis.bench_contributions import (
    parse_schedule_response,
    RosterPlayer,
    compute_availability_rate,
    distribute_sp_starts,
    SimulationResult,
    simulate_season,
    aggregate_by_role,
    RoleAggregation,
    compute_stat_impact,
)


class TestStatImpact:
    def test_stat_impact_scales_by_contribution_rate(self):
        """Season stat impact = projected stats * contribution rate."""
        player = RosterPlayer(
            mlb_id=1, name="Bench Hitter", position="OF", player_type="hitter",
            eligible_positions="OF", team="NYY",
            proj_pa=400, proj_r=60, proj_tb=150, proj_rbi=55,
            proj_sb=10, proj_obp=0.320, overall_rank=100,
        )
        rates = {1: 0.20}
        impact = compute_stat_impact([player], rates)
        assert impact["R"] == pytest.approx(60 * 0.20, abs=0.1)
        assert impact["TB"] == pytest.approx(150 * 0.20, abs=0.1)
        assert impact["RBI"] == pytest.approx(55 * 0.20, abs=0.1)
        assert impact["SB"] == pytest.approx(10 * 0.20, abs=0.1)

    def test_stat_impact_sums_multiple_players(self):
        """Impact sums across all players in the group."""
        p1 = RosterPlayer(
            mlb_id=1, name="H1", position="OF", player_type="hitter",
            eligible_positions="OF", team="NYY",
            proj_pa=400, proj_r=60, proj_tb=150, proj_rbi=55,
            proj_sb=10, proj_obp=0.320, overall_rank=100,
        )
        p2 = RosterPlayer(
            mlb_id=2, name="H2", position="1B", player_type="hitter",
            eligible_positions="1B", team="NYY",
            proj_pa=300, proj_r=40, proj_tb=100, proj_rbi=35,
            proj_sb=5, proj_obp=0.310, overall_rank=120,
        )
        rates = {1: 0.20, 2: 0.15}
        impact = compute_stat_impact([p1, p2], rates)
        assert impact["R"] == pytest.approx(60 * 0.20 + 40 * 0.15, abs=0.1)

    def test_pitcher_stat_impact(self):
        """Pitching stats are included for pitcher players."""
        pitcher = RosterPlayer(
            mlb_id=10, name="SP", position="SP", player_type="pitcher",
            eligible_positions="SP", team="NYY",
            proj_ip=150.0, proj_k=140, proj_qs=15,
            proj_era=3.50, proj_whip=1.15, proj_svhd=0,
            overall_rank=60,
        )
        rates = {10: 0.30}
        impact = compute_stat_impact([pitcher], rates)
        assert impact["K"] == pytest.approx(140 * 0.30, abs=0.1)
        assert impact["QS"] == pytest.approx(15 * 0.30, abs=0.1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/backend/analysis/test_bench_contributions.py::TestStatImpact -v`
Expected: FAIL — `cannot import name 'compute_stat_impact'`

- [ ] **Step 3: Implement stat impact calculation**

Add to `backend/analysis/bench_contributions.py`:

```python
HITTING_CATS = ["R", "TB", "RBI", "SB", "OBP"]
PITCHING_CATS = ["K", "QS", "ERA", "WHIP", "SVHD"]
ALL_CATS = HITTING_CATS + PITCHING_CATS

# Mapping from category name to RosterPlayer projection field
_CAT_TO_FIELD: dict[str, str] = {
    "R": "proj_r", "TB": "proj_tb", "RBI": "proj_rbi", "SB": "proj_sb",
    "K": "proj_k", "QS": "proj_qs", "SVHD": "proj_svhd",
}

# Rate stats need special handling (PA/IP weighted, not multiplied by rate)
_RATE_CATS = {"OBP", "ERA", "WHIP"}


def compute_stat_impact(
    players: list[RosterPlayer],
    contribution_rates: dict[int, float],
) -> dict[str, float]:
    """Compute total season stat contribution for a group of players.

    Counting stats are multiplied by contribution rate.
    Rate stats (OBP, ERA, WHIP) are PA/IP-weighted averages.
    """
    totals: dict[str, float] = {cat: 0.0 for cat in ALL_CATS}
    total_pa = 0.0
    total_ip = 0.0
    weighted_obp = 0.0
    weighted_era = 0.0
    weighted_whip = 0.0

    for p in players:
        rate = contribution_rates.get(p.mlb_id, 0.0)

        # Counting stats
        for cat, field in _CAT_TO_FIELD.items():
            totals[cat] += getattr(p, field, 0) * rate

        # Rate stat accumulators
        if p.player_type == "hitter" and p.proj_pa > 0:
            pa_contrib = p.proj_pa * rate
            total_pa += pa_contrib
            weighted_obp += p.proj_obp * pa_contrib
        if p.player_type == "pitcher" and p.proj_ip > 0:
            ip_contrib = p.proj_ip * rate
            total_ip += ip_contrib
            weighted_era += p.proj_era * ip_contrib
            weighted_whip += p.proj_whip * ip_contrib

    totals["OBP"] = weighted_obp / total_pa if total_pa > 0 else 0.0
    totals["ERA"] = weighted_era / total_ip if total_ip > 0 else 0.0
    totals["WHIP"] = weighted_whip / total_ip if total_ip > 0 else 0.0

    return totals
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/backend/analysis/test_bench_contributions.py::TestStatImpact -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/analysis/bench_contributions.py tests/backend/analysis/test_bench_contributions.py
git commit -m "feat(bench): add season stat impact calculation"
```

---

### Task 7: Sweep Mode — Roster Composition Variations

**Files:**
- Modify: `tests/backend/analysis/test_bench_contributions.py`
- Modify: `backend/analysis/bench_contributions.py`

- [ ] **Step 1: Write failing test for replacement-level player generation**

```python
# Add to tests/backend/analysis/test_bench_contributions.py

from backend.analysis.bench_contributions import (
    parse_schedule_response,
    RosterPlayer,
    compute_availability_rate,
    distribute_sp_starts,
    SimulationResult,
    simulate_season,
    aggregate_by_role,
    RoleAggregation,
    compute_stat_impact,
    build_sweep_configs,
    SweepConfig,
)


class TestSweepConfigs:
    def test_baseline_config_unchanged(self):
        """First config is 'baseline' with the original roster."""
        roster = [
            _make_hitter(1, "H1", "C", "NYY", rank=10),
            _make_hitter(2, "H2", "1B", "NYY", rank=50),
            _make_pitcher(10, "SP1", "SP", "NYY", ip=180.0, rank=20),
            _make_pitcher(11, "RP1", "RP", "NYY", ip=60.0, rank=90),
        ]
        configs = build_sweep_configs(roster)
        assert configs[0].label == "baseline"
        assert len(configs[0].roster) == 4

    def test_plus_one_hitter_drops_worst_pitcher(self):
        """+1 hitter config drops the lowest-ranked pitcher."""
        roster = [
            _make_hitter(1, "H1", "C", "NYY", rank=10),
            _make_pitcher(10, "SP1", "SP", "NYY", ip=180.0, rank=20),
            _make_pitcher(11, "RP1", "RP", "NYY", ip=60.0, rank=90),
        ]
        configs = build_sweep_configs(roster)
        plus1 = next(c for c in configs if c.label == "+1 hitter")
        # Should have dropped RP1 (rank 90) and added a replacement hitter
        pitcher_ids = [p.mlb_id for p in plus1.roster if p.player_type == "pitcher"]
        assert 11 not in pitcher_ids
        hitter_ids = [p.mlb_id for p in plus1.roster if p.player_type == "hitter"]
        assert len(hitter_ids) == 2  # original + replacement

    def test_minus_one_hitter_drops_worst_hitter(self):
        """-1 hitter config drops the lowest-ranked hitter."""
        roster = [
            _make_hitter(1, "H1", "C", "NYY", rank=10),
            _make_hitter(2, "H2", "OF", "NYY", rank=100),
            _make_pitcher(10, "SP1", "SP", "NYY", ip=180.0, rank=20),
        ]
        configs = build_sweep_configs(roster)
        minus1 = next(c for c in configs if c.label == "-1 hitter")
        hitter_ids = [p.mlb_id for p in minus1.roster if p.player_type == "hitter"]
        assert 2 not in hitter_ids
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/backend/analysis/test_bench_contributions.py::TestSweepConfigs -v`
Expected: FAIL — `cannot import name 'build_sweep_configs'`

- [ ] **Step 3: Implement sweep config builder**

Add to `backend/analysis/bench_contributions.py`:

```python
@dataclass
class SweepConfig:
    """A roster configuration to test in the sweep."""
    label: str
    roster: list[RosterPlayer]


def _replacement_level_hitter(team: str) -> RosterPlayer:
    """Generate a replacement-level hitter using typical waiver-wire projections."""
    return RosterPlayer(
        mlb_id=-1,  # Synthetic player
        name="Repl. Hitter",
        position="OF",
        player_type="hitter",
        eligible_positions="OF/DH",
        team=team,
        proj_pa=350,
        proj_r=40,
        proj_tb=100,
        proj_rbi=35,
        proj_sb=5,
        proj_obp=0.300,
        overall_rank=300,
    )


def _replacement_level_pitcher(team: str) -> RosterPlayer:
    """Generate a replacement-level pitcher using typical waiver-wire projections."""
    return RosterPlayer(
        mlb_id=-2,  # Synthetic player
        name="Repl. Pitcher",
        position="SP",
        player_type="pitcher",
        eligible_positions="SP",
        team=team,
        proj_ip=100.0,
        proj_k=80,
        proj_qs=6,
        proj_era=4.50,
        proj_whip=1.35,
        proj_svhd=0,
        overall_rank=350,
    )


def build_sweep_configs(roster: list[RosterPlayer]) -> list[SweepConfig]:
    """Build roster variations for the bench composition sweep.

    Generates: baseline, +1 hitter, +2 hitters, -1 hitter.
    Drops/adds are by overall_rank (worst-ranked first).
    """
    configs: list[SweepConfig] = [SweepConfig(label="baseline", roster=list(roster))]

    pitchers_by_rank = sorted(
        [p for p in roster if p.player_type == "pitcher"],
        key=lambda p: p.overall_rank,
        reverse=True,  # worst first
    )
    hitters_by_rank = sorted(
        [p for p in roster if p.player_type == "hitter"],
        key=lambda p: p.overall_rank,
        reverse=True,  # worst first
    )

    # Pick a team for replacement players (use most common team on roster)
    team_counts: dict[str, int] = {}
    for p in roster:
        team_counts[p.team] = team_counts.get(p.team, 0) + 1
    default_team = max(team_counts, key=team_counts.get) if team_counts else "NYY"

    # +1 hitter: drop worst pitcher, add replacement hitter
    if pitchers_by_rank:
        drop = pitchers_by_rank[0]
        repl = _replacement_level_hitter(default_team)
        repl.mlb_id = -(drop.mlb_id * 10 + 1)  # Unique synthetic ID
        new_roster = [p for p in roster if p.mlb_id != drop.mlb_id] + [repl]
        configs.append(SweepConfig(label="+1 hitter", roster=new_roster))

    # +2 hitters: drop 2 worst pitchers, add 2 replacement hitters
    if len(pitchers_by_rank) >= 2:
        drop_ids = {pitchers_by_rank[0].mlb_id, pitchers_by_rank[1].mlb_id}
        repl1 = _replacement_level_hitter(default_team)
        repl1.mlb_id = -(pitchers_by_rank[0].mlb_id * 10 + 1)
        repl2 = _replacement_level_hitter(default_team)
        repl2.mlb_id = -(pitchers_by_rank[1].mlb_id * 10 + 2)
        new_roster = [p for p in roster if p.mlb_id not in drop_ids] + [repl1, repl2]
        configs.append(SweepConfig(label="+2 hitters", roster=new_roster))

    # -1 hitter: drop worst hitter, add replacement pitcher
    if hitters_by_rank:
        drop = hitters_by_rank[0]
        repl = _replacement_level_pitcher(default_team)
        repl.mlb_id = -(drop.mlb_id * 10 + 3)
        new_roster = [p for p in roster if p.mlb_id != drop.mlb_id] + [repl]
        configs.append(SweepConfig(label="-1 hitter", roster=new_roster))

    return configs
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/backend/analysis/test_bench_contributions.py::TestSweepConfigs -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/analysis/bench_contributions.py tests/backend/analysis/test_bench_contributions.py
git commit -m "feat(bench): add sweep mode with roster composition variations"
```

---

### Task 8: CLI Entry Point — ESPN Roster Fetch & Main Loop

**Files:**
- Create: `sweep_bench_contributions.py`

- [ ] **Step 1: Write the CLI script**

```python
# sweep_bench_contributions.py
"""Sweep bench contribution rates by simulating daily lineups across a full MLB season.

Fetches your ESPN roster, loads projections from the rankings DB, fetches the
MLB schedule, and runs Monte Carlo simulations to determine how often each
bench player actually starts.

Usage:
    python3 sweep_bench_contributions.py --league-id 123 --team-id 4 --swid '{...}' --espn-s2 '...'
    python3 sweep_bench_contributions.py --league-id 123 --team-id 4 --swid '{...}' --espn-s2 '...' --sims 500 --seed 42
"""

from __future__ import annotations

import argparse
import sys

import httpx

from backend.analysis.bench_contributions import (
    ALL_CATS,
    HITTING_CATS,
    PITCHING_CATS,
    RosterPlayer,
    SimulationResult,
    SweepConfig,
    aggregate_by_role,
    build_sweep_configs,
    compute_stat_impact,
    fetch_season_schedule,
    simulate_season,
)
from backend.analysis.waivers import (
    load_projections_for_players,
    resolve_espn_names_to_mlbid,
)

ESPN_API_BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb"

# ESPN defaultPositionId -> position string
ESPN_POS_MAP: dict[int, str] = {
    1: "SP", 2: "C", 3: "1B", 4: "2B", 5: "3B",
    6: "SS", 7: "LF", 8: "CF", 9: "RF", 10: "DH", 11: "RP",
}

# ESPN proTeamId -> team abbreviation
ESPN_TEAM_MAP: dict[int, str] = {
    1: "BAL", 2: "BOS", 3: "LAA", 4: "CWS", 5: "CLE", 6: "DET",
    7: "KC", 8: "MIL", 9: "MIN", 10: "NYY", 11: "OAK", 12: "SEA",
    13: "TEX", 14: "TOR", 15: "ATL", 16: "CHC", 17: "CIN", 18: "HOU",
    19: "LAD", 20: "WSH", 21: "NYM", 22: "PHI", 23: "PIT", 24: "STL",
    25: "SD", 26: "SF", 27: "COL", 28: "MIA", 29: "ARI", 30: "TB",
}

# Season date range
SEASON_START = "2026-03-26"
SEASON_END = "2026-09-27"


def fetch_espn_roster(
    league_id: str,
    team_id: int,
    season: str,
    swid: str,
    espn_s2: str,
) -> list[dict]:
    """Fetch roster entries from ESPN Fantasy API."""
    url = f"{ESPN_API_BASE}/seasons/{season}/segments/0/leagues/{league_id}"
    headers = {
        "Cookie": f"swid={swid}; espn_s2={espn_s2}",
        "Content-Type": "application/json",
    }
    resp = httpx.get(url, params=[("view", "mRoster"), ("view", "kona_player_info")], headers=headers)
    resp.raise_for_status()
    data = resp.json()

    for team in data.get("teams", []):
        if team["id"] == team_id:
            entries = team.get("roster", {}).get("entries", [])
            result = []
            for entry in entries:
                player_data = entry.get("playerPoolEntry", {}).get("player", {})
                if not player_data:
                    continue
                pos_id = player_data.get("defaultPositionId", 0)
                player_type = "pitcher" if pos_id in (1, 11) else "hitter"
                pro_team_id = player_data.get("proTeamId", 0)
                result.append({
                    "name": player_data.get("fullName", "Unknown"),
                    "player_type": player_type,
                    "position": ESPN_POS_MAP.get(pos_id, "UTIL"),
                    "team": ESPN_TEAM_MAP.get(pro_team_id, ""),
                    "lineup_slot_id": entry.get("lineupSlotId", 0),
                    "eligible_slots": player_data.get("eligibleSlots", []),
                })
            return result
    return []


def build_roster_players(
    espn_entries: list[dict],
    season: int,
) -> list[RosterPlayer]:
    """Resolve ESPN roster entries to RosterPlayer objects with projections."""
    # Resolve names to mlb_ids
    name_to_id = resolve_espn_names_to_mlbid(espn_entries, season=season)
    mlb_ids = list(name_to_id.values())

    # Load projections
    projections = load_projections_for_players(mlb_ids, season)

    roster: list[RosterPlayer] = []
    for entry in espn_entries:
        mlb_id = name_to_id.get(entry["name"])
        if not mlb_id:
            print(f"  WARN: Could not resolve '{entry['name']}' — skipping")
            continue

        proj = projections.get(mlb_id)
        if not proj:
            print(f"  WARN: No projections for '{entry['name']}' (mlb_id={mlb_id}) — skipping")
            continue

        # Skip IL players (lineup_slot_id >= 17)
        if entry.get("lineup_slot_id", 0) >= 17:
            continue

        roster.append(RosterPlayer(
            mlb_id=mlb_id,
            name=proj.name,
            position=proj.position,
            player_type=proj.player_type,
            eligible_positions=proj.eligible_positions,
            team=entry.get("team", ""),
            proj_pa=proj.pa,
            proj_ip=proj.ip,
            overall_rank=proj.overall_rank,
            proj_r=proj.r,
            proj_tb=proj.tb,
            proj_rbi=proj.rbi,
            proj_sb=proj.sb,
            proj_obp=proj.obp,
            proj_k=proj.k,
            proj_qs=proj.qs,
            proj_era=proj.era,
            proj_whip=proj.whip,
            proj_svhd=proj.svhd,
        ))

    return roster


def print_contribution_report(
    label: str,
    roster: list[RosterPlayer],
    result: SimulationResult,
) -> None:
    """Print per-player contribution rates and role averages."""
    agg = aggregate_by_role(result.player_contribution_rates, roster)

    print(f"\n{'=' * 78}")
    print(f"  {label}")
    print(f"{'=' * 78}")
    print(f"  {'Player':<25} {'Pos':<6} {'Type':<8} {'Rank':>5} {'Rate':>6} {'Days':>6}")
    print(f"  {'-' * 72}")

    # Sort all by contribution rate descending
    sorted_players = sorted(
        roster,
        key=lambda p: result.player_contribution_rates.get(p.mlb_id, 0.0),
        reverse=True,
    )
    for p in sorted_players:
        rate = result.player_contribution_rates.get(p.mlb_id, 0.0)
        days = result.player_days_started.get(p.mlb_id, 0.0)
        print(f"  {p.name:<25} {p.position:<6} {p.player_type:<8} {p.overall_rank:>5} {rate:>6.1%} {days:>6.1f}")

    print(f"\n  Role Averages:")
    print(f"    Bench Hitter: {agg.avg_bench_hitter_rate:.1%}  ({len(agg.bench_hitters)} players)")
    print(f"    Bench SP:     {agg.avg_bench_sp_rate:.1%}  ({len(agg.bench_sps)} players)")
    print(f"    Bench RP:     {agg.avg_bench_rp_rate:.1%}  ({len(agg.bench_rps)} players)")


def print_sweep_summary(
    configs: list[SweepConfig],
    results: list[SimulationResult],
) -> None:
    """Print sweep comparison table with stat deltas."""
    print(f"\n{'=' * 90}")
    print(f"{'BENCH COMPOSITION SWEEP SUMMARY':^90}")
    print(f"{'=' * 90}")

    # Compute stat impacts per config
    impacts: list[dict[str, float]] = []
    for config, result in zip(configs, results):
        impact = compute_stat_impact(config.roster, result.player_contribution_rates)
        impacts.append(impact)

    baseline_impact = impacts[0]

    # Header
    cats = ["R", "TB", "RBI", "SB", "OBP", "K", "QS", "ERA", "WHIP", "SVHD"]
    header = f"  {'Config':<14}"
    for cat in cats:
        header += f" {cat:>6}"
    print(header)
    print(f"  {'-' * 86}")

    # Baseline row
    line = f"  {'baseline':<14}"
    for cat in cats:
        val = baseline_impact[cat]
        if cat in ("OBP", "ERA", "WHIP"):
            line += f" {val:>6.3f}"
        else:
            line += f" {val:>6.1f}"
    print(line)

    # Delta rows
    for config, impact in zip(configs[1:], impacts[1:]):
        line = f"  {config.label:<14}"
        for cat in cats:
            delta = impact[cat] - baseline_impact[cat]
            if cat in ("OBP", "ERA", "WHIP"):
                line += f" {delta:>+6.3f}"
            else:
                line += f" {delta:>+6.1f}"
        print(line)

    print(f"  {'-' * 86}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Sweep bench contribution rates via daily lineup simulation")
    parser.add_argument("--league-id", required=True, help="ESPN league ID")
    parser.add_argument("--team-id", type=int, required=True, help="ESPN team ID")
    parser.add_argument("--swid", required=True, help="ESPN SWID cookie")
    parser.add_argument("--espn-s2", required=True, help="ESPN espn_s2 cookie")
    parser.add_argument("--season", default="2026", help="Season year (default: 2026)")
    parser.add_argument("--sims", type=int, default=200, help="Monte Carlo iterations (default: 200)")
    parser.add_argument("--seed", type=int, default=None, help="RNG seed for reproducibility")
    parser.add_argument("--no-sweep", action="store_true", help="Only run baseline (skip composition sweep)")
    args = parser.parse_args()

    season_int = int(args.season)

    # 1. Fetch ESPN roster
    print(f"Fetching ESPN roster for league {args.league_id}, team {args.team_id}...")
    espn_entries = fetch_espn_roster(args.league_id, args.team_id, args.season, args.swid, args.espn_s2)
    if not espn_entries:
        print("ERROR: No roster entries found. Check league ID, team ID, and credentials.")
        sys.exit(1)
    print(f"  Found {len(espn_entries)} roster entries")

    # 2. Resolve to RosterPlayers with projections
    print("Resolving players and loading projections...")
    roster = build_roster_players(espn_entries, season_int)
    print(f"  Resolved {len(roster)} players with projections")

    hitter_count = sum(1 for p in roster if p.player_type == "hitter")
    pitcher_count = sum(1 for p in roster if p.player_type == "pitcher")
    print(f"  Composition: {hitter_count} hitters, {pitcher_count} pitchers")

    # 3. Fetch MLB schedule
    print(f"Fetching MLB schedule ({SEASON_START} to {SEASON_END})...")
    schedule = fetch_season_schedule(SEASON_START, SEASON_END)
    print(f"  {len(schedule)} game dates loaded")

    # Compute team season games
    team_season_games: dict[str, int] = {}
    for teams in schedule.values():
        for team in teams:
            team_season_games[team] = team_season_games.get(team, 0) + 1

    # 4. Build configs
    if args.no_sweep:
        configs = [SweepConfig(label="baseline", roster=roster)]
    else:
        configs = build_sweep_configs(roster)

    # 5. Run simulations
    results: list[SimulationResult] = []
    for config in configs:
        print(f"\nSimulating '{config.label}' ({args.sims} iterations)...")
        result = simulate_season(config.roster, schedule, team_season_games, args.sims, args.seed)
        results.append(result)
        print_contribution_report(config.label, config.roster, result)

    # 6. Print sweep summary
    if len(configs) > 1:
        print_sweep_summary(configs, results)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify it runs (dry run with --help)**

Run: `python3 sweep_bench_contributions.py --help`
Expected: Shows help with all arguments

- [ ] **Step 3: Commit**

```bash
git add sweep_bench_contributions.py
git commit -m "feat(bench): add CLI entry point for bench contribution sweep"
```

---

### Task 9: Run All Tests & Integration Smoke Test

**Files:**
- No new files

- [ ] **Step 1: Run full test suite**

Run: `python3 -m pytest tests/backend/analysis/test_bench_contributions.py -v`
Expected: All tests pass

- [ ] **Step 2: Run existing tests to verify no regressions**

Run: `python3 -m pytest tests/backend/analysis/ -v`
Expected: All existing tests still pass

- [ ] **Step 3: Run a live integration test with ESPN credentials**

Run: `python3 sweep_bench_contributions.py --league-id <LEAGUE_ID> --team-id <TEAM_ID> --swid '<SWID>' --espn-s2 '<ESPN_S2>' --sims 20 --seed 42`

Expected: Prints per-player contribution rates and sweep summary without errors. Verify:
- Starter hitters have ~0.8-1.0 contribution rates
- Bench hitters have ~0.1-0.3 rates
- Bench SPs have moderate rates
- Sweep delta table shows reasonable stat differences

- [ ] **Step 4: Commit any fixes from integration testing**

```bash
git add -u
git commit -m "fix(bench): address integration test findings"
```
