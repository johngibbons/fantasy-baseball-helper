# Streaming-Aware Bench Simulation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the bench contribution simulation to model SP streaming (cycling add/drops through bench pitcher slots) and determine the optimal bench composition given a 10 transaction/week budget.

**Architecture:** Add streaming logic to the existing `simulate_season` function in `bench_contributions.py`. A new `allocate_weekly_streams` function greedily assigns replacement-level SP pickups to empty pitcher slots within the weekly transaction budget. The CLI sweep tests a 2D grid of roster composition x streaming intensity.

**Tech Stack:** Python 3.12, existing `bench_contributions.py` module, existing `optimize_daily_lineup` from `matchup.py`, pytest.

---

## File Structure

| File | Changes |
|------|---------|
| `backend/analysis/bench_contributions.py` | Add `replacement_level_per_start_stats()`, `allocate_weekly_streams()`, extend `simulate_season` with `streams_per_week` param, add streaming stat tracking to `SimulationResult` |
| `tests/backend/analysis/test_bench_contributions.py` | Add `TestStreaming` class with tests for weekly allocation and season simulation with streaming |
| `sweep_bench_contributions.py` | Update to run composition x streaming grid, new `print_streaming_sweep_summary()` |

---

### Task 1: Replacement-Level Per-Start Stats

**Files:**
- Modify: `tests/backend/analysis/test_bench_contributions.py`
- Modify: `backend/analysis/bench_contributions.py`

- [ ] **Step 1: Write failing test**

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
    replacement_level_per_start_stats,
)


class TestStreaming:
    def test_replacement_level_per_start_stats(self):
        """Per-start stats are full-season replacement-level projections / projected starts."""
        stats = replacement_level_per_start_stats()
        # Replacement-level SP: 100 IP, 80 K, 6 QS over ~18 starts (100/5.5)
        assert stats["k"] == pytest.approx(80 / 18, abs=0.5)
        assert stats["qs"] == pytest.approx(6 / 18, abs=0.1)
        assert stats["ip"] == pytest.approx(100 / 18, abs=0.5)
        assert stats["era"] == pytest.approx(4.50, abs=0.01)
        assert stats["whip"] == pytest.approx(1.35, abs=0.01)
        assert stats["svhd"] == pytest.approx(0.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/backend/analysis/test_bench_contributions.py::TestStreaming::test_replacement_level_per_start_stats -v`
Expected: FAIL — `cannot import name 'replacement_level_per_start_stats'`

- [ ] **Step 3: Implement**

Add to `backend/analysis/bench_contributions.py`, after the `_replacement_level_pitcher` function:

```python
# Replacement-level SP full-season projections (same as _replacement_level_pitcher)
_REPL_SP_IP = 100.0
_REPL_SP_K = 80
_REPL_SP_QS = 6
_REPL_SP_ERA = 4.50
_REPL_SP_WHIP = 1.35
_REPL_SP_SVHD = 0
_REPL_SP_STARTS = round(_REPL_SP_IP / IP_PER_START)  # ~18


def replacement_level_per_start_stats() -> dict[str, float]:
    """Return per-start stat line for a replacement-level streaming SP.

    Derived from full-season replacement-level projections (100 IP, 80 K, 6 QS,
    4.50 ERA, 1.35 WHIP) divided by projected starts (~18).
    """
    return {
        "ip": _REPL_SP_IP / _REPL_SP_STARTS,
        "k": _REPL_SP_K / _REPL_SP_STARTS,
        "qs": _REPL_SP_QS / _REPL_SP_STARTS,
        "era": _REPL_SP_ERA,   # rate stat — carried as-is
        "whip": _REPL_SP_WHIP,  # rate stat — carried as-is
        "svhd": 0.0,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/backend/analysis/test_bench_contributions.py::TestStreaming::test_replacement_level_per_start_stats -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/analysis/bench_contributions.py tests/backend/analysis/test_bench_contributions.py
git commit -m "feat(streaming): add replacement-level per-start stats"
```

---

### Task 2: Weekly Stream Allocation

**Files:**
- Modify: `tests/backend/analysis/test_bench_contributions.py`
- Modify: `backend/analysis/bench_contributions.py`

- [ ] **Step 1: Write failing test**

```python
# Add to TestStreaming class in tests/backend/analysis/test_bench_contributions.py

    def test_allocate_weekly_streams_respects_budget(self):
        """allocate_weekly_streams never exceeds max_transactions."""
        # 7 days, teams playing every day, 2 streaming slots
        week_dates = [f"2026-04-{d:02d}" for d in range(6, 13)]  # Mon-Sun
        schedule = {d: {"NYY", "BOS", "LAD"} for d in week_dates}
        # No anchored SPs pitching on any day → all 7 days are streamable
        sp_start_dates: dict[int, set[str]] = {}
        streaming_slot_ids = [-100, -200]  # two streaming slots

        streams = allocate_weekly_streams(
            streaming_slot_ids=streaming_slot_ids,
            sp_start_dates=sp_start_dates,
            week_dates=week_dates,
            schedule=schedule,
            max_transactions=3,
        )
        total_pickups = sum(len(v) for v in streams.values())
        assert total_pickups == 3  # capped at budget

    def test_allocate_weekly_streams_skips_days_with_anchored_start(self):
        """Don't stream into a slot on days when its anchored SP is already pitching."""
        week_dates = [f"2026-04-{d:02d}" for d in range(6, 13)]
        schedule = {d: {"NYY"} for d in week_dates}
        # Slot -100's anchored SP pitches on day 6 and 11
        sp_start_dates = {-100: {"2026-04-06", "2026-04-11"}}
        streaming_slot_ids = [-100]

        streams = allocate_weekly_streams(
            streaming_slot_ids=streaming_slot_ids,
            sp_start_dates=sp_start_dates,
            week_dates=week_dates,
            schedule=schedule,
            max_transactions=10,
        )
        # Should not stream on days 6 and 11 (anchored SP pitching)
        assert "2026-04-06" not in streams or -100 not in [s["slot_id"] for s in streams.get("2026-04-06", [])]
        assert "2026-04-11" not in streams or -100 not in [s["slot_id"] for s in streams.get("2026-04-11", [])]
        # Should stream on the other 5 days
        streamed_days = sum(1 for d, v in streams.items() if len(v) > 0)
        assert streamed_days == 5

    def test_allocate_weekly_streams_zero_budget(self):
        """Zero transactions means no streaming."""
        week_dates = [f"2026-04-{d:02d}" for d in range(6, 13)]
        schedule = {d: {"NYY"} for d in week_dates}
        streams = allocate_weekly_streams(
            streaming_slot_ids=[-100],
            sp_start_dates={},
            week_dates=week_dates,
            schedule=schedule,
            max_transactions=0,
        )
        total_pickups = sum(len(v) for v in streams.values())
        assert total_pickups == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/backend/analysis/test_bench_contributions.py::TestStreaming -v`
Expected: FAIL — `cannot import name 'allocate_weekly_streams'`

- [ ] **Step 3: Implement**

Add to `backend/analysis/bench_contributions.py`, after `replacement_level_per_start_stats`:

```python
def allocate_weekly_streams(
    streaming_slot_ids: list[int],
    sp_start_dates: dict[int, set[str]],
    week_dates: list[str],
    schedule: dict[str, set[str]],
    max_transactions: int,
) -> dict[str, list[dict]]:
    """Greedily assign streaming SP pickups across a week within the transaction budget.

    For each streaming slot, on days when the slot's anchored SP is NOT pitching
    and there are teams playing, assign a replacement-level streamer. Fills days
    greedily until the transaction budget is exhausted.

    Args:
        streaming_slot_ids: mlb_ids of roster players designated as streaming slots.
        sp_start_dates: mlb_id -> set of dates when that SP is pitching (from simulation).
        week_dates: ordered list of date strings for this week.
        schedule: date -> set of team abbreviations playing that day.
        max_transactions: maximum pickups allowed this week.

    Returns:
        dict mapping date -> list of streamer dicts (each with "slot_id" and "player" keys).
        The "player" dict has the keys needed by optimize_daily_lineup.
    """
    if max_transactions <= 0 or not streaming_slot_ids:
        return {}

    # Collect all (date, slot_id) pairs where streaming is possible
    streamable: list[tuple[str, int]] = []
    for date in week_dates:
        if not schedule.get(date):
            continue
        for slot_id in streaming_slot_ids:
            # Don't stream if the anchored SP is pitching this day
            if date in sp_start_dates.get(slot_id, set()):
                continue
            streamable.append((date, slot_id))

    # Greedily take up to max_transactions (already in date order)
    streams: dict[str, list[dict]] = {}
    used = 0
    for date, slot_id in streamable:
        if used >= max_transactions:
            break
        streamer_id = -(slot_id * 1000 + used)  # unique synthetic ID
        entry = {
            "slot_id": slot_id,
            "player": {
                "mlb_id": streamer_id,
                "position": "SP",
                "player_type": "pitcher",
                "eligible_positions": "SP",
            },
        }
        streams.setdefault(date, []).append(entry)
        used += 1

    return streams
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/backend/analysis/test_bench_contributions.py::TestStreaming -v`
Expected: PASS (4 tests — 1 from Task 1 + 3 new)

- [ ] **Step 5: Commit**

```bash
git add backend/analysis/bench_contributions.py tests/backend/analysis/test_bench_contributions.py
git commit -m "feat(streaming): add weekly stream allocation with transaction budget"
```

---

### Task 3: Extend simulate_season with Streaming

**Files:**
- Modify: `tests/backend/analysis/test_bench_contributions.py`
- Modify: `backend/analysis/bench_contributions.py`

- [ ] **Step 1: Write failing test**

```python
# Add to TestStreaming class

    def test_streaming_adds_extra_starts(self):
        """With streaming enabled, total pitcher starts should increase."""
        # Minimal roster: hitters fill slots, a few SPs, one streaming slot
        roster = [
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
            # Pitchers
            _make_pitcher(20, "SP1", "SP", "NYY", ip=180.0, rank=10),
            _make_pitcher(21, "SP2", "SP", "NYY", ip=180.0, rank=11),
            _make_pitcher(22, "SP3", "SP", "NYY", ip=180.0, rank=12),
            _make_pitcher(23, "RP1", "RP", "NYY", ip=60.0, rank=30),
            _make_pitcher(24, "RP2", "RP", "NYY", ip=60.0, rank=31),
            # Streaming slot — worst-ranked pitcher
            _make_pitcher(25, "StreamSP", "SP", "NYY", ip=100.0, rank=350),
        ]
        # 4-week schedule, NYY plays every day
        schedule = {f"2026-04-{d:02d}" for d in range(1, 29)}
        schedule_dict = {d: {"NYY"} for d in sorted(schedule)}

        # Run without streaming
        result_no_stream = simulate_season(
            roster, schedule_dict, team_season_games={"NYY": 162},
            num_sims=30, seed=42, streams_per_week=0,
        )

        # Run with streaming (10/week)
        result_streaming = simulate_season(
            roster, schedule_dict, team_season_games={"NYY": 162},
            num_sims=30, seed=42, streams_per_week=10,
        )

        # Streaming should produce more total streamer starts
        assert result_streaming.streaming_starts > 0
        assert result_no_stream.streaming_starts == 0

    def test_streaming_zero_is_backward_compatible(self):
        """streams_per_week=0 produces identical results to no streaming."""
        roster = [
            _make_hitter(1, "C1", "C", "NYY", rank=10),
            _make_hitter(2, "1B1", "1B", "NYY", rank=11),
            _make_pitcher(20, "SP1", "SP", "NYY", ip=180.0, rank=10),
            _make_pitcher(21, "RP1", "RP", "NYY", ip=60.0, rank=30),
        ]
        schedule = {f"2026-04-{d:02d}": {"NYY"} for d in range(1, 8)}
        r1 = simulate_season(roster, schedule, {"NYY": 162}, num_sims=20, seed=42)
        r2 = simulate_season(roster, schedule, {"NYY": 162}, num_sims=20, seed=42, streams_per_week=0)
        assert r1.player_contribution_rates == r2.player_contribution_rates
        assert r1.streaming_starts == 0
        assert r2.streaming_starts == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/backend/analysis/test_bench_contributions.py::TestStreaming::test_streaming_adds_extra_starts -v`
Expected: FAIL — `simulate_season() got an unexpected keyword argument 'streams_per_week'`

- [ ] **Step 3: Extend SimulationResult and simulate_season**

Update `SimulationResult` in `backend/analysis/bench_contributions.py`:

```python
@dataclass
class SimulationResult:
    """Results from a full-season Monte Carlo lineup simulation."""
    player_contribution_rates: dict[int, float]   # mlb_id -> fraction of team games started
    player_days_started: dict[int, float]          # mlb_id -> avg days started across sims
    player_days_available: dict[int, float]        # mlb_id -> avg days team played
    streaming_starts: float = 0.0                  # avg streamer starts per sim
    streaming_stats: dict[str, float] | None = None  # avg season stats from streamers
```

Update `simulate_season` signature and add streaming logic. Add `streams_per_week: int = 0` parameter. Inside the simulation loop, after distributing SP starts and before the daily loop, group dates into weeks and call `allocate_weekly_streams`. Inject streamers into `available_today`.

The full updated `simulate_season`:

```python
def simulate_season(
    roster: list[RosterPlayer],
    schedule: dict[str, set[str]],
    team_season_games: dict[str, int],
    num_sims: int = 200,
    seed: int | None = None,
    streams_per_week: int = 0,
) -> SimulationResult:
    """Run Monte Carlo daily lineup simulation across a full MLB season.

    For each iteration:
    1. Distribute each SP's projected starts across their team's schedule (with jitter)
    2. If streaming enabled, allocate weekly streamer pickups within transaction budget
    3. For each day, determine which players are available (including streamers)
    4. Run the lineup optimizer on available players
    5. Track starts vs bench for roster players and streamers separately
    """
    from backend.analysis.matchup import optimize_daily_lineup

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

    # Streaming stats tracking
    total_streaming_starts = 0
    per_start = replacement_level_per_start_stats() if streams_per_week > 0 else {}
    streaming_stat_totals: dict[str, float] = {cat: 0.0 for cat in ["ip", "k", "qs", "era", "whip", "svhd"]}

    # Identify streaming slot candidates: lowest-ranked bench SPs
    # (We'll determine which are "bench" by rank — worst-ranked pitchers)
    pitchers_by_rank = sorted(
        [p for p in roster if p.player_type == "pitcher"],
        key=lambda p: p.overall_rank, reverse=True,
    )
    # Streaming slots are the worst-ranked pitchers, up to streams_per_week
    # (you won't stream more slots than you have transactions)
    streaming_slot_ids = [p.mlb_id for p in pitchers_by_rank[:streams_per_week]] if streams_per_week > 0 else []

    # Group dates into weeks (Mon-Sun)
    weeks: list[list[str]] = []
    if sorted_dates:
        from datetime import date as dt_date
        current_week: list[str] = []
        for d in sorted_dates:
            parsed = dt_date.fromisoformat(d)
            if current_week and parsed.weekday() == 0:  # Monday = new week
                weeks.append(current_week)
                current_week = []
            current_week.append(d)
        if current_week:
            weeks.append(current_week)

    for _sim in range(num_sims):
        # Distribute SP starts for this iteration
        sp_start_dates: dict[int, set[str]] = {}
        for p in roster:
            if _is_sp(p):
                full_season_starts = round(p.proj_ip / IP_PER_START)
                dates = team_game_dates.get(p.team, [])
                season_games = team_season_games.get(p.team, 162)
                if season_games > 0:
                    sim_starts = max(1, round(full_season_starts * len(dates) / season_games))
                else:
                    sim_starts = full_season_starts
                sp_start_dates[p.mlb_id] = distribute_sp_starts(sim_starts, dates, rng)

        # Allocate streaming pickups per week
        all_streams: dict[str, list[dict]] = {}
        if streams_per_week > 0:
            for week_dates in weeks:
                week_streams = allocate_weekly_streams(
                    streaming_slot_ids=streaming_slot_ids,
                    sp_start_dates=sp_start_dates,
                    week_dates=week_dates,
                    schedule=schedule,
                    max_transactions=streams_per_week,
                )
                for d, entries in week_streams.items():
                    all_streams.setdefault(d, []).extend(entries)

        for date in sorted_dates:
            teams_playing = schedule[date]
            available_today: list[dict] = []

            for p in roster:
                if p.team not in teams_playing:
                    continue
                total_team_days[p.mlb_id] += 1

                if p.player_type == "hitter":
                    if rng.random() > availability_rates[p.mlb_id]:
                        continue
                elif _is_sp(p):
                    if date not in sp_start_dates.get(p.mlb_id, set()):
                        continue

                available_today.append({
                    "mlb_id": p.mlb_id,
                    "position": p.position,
                    "player_type": p.player_type,
                    "eligible_positions": p.eligible_positions,
                })

            # Add streamers for today
            for stream_entry in all_streams.get(date, []):
                available_today.append(stream_entry["player"])

            lineup = optimize_daily_lineup(available_today)
            starting_ids = {pl["mlb_id"] for pl in lineup["starters"]}

            for mid in starting_ids:
                if mid in total_starts:
                    total_starts[mid] += 1

            # Track streaming starts and stats
            for stream_entry in all_streams.get(date, []):
                streamer_id = stream_entry["player"]["mlb_id"]
                if streamer_id in starting_ids:
                    total_streaming_starts += 1
                    for stat in ["ip", "k", "qs", "svhd"]:
                        streaming_stat_totals[stat] += per_start[stat]
                    streaming_stat_totals["era"] += per_start["era"] * per_start["ip"]
                    streaming_stat_totals["whip"] += per_start["whip"] * per_start["ip"]

    contribution_rates: dict[int, float] = {}
    avg_starts: dict[int, float] = {}
    avg_available: dict[int, float] = {}

    for p in roster:
        mid = p.mlb_id
        team_days = total_team_days[mid]
        avg_available[mid] = team_days / num_sims
        avg_starts[mid] = total_starts[mid] / num_sims
        contribution_rates[mid] = total_starts[mid] / team_days if team_days > 0 else 0.0

    # Compute average streaming stats per sim
    avg_streaming_stats: dict[str, float] | None = None
    if streams_per_week > 0:
        total_stream_ip = streaming_stat_totals["ip"]
        avg_streaming_stats = {
            "IP": total_stream_ip / num_sims,
            "K": streaming_stat_totals["k"] / num_sims,
            "QS": streaming_stat_totals["qs"] / num_sims,
            "ERA": streaming_stat_totals["era"] / total_stream_ip if total_stream_ip > 0 else 0.0,
            "WHIP": streaming_stat_totals["whip"] / total_stream_ip if total_stream_ip > 0 else 0.0,
            "SVHD": streaming_stat_totals["svhd"] / num_sims,
        }

    return SimulationResult(
        player_contribution_rates=contribution_rates,
        player_days_started=avg_starts,
        player_days_available=avg_available,
        streaming_starts=total_streaming_starts / num_sims,
        streaming_stats=avg_streaming_stats,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/backend/analysis/test_bench_contributions.py::TestStreaming -v`
Expected: PASS (6 tests total)

- [ ] **Step 5: Run full test suite to check backward compatibility**

Run: `.venv/bin/python -m pytest tests/backend/analysis/test_bench_contributions.py -v`
Expected: All 28 tests pass (22 existing + 6 new). The existing tests don't pass `streams_per_week`, which defaults to 0 — backward compatible.

- [ ] **Step 6: Commit**

```bash
git add backend/analysis/bench_contributions.py tests/backend/analysis/test_bench_contributions.py
git commit -m "feat(streaming): extend simulate_season with streaming support"
```

---

### Task 4: Update CLI Sweep for Composition x Streaming Grid

**Files:**
- Modify: `sweep_bench_contributions.py`

- [ ] **Step 1: Update compute_stat_impact to include streaming stats**

The existing `compute_stat_impact` computes stats from rostered players. For the streaming sweep, we need to ADD streaming stats on top. Update `print_sweep_summary` in the CLI to merge `result.streaming_stats` into the stat impact.

Add a helper function in `sweep_bench_contributions.py`:

```python
def compute_total_impact(
    config: SweepConfig,
    result: SimulationResult,
) -> dict[str, float]:
    """Compute total stat impact: roster player contributions + streaming stats."""
    impact = compute_stat_impact(config.roster, result.player_contribution_rates)
    if result.streaming_stats:
        # Add streaming counting stats
        for cat in ["K", "QS", "SVHD"]:
            impact[cat] += result.streaming_stats.get(cat, 0.0)
        # Blend streaming rate stats with roster rate stats (IP-weighted)
        stream_ip = result.streaming_stats.get("IP", 0.0)
        if stream_ip > 0:
            # Recompute ERA/WHIP blending roster + streaming IP
            roster_ip = sum(
                p.proj_ip * result.player_contribution_rates.get(p.mlb_id, 0.0)
                for p in config.roster if p.player_type == "pitcher" and p.proj_ip > 0
            )
            total_ip = roster_ip + stream_ip
            if total_ip > 0:
                impact["ERA"] = (impact["ERA"] * roster_ip + result.streaming_stats["ERA"] * stream_ip) / total_ip
                impact["WHIP"] = (impact["WHIP"] * roster_ip + result.streaming_stats["WHIP"] * stream_ip) / total_ip
    return impact
```

- [ ] **Step 2: Rewrite the main loop and summary for the 2D grid**

Replace the sweep logic in `main()` and add `print_streaming_sweep_summary`:

```python
STREAMING_LEVELS = [0, 3, 6, 10]


def print_streaming_sweep_summary(
    configs: list[SweepConfig],
    all_results: dict[str, dict[int, SimulationResult]],
) -> None:
    """Print 2D grid: rows = compositions, columns = streaming levels."""
    cats = ["R", "TB", "RBI", "SB", "OBP", "K", "QS", "ERA", "WHIP", "SVHD"]

    print(f"\n{'=' * 100}")
    print(f"{'BENCH COMPOSITION x STREAMING SWEEP':^100}")
    print(f"{'=' * 100}")

    # Find baseline (first config, 0 streams)
    baseline_config = configs[0]
    baseline_result = all_results[baseline_config.label][0]
    baseline_impact = compute_total_impact(baseline_config, baseline_result)

    for stream_level in STREAMING_LEVELS:
        print(f"\n  --- {stream_level} streams/week ---")
        header = f"  {'Config':<14}"
        for cat in cats:
            header += f" {cat:>6}"
        header += f" {'StrmK':>6} {'StrmQS':>6}"
        print(header)
        print(f"  {'-' * 96}")

        for config in configs:
            result = all_results[config.label][stream_level]
            impact = compute_total_impact(config, result)

            line = f"  {config.label:<14}"
            for cat in cats:
                delta = impact[cat] - baseline_impact[cat]
                if config.label == "baseline" and stream_level == 0:
                    # Show absolute values for baseline/0-stream
                    if cat in ("OBP", "ERA", "WHIP"):
                        line += f" {impact[cat]:>6.3f}"
                    else:
                        line += f" {impact[cat]:>6.1f}"
                else:
                    if cat in ("OBP", "ERA", "WHIP"):
                        line += f" {delta:>+6.3f}"
                    else:
                        line += f" {delta:>+6.1f}"

            # Show streaming-specific stats
            stream_k = result.streaming_stats.get("K", 0.0) if result.streaming_stats else 0.0
            stream_qs = result.streaming_stats.get("QS", 0.0) if result.streaming_stats else 0.0
            line += f" {stream_k:>6.1f} {stream_qs:>6.1f}"
            print(line)

    print(f"\n  Baseline = current roster with 0 streams. All other cells show delta vs baseline.")
    print(f"  StrmK/StrmQS = K and QS contributed by streamers only.")
    print()
```

Update `main()` to run the 2D grid:

```python
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

    team_season_games: dict[str, int] = {}
    for teams in schedule.values():
        for team in teams:
            team_season_games[team] = team_season_games.get(team, 0) + 1

    # 4. Build configs
    if args.no_sweep:
        configs = [SweepConfig(label="baseline", roster=roster)]
        stream_levels = [0]
    else:
        configs = build_sweep_configs(roster)
        stream_levels = STREAMING_LEVELS

    # 5. Run 2D grid: composition x streaming
    all_results: dict[str, dict[int, SimulationResult]] = {}
    total_runs = len(configs) * len(stream_levels)
    run_num = 0

    for config in configs:
        all_results[config.label] = {}
        for stream_level in stream_levels:
            run_num += 1
            print(f"\n[{run_num}/{total_runs}] '{config.label}' @ {stream_level} streams/week ({args.sims} sims)...")
            result = simulate_season(
                config.roster, schedule, team_season_games,
                args.sims, args.seed, streams_per_week=stream_level,
            )
            all_results[config.label][stream_level] = result

            # Print per-player report for baseline config only
            if config.label == "baseline" and stream_level == 0:
                print_contribution_report(config.label, config.roster, result)

    # 6. Print streaming sweep summary
    if len(configs) > 1 or len(stream_levels) > 1:
        print_streaming_sweep_summary(configs, all_results)
```

- [ ] **Step 3: Verify the script runs with --help**

Run: `.venv/bin/python sweep_bench_contributions.py --help`
Expected: Shows all arguments

- [ ] **Step 4: Commit**

```bash
git add sweep_bench_contributions.py
git commit -m "feat(streaming): update CLI sweep for composition x streaming grid"
```

---

### Task 5: Run Full Test Suite and Integration Test

**Files:**
- No new files

- [ ] **Step 1: Run full test suite**

Run: `.venv/bin/python -m pytest tests/backend/analysis/test_bench_contributions.py -v`
Expected: All tests pass (22 existing + 6 streaming = 28)

- [ ] **Step 2: Run all analysis tests for regressions**

Run: `.venv/bin/python -m pytest tests/backend/analysis/ -v`
Expected: All tests pass

- [ ] **Step 3: Run live integration test**

Run: `.venv/bin/python sweep_bench_contributions.py --league-id <LEAGUE_ID> --team-id <TEAM_ID> --swid '<SWID>' --espn-s2 '<ESPN_S2>' --sims 50 --seed 42`

Expected: Prints the 2D grid showing how each composition performs at each streaming level. Verify:
- At 0 streams, results match previous run
- At 10 streams, K and QS increase significantly for pitcher-heavy compositions
- The grid makes it clear which composition + streaming combo is best

- [ ] **Step 4: Commit any fixes from integration testing**

```bash
git add -u
git commit -m "fix(streaming): address integration test findings"
```
