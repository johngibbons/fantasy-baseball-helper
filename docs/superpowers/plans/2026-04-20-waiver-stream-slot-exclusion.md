# Waiver Stream-Slot Exclusion & Same-Type Swaps — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop waiver recommendations from proposing the user's streaming pitcher as the drop for every hitter FA. Add a stream-slot concept (auto-detected, toggleable) and default to same-type drops (hitter→hitter, pitcher→pitcher) with a cross-type toggle.

**Architecture:** Backend change in `backend/analysis/waivers.py` adds (1) a stream-slot identifier function, (2) an optional `stream_slot_id` parameter to `build_team_totals` that zero-weights that player, and (3) two new flags on `compute_waiver_recommendations` (`exclude_stream_slot`, `same_type_only`). FastAPI model gains matching fields. Next.js proxy route passes through new request fields. Frontend adds two checkboxes and a STREAM badge on the roster panel.

**Tech Stack:** Python 3.11 (pytest), FastAPI + Pydantic, Next.js 14 App Router, React hooks, TailwindCSS.

**Reference spec:** `docs/superpowers/specs/2026-04-20-waiver-stream-slot-exclusion-design.md`

---

## File Structure

- **Modify** `backend/analysis/waivers.py` — add `identify_stream_slot`, extend `build_team_totals`, extend `compute_waiver_recommendations`, include `stream_slot_player` in response payload.
- **Modify** `tests/backend/analysis/test_waivers.py` — add tests for the new behavior.
- **Modify** `backend/api/routes.py` — add `exclude_stream_slot` and `include_cross_type` fields to `WaiverRequest`; pass through to the engine.
- **Modify** `src/app/api/waivers/recommendations/route.ts` — accept the two flags from the frontend body, forward to FastAPI as snake_case.
- **Modify** `src/app/waivers/page.tsx` — add `excludeStreamSlot` / `includeCrossType` state, two checkboxes, STREAM badge on the matching roster row, include flags in request body, auto-refetch on change.

No new files.

---

## Task 1: Add `identify_stream_slot` with tests

**Files:**
- Modify: `backend/analysis/waivers.py` (append new function after `build_team_totals`, around line 397)
- Test: `tests/backend/analysis/test_waivers.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/backend/analysis/test_waivers.py`:

```python
from backend.analysis.waivers import identify_stream_slot


class TestIdentifyStreamSlot:
    def test_picks_highest_rank_pitcher(self):
        """Highest overall_rank = worst projection = stream slot."""
        projections = {
            1: _proj(1, "Ace",    "SP", "pitcher", overall_rank=20,  ip=180),
            2: _proj(2, "Mid",    "SP", "pitcher", overall_rank=120, ip=150),
            3: _proj(3, "Streamer", "SP", "pitcher", overall_rank=400, ip=80),
        }
        slots = [{"mlb_id": i, "lineup_slot_id": 14} for i in (1, 2, 3)]
        assert identify_stream_slot(slots, projections) == 3

    def test_tie_breaks_by_lowest_ip(self):
        """Equal overall_rank → fewer IP wins (more churn-like)."""
        projections = {
            1: _proj(1, "A", "SP", "pitcher", overall_rank=300, ip=140),
            2: _proj(2, "B", "SP", "pitcher", overall_rank=300, ip=90),
        }
        slots = [{"mlb_id": i, "lineup_slot_id": 14} for i in (1, 2)]
        assert identify_stream_slot(slots, projections) == 2

    def test_ignores_il_pitchers(self):
        """IL pitchers are not candidates."""
        projections = {
            1: _proj(1, "Active",   "SP", "pitcher", overall_rank=50, ip=180),
            2: _proj(2, "InjuredWorst", "SP", "pitcher", overall_rank=500, ip=40),
        }
        slots = [
            {"mlb_id": 1, "lineup_slot_id": 14},
            {"mlb_id": 2, "lineup_slot_id": 17},  # IL
        ]
        assert identify_stream_slot(slots, projections) == 1

    def test_ignores_hitters(self):
        projections = {
            1: _proj(1, "SP", "SP", "pitcher", overall_rank=60, ip=180),
            2: _proj(2, "WorstBatter", "2B", "hitter", overall_rank=999, r=5),
        }
        slots = [
            {"mlb_id": 1, "lineup_slot_id": 14},
            {"mlb_id": 2, "lineup_slot_id": 2},
        ]
        assert identify_stream_slot(slots, projections) == 1

    def test_returns_none_when_no_active_pitchers(self):
        projections = {
            1: _proj(1, "H", "SS", "hitter", overall_rank=10, r=80),
        }
        slots = [{"mlb_id": 1, "lineup_slot_id": 4}]
        assert identify_stream_slot(slots, projections) is None

    def test_skips_players_without_projections(self):
        projections = {
            1: _proj(1, "A", "SP", "pitcher", overall_rank=50, ip=180),
        }
        slots = [
            {"mlb_id": 1, "lineup_slot_id": 14},
            {"mlb_id": 99, "lineup_slot_id": 14},  # no projection
        ]
        assert identify_stream_slot(slots, projections) == 1
```

- [ ] **Step 2: Run tests to verify they fail with import error**

Run: `pytest tests/backend/analysis/test_waivers.py::TestIdentifyStreamSlot -v`
Expected: FAIL with `ImportError: cannot import name 'identify_stream_slot'`

- [ ] **Step 3: Implement `identify_stream_slot`**

Insert this function in `backend/analysis/waivers.py` immediately after `build_team_totals` (after the closing of `return totals, weights`, roughly line 397) and before the `# ── Core recommendation engine` divider:

```python
def identify_stream_slot(
    roster_slots: list[dict],
    projections: dict[int, PlayerProjection],
) -> Optional[int]:
    """Pick the stream-slot pitcher: worst active pitcher by projection.

    "Worst" = highest overall_rank (rank 500 is worse than rank 50).
    Ties broken by lowest proj_ip (fewer innings = more churn-like).
    Returns None if no eligible active pitcher exists.
    """
    candidates: list[tuple[int, int, float]] = []  # (overall_rank, -ip, mlb_id)
    for slot in roster_slots:
        if slot.get("lineup_slot_id", 0) >= IL_SLOT_THRESHOLD:
            continue
        pid = slot["mlb_id"]
        proj = projections.get(pid)
        if not proj or proj.player_type != "pitcher":
            continue
        candidates.append((proj.overall_rank, proj.ip, pid))

    if not candidates:
        return None

    # Highest rank wins; tie-break by lowest ip
    candidates.sort(key=lambda t: (-t[0], t[1]))
    return candidates[0][2]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/backend/analysis/test_waivers.py::TestIdentifyStreamSlot -v`
Expected: 6 passing tests.

- [ ] **Step 5: Commit**

```bash
git add backend/analysis/waivers.py tests/backend/analysis/test_waivers.py
git commit -m "feat(waivers): add identify_stream_slot helper"
```

---

## Task 2: Extend `build_team_totals` to zero-weight the stream slot

**Files:**
- Modify: `backend/analysis/waivers.py` (`build_team_totals`, around lines 339-396)
- Test: `tests/backend/analysis/test_waivers.py`

- [ ] **Step 1: Write the failing test**

Append to the existing `TestBuildTeamTotals` class in `tests/backend/analysis/test_waivers.py`:

```python
    def test_stream_slot_zero_weighted(self):
        """Stream-slot pitcher is weight 0 — his projections don't enter totals."""
        projections = {
            1: _proj(1, "Ace",      "SP", "pitcher", overall_rank=30,
                     ip=180, k=220, qs=18, era=3.20, whip=1.10),
            2: _proj(2, "Streamer", "SP", "pitcher", overall_rank=400,
                     ip=80,  k=60,  qs=4,  era=5.80, whip=1.55),
        }
        slots = [
            {"mlb_id": 1, "lineup_slot_id": 14},
            {"mlb_id": 2, "lineup_slot_id": 14},
        ]
        totals_with, weights_with = build_team_totals(
            slots, projections, stream_slot_id=2,
        )
        # Compare against totals built from the ace alone
        ace_only_slots = [{"mlb_id": 1, "lineup_slot_id": 14}]
        totals_ace, _ = build_team_totals(ace_only_slots, projections)

        assert weights_with[2] == 0.0
        assert weights_with[1] == 1.0
        # Zero-weighting is equivalent to absence for all count & rate-weighted sums
        assert totals_with.k == pytest.approx(totals_ace.k)
        assert totals_with.qs == pytest.approx(totals_ace.qs)
        assert totals_with.total_ip == pytest.approx(totals_ace.total_ip)
        assert totals_with.weighted_era == pytest.approx(totals_ace.weighted_era)
        assert totals_with.weighted_whip == pytest.approx(totals_ace.weighted_whip)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/backend/analysis/test_waivers.py::TestBuildTeamTotals::test_stream_slot_zero_weighted -v`
Expected: FAIL — `TypeError: build_team_totals() got an unexpected keyword argument 'stream_slot_id'`

- [ ] **Step 3: Update `build_team_totals` signature and body**

In `backend/analysis/waivers.py`, replace the current `build_team_totals` function (lines 339-396) with:

```python
def build_team_totals(
    roster_slots: list[dict],
    projections: dict[int, PlayerProjection],
    stream_slot_id: Optional[int] = None,
) -> tuple[TeamTotals, dict[int, float]]:
    """Build team totals using lineup-optimized weights.

    Pitchers: all non-IL at 1.0 (daily league rotation).
    Hitters: run greedy optimizer to assign active (1.0) or bench (0.20).
    IL: 0.0.
    Stream slot (if provided): 0.0 — treated as replacement-level.

    Returns:
        (TeamTotals, {mlb_id: weight})
    """
    totals = TeamTotals()
    weights: dict[int, float] = {}

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

        if stream_slot_id is not None and pid == stream_slot_id:
            weights[pid] = 0.0
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

- [ ] **Step 4: Run the new test and all existing `TestBuildTeamTotals` tests to verify**

Run: `pytest tests/backend/analysis/test_waivers.py::TestBuildTeamTotals -v`
Expected: all tests pass (new test + 4 existing).

- [ ] **Step 5: Commit**

```bash
git add backend/analysis/waivers.py tests/backend/analysis/test_waivers.py
git commit -m "feat(waivers): zero-weight stream slot in build_team_totals"
```

---

## Task 3: Extend `compute_waiver_recommendations` with exclude_stream_slot + same_type_only

**Files:**
- Modify: `backend/analysis/waivers.py` (`compute_waiver_recommendations`, lines 402-572)
- Test: `tests/backend/analysis/test_waivers.py`

- [ ] **Step 1: Write failing integration-style tests**

Append to `tests/backend/analysis/test_waivers.py`:

```python
from unittest.mock import patch
from backend.analysis.waivers import compute_waiver_recommendations


def _build_test_projections():
    """Minimal roster + opponents + FAs sufficient to exercise the engine."""
    projs = {}
    # My roster: 10 hitters + 1 ace + 1 streamer
    hitter_defs = [
        (101, "C_Me",   "C",   10, 85, 280, 95, 5, 0.360),
        (102, "1B_Me",  "1B",  20, 90, 300, 100, 2, 0.370),
        (103, "2B_Me",  "2B",  30, 80, 240, 70, 20, 0.340),
        (104, "3B_Me",  "3B",  40, 75, 260, 85, 5, 0.355),
        (105, "SS_Me",  "SS",  50, 85, 250, 75, 25, 0.345),
        (106, "OF1_Me", "OF",  60, 95, 310, 100, 8, 0.370),
        (107, "OF2_Me", "OF",  70, 75, 230, 80, 12, 0.335),
        (108, "OF3_Me", "OF",  80, 70, 210, 65, 18, 0.325),
        (109, "DH_Me",  "DH",  90, 100, 330, 120, 0, 0.390),
        (110, "BenchH", "1B", 300, 40, 120, 40, 3, 0.310),  # bench-worthy
    ]
    for pid, name, pos, rk, r, tb, rbi, sb, obp in hitter_defs:
        projs[pid] = _proj(pid, name, pos, "hitter",
                           eligible_positions=pos, overall_rank=rk,
                           pa=600, r=r, tb=tb, rbi=rbi, sb=sb, obp=obp)

    projs[201] = _proj(201, "Ace_Me",      "SP", "pitcher",
                       overall_rank=25, ip=200, k=240, qs=20,
                       era=3.10, whip=1.05, svhd=0)
    projs[202] = _proj(202, "Streamer_Me", "SP", "pitcher",
                       overall_rank=450, ip=60,  k=40,  qs=2,
                       era=5.80, whip=1.55, svhd=0)

    # Opponents: 9 copies of a "median" team
    for i in range(301, 310):
        projs[i] = _proj(i, f"Opp{i}", "SS", "hitter",
                         eligible_positions="SS", overall_rank=100,
                         pa=600, r=75, tb=250, rbi=80, sb=10, obp=0.340)
    for i in range(401, 410):
        projs[i] = _proj(i, f"OppSP{i}", "SP", "pitcher",
                         overall_rank=150, ip=180, k=180, qs=14,
                         era=3.80, whip=1.25, svhd=0)

    # Free agents
    projs[501] = _proj(501, "FA_Hitter", "2B", "hitter",
                       eligible_positions="2B", overall_rank=70,
                       pa=600, r=90, tb=290, rbi=95, sb=8, obp=0.365)
    projs[502] = _proj(502, "FA_Pitcher", "SP", "pitcher",
                       overall_rank=80,  ip=190, k=210, qs=18,
                       era=3.30, whip=1.10, svhd=0)
    return projs


def _call_engine(**kwargs):
    """Call compute_waiver_recommendations with _build_test_projections patched in."""
    projs = _build_test_projections()
    my_roster_ids = list(range(101, 111)) + [201, 202]
    my_roster_slots = (
        [{"mlb_id": i, "lineup_slot_id": 0} for i in range(101, 111)]
        + [{"mlb_id": 201, "lineup_slot_id": 14},
           {"mlb_id": 202, "lineup_slot_id": 14}]
    )
    # 9 opponent teams, each a median hitter + median pitcher
    opp_team_slots = [
        [{"mlb_id": 301 + i, "lineup_slot_id": 0},
         {"mlb_id": 401 + i, "lineup_slot_id": 14}]
        for i in range(9)
    ]
    fa_ids = [501, 502]

    defaults = dict(
        my_roster_ids=my_roster_ids,
        my_roster_slots=my_roster_slots,
        all_team_roster_slots=opp_team_slots,
        free_agent_ids=fa_ids,
        season=2026,
        remaining_faab=100.0,
        open_roster_slots=0,
    )
    defaults.update(kwargs)

    with patch(
        "backend.analysis.waivers.load_projections_for_players",
        return_value=projs,
    ):
        return compute_waiver_recommendations(**defaults)


class TestComputeWaiverRecommendationsStreamSlot:
    def test_stream_slot_never_appears_as_drop_when_excluded(self):
        result = _call_engine(exclude_stream_slot=True, same_type_only=False)
        drop_ids = [
            r["drop_player"]["id"]
            for r in result["recommendations"]
            if r["drop_player"] is not None
        ]
        assert 202 not in drop_ids, f"Stream slot 202 appeared as drop: {drop_ids}"

    def test_stream_slot_included_when_flag_off(self):
        """Disabling the flag returns to the pre-change behavior."""
        result = _call_engine(exclude_stream_slot=False, same_type_only=False)
        drop_ids = [
            r["drop_player"]["id"]
            for r in result["recommendations"]
            if r["drop_player"] is not None
        ]
        # Streamer becomes a drop candidate again (for hitter adds)
        assert 202 in drop_ids

    def test_response_includes_stream_slot_player(self):
        result = _call_engine(exclude_stream_slot=True)
        assert result["stream_slot_player"] is not None
        assert result["stream_slot_player"]["id"] == 202
        assert result["stream_slot_player"]["name"] == "Streamer_Me"

    def test_response_stream_slot_null_when_flag_off(self):
        result = _call_engine(exclude_stream_slot=False)
        assert result["stream_slot_player"] is None


class TestComputeWaiverRecommendationsSameType:
    def test_same_type_only_no_cross_type_drops(self):
        result = _call_engine(exclude_stream_slot=True, same_type_only=True)
        for r in result["recommendations"]:
            if r["drop_player"] is None:
                continue
            add_pos = r["add_player"]["position"]
            drop_pos = r["drop_player"]["position"]
            add_is_pitcher = add_pos in ("SP", "RP", "P")
            drop_is_pitcher = drop_pos in ("SP", "RP", "P")
            assert add_is_pitcher == drop_is_pitcher, (
                f"Cross-type rec: add={add_pos} drop={drop_pos}"
            )

    def test_same_type_default_off_allows_cross_type(self):
        """When disabled, the engine can return cross-type recommendations."""
        result = _call_engine(exclude_stream_slot=False, same_type_only=False)
        # FA_Hitter (501, hitter) may have a pitcher drop in this mode
        crosses = [
            r for r in result["recommendations"]
            if r["drop_player"] is not None
            and r["add_player"]["id"] == 501
            and r["drop_player"]["position"] in ("SP", "RP", "P")
        ]
        assert len(crosses) >= 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/backend/analysis/test_waivers.py::TestComputeWaiverRecommendationsStreamSlot tests/backend/analysis/test_waivers.py::TestComputeWaiverRecommendationsSameType -v`
Expected: FAIL — `TypeError: compute_waiver_recommendations() got an unexpected keyword argument 'exclude_stream_slot'`

- [ ] **Step 3: Update `compute_waiver_recommendations` signature and body**

In `backend/analysis/waivers.py`, replace `compute_waiver_recommendations` (lines 402-572) with this version. Diffs vs current: new params, identify stream slot, pass to `build_team_totals`, filter `droppable_ids`, filter drop loop by `same_type_only`, add `stream_slot_player` to response.

```python
def compute_waiver_recommendations(
    my_roster_ids: list[int],
    my_roster_slots: list[dict],
    all_team_roster_slots: list[list[dict]],
    free_agent_ids: list[int],
    season: int,
    remaining_faab: float = 100.0,
    open_roster_slots: int = 0,
    exclude_stream_slot: bool = True,
    same_type_only: bool = True,
) -> dict:
    """Compute waiver wire recommendations.

    For each (FA, drop) pair, builds the trial roster and re-optimizes the
    lineup to determine proper starter/bench assignments.

    Args:
        exclude_stream_slot: If True, the user's worst-projected active pitcher
            is treated as replacement-level (weight 0 in baseline, not a drop
            candidate). Matches the real-world behavior of streaming that slot.
        same_type_only: If True, only hitter-for-hitter and pitcher-for-pitcher
            drops are evaluated. If False, cross-type drops are also considered
            (tracks one best drop per dropped-player type).
    """
    other_team_ids = [s["mlb_id"] for team in all_team_roster_slots for s in team]
    all_ids = list(set(my_roster_ids + other_team_ids + free_agent_ids))

    projections = load_projections_for_players(all_ids, season)

    # Identify stream slot (may be None)
    stream_slot_id: Optional[int] = None
    if exclude_stream_slot:
        stream_slot_id = identify_stream_slot(my_roster_slots, projections)

    # Build my baseline using lineup optimization
    my_totals, my_weights = build_team_totals(
        my_roster_slots, projections, stream_slot_id=stream_slot_id,
    )

    # Build other teams' totals (stream-slot logic is user-only in v1)
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
    logger.info(f"Stream slot id: {stream_slot_id}, same_type_only: {same_type_only}")
    baseline_wins, baseline_cat_probs = compute_expected_wins(my_cat_values, other_cat_values)

    # Identify droppable players (exclude IL and stream slot)
    droppable_ids: list[int] = []
    for slot in my_roster_slots:
        pid = slot["mlb_id"]
        if slot.get("lineup_slot_id", 0) >= IL_SLOT_THRESHOLD:
            continue
        if stream_slot_id is not None and pid == stream_slot_id:
            continue
        droppable_ids.append(pid)

    # Evaluate each free agent
    recommendations: list[WaiverRecommendation] = []

    for fa_id in free_agent_ids:
        fa_proj = projections.get(fa_id)
        if not fa_proj:
            continue

        # Track best drop per dropped-player type (or just "same_type" when filtered)
        # Keys: "no_drop", "hitter", "pitcher"
        best_drops: dict[str, dict] = {}

        # Try "add without drop" if open roster slots available
        if open_roster_slots > 0:
            trial_slots = list(my_roster_slots) + [{"mlb_id": fa_id, "lineup_slot_id": 0}]
            trial_totals, _ = build_team_totals(
                trial_slots, projections, stream_slot_id=stream_slot_id,
            )
            trial_cat_values = trial_totals.category_values()
            trial_wins, trial_cat_probs = compute_expected_wins(trial_cat_values, other_cat_values)
            delta = trial_wins - baseline_wins
            best_drops["no_drop"] = {
                "delta": delta,
                "drop_id": None,
                "cat_impact": {
                    cat: round(trial_cat_probs[cat] - baseline_cat_probs[cat], 4)
                    for cat in ALL_CATS
                },
                "stat_delta": {
                    cat: round(trial_cat_values[cat] - my_cat_values[cat], 3)
                    for cat in ALL_CATS
                },
            }

        # Try each drop option, tracking best per dropped-player type
        for drop_id in droppable_ids:
            drop_proj = projections.get(drop_id)
            if not drop_proj:
                continue

            drop_type = drop_proj.player_type  # "hitter" or "pitcher"

            # Same-type filter: skip cross-type drops when enabled
            if same_type_only and drop_type != fa_proj.player_type:
                continue

            trial_slots = [s for s in my_roster_slots if s["mlb_id"] != drop_id]
            trial_slots.append({"mlb_id": fa_id, "lineup_slot_id": 0})

            trial_totals, _ = build_team_totals(
                trial_slots, projections, stream_slot_id=stream_slot_id,
            )
            trial_cat_values = trial_totals.category_values()
            trial_wins, trial_cat_probs = compute_expected_wins(trial_cat_values, other_cat_values)
            delta = trial_wins - baseline_wins

            # Compare against current best for this drop type
            current_best = best_drops.get(drop_type)
            drop_rank = drop_proj.overall_rank
            if current_best is None:
                is_better = True
            else:
                cur_drop_id = current_best["drop_id"]
                cur_drop_rank = projections[cur_drop_id].overall_rank if cur_drop_id and cur_drop_id in projections else -1
                is_better = delta > current_best["delta"] or (delta == current_best["delta"] and drop_rank > cur_drop_rank)

            if is_better:
                best_drops[drop_type] = {
                    "delta": delta,
                    "drop_id": drop_id,
                    "cat_impact": {
                        cat: round(trial_cat_probs[cat] - baseline_cat_probs[cat], 4)
                        for cat in ALL_CATS
                    },
                    "stat_delta": {
                        cat: round(trial_cat_values[cat] - my_cat_values[cat], 3)
                        for cat in ALL_CATS
                    },
                }

        # Emit one recommendation per drop type
        for entry in best_drops.values():
            drop_id = entry["drop_id"]
            drop_proj = projections.get(drop_id) if drop_id else None
            recommendations.append(WaiverRecommendation(
                add_player_id=fa_id,
                add_player_name=fa_proj.name,
                add_player_position=fa_proj.position,
                drop_player_id=drop_id,
                drop_player_name=drop_proj.name if drop_proj else None,
                drop_player_position=drop_proj.position if drop_proj else None,
                delta_expected_wins=round(entry["delta"], 4),
                suggested_faab_bid=0,
                category_impact=entry["cat_impact"],
                category_stat_delta=entry["stat_delta"],
            ))

    recommendations.sort(key=lambda r: r.delta_expected_wins, reverse=True)
    _assign_faab_bids(recommendations, remaining_faab)

    stream_slot_payload = None
    if stream_slot_id is not None:
        sp = projections.get(stream_slot_id)
        if sp is not None:
            stream_slot_payload = {
                "id": stream_slot_id,
                "name": sp.name,
                "position": sp.position,
            }

    return {
        "baseline_expected_wins": round(baseline_wins, 3),
        "baseline_category_probs": {cat: round(v, 4) for cat, v in baseline_cat_probs.items()},
        "my_team_totals": {k: round(v, 3) for k, v in my_cat_values.items()},
        "stream_slot_player": stream_slot_payload,
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
                "category_stat_delta": r.category_stat_delta,
            }
            for i, r in enumerate(recommendations)
        ],
    }
```

- [ ] **Step 4: Run the new tests and the whole waivers test file to catch regressions**

Run: `pytest tests/backend/analysis/test_waivers.py -v`
Expected: all tests pass (pre-existing + all new ones added in Tasks 1-3).

- [ ] **Step 5: Commit**

```bash
git add backend/analysis/waivers.py tests/backend/analysis/test_waivers.py
git commit -m "feat(waivers): add exclude_stream_slot and same_type_only flags"
```

---

## Task 4: Expose new flags through the FastAPI route

**Files:**
- Modify: `backend/api/routes.py` (around lines 633-710)

- [ ] **Step 1: Add fields to `WaiverRequest`**

In `backend/api/routes.py`, replace the `WaiverRequest` class (lines 633-639) with:

```python
class WaiverRequest(BaseModel):
    my_roster: list[WaiverRosterPlayer]
    other_team_rosters: list[WaiverTeamRoster]
    free_agents: list[WaiverRosterPlayer]
    remaining_faab: float = 100.0
    season: int = 2026
    open_roster_slots: int = 0
    exclude_stream_slot: bool = True
    include_cross_type: bool = False
```

- [ ] **Step 2: Pass the new flags into the engine call**

In the same file, replace the `compute_waiver_recommendations(...)` call (lines 702-710) with:

```python
    result = compute_waiver_recommendations(
        my_roster_ids=my_roster_ids,
        my_roster_slots=my_roster_slots,
        all_team_roster_slots=other_team_rosters,
        free_agent_ids=fa_ids,
        season=req.season,
        remaining_faab=req.remaining_faab,
        open_roster_slots=req.open_roster_slots,
        exclude_stream_slot=req.exclude_stream_slot,
        same_type_only=not req.include_cross_type,
    )
```

(Note: the UI flag `include_cross_type` inverts into the engine flag `same_type_only`.)

- [ ] **Step 3: Smoke-test the route by importing routes.py**

Run: `python -c "from backend.api import routes; print('ok')"`
Expected: prints `ok` with no errors.

- [ ] **Step 4: Run the full backend test suite to catch regressions**

Run: `pytest tests/backend/ -v`
Expected: all tests pass. (Existing waiver tests continue to work because the new params default to the new behavior and pre-existing integration tests don't assert cross-type rows.)

- [ ] **Step 5: Commit**

```bash
git add backend/api/routes.py
git commit -m "feat(waivers): accept exclude_stream_slot and include_cross_type on API"
```

---

## Task 5: Forward new flags through the Next.js proxy route

**Files:**
- Modify: `src/app/api/waivers/recommendations/route.ts` (lines 30-120)

- [ ] **Step 1: Read and forward the flags**

In `src/app/api/waivers/recommendations/route.ts`, replace the destructuring on line 33:

```ts
    const { leagueId, teamId, season = '2026' } = body
```

with:

```ts
    const {
      leagueId,
      teamId,
      season = '2026',
      excludeStreamSlot = true,
      includeCrossType = false,
    } = body
```

Then replace the backend fetch body (lines 111-119) with:

```ts
      body: JSON.stringify({
        my_roster: myRoster,
        other_team_rosters: otherTeamRosters,
        free_agents: faList,
        remaining_faab: remainingFaab,
        season: parseInt(season),
        open_roster_slots: openRosterSlots,
        exclude_stream_slot: excludeStreamSlot,
        include_cross_type: includeCrossType,
      }),
```

- [ ] **Step 2: Verify the TypeScript compiles**

Run: `npx tsc --noEmit`
Expected: exit code 0, no type errors.

- [ ] **Step 3: Commit**

```bash
git add src/app/api/waivers/recommendations/route.ts
git commit -m "feat(waivers): pass stream-slot and cross-type flags to backend"
```

---

## Task 6: Frontend UI — checkboxes, STREAM badge, refetch plumbing

**Files:**
- Modify: `src/app/waivers/page.tsx`

- [ ] **Step 1: Extend the `WaiverResults` interface**

In `src/app/waivers/page.tsx`, find the `WaiverResults` interface (around line 45) and add `stream_slot_player`. Replace the interface with:

```tsx
interface WaiverResults {
  baseline_expected_wins: number
  baseline_category_probs: Record<string, number>
  recommendations: Recommendation[]
  remaining_faab: number
  my_roster_count: number
  free_agent_count: number
  other_teams_count: number
  open_roster_slots: number
  my_roster_display: RosterPlayer[]
  stream_slot_player: { id: number; name: string; position: string } | null
}
```

- [ ] **Step 2: Add state and pass flags in the fetch**

In the `WaiversPage` component, after the existing `useState` declarations (around line 137, after `const [refreshStatus, setRefreshStatus] = useState<string | null>(null)`), add:

```tsx
  const [excludeStreamSlot, setExcludeStreamSlot] = useState(true)
  const [includeCrossType, setIncludeCrossType] = useState(false)
```

Then replace the `handleFetchRecommendations` body (specifically the `body` of the fetch, lines 215-218) to include the flags:

```tsx
        body: JSON.stringify({
          leagueId: selectedLeague,
          teamId: selectedTeam,
          excludeStreamSlot,
          includeCrossType,
        }),
```

- [ ] **Step 3: Auto-refetch when flags change**

Below the existing "Auto-fetch recommendations when settings are restored" effect (around line 197), add a new effect that re-fetches when the flags change but only after the initial load:

```tsx
  useEffect(() => {
    if (!results) return  // only refetch if we already have data
    handleFetchRecommendations()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [excludeStreamSlot, includeCrossType])
```

- [ ] **Step 4: Add the checkboxes UI**

In the JSX, locate the position filter row:

```tsx
            {/* Position filter */}
            <div className="flex gap-1 mb-3 flex-wrap">
```

Insert, immediately **above** that block (before the comment), this new block:

```tsx
            {/* Recommendation filters */}
            <div className="flex gap-4 mb-2 text-xs">
              <label className="flex items-center gap-1.5 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={excludeStreamSlot}
                  onChange={(e) => setExcludeStreamSlot(e.target.checked)}
                  className="accent-blue-500"
                />
                <span className="text-gray-400">
                  Exclude stream slot
                  {results.stream_slot_player && (
                    <span className="text-gray-500"> ({results.stream_slot_player.name})</span>
                  )}
                </span>
              </label>
              <label className="flex items-center gap-1.5 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={includeCrossType}
                  onChange={(e) => setIncludeCrossType(e.target.checked)}
                  className="accent-blue-500"
                />
                <span className="text-gray-400">Show cross-type swaps</span>
              </label>
            </div>
```

- [ ] **Step 5: Add the STREAM badge on the roster row**

Find the roster-display rendering (around lines 405-419). Replace the player-row JSX with a version that shows a STREAM badge when the player is the stream slot:

```tsx
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-x-4 gap-y-0.5 text-xs">
                {rosterBySlot.map(({ slot, players }) => (
                  players.map((p, i) => {
                    const isStreamSlot = !!(
                      results.stream_slot_player &&
                      p.mlb_id === results.stream_slot_player.id &&
                      excludeStreamSlot
                    )
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
                        <span className={`text-[10px] ${posColors[p.position] || 'text-gray-500'}`}>{p.position}</span>
                        {isStreamSlot && (
                          <span className="text-[9px] font-bold text-orange-400 bg-orange-500/10 px-1 rounded">STREAM</span>
                        )}
                      </div>
                    )
                  })
                ))}
              </div>
```

- [ ] **Step 6: Verify TypeScript compiles**

Run: `npx tsc --noEmit`
Expected: exit code 0, no type errors.

- [ ] **Step 7: Start the dev server and manually verify**

Run: `npm run dev` (in one terminal) and `uvicorn backend.api.main:app --reload --port 8000` (in another, if not already running).

Open `http://localhost:3000/waivers`, select your league + team, wait for recommendations.

Verify:
- The "Exclude stream slot (<name>)" checkbox appears above the position filter, checked by default.
- The "Show cross-type swaps" checkbox appears next to it, unchecked by default.
- The stream-slot player (likely Will Warren) has a STREAM badge next to his name in the roster panel.
- The top recommendations now show hitter-for-hitter drops (the worst hitter on your roster) instead of "drop Will Warren" for every hitter FA.
- Unchecking "Exclude stream slot" refetches and brings back the old behavior.
- Checking "Show cross-type swaps" refetches and reveals additional rows that cross types.

- [ ] **Step 8: Commit**

```bash
git add src/app/waivers/page.tsx
git commit -m "feat(waivers): add stream-slot & cross-type toggles, STREAM badge"
```

---

## Task 7: Final check — run full test suite and review

**Files:** none

- [ ] **Step 1: Run backend tests**

Run: `pytest tests/backend/ -v`
Expected: all pass.

- [ ] **Step 2: Run TypeScript check**

Run: `npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Confirm memory file is updated**

If any durable facts about the new behavior belong in project memory, add them via the memory system. (Most of this plan's changes are self-documenting in the design spec already — only add memory if there's a non-obvious runtime quirk discovered during implementation.)

---

## Done

All seven tasks complete. The waivers page now answers "which FAs are real upgrades to my core roster" by excluding the streamed slot and defaulting to same-type swaps, with both behaviors user-toggleable.
