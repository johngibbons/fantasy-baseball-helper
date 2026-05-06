# Waiver Wire Lineup Optimization

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite the waiver recommendation engine to re-optimize the lineup for each trial roster, so swaps correctly model whether a FA would start or bench.

**Architecture:** Extract a position-aware greedy lineup optimizer into its own module (`backend/analysis/lineup_optimizer.py`). The waivers engine calls it for both the baseline roster and each trial roster to determine proper starter/bench weights. Pitchers all get weight 1.0 (daily league), hitters get 1.0 (starter) or 0.20 (bench) based on optimizer output.

**Tech Stack:** Python, pytest, SQLite (existing DB schema)

---

### Task 1: Lineup Optimizer Module

**Files:**
- Create: `backend/analysis/lineup_optimizer.py`
- Create: `tests/backend/analysis/test_lineup_optimizer.py`

This module is a Python port of the greedy algorithm in `src/lib/roster-optimizer.ts`. It takes a list of players with position eligibility and overall rank, and assigns them to active slots or bench.

- [ ] **Step 1: Write failing tests for the lineup optimizer**

```python
# tests/backend/analysis/test_lineup_optimizer.py

import pytest
from backend.analysis.lineup_optimizer import (
    optimize_hitter_lineup,
    HitterSlotAssignment,
    HITTER_ACTIVE_SLOTS,
    POSITION_TO_ACTIVE_SLOTS,
)


def _hitter(mlb_id: int, positions: str, overall_rank: int) -> dict:
    """Helper to build a hitter dict matching optimizer input."""
    return {
        "mlb_id": mlb_id,
        "eligible_positions": positions,
        "overall_rank": overall_rank,
        "player_type": "hitter",
    }


class TestOptimizeHitterLineup:
    def test_all_starters_when_roster_fits(self):
        """9 hitters with distinct positions all become starters."""
        hitters = [
            _hitter(1, "C", 10),
            _hitter(2, "1B", 20),
            _hitter(3, "2B", 30),
            _hitter(4, "3B", 40),
            _hitter(5, "SS", 50),
            _hitter(6, "OF", 60),
            _hitter(7, "OF", 70),
            _hitter(8, "OF", 80),
            _hitter(9, "DH", 90),  # DH -> UTIL
        ]
        result = optimize_hitter_lineup(hitters)
        assert all(a.is_starter for a in result)
        assert len(result) == 9

    def test_bench_overflow(self):
        """12 hitters — top 9 start, bottom 3 bench."""
        hitters = [
            _hitter(1, "C", 10),
            _hitter(2, "1B", 20),
            _hitter(3, "2B", 30),
            _hitter(4, "3B", 40),
            _hitter(5, "SS", 50),
            _hitter(6, "OF", 60),
            _hitter(7, "CF", 70),
            _hitter(8, "RF", 80),
            _hitter(9, "1B/DH", 90),  # UTIL
            _hitter(10, "OF/DH", 100),  # UTIL
            _hitter(11, "1B/DH", 200),  # bench — no slots left
            _hitter(12, "OF", 250),  # bench
        ]
        result = optimize_hitter_lineup(hitters)
        starters = [a for a in result if a.is_starter]
        bench = [a for a in result if not a.is_starter]
        assert len(starters) == 9
        assert len(bench) == 3
        bench_ids = {a.mlb_id for a in bench}
        assert 11 in bench_ids
        assert 12 in bench_ids

    def test_constrained_position_gets_priority(self):
        """A catcher (only eligible for C/UTIL) gets the C slot even if
        a better-ranked multi-position player could also fill it."""
        hitters = [
            _hitter(1, "C/1B", 5),   # rank 5 — could go C, 1B, or UTIL
            _hitter(2, "C", 50),      # rank 50 — can only go C or UTIL
            _hitter(3, "1B", 10),
            _hitter(4, "2B", 15),
            _hitter(5, "3B", 20),
            _hitter(6, "SS", 25),
            _hitter(7, "OF", 30),
            _hitter(8, "OF", 35),
            _hitter(9, "OF", 40),
            _hitter(10, "DH", 45),   # UTIL
            _hitter(11, "DH", 55),   # UTIL
        ]
        result = optimize_hitter_lineup(hitters)
        # Player 2 (C-only) should get the C slot, not be benched
        p2 = next(a for a in result if a.mlb_id == 2)
        assert p2.is_starter
        assert p2.slot == "C"
        # Player 1 should still start (1B or UTIL)
        p1 = next(a for a in result if a.mlb_id == 1)
        assert p1.is_starter

    def test_multi_position_player_fills_best_slot(self):
        """A SS/2B player fills whichever slot is available."""
        hitters = [
            _hitter(1, "C", 10),
            _hitter(2, "1B", 20),
            _hitter(3, "SS/2B", 30),  # should fill 2B or SS
            _hitter(4, "3B", 40),
            _hitter(5, "SS", 50),     # should fill SS if 3 took 2B
            _hitter(6, "OF", 60),
            _hitter(7, "OF", 70),
            _hitter(8, "OF", 80),
            _hitter(9, "DH", 90),
        ]
        result = optimize_hitter_lineup(hitters)
        starters = {a.mlb_id for a in result if a.is_starter}
        # All 9 should start — positions work out
        assert len(starters) == 9

    def test_empty_roster(self):
        result = optimize_hitter_lineup([])
        assert result == []

    def test_swap_changes_assignment(self):
        """Removing a bench hitter and adding a better one changes who starts."""
        base = [
            _hitter(1, "C", 10),
            _hitter(2, "1B", 20),
            _hitter(3, "2B", 30),
            _hitter(4, "3B", 40),
            _hitter(5, "SS", 50),
            _hitter(6, "OF", 60),
            _hitter(7, "OF", 70),
            _hitter(8, "OF", 80),
            _hitter(9, "DH", 90),   # UTIL #1
            _hitter(10, "DH", 95),  # UTIL #2
            _hitter(11, "1B", 200), # bench — rank 200
        ]
        # Baseline: player 11 benched
        baseline = optimize_hitter_lineup(base)
        p11 = next(a for a in baseline if a.mlb_id == 11)
        assert not p11.is_starter

        # Swap: drop player 11, add FA with rank 15 (better than player 2)
        trial = [h for h in base if h["mlb_id"] != 11]
        trial.append(_hitter(99, "1B", 15))
        trial_result = optimize_hitter_lineup(trial)

        # FA 99 should start at 1B, player 2 goes to UTIL or stays
        p99 = next(a for a in trial_result if a.mlb_id == 99)
        assert p99.is_starter


class TestPositionEligibility:
    def test_of_aliases(self):
        """LF, CF, RF all map to OF slot."""
        for pos in ["LF", "CF", "RF"]:
            slots = POSITION_TO_ACTIVE_SLOTS.get(pos, POSITION_TO_ACTIVE_SLOTS.get("OF"))
            assert "OF" in slots

    def test_dh_only_util(self):
        assert POSITION_TO_ACTIVE_SLOTS["DH"] == ["UTIL"]

    def test_pitcher_positions_not_in_hitter_slots(self):
        assert "SP" not in POSITION_TO_ACTIVE_SLOTS
        assert "RP" not in POSITION_TO_ACTIVE_SLOTS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/backend/analysis/test_lineup_optimizer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.analysis.lineup_optimizer'`

- [ ] **Step 3: Implement the lineup optimizer**

```python
# backend/analysis/lineup_optimizer.py

"""Position-aware greedy lineup optimizer for daily-lineup fantasy leagues.

Assigns hitters to active roster slots (C, 1B, 2B, 3B, SS, OF×3, UTIL×2)
or bench. Most constrained positions are assigned first (fewest eligible
active slots), with ties broken by overall_rank (best rank first).

Pitchers don't need optimization — in daily-lineup leagues all non-IL
pitchers contribute at full weight regardless of ESPN bench/active slot.
"""

from __future__ import annotations

from dataclasses import dataclass


# Active hitter slot capacities (matches roster-optimizer.ts ROSTER_SLOTS)
HITTER_ACTIVE_SLOTS: dict[str, int] = {
    "C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 3, "UTIL": 2,
}

# Maps each position to the active slots it can fill (most restrictive first).
# Mirrors POSITION_TO_SLOTS in roster-optimizer.ts but excludes BE.
POSITION_TO_ACTIVE_SLOTS: dict[str, list[str]] = {
    "C":  ["C", "UTIL"],
    "1B": ["1B", "UTIL"],
    "2B": ["2B", "UTIL"],
    "3B": ["3B", "UTIL"],
    "SS": ["SS", "UTIL"],
    "OF": ["OF", "UTIL"],
    "LF": ["OF", "UTIL"],
    "CF": ["OF", "UTIL"],
    "RF": ["OF", "UTIL"],
    "DH": ["UTIL"],
}


@dataclass
class HitterSlotAssignment:
    mlb_id: int
    slot: str        # "C", "1B", ..., "UTIL", "BE"
    is_starter: bool  # True if assigned to an active slot


def _eligible_active_slots(eligible_positions: str) -> list[str]:
    """Parse eligible_positions string (e.g. 'SS/2B') into deduplicated
    active slot list, ordered most-restrictive-first."""
    if not eligible_positions:
        return ["UTIL"]
    positions = eligible_positions.split("/")
    seen: set[str] = set()
    slots: list[str] = []
    for pos in positions:
        pos_slots = POSITION_TO_ACTIVE_SLOTS.get(pos, [])
        for s in pos_slots:
            if s not in seen:
                seen.add(s)
                slots.append(s)
    return slots if slots else ["UTIL"]


def optimize_hitter_lineup(
    hitters: list[dict],
) -> list[HitterSlotAssignment]:
    """Assign hitters to active slots or bench using greedy optimization.

    Algorithm (matches roster-optimizer.ts):
    1. For each hitter, compute eligible active slots from eligible_positions.
    2. Sort by (fewest eligible active slots ASC, overall_rank ASC).
       Most constrained players get first pick of slots; among equally
       constrained, the best-ranked player gets priority.
    3. Greedily assign each hitter to their first available active slot.
    4. If no active slot available → bench.

    Args:
        hitters: List of dicts with keys: mlb_id, eligible_positions (str),
                 overall_rank (int), player_type (str).

    Returns:
        List of HitterSlotAssignment (one per input hitter).
    """
    if not hitters:
        return []

    capacity = dict(HITTER_ACTIVE_SLOTS)  # mutable copy

    # Pre-compute eligible slots per hitter
    enriched: list[tuple[dict, list[str]]] = []
    for h in hitters:
        slots = _eligible_active_slots(h.get("eligible_positions", "") or "")
        enriched.append((h, slots))

    # Sort: fewest eligible active slots first, then best rank first
    enriched.sort(key=lambda x: (len(x[1]), x[0].get("overall_rank", 9999)))

    assignments: list[HitterSlotAssignment] = []
    for h, slots in enriched:
        placed = False
        for slot in slots:
            if capacity.get(slot, 0) > 0:
                capacity[slot] -= 1
                assignments.append(HitterSlotAssignment(
                    mlb_id=h["mlb_id"],
                    slot=slot,
                    is_starter=True,
                ))
                placed = True
                break
        if not placed:
            assignments.append(HitterSlotAssignment(
                mlb_id=h["mlb_id"],
                slot="BE",
                is_starter=False,
            ))

    return assignments
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/backend/analysis/test_lineup_optimizer.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/analysis/lineup_optimizer.py tests/backend/analysis/test_lineup_optimizer.py
git commit -m "feat(waivers): add position-aware greedy lineup optimizer

Ports the greedy algorithm from roster-optimizer.ts to Python.
Assigns hitters to active slots (C/1B/2B/3B/SS/OF×3/UTIL×2) or bench
based on position eligibility and overall rank."
```

---

### Task 2: Add eligible_positions and overall_rank to projection loading

**Files:**
- Modify: `backend/analysis/waivers.py:44-65` (PlayerProjection dataclass)
- Modify: `backend/analysis/waivers.py:258-299` (load_projections_for_players)
- Create: `tests/backend/analysis/test_waivers.py`

The existing `PlayerProjection` and `load_projections_for_players` need two new fields so the lineup optimizer can work.

- [ ] **Step 1: Write failing test for extended projection loading**

```python
# tests/backend/analysis/test_waivers.py

import pytest
from unittest.mock import patch, MagicMock
from backend.analysis.waivers import PlayerProjection, load_projections_for_players


class TestPlayerProjectionFields:
    def test_has_eligible_positions_field(self):
        p = PlayerProjection(
            mlb_id=1, name="Test", position="SS", player_type="hitter",
            eligible_positions="SS/2B", overall_rank=50,
        )
        assert p.eligible_positions == "SS/2B"
        assert p.overall_rank == 50

    def test_defaults_for_new_fields(self):
        p = PlayerProjection(
            mlb_id=1, name="Test", position="SS", player_type="hitter",
        )
        assert p.eligible_positions == ""
        assert p.overall_rank == 9999
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/backend/analysis/test_waivers.py::TestPlayerProjectionFields -v`
Expected: FAIL — `TypeError: PlayerProjection.__init__() got an unexpected keyword argument 'eligible_positions'`

- [ ] **Step 3: Add fields to PlayerProjection and update the loader**

In `backend/analysis/waivers.py`, add two fields to `PlayerProjection`:

```python
@dataclass
class PlayerProjection:
    """Projection data matching the rankings table fields used by the draft."""
    mlb_id: int
    name: str
    position: str
    player_type: str
    # Count stats
    pa: int = 0
    r: int = 0
    tb: int = 0
    rbi: int = 0
    sb: int = 0
    ip: float = 0.0
    k: int = 0
    qs: int = 0
    svhd: int = 0
    # Rate stats (pre-computed, weighted by PA/IP when aggregating)
    obp: float = 0.0
    era: float = 0.0
    whip: float = 0.0
    # Lineup optimizer fields
    eligible_positions: str = ""
    overall_rank: int = 9999
```

Update the SQL query in `load_projections_for_players` to fetch the new columns:

```python
def load_projections_for_players(
    mlb_ids: list[int],
    season: int,
) -> dict[int, PlayerProjection]:
    """Load projections from the rankings table (same data the draft uses)."""
    conn = get_connection()
    placeholders = ",".join(["?"] * len(mlb_ids))
    rows = conn.execute(
        f"""SELECT r.mlb_id, pl.full_name, pl.primary_position, r.player_type,
                   r.proj_pa, r.proj_r, r.proj_tb, r.proj_rbi, r.proj_sb, r.proj_obp,
                   r.proj_ip, r.proj_k, r.proj_qs, r.proj_era, r.proj_whip, r.proj_svhd,
                   pl.eligible_positions, r.overall_rank
            FROM rankings r
            JOIN players pl ON r.mlb_id = pl.mlb_id
            WHERE r.mlb_id IN ({placeholders})
              AND r.season = ?""",
        (*mlb_ids, season),
    ).fetchall()

    projections: dict[int, PlayerProjection] = {}
    for row in rows:
        projections[row["mlb_id"]] = PlayerProjection(
            mlb_id=row["mlb_id"],
            name=row["full_name"],
            position=row["primary_position"] or "",
            player_type=row["player_type"] or "hitter",
            pa=row["proj_pa"] or 0,
            r=row["proj_r"] or 0,
            tb=row["proj_tb"] or 0,
            rbi=row["proj_rbi"] or 0,
            sb=row["proj_sb"] or 0,
            obp=row["proj_obp"] or 0.0,
            ip=row["proj_ip"] or 0.0,
            k=row["proj_k"] or 0,
            qs=row["proj_qs"] or 0,
            era=row["proj_era"] or 0.0,
            whip=row["proj_whip"] or 0.0,
            svhd=row["proj_svhd"] or 0,
            eligible_positions=row["eligible_positions"] or "",
            overall_rank=row["overall_rank"] or 9999,
        )

    conn.close()
    logger.info(f"Loaded projections for {len(projections)}/{len(mlb_ids)} players from rankings")
    return projections
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/backend/analysis/test_waivers.py::TestPlayerProjectionFields -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/analysis/waivers.py tests/backend/analysis/test_waivers.py
git commit -m "feat(waivers): add eligible_positions and overall_rank to projections

These fields feed the lineup optimizer so it can determine who starts
vs benches when evaluating waiver swaps."
```

---

### Task 3: Rewrite compute_waiver_recommendations with lineup optimization

**Files:**
- Modify: `backend/analysis/waivers.py:334-560` (player_weight, compute_waiver_recommendations)
- Test: `tests/backend/analysis/test_waivers.py`

This is the core change. Replace the old weight-based swap logic with the new approach: for each trial roster, re-run the lineup optimizer and compute totals from scratch.

- [ ] **Step 1: Write failing test for the new swap logic**

Add to `tests/backend/analysis/test_waivers.py`:

```python
from backend.analysis.waivers import (
    PlayerProjection,
    TeamTotals,
    compute_expected_wins,
    build_team_totals,
    HITTER_BENCH_WEIGHT,
)


def _proj(mlb_id: int, name: str, position: str, player_type: str,
          eligible_positions: str = "", overall_rank: int = 9999, **kwargs) -> PlayerProjection:
    defaults = dict(pa=0, r=0, tb=0, rbi=0, sb=0, obp=0.0,
                    ip=0.0, k=0, qs=0, era=0.0, whip=0.0, svhd=0)
    defaults.update(kwargs)
    return PlayerProjection(
        mlb_id=mlb_id, name=name, position=position, player_type=player_type,
        eligible_positions=eligible_positions, overall_rank=overall_rank,
        **defaults,
    )


class TestBuildTeamTotals:
    """Test that build_team_totals uses the lineup optimizer for hitters
    and weights all non-IL pitchers at 1.0."""

    def test_bench_hitter_gets_reduced_weight(self):
        """With 10 hitters and 9 active slots, the worst-ranked hitter benches."""
        projections = {
            1: _proj(1, "C", "C", "hitter", "C", 10, r=80),
            2: _proj(2, "1B", "1B", "hitter", "1B", 20, r=70),
            3: _proj(3, "2B", "2B", "hitter", "2B", 30, r=60),
            4: _proj(4, "3B", "3B", "hitter", "3B", 40, r=50),
            5: _proj(5, "SS", "SS", "hitter", "SS", 50, r=40),
            6: _proj(6, "OF", "OF", "hitter", "OF", 60, r=30),
            7: _proj(7, "OF", "OF", "hitter", "OF", 70, r=20),
            8: _proj(8, "OF", "OF", "hitter", "OF", 80, r=10),
            9: _proj(9, "UTIL", "DH", "hitter", "DH", 90, r=5),
            10: _proj(10, "UTIL2", "DH", "hitter", "DH", 100, r=3),
            # Player 11: worst rank, should bench
            11: _proj(11, "Bench", "1B", "hitter", "1B", 300, r=100),
        }
        roster_slots = [{"mlb_id": i, "lineup_slot_id": 0} for i in range(1, 12)]
        totals, weights = build_team_totals(roster_slots, projections)
        # Player 11 should be benched at HITTER_BENCH_WEIGHT
        assert weights[11] == pytest.approx(HITTER_BENCH_WEIGHT)
        # All others should be starters at 1.0
        for pid in range(1, 11):
            assert weights[pid] == pytest.approx(1.0), f"Player {pid} should be starter"

    def test_pitcher_always_weight_1(self):
        """Non-IL pitchers always get weight 1.0 regardless of ESPN slot."""
        projections = {
            1: _proj(1, "SP1", "SP", "pitcher", "SP", 10, k=200, qs=16, ip=180, era=3.0, whip=1.1),
            2: _proj(2, "SP2", "SP", "pitcher", "SP", 20, k=150, qs=12, ip=160, era=3.5, whip=1.2),
        }
        # Slot 16 = bench in ESPN
        roster_slots = [
            {"mlb_id": 1, "lineup_slot_id": 14},  # active SP slot
            {"mlb_id": 2, "lineup_slot_id": 16},  # bench slot
        ]
        totals, weights = build_team_totals(roster_slots, projections)
        assert weights[1] == 1.0
        assert weights[2] == 1.0

    def test_il_pitcher_weight_0(self):
        projections = {
            1: _proj(1, "SP1", "SP", "pitcher", "SP", 10, k=200, qs=16, ip=180, era=3.0, whip=1.1),
        }
        roster_slots = [{"mlb_id": 1, "lineup_slot_id": 17}]  # IL
        totals, weights = build_team_totals(roster_slots, projections)
        assert weights[1] == 0.0

    def test_swap_fa_displaces_weak_starter(self):
        """Adding a better FA should displace the weakest starter to bench."""
        # 10 hitters filling 9 active + 1 bench
        base_projs = {
            1: _proj(1, "C", "C", "hitter", "C", 10, r=80),
            2: _proj(2, "1B_weak", "1B", "hitter", "1B", 200, r=20),  # weak 1B starter
            3: _proj(3, "2B", "2B", "hitter", "2B", 30, r=60),
            4: _proj(4, "3B", "3B", "hitter", "3B", 40, r=50),
            5: _proj(5, "SS", "SS", "hitter", "SS", 50, r=40),
            6: _proj(6, "OF1", "OF", "hitter", "OF", 60, r=30),
            7: _proj(7, "OF2", "OF", "hitter", "OF", 70, r=25),
            8: _proj(8, "OF3", "OF", "hitter", "OF", 80, r=20),
            9: _proj(9, "UTIL1", "DH", "hitter", "DH", 90, r=15),
            10: _proj(10, "UTIL2", "DH", "hitter", "DH", 100, r=10),
            11: _proj(11, "Bench", "1B", "hitter", "1B", 300, r=5),  # bench
        }
        base_slots = [{"mlb_id": i, "lineup_slot_id": 0} for i in range(1, 12)]

        # Baseline: player 11 benched (rank 300)
        _, base_weights = build_team_totals(base_slots, base_projs)
        assert base_weights[11] == pytest.approx(HITTER_BENCH_WEIGHT)
        assert base_weights[2] == pytest.approx(1.0)  # weak 1B starts

        # Trial: drop bench player 11, add strong 1B FA (rank 15)
        fa = _proj(99, "FA_1B", "1B", "hitter", "1B", 15, r=75)
        trial_projs = {k: v for k, v in base_projs.items() if k != 11}
        trial_projs[99] = fa
        trial_slots = [s for s in base_slots if s["mlb_id"] != 11]
        trial_slots.append({"mlb_id": 99, "lineup_slot_id": 0})

        _, trial_weights = build_team_totals(trial_slots, trial_projs)
        # FA (rank 15) should start; weak 1B (rank 200) now benched
        assert trial_weights[99] == pytest.approx(1.0)
        assert trial_weights[2] == pytest.approx(HITTER_BENCH_WEIGHT)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/backend/analysis/test_waivers.py::TestBuildTeamTotals -v`
Expected: FAIL — `ImportError: cannot import name 'build_team_totals' from 'backend.analysis.waivers'`

- [ ] **Step 3: Implement build_team_totals and rewrite compute_waiver_recommendations**

In `backend/analysis/waivers.py`, replace the `player_weight` function and rework the team totals building logic:

```python
# Replace the old player_weight function and add build_team_totals.
# Keep IL_WEIGHT and HITTER_BENCH_WEIGHT constants. Remove the unused
# SP_BENCH_WEIGHT and RP_BENCH_WEIGHT constants.

from backend.analysis.lineup_optimizer import optimize_hitter_lineup

IL_SLOT_THRESHOLD = 17  # ESPN lineup_slot_id >= 17 means IL

HITTER_BENCH_WEIGHT = 0.20
IL_WEIGHT = 0.0


def build_team_totals(
    roster_slots: list[dict],
    projections: dict[int, PlayerProjection],
) -> tuple[TeamTotals, dict[int, float]]:
    """Build team totals using lineup-optimized weights.

    Pitchers: all non-IL at 1.0 (daily league rotation).
    Hitters: run greedy optimizer to assign active (1.0) or bench (0.20).
    IL: 0.0.

    Returns:
        (TeamTotals, {mlb_id: weight})
    """
    totals = TeamTotals()
    weights: dict[int, float] = {}

    # Separate IL, pitchers, and hitters
    il_ids: set[int] = set()
    pitcher_ids: list[int] = []
    hitter_dicts: list[dict] = []

    for slot in roster_slots:
        pid = slot["mlb_id"]
        proj = projections.get(pid)
        if not proj:
            continue

        if slot.get("lineup_slot_id", 0) >= IL_SLOT_THRESHOLD:
            il_ids.add(pid)
            weights[pid] = IL_WEIGHT
            continue

        if proj.player_type == "pitcher":
            pitcher_ids.append(pid)
        else:
            hitter_dicts.append({
                "mlb_id": pid,
                "eligible_positions": proj.eligible_positions,
                "overall_rank": proj.overall_rank,
                "player_type": proj.player_type,
            })

    # Pitchers: all non-IL at 1.0
    for pid in pitcher_ids:
        w = 1.0
        weights[pid] = w
        totals.add_player(projections[pid], w)

    # Hitters: optimize lineup
    assignments = optimize_hitter_lineup(hitter_dicts)
    for a in assignments:
        proj = projections.get(a.mlb_id)
        if not proj:
            continue
        w = 1.0 if a.is_starter else HITTER_BENCH_WEIGHT
        weights[a.mlb_id] = w
        totals.add_player(proj, w)

    return totals, weights
```

Now rewrite `compute_waiver_recommendations` to use `build_team_totals` for both baseline and each trial:

```python
def compute_waiver_recommendations(
    my_roster_ids: list[int],
    my_roster_slots: list[dict],
    all_team_roster_slots: list[list[dict]],
    free_agent_ids: list[int],
    season: int,
    remaining_faab: float = 100.0,
    open_roster_slots: int = 0,
) -> dict:
    """Compute waiver wire recommendations.

    For each (FA, drop) pair, builds the trial roster and re-optimizes the
    lineup to determine proper starter/bench assignments. This correctly
    models whether a FA would start or sit on the bench.
    """
    other_team_ids = [s["mlb_id"] for team in all_team_roster_slots for s in team]
    all_ids = list(set(my_roster_ids + other_team_ids + free_agent_ids))

    projections = load_projections_for_players(all_ids, season)

    # Build my baseline using lineup optimization
    my_totals, my_weights = build_team_totals(my_roster_slots, projections)

    # Build other teams' totals (use same model)
    other_team_totals: list[TeamTotals] = []
    for team_slots in all_team_roster_slots:
        tt, _ = build_team_totals(team_slots, projections)
        other_team_totals.append(tt)

    # Compute baseline expected wins
    my_roster_with_proj = sum(1 for pid in my_roster_ids if pid in projections)
    my_roster_without_proj = [pid for pid in my_roster_ids if pid not in projections]
    logger.info(
        f"My roster projections: {my_roster_with_proj}/{len(my_roster_ids)} have projections, "
        f"missing: {my_roster_without_proj[:10]}"
    )
    my_cat_values = my_totals.category_values()
    other_cat_values = [t.category_values() for t in other_team_totals]
    logger.info(f"My team category values: {my_cat_values}")
    baseline_wins, baseline_cat_probs = compute_expected_wins(my_cat_values, other_cat_values)

    # Identify droppable players (exclude IL)
    droppable_ids: list[int] = []
    for slot in my_roster_slots:
        pid = slot["mlb_id"]
        if slot.get("lineup_slot_id", 0) >= IL_SLOT_THRESHOLD:
            continue
        droppable_ids.append(pid)

    # Evaluate each free agent
    recommendations: list[WaiverRecommendation] = []

    for fa_id in free_agent_ids:
        fa_proj = projections.get(fa_id)
        if not fa_proj:
            continue

        best_delta = -999.0
        best_drop_id: Optional[int] = None
        best_cat_impact: dict[str, float] = {}
        is_no_drop = False

        # Try "add without drop" if open roster slots available
        if open_roster_slots > 0:
            trial_slots = list(my_roster_slots) + [{"mlb_id": fa_id, "lineup_slot_id": 0}]
            trial_totals, _ = build_team_totals(trial_slots, projections)
            trial_cat_values = trial_totals.category_values()
            trial_wins, trial_cat_probs = compute_expected_wins(trial_cat_values, other_cat_values)
            delta = trial_wins - baseline_wins
            if delta > best_delta:
                best_delta = delta
                best_drop_id = None
                is_no_drop = True
                best_cat_impact = {
                    cat: round(trial_cat_probs[cat] - baseline_cat_probs[cat], 4)
                    for cat in ALL_CATS
                }

        # Try each drop option
        for drop_id in droppable_ids:
            drop_proj = projections.get(drop_id)
            if not drop_proj:
                continue

            # Build trial roster slots: remove drop, add FA
            trial_slots = [s for s in my_roster_slots if s["mlb_id"] != drop_id]
            trial_slots.append({"mlb_id": fa_id, "lineup_slot_id": 0})

            # Re-optimize lineup for trial roster
            trial_totals, _ = build_team_totals(trial_slots, projections)
            trial_cat_values = trial_totals.category_values()
            trial_wins, trial_cat_probs = compute_expected_wins(trial_cat_values, other_cat_values)
            delta = trial_wins - baseline_wins

            if delta > best_delta:
                best_delta = delta
                best_drop_id = drop_id
                is_no_drop = False
                best_cat_impact = {
                    cat: round(trial_cat_probs[cat] - baseline_cat_probs[cat], 4)
                    for cat in ALL_CATS
                }

        if best_delta > -10 and (best_drop_id is not None or is_no_drop):
            drop_proj = projections.get(best_drop_id) if best_drop_id else None
            recommendations.append(WaiverRecommendation(
                add_player_id=fa_id,
                add_player_name=fa_proj.name,
                add_player_position=fa_proj.position,
                drop_player_id=best_drop_id,
                drop_player_name=drop_proj.name if drop_proj else None,
                drop_player_position=drop_proj.position if drop_proj else None,
                delta_expected_wins=round(best_delta, 4),
                suggested_faab_bid=0,
                category_impact=best_cat_impact,
            ))

    recommendations.sort(key=lambda r: r.delta_expected_wins, reverse=True)
    _assign_faab_bids(recommendations, remaining_faab)

    return {
        "baseline_expected_wins": round(baseline_wins, 3),
        "baseline_category_probs": {cat: round(v, 4) for cat, v in baseline_cat_probs.items()},
        "my_team_totals": {k: round(v, 3) for k, v in my_cat_values.items()},
        "projection_coverage": {
            "my_roster": f"{my_roster_with_proj}/{len(my_roster_ids)}",
            "missing_ids": my_roster_without_proj[:10],
        },
        "recommendations": [
            {
                "rank": i + 1,
                "add_player": {
                    "id": r.add_player_id,
                    "name": r.add_player_name,
                    "position": r.add_player_position,
                },
                "drop_player": {
                    "id": r.drop_player_id,
                    "name": r.drop_player_name,
                    "position": r.drop_player_position,
                } if r.drop_player_id else None,
                "delta_expected_wins": r.delta_expected_wins,
                "suggested_faab_bid": r.suggested_faab_bid,
                "category_impact": r.category_impact,
            }
            for i, r in enumerate(recommendations)
        ],
    }
```

Also remove the now-unused `player_weight` function, `SP_BENCH_WEIGHT`, `RP_BENCH_WEIGHT`, and `ACTIVE_SLOT_IDS` constants. Keep `remove_player` and `copy` on TeamTotals — they're no longer used by the main engine but are harmless and may be useful.

- [ ] **Step 4: Run all waivers tests**

Run: `python3 -m pytest tests/backend/analysis/test_waivers.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/analysis/waivers.py tests/backend/analysis/test_waivers.py
git commit -m "feat(waivers): rewrite swap engine with lineup re-optimization

Each trial roster gets a fresh lineup optimization to determine who
starts and who benches. Pitchers: all non-IL at 1.0 (daily league).
Hitters: greedy optimizer assigns active (1.0) or bench (0.20).

Fixes incorrect category deltas caused by the old model always adding
FAs at starter weight regardless of where they'd actually slot in."
```

---

### Task 4: Smoke-test with live data

**Files:** None modified — manual verification only.

- [ ] **Step 1: Start the backend and frontend**

Run: `python3 -m uvicorn backend.api.routes:app --reload --port 8000 &`
Run: `npm run dev &`

- [ ] **Step 2: Open the waivers page and run recommendations**

Navigate to `http://localhost:3000/waivers`, select league and team, click "Get Recommendations".

**Verify:**
- Recommendations load without errors (check browser console and backend logs)
- The Kikuchi/Boyd case: Kikuchi over Boyd should now show a **negative** QS delta (Kikuchi has 15 QS vs Boyd's 16 QS, and both are weighted equally as non-IL pitchers at 1.0)
- Category impacts look reasonable — no wildly inflated values from bench/starter weight asymmetry
- Pitcher-for-pitcher swaps show pure projection-quality differences
- Hitter swaps where the FA is worse than all starters show small deltas (FA would bench)

- [ ] **Step 3: Check backend logs for optimizer activity**

In the uvicorn output, verify:
- "Loaded projections for X/Y players" appears
- No Python tracebacks

- [ ] **Step 4: Commit if any minor fixups were needed**

If any small issues were found and fixed in steps 2-3:

```bash
git add -u
git commit -m "fix(waivers): address smoke-test issues from lineup optimization rewrite"
```
