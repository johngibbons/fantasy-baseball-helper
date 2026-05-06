# Operations

## Daily Breakout Sync

Schedule: **03:00 ET daily** (before the 04:00 ET ESPN waiver run).

The script runs three idempotent steps:
1. `sync_rolling_stats` — fetches 7/14/30-day game-log windows via pybaseball, upserts into `rolling_batting_stats` / `rolling_pitching_stats`.
2. `sync_statcast_data` — refreshes current-season Statcast (xwOBA, xERA, barrel%, whiff%, etc.).
3. `compute_skill_baselines` — joins current vs prior-season Statcast, computes per-player deltas, z-scores, and sustainability scores; writes to `statcast_baselines`.

Failures in one step don't block the others. Re-running on the same day overwrites existing rows.

Skip individual steps with `--skip-rolling`, `--skip-statcast`, `--skip-baselines` (useful for ad-hoc reruns).

### Railway production setup

Run as a dedicated cron service in the `brave-vibrancy` project. The Railway CLI can't fully configure a cron schedule today (the dashboard is required for the schedule field), so the setup is a one-time dashboard task.

1. **Create the service.** Dashboard → `brave-vibrancy` → "+ New" → "Empty Service" → name: `breakout-sync`.
2. **Connect the source.** Settings → Source → GitHub repo `johngibbons/fantasy-baseball-helper`, branch `main`. Use the same Dockerfile / Nixpacks build as the main service.
3. **Set the start command.** Settings → Deploy → Custom Start Command:
   ```
   python -m backend.scripts.daily_breakout_sync --season 2026
   ```
4. **Set the cron schedule.** Settings → Cron Schedule:
   ```
   0 7 * * *
   ```
   (07:00 UTC = 03:00 ET, before the 04:00 ET ESPN waiver run.)
5. **Wire up the database.** Variables → Add reference variable → `DATABASE_URL` from the Postgres plugin.

Once configured, Railway runs the service on schedule. Logs land in the service's deploy log.

### Local / ad-hoc run

```bash
DATABASE_URL="$RAILWAY_PUBLIC_DB_URL" \
  .venv/bin/python -m backend.scripts.daily_breakout_sync --season 2026
```

Use the public proxy URL (`crossover.proxy.rlwy.net:...`), not the internal hostname, when running outside Railway's network.
