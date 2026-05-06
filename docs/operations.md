# Operations

## Daily Breakout Sync

Schedule: **03:00 ET daily** (before the 04:00 ET ESPN waiver run).

```cron
0 3 * * * cd /path/to/fantasy-baseball-helper && .venv/bin/python -m backend.scripts.daily_breakout_sync --season 2026 >> logs/breakout-sync.log 2>&1
```

The script runs three idempotent steps:
1. `sync_rolling_stats` — fetches 7/14/30-day game-log windows via pybaseball, upserts into `rolling_batting_stats` / `rolling_pitching_stats`.
2. `sync_statcast_data` — refreshes current-season Statcast (xwOBA, xERA, barrel%, whiff%, etc.).
3. `compute_skill_baselines` — joins current vs prior-season Statcast, computes per-player deltas, z-scores, and sustainability scores; writes to `statcast_baselines`.

Failures in one step don't block the others; check `logs/breakout-sync.log` for any error trace. Re-running the script in the same day overwrites existing rows.

Skip individual steps with `--skip-rolling`, `--skip-statcast`, `--skip-baselines` (useful for ad-hoc reruns).
