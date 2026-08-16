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

## Draft Day Checklist

The 2026 retrospective could not use the board the draft actually ran on. The
`rankings` and `projections` tables are unique per player-season, so every
refresh overwrites them in place; by mid-season they held rest-of-season
projections, and the preseason board was gone. The baseline had to be
reconstructed from committed CSVs instead.

Three steps stop that happening again. Do them on draft day.

**1. Snapshot the board before the draft starts.**

```bash
DATABASE_URL="$RAILWAY_PUBLIC_DB_URL" \
  .venv/bin/python -m backend.scripts.retro_snapshot \
    --season 2027 --create-label preseason-2027
```

Or hit the API: `POST /api/v2/snapshots?label=preseason-2027&season=2027`.

Named snapshots are never pruned. Automatic ones (`auto-YYYY-MM-DD`) are taken
before every projection refresh as a safety net, but they expire after ~400
days and should not be relied on for a preseason baseline.

**2. Save the ADP export with a dated filename.**

`rankings.espn_adp` is refreshed from ESPN's live API all season, so it stops
being draft-day ADP within days. The CSV export at the repo root is the only
record of what the board showed on the day. Keep it as
`espn_adp_500_2027-03-DD.csv` rather than overwriting the previous one.

**3. Snapshot the completed draft immediately afterwards.**

```bash
.venv/bin/python -m backend.scripts.retro_snapshot --season 2027
```

This writes `backend/data/fixtures/retro_2027/draft_state_2027.json` from
production. The draft lives in a single overwritable `draft_state` row; if the
board is ever re-seeded it is unrecoverable. Commit the fixture.

Note when reading that file: `state["picks"]` is a Map dumped to an array
(mlb_id → teamId), so its array positions are insertion order, **not** pick
numbers. Only `pickLog[].pickIndex` and keeper round costs are authoritative
for ordering — see `build_draft_board` in `backend/analysis/retro/draft_replay.py`.
