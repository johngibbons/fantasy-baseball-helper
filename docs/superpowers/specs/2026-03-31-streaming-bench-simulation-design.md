# Streaming-Aware Bench Contribution Simulation — Design Spec

**Date**: 2026-03-31
**Goal**: Extend the bench contribution simulation to model SP streaming (add/drop cycling), then determine the optimal bench composition given a 10 transaction/week budget.

## Problem

The current bench contribution simulation treats roster slots as fixed — each player stays on the roster all season. In reality, managers can add/drop up to 10 players per week (each add/drop pair = 1 transaction), cycling replacement-level SPs through bench slots on their start days to accumulate extra K, QS, and IP. This "streaming" dramatically increases the effective value of a pitcher bench slot.

Without modeling streaming, the simulation can't answer: "How many bench slots should I dedicate to streaming pitchers vs keeping fixed bench hitters?"

## Streaming Model

Each simulated week (Mon-Sun), the simulation has a configurable **streaming budget** (0-10 transactions/week).

### Streaming-eligible slots

The N lowest-ranked bench pitchers are designated as "streaming slots." On days their anchored pitcher isn't starting, the slot can be used for a streamed SP instead. The number of streaming slots is implicitly determined by roster composition and streaming budget — you won't stream more slots than you have bench pitchers or transactions.

### Streamable SP pool

For each day, one replacement-level SP is available per MLB team that's playing. Each uses replacement-level projections: 100 IP, 80 K, 6 QS, 4.50 ERA, 1.35 WHIP, 0 SVHD over a full season. Per-start stats are derived from these (dividing by projected starts = `100 / 5.5 ≈ 18` starts).

This is a simplification — in a 10-team league, there are typically many streamable SPs available on any day. Using one per team is conservative.

### Greedy weekly allocation

At the start of each simulated week:
1. Identify streaming slots (lowest-ranked bench pitchers)
2. Look at all 6-7 days in the week
3. For each streaming slot on each day: if no anchored SP is pitching in that slot, a streamer could fill it
4. Greedily assign streamers to maximize total starts, consuming 1 transaction per pickup
5. Stop when the weekly transaction budget is exhausted

### Stat accumulation

Streamed SPs enter the daily lineup optimizer like any rostered player. They contribute per-start stats for that day only. On the next day, the streaming slot reverts to empty (unless another streamer is picked up).

## Sweep Configurations

The sweep tests a grid of **roster composition x streaming intensity**:

### Roster compositions
- **Current roster** (baseline — 12 hitters, 12 pitchers)
- **+1 hitter / -1 pitcher** (13H/11P)
- **+2 hitters / -2 pitchers** (14H/10P)
- **-1 hitter / +1 pitcher** (11H/13P)

### Streaming intensity (transactions/week)
- **0** — no streaming (matches pre-streaming simulation)
- **3** — light streaming (saving transactions for waiver pickups)
- **6** — moderate streaming
- **10** — max streaming (all transactions used for SP cycling)

Each cell in the grid shows total season stat impact across all 10 categories. The summary identifies which composition + streaming level maximizes overall production.

## Architecture Changes

### Modified files

- **`backend/analysis/bench_contributions.py`** — Add streaming to `simulate_season`:
  - New function `generate_streaming_pool(schedule_date, schedule)` — returns list of replacement-level SP dicts available that day (one per team playing)
  - New function `allocate_weekly_streams(roster, schedule, sp_start_dates, week_dates, max_transactions)` — greedy scheduler that identifies streaming slots and assigns pickups to maximize starts within the transaction budget. Returns a `dict[str, list[dict]]` mapping date → list of streamer player dicts to add to available_today.
  - Updated `simulate_season` signature: add `streams_per_week: int = 0` parameter. When > 0, runs weekly stream allocation before the daily loop and injects streamers into available_today.
  - New function `replacement_level_per_start_stats()` — returns per-start stat dict for a replacement-level SP (derived from full-season replacement-level projections / projected starts).

- **`sweep_bench_contributions.py`** — Update to test composition x streaming grid:
  - `build_sweep_configs` returns configs for all 4 roster compositions
  - Main loop runs each config at each streaming level (0, 3, 6, 10)
  - `print_sweep_summary` outputs a 2D grid (rows = compositions, columns grouped by streaming level)

### No new files

When `streams_per_week=0`, behavior is identical to the current simulation.

### Key simulation loop change

```
For each simulated week (group dates into Mon-Sun chunks):
    weekly_streams = allocate_weekly_streams(
        roster, schedule, sp_start_dates, week_dates, streams_per_week
    )
    For each day in the week:
        # Existing: build available_today from roster
        # New: append any streamers assigned to this day
        for streamer in weekly_streams.get(date, []):
            available_today.append(streamer)
        # Run lineup optimizer as before
```
