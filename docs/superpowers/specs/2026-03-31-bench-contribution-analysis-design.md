# Bench Contribution Rate Analysis — Design Spec

**Date**: 2026-03-31
**Goal**: Empirically calculate bench player contribution rates via full-season daily lineup simulation, replacing the hard-coded estimates (20% hitter, 45% SP, 15% RP) with data-driven values. Also determine optimal bench composition (hitters vs pitchers) for the user's specific roster.

## Problem

The draft simulation and waiver analysis use hard-coded bench contribution rates:
- Bench hitters: 20%
- Bench SP: 45%
- Bench RP: 15%

These are theoretical estimates, not calibrated from data. If wrong, all composition analysis built on them is unreliable. The matchup engine (`matchup.py`) takes a more realistic approach by simulating daily lineups, but only for a single matchup week — not a full season.

## Approach

Full-season Monte Carlo daily lineup simulation. For a given roster, simulate every day of the MLB season:
1. Determine which teams play (from MLB schedule API)
2. Determine which players are available (stochastic, based on projected playing time)
3. Run the lineup optimizer to assign starters and bench
4. Track starts vs bench across all days and iterations
5. Calculate empirical contribution rates per player and per role

## Inputs & Data Sources

- **Roster**: Fetched via ESPN API using league/team IDs (reusing existing ESPN roster-fetching flow)
- **Projections**: From the `rankings` table — `proj_pa` for hitters, `proj_ip`/`proj_qs` for pitchers
- **MLB Schedule**: Full 2026 season from MLB Stats API (`/schedule?sportId=1&startDate=2026-03-26&endDate=2026-09-27`). Parsed into `dict[str, set[str]]` — date to set of team abbreviations playing that day.

### Derived per-player availability

- **Hitters**: `availability_rate = min(1.0, (proj_pa / 4.0) / team_season_games)`. Full-timer (~600 PA) gets ~0.93; platoon (~350 PA) gets ~0.54.
- **SPs**: Available only on start days. Projected starts = `proj_ip / 5.5` (5.5 IP/start reflects modern MLB averages, replacing the less accurate 6.0 used elsewhere in the codebase). Starts distributed evenly across team schedule with +/-1 day jitter.
- **RPs**: Available whenever their team plays (RP appearances aren't predictable day-to-day).

## Simulation Engine

### Monte Carlo loop (default 200 iterations)

```
For each iteration:
    Distribute each SP's projected starts across their team's schedule (with jitter)
    For each day in MLB season:
        For each rostered player whose team plays today:
            Hitters: roll against availability_rate
            SPs: available if this is a scheduled start day
            RPs: always available
        Run greedy lineup optimizer on available players
        Record: each player started or sat
```

### Lineup optimizer

Reuse the greedy most-constrained-first algorithm from `matchup.py:optimize_daily_lineup`, which handles both hitters and pitchers:

- **Hitter slots**: C(1), 1B(1), 2B(1), 3B(1), SS(1), OF(3), UTIL(2) = 10 slots
- **Pitcher slots**: SP(3), RP(2), P(2) = 7 slots
- Players sorted by fewest eligible slots first. Each assigned to first available slot. Overflow goes to bench (0 contribution that day).

Only SPs who are pitching that day are passed to the optimizer (non-starting SPs are excluded from the daily input entirely — they can't contribute on non-start days). On days with multiple SPs starting, if all 7 pitcher slots are occupied, lower-ranked SPs bench and score 0.

### Output per player

- `days_started / days_team_played` = contribution rate
- Averaged across all Monte Carlo iterations

### Aggregated output

- Average contribution rate by role: bench hitter, bench SP, bench RP
- Breakdown by bench depth position (1st bench hitter vs 2nd vs 3rd, by overall rank)

## Sweep Mode

Tests different bench compositions to answer: "should I add/drop bench hitters?"

### Configurations tested

- **Current roster** (baseline)
- **+1 bench hitter** (drop lowest-ranked pitcher, replace with replacement-level hitter)
- **+2 bench hitters** (drop 2 lowest-ranked pitchers, replace with replacement-level hitters)
- **-1 bench hitter** (drop lowest-ranked hitter, replace with replacement-level pitcher)

Replacement-level players use median projections from the bottom quartile of ranked players at the relevant position type (hitter/pitcher). This avoids needing ESPN free agent data while providing a realistic baseline.

"Lowest-ranked" is determined by overall rank from projections, not by current ESPN lineup slot (since lineups change daily).

### Per-configuration output

1. Per-player contribution rates
2. Aggregated role averages (bench hitter avg, bench SP avg, bench RP avg)
3. **Estimated season stat impact**: each bench player's projected stats multiplied by their contribution rate, summed across roster. Show delta between configurations (e.g., "+15 R, +20 TB, -8 K, -1.2 QS").

The stat impact is the punchline — it translates contribution rates into concrete gains/losses from changing bench composition.

## Architecture & File Layout

### New files

- **`backend/analysis/bench_contributions.py`** — Core simulation engine: schedule fetching, availability model, Monte Carlo daily lineup sim, contribution rate calculation.
- **`sweep_bench_contributions.py`** — CLI entry point at project root (matches existing `sweep_bench.py`, `sweep_composition.py` pattern). Parses args, loads roster + projections, calls the engine, prints results.

### Reused (no changes)

- `backend/analysis/matchup.py` — `optimize_daily_lineup()` function handles both hitters and pitchers via greedy most-constrained-first assignment
- Rankings/projections from `rankings` table via existing DB helpers
- MLB Stats API schedule endpoint (same base URL as `mlb-schedule.ts` and `mlb_api.py`)

### Roster fetching

The script accepts ESPN league/team IDs and fetches the roster via the existing API flow. The waiver route (`backend/analysis/waivers.py`) already does ESPN roster fetch + player ID resolution — we extract the roster-fetching into a reusable function.

### CLI interface

```
python3 sweep_bench_contributions.py --league-id 123 --team-id 4 --sims 200 --seed 42
```

Output format: CLI table matching existing sweep scripts, with a summary comparison table.
