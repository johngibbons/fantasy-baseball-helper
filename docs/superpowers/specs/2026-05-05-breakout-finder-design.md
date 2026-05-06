# Breakout Finder — Design Spec

## Context

The current `/waivers` page ranks free agents by RoS-projection-driven expected-wins improvement. It's strong for "who will help me from here on out" decisions, but weak at surfacing players who are *currently breaking out*: hot in recent days/weeks, with underlying metrics (xwOBA, barrel%, K%, etc.) that suggest the surge is real and likely to persist.

Two breakout patterns are interesting:

1. **Hot now + sustainable** — last 14 days are well above projection AND underlying metrics support the run continuing.
2. **Stealth breakouts** — underlying metrics have meaningfully shifted from prior years/projections, but counting stats haven't caught up yet. Highest-leverage waiver pickups.

This spec adds both views as new tabs on the existing `/waivers` page.

## Goal

Add two new tabs alongside the existing projections-based recommendations:

- **Hot + Sustainable** — players whose recent (7/14/30 day) production, extrapolated to RoS via the existing MCW pipeline, would add expected wins; filtered/badged for sustainability via Statcast metrics.
- **Stealth Breakouts** — players ranked by composite skill-change z-score relative to a per-player baseline (prior season Statcast, with fallback chain).

Both views support all-roster scope (free agents, rostered, all) with FA as the default landing filter.

## Architecture

### Data Flow

```
Daily cron (3am ET, before 4am ET ESPN waivers run):
  1. sync_rolling_stats(season, windows=[7, 14, 30])
       — game logs → rolling_batting_stats / rolling_pitching_stats
  2. sync_statcast_data(season)
       — already exists; refreshes current-season Statcast tables
  3. compute_skill_baselines(season)
       — joins current-season vs prior-season Statcast (with fallback chain),
         writes deltas + composite scores to statcast_baselines

User opens /waivers → Hot or Stealth tab:
  POST /api/breakouts/recommendations
    { league, season, view: "hot"|"stealth", window: 7|14|30,
      scope: "FA"|"rostered"|"all", position?: string }
  →
    1. Next.js route: fetch ESPN free agents + rosters (same as projections tab)
    2. Backend joins rolling_stats + statcast + statcast_baselines + projections
    3. Hot view: pro-rate window stats to RoS, run MCW, apply sustainability filter
    4. Stealth view: rank by skill-change z-score, attach metric deltas + badges
    5. Return ranked list + supporting metrics
```

The Hot and Stealth paths share data plumbing but produce independent rankings — no fusion. Hot = MCW wins-pace + roster swap integration. Stealth = z-score-of-skill-deltas + simple ranking (watch list, not action list).

### Component Breakdown

#### 1. Rolling Stats Ingestion

**File:** `backend/data/rolling_stats.py` (new)

`sync_rolling_stats(season, windows=[7, 14, 30])`:
- For each window, compute `start_date = today - window_days`, `end_date = today`.
- Fetch game logs from Baseball Savant via `pybaseball.statcast` (date range) or MLB Stats API per player.
- Aggregate per-player totals (G, PA, AB, R, H, HR, RBI, SB, BB, K, HBP, SF, TB) and rates (AVG, OBP, SLG, OPS).
- For pitchers: G, GS, IP, K, BB, H, ER, HR, SV, HLD, QS, ERA, WHIP, K/9, BB/9.
- Upsert into `rolling_batting_stats` / `rolling_pitching_stats` with `as_of_date = today`.
- Idempotent — re-running same day overwrites for that `(mlb_id, season, window_days)` row.
- Batched by player_type. Logs match counts.

#### 2. Skill Baselines

**File:** `backend/analysis/skill_baselines.py` (new)

`compute_skill_baselines(season)`:
- For each player with current-season Statcast data, compute per-metric deltas vs baseline.
- Baseline fallback chain (per metric):
  1. Prior-season Statcast — if player had ≥ 100 PA / 30 IP last year
  2. Preseason ATC DC component rates (mapped to Statcast-equivalents where possible)
  3. League average
- Record which `baseline_source` was used so the UI can footnote rookie comparisons.

`_skill_change_zscore()`:
- Per metric, compute population-normalized z-score of the delta (so `+5pp barrel%` is interpreted relative to how much barrel% varies across hitters).
- Aggregate weighted average:
  - Hitters: `Δ xwOBA (×3) + Δ barrel% (×2) + Δ hard-hit% (×1.5) + Δ sprint_speed (×1)`
  - Pitchers: `Δ xERA inverted (×3) + Δ whiff% (×2) + Δ K%-BB% (×2) + Δ chase_rate (×1)`
- Players need ≥ 50 PA (hitters) or ≥ 20 IP (pitchers) this season to qualify; below threshold → `skill_change_zscore = NULL`.

`_sustainability_score()` (0–100):
- Composite indicator that surface stats are likely to hold up. Used by Hot view filter and as a sortable tiebreaker.
- Hitters: based on `xwOBA - wOBA` gap (positive or small-negative is good), barrel% rank, hard-hit% rank, K%-BB% rank.
- Pitchers: based on `xERA - ERA` gap (negative is good), whiff% rank, CSW% rank, BB% rank.

Output written to `statcast_baselines` table (see Schema below).

#### 3. Breakout Engine

**File:** `backend/analysis/breakouts.py` (new)

`compute_breakout_recommendations(my_roster, all_rosters, free_agents, projections, season, view, window, scope, position_filter, remaining_faab)`:

Branches on `view`:

**`_compute_hot_view()`:**
1. Pull `rolling_batting_stats` / `rolling_pitching_stats` for the requested window.
2. For each player, pro-rate the window's pace to RoS:
   - Counting stats: `proj_remaining = window_total * (games_remaining / games_in_window)`
   - Rate stats: use the window's rate directly (already a rate)
3. Feed pro-rated totals into the existing MCW pipeline (`compute_rank` + `win_prob_from_rank` from `backend/simulation/scoring_model.py`), with the same swap loop as the projections tab in `backend/analysis/waivers.py`:
   - For each candidate, find the best drop player, compute `wins_added_if_rate_continues`.
4. Apply the **sustainability hard filter** — player passes if **≥ 2 of 3** core checks (see Tunables below). Underlying metrics come from current-season `statcast_batting` / `statcast_pitching` tables.
5. Attach **per-metric badges** (green / yellow / red, plus gray for n/a). Use `statcast_baselines.sustainability_score` as the tiebreaker when two candidates have equal `wins_added_if_rate_continues`.
6. Compute FAAB bid via the existing `compute_faab_bids()` helper from `backend/analysis/waivers.py`, refactored to take the delta-wins metric as a parameter so both tabs share one implementation.
7. Return ranked list with `wins_added_if_rate_continues`, drop pair, badges, window stats.

**`_compute_stealth_view()`:**
1. Pull `statcast_baselines` for the season; filter to players meeting the PA/IP threshold.
2. Filter by `scope` (FA / rostered / all) and `position`.
3. Rank by `skill_change_zscore` descending.
4. For each player, attach:
   - **Headline delta** — the largest single-metric jump (e.g., `+5.2pp barrel%`).
   - **All metric deltas** with badges.
   - **Current surface stats vs preseason projection** — small contextual text ("OPS .720 vs projected .780") so users see "metrics suggest more is coming."
   - Roster status (FA / on team {X} / on user's team).
5. No drop pair, no FAAB — this is a watch list. The user clicks through to the Hot or Projections tab to act.

#### 4. Shared Helpers

Both views reuse:
- `compute_rank()` and `win_prob_from_rank()` from `backend/simulation/scoring_model.py`
- ESPN free agent + roster fetching (already in `src/lib/espn-api.ts`)
- Player ID resolution (already in `backend/data/projections.py` style)
- Position eligibility logic from the existing waivers engine
- League-avg constants colocated in `backend/analysis/skill_baselines.py`

#### 5. FastAPI Endpoint

**File:** `backend/api/routes.py` (extend)

```
POST /api/breakouts/recommendations
```

Request:
```json
{
  "my_roster": [...],
  "all_rosters": {...},
  "free_agents": [...],
  "remaining_faab": 85,
  "season": 2026,
  "view": "hot",
  "window": 14,
  "scope": "FA",
  "position": "OF"
}
```

Response (Hot view):
```json
{
  "as_of_date": "2026-05-05",
  "view": "hot",
  "window": 14,
  "baseline_expected_wins": 5.2,
  "recommendations": [
    {
      "rank": 1,
      "add_player": {"id": 67890, "name": "Player A", "position": "OF", "team": "BOS",
                     "roster_status": "FA"},
      "drop_player": {"id": 11111, "name": "Player B", "position": "OF"},
      "wins_added_if_rate_continues": 0.32,
      "suggested_faab_bid": 18,
      "window_stats": {"pa": 58, "r": 12, "tb": 28, "rbi": 14, "sb": 3, "obp": 0.395},
      "sustainability_badges": {
        "xwoba_gap": "green", "barrel_pct": "green", "hard_hit_pct": "yellow",
        "k_pct": "green", "bb_pct": "yellow"
      },
      "sustainability_score": 78
    }
  ]
}
```

Response (Stealth view):
```json
{
  "as_of_date": "2026-05-05",
  "view": "stealth",
  "recommendations": [
    {
      "rank": 1,
      "player": {"id": 99999, "name": "Player C", "position": "SP", "team": "LAD",
                 "roster_status": "FA"},
      "skill_change_zscore": 2.4,
      "headline_delta": {"metric": "whiff_pct", "label": "+5.2pp whiff%"},
      "metric_deltas": {
        "xera": {"value": -0.85, "badge": "green"},
        "whiff_pct": {"value": 5.2, "badge": "green"},
        "k_pct": {"value": 4.1, "badge": "green"},
        "bb_pct": {"value": -0.5, "badge": "green"},
        "chase_rate": {"value": 1.8, "badge": "yellow"}
      },
      "current_vs_projection": {
        "era": {"current": 4.20, "projected": 3.85},
        "whip": {"current": 1.32, "projected": 1.21}
      },
      "baseline_source": "prior_season"
    }
  ]
}
```

#### 6. Frontend

**Tab structure on `/waivers`:**
A tab strip at the top under the header:
- Projections-Based (current page, default)
- Hot + Sustainable (new)
- Stealth Breakouts (new)

Tab state in URL (`?tab=hot`) — bookmarkable, survives refresh. Roster panel + league/credentials state shared across all three.

**File layout:**
- `src/app/waivers/page.tsx` — adds tab strip, conditionally renders the active tab
- `src/app/waivers/_components/ProjectionsTab.tsx` — extracted from current page (refactor)
- `src/app/waivers/_components/HotTab.tsx` (new)
- `src/app/waivers/_components/StealthTab.tsx` (new)
- `src/app/api/breakouts/recommendations/route.ts` (new) — orchestrator: fetch ESPN data + forward to Python backend

**Hot + Sustainable tab UI:**
- **Top controls:** window dropdown (7/14/30, default 14), scope filter (FA [default] / Rostered / All), position filter.
- **Table columns:** Rank, Add (player+team+pos), Drop, Wins-pace delta, Window stats (compact), Sustainability badges (colored chips per metric), Suggested FAAB bid.

**Stealth Breakouts tab UI:**
- **Top controls:** scope filter, position filter, player type (hitter/pitcher).
- **Table columns:** Rank, Player (name+team+pos+roster status), Headline delta, Metric deltas with badges, Current surface stats vs projection (small text), no drop / no FAAB.
- "Data as of {as_of_date}" note at table footer.

## Schema (New Tables)

**`rolling_batting_stats`**
```sql
CREATE TABLE rolling_batting_stats (
  mlb_id INTEGER NOT NULL,
  season INTEGER NOT NULL,
  window_days INTEGER NOT NULL,  -- 7 | 14 | 30
  as_of_date DATE NOT NULL,
  games INTEGER DEFAULT 0,
  pa INTEGER DEFAULT 0,
  ab INTEGER DEFAULT 0,
  r INTEGER DEFAULT 0,
  h INTEGER DEFAULT 0,
  hr INTEGER DEFAULT 0,
  rbi INTEGER DEFAULT 0,
  sb INTEGER DEFAULT 0,
  bb INTEGER DEFAULT 0,
  k INTEGER DEFAULT 0,
  hbp INTEGER DEFAULT 0,
  sf INTEGER DEFAULT 0,
  total_bases INTEGER DEFAULT 0,
  batting_avg REAL DEFAULT 0,
  obp REAL DEFAULT 0,
  slg REAL DEFAULT 0,
  ops REAL DEFAULT 0,
  updated_at TIMESTAMP DEFAULT NOW(),
  PRIMARY KEY (mlb_id, season, window_days),
  FOREIGN KEY (mlb_id) REFERENCES players(mlb_id)
);
```

**`rolling_pitching_stats`**
```sql
CREATE TABLE rolling_pitching_stats (
  mlb_id INTEGER NOT NULL,
  season INTEGER NOT NULL,
  window_days INTEGER NOT NULL,
  as_of_date DATE NOT NULL,
  games INTEGER DEFAULT 0,
  games_started INTEGER DEFAULT 0,
  ip REAL DEFAULT 0,
  k INTEGER DEFAULT 0,
  bb INTEGER DEFAULT 0,
  h_allowed INTEGER DEFAULT 0,
  er INTEGER DEFAULT 0,
  hr_allowed INTEGER DEFAULT 0,
  saves INTEGER DEFAULT 0,
  holds INTEGER DEFAULT 0,
  quality_starts INTEGER DEFAULT 0,
  era REAL DEFAULT 0,
  whip REAL DEFAULT 0,
  k_per_9 REAL DEFAULT 0,
  bb_per_9 REAL DEFAULT 0,
  updated_at TIMESTAMP DEFAULT NOW(),
  PRIMARY KEY (mlb_id, season, window_days),
  FOREIGN KEY (mlb_id) REFERENCES players(mlb_id)
);
```

**`statcast_baselines`**
```sql
CREATE TABLE statcast_baselines (
  mlb_id INTEGER NOT NULL,
  season INTEGER NOT NULL,
  player_type TEXT CHECK(player_type IN ('hitter', 'pitcher')),
  -- Hitter deltas (NULL for pitchers / missing data)
  delta_xwoba REAL,
  delta_barrel_pct REAL,
  delta_hard_hit_pct REAL,
  delta_sprint_speed REAL,
  -- Pitcher deltas (NULL for hitters / missing data)
  delta_xera REAL,
  delta_whiff_pct REAL,
  delta_k_pct REAL,
  delta_bb_pct REAL,
  delta_chase_rate REAL,
  -- Composite scores
  skill_change_zscore REAL,
  sustainability_score REAL,    -- 0-100
  baseline_source TEXT,         -- "prior_season" | "preseason_projection" | "league_avg"
  qualifies_pa_ip INTEGER DEFAULT 0,  -- 1 if ≥ 50 PA / 20 IP this season
  updated_at TIMESTAMP DEFAULT NOW(),
  PRIMARY KEY (mlb_id, season),
  FOREIGN KEY (mlb_id) REFERENCES players(mlb_id)
);

CREATE INDEX idx_baselines_zscore ON statcast_baselines(season, skill_change_zscore DESC);
```

## Tunables

All constants live at the top of `backend/analysis/skill_baselines.py` for easy tuning.

### Sustainability Hard Filter (Hot view)

A player passes if **≥ 2 of 3** core checks pass.

**Hitters:**
- `xwOBA >= wOBA - 0.020` — small wOBA over-performance OK; large gap is BABIP luck.
- `barrel_pct >= league_avg * 0.85` OR `hard_hit_pct >= league_avg * 0.95`
- For SB-driven breakouts: `sprint_speed >= 27.0 ft/s`

**Pitchers:**
- `xERA <= ERA + 0.50`
- `whiff_pct >= league_avg * 0.95` OR `csw_pct >= league_avg * 0.95`
- `bb_pct <= league_avg * 1.20` — control breakdowns don't sustain.

### Sustainability Badges

Per metric (all visible regardless of filter pass):
- 🟢 green: ≥ 60th percentile vs current population
- 🟡 yellow: 40th–60th
- 🔴 red: < 40th
- ⚪ gray: data unavailable

### Skill-Change Z-Score Weights (Stealth view)

- **Hitters:** Δ xwOBA (×3), Δ barrel% (×2), Δ hard-hit% (×1.5), Δ sprint_speed (×1)
- **Pitchers:** Δ xERA inverted (×3), Δ whiff% (×2), Δ K%-BB% (×2), Δ chase_rate (×1)

### Qualification Thresholds

- Hitters: ≥ 50 PA this season
- Pitchers: ≥ 20 IP this season

### League Averages (used in filters)

Approximate MLB averages, refreshed annually:
- Barrel %: 7.0
- Hard-hit %: 35.0
- Whiff %: 25.0
- CSW %: 28.0
- BB %: 8.5

## Daily Sync Schedule

A new cron entry runs at **3am ET daily**, before the 4am ET ESPN waiver run:

```
03:00 ET  python -m backend.data.rolling_stats        # 7/14/30d windows
03:15 ET  python -m backend.data.statcast             # current-season Statcast
03:30 ET  python -m backend.analysis.skill_baselines  # deltas + composites
```

Each step is idempotent and logs its own match counts. Failures are logged but don't block subsequent steps — partial data is better than no data, and `as_of_date` makes staleness visible.

## Error Handling

- **Missing rolling data** for a player → exclude from Hot view; log debug. Don't fall back to projections — the point is recent performance.
- **Missing Statcast** → exclude from Stealth view; in Hot view, badges show as gray "n/a" but player can still pass on other criteria.
- **Missing prior-season baseline** → walk the fallback chain; record `baseline_source` so UI can footnote rookies as "vs ATC DC" or "vs league avg."
- **Sync failures** — daily cron logs and continues. Page shows "data as of {as_of_date}" so stale data is visible.
- **No qualifying players** for a view (e.g., very early season) → show empty-state message explaining the window/qualification thresholds.
- **Two-way players** — handled the same way the existing waivers engine handles them (component stats adjusted for both batting and pitching when applicable).

## Verification

1. **Unit tests** in `backend/tests/`:
   - `test_rolling_stats.py` — mocked game logs aggregate correctly into 7/14/30d totals; idempotent re-runs produce same row.
   - `test_skill_baselines.py` — known-input deltas produce expected z-scores; baseline fallback chain works (prior-season → projection → league avg); qualification threshold excludes low-PA/IP players.
   - `test_breakouts.py` — Hot view produces same MCW math as projections engine when fed identical input; Stealth view ranks correctly by skill-change z-score; sustainability filter excludes/includes per spec.
2. **Manual end-to-end**: open `/waivers`, switch to Hot tab during active season, verify ≥ 1 recommendation with sane metric badges; switch to Stealth tab, verify top recommendation has a clearly visible skill jump in at least one metric.
3. **Sanity checks**:
   - Hot view top recommendation should have both elite recent surface stats AND ≥ 2/3 sustainability checks passing.
   - Stealth view should not surface players whose surface stats are already eye-popping (those belong to Hot tab, not stealth).
   - Backtest on a known historical breakout (e.g., 2025 data once available) — the player should appear high in at least one tab.

## Key Assumptions

- Game logs available via Baseball Savant / `pybaseball.statcast` date-range queries, or MLB Stats API per player. Either approach works; the `rolling_stats.py` implementation will pick whichever is more reliable in practice.
- Current-season Statcast is refreshed daily via the existing `sync_statcast_data` job (the existing job is re-run rather than a parallel one being created).
- League-average constants are slow-moving and can be hardcoded with annual review; they don't need real-time computation.
- ESPN free agent + roster fetching reuses the existing `getFreeAgents()` and `getRosters()` infrastructure already used by the projections tab.
- The existing MCW pipeline (`compute_rank`, `win_prob_from_rank`) handles the Hot view's wins-pace math without modification — we just feed it pro-rated rolling stats instead of preseason projections.

## What This Does NOT Include (Future Work)

- "Cold" or "regression candidate" view (the inverse — players whose underlying metrics suggest a slump is coming).
- Trade target deep-dive view that combines Hot + Stealth signals on rostered players.
- Historical breakout tracking ("which of last year's stealth picks panned out") — useful for tuning weights but not v1.
- Per-pitch arsenal change detection (e.g., new slider with elite whiff%) — beyond the per-pitcher whiff% / chase_rate aggregates we already track.
- Notification / alert flow ("Player X just crossed into the top 10 of stealth breakouts").
- User-tunable filter thresholds via UI — config lives in code for now.
