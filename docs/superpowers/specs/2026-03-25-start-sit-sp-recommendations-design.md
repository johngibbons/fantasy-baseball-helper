# Start/Sit SP Recommendations — Design Spec

## Context

The fantasy baseball helper has waiver wire recommendations and trade analysis, but no tooling for daily lineup decisions. The user plays in an ESPN H2H categories league with daily lineups that lock at game time. Currently they leave all SPs in their lineup without considering matchups or weekly category context. The app runs on Railway and needs to be accessible from any device (phone, desktop) without per-device credential setup.

## Goal

Build a start/sit recommendation page for starting pitchers that combines:
1. Per-start matchup quality (via PitcherList weekly Sit/Start rankings)
2. Weekly matchup optimization (using current H2H category state to adjust recommendations)

The result: open `/start-sit` on your phone, see today's SP recommendations with context-aware rationale.

## League Settings (ESPN)

- H2H Categories, 10 categories (R, TB, RBI, OBP, SB, K, QS, ERA, WHIP, SVHD)
- Daily lineups, lock at game time
- Roster: C, 1B, 2B, 3B, SS, 3 OF, 2 UTIL, 3 SP, 2 RP, 2 P, 8 Bench (25 total)

## Architecture

### Data Sources

#### PitcherList Sit/Start Rankings

PitcherList publishes a weekly "Sit/Start" article covering all probable starter matchups for the week (e.g., "Sit/Start Week 0: Reviewing All Starting Pitcher Matchups From 3/25 - 3/29").

**Format:** HTML tables organized by game date. Each entry contains:
- Pitcher name
- Opposing team
- A tiered score: **Start (1-10)**, **Maybe (1-6)**, or **Sit (1-3)**
  - Start-10 = highest confidence start; Start-1 = weakest start
  - Maybe = league-dependent, risky
  - Sit-3 = strongest sit; Sit-1 = weakest sit

**Article discovery:** Rather than constructing a URL from a slug pattern (which varies), discover the latest Sit/Start article by:
1. Fetch PitcherList's Sit/Start category page (e.g., `/category/fantasy/daily/sit-start/` or search the homepage)
2. Find the most recent article link matching "Sit/Start Week" in the title
3. Fetch that article URL
4. Cache the resolved URL for the week

This is more robust than guessing the URL slug format, which includes date ranges with inconsistent formatting.

**Scraping approach:**
- Fetch the discovered Sit/Start article page
- Parse HTML tables: consistent column structure per game date
- Extract: pitcher name, opponent, tier (Start/Maybe/Sit), score (1-10)
- The tables are well-structured and highly parseable (confirmed via page inspection)

**Caching:** Cache the parsed data keyed by week. The article covers an entire matchup period and does not change after publication.

**Failure mode:** If scraping fails (page structure changes, site down):
- Return a clear error to the frontend: "PitcherList data unavailable"
- Show the matchup category context without per-start recommendations
- Log the failure for debugging

#### ESPN API — Matchup Scoreboard

**View:** `mMatchupScore` + `mScoreboard` (confirmed via espn-api library)

**Endpoint:**
```
GET /apis/v3/games/flb/seasons/{season}/segments/0/leagues/{leagueId}?view=mMatchupScore&view=mScoreboard&scoringPeriodId={scoringPeriodId}
```

**`scoringPeriodId` vs `matchupPeriodId`:** ESPN uses two distinct period concepts:
- `scoringPeriodId`: daily (day 1, day 2, ... of the season). Corresponds to each day's games.
- `matchupPeriodId`: weekly (week 1, week 2, ...). Groups scoring periods into H2H matchup weeks.

To get the current matchup scoreboard, we need the `matchupPeriodId` (weekly). The `mSettings` view returns `status.currentMatchupPeriod` which is what we want. We filter the `schedule` array by `matchupPeriodId` to find the current week's matchup.

**How to get `currentMatchupPeriod`:** Already available from `ESPNApi.getLeague()` which fetches `mSettings`. The response includes `status.currentMatchupPeriod`. The existing `ESPNLeague` interface already has `currentMatchupPeriod` field.

**Response structure:** The `schedule` array contains matchup objects with `home` and `away` teams. Filter by `matchupPeriodId == currentMatchupPeriod`. Each team has `cumulativeScore.scoreByStat` — a dict keyed by ESPN stat ID mapping to `{score, result}`. This gives per-category totals for the current matchup period.

ESPN stat IDs for our categories (from espn-api library STATS_MAP — verify at implementation with a test API call):
- R=20, TB=not directly mapped (compute from H=2+2B+2*3B+3*HR or use ESPN's stat ID), RBI=5, SB=11
- K=48, QS=63, SVHD=saves(57)+holds(needs verification)
- OBP=17, ERA=47, WHIP=41
- Note: exact IDs may vary; the implementation should make a test call and log the `scoreByStat` keys to confirm the mapping

**What this provides:** All 10 category totals for both teams in the current matchup — exactly what we need for the optimization engine.

#### Probable Pitchers

**Source: PitcherList data itself.** If a user's SP appears in PitcherList's daily table, they are a probable starter that day. This avoids needing a separate probable pitcher API call.

**Fallback:** If PitcherList data is unavailable, we cannot determine probable starters. The page shows the matchup context and a message that per-start recommendations require PitcherList data.

### Component Breakdown

#### 1. PitcherList Scraper

**File:** `backend/data/pitcherlist.py` (new)

- Fetch PitcherList's weekly Sit/Start article
- Parse HTML tables by game date
- Extract per pitcher: name, opponent, tier (Start/Maybe/Sit), score (1-10)
- Name-match pitchers to our player database using existing accent-stripping/matching patterns from `backend/data/projections.py`
- Cache parsed results keyed by week number (one fetch per matchup period)
- Return structured data: list of `{pitcher_name, mlb_id, opponent, date, tier, score}`

**Tier mapping for downstream use:**
- Start 7-10 → "strong_start"
- Start 1-6 → "start"
- Maybe 1-6 → "maybe"
- Sit 1-3 → "sit"

#### 2. Start/Sit Optimization Engine

**File:** `backend/analysis/start_sit.py` (new)

**Input:**
- User's SP roster (from ESPN API)
- Today's probable starters (from PitcherList — which of user's SPs appear in today's table)
- Current matchup category totals for all 10 categories (user vs opponent)
- PitcherList rankings for today's starters
- Days remaining in matchup period
- Current IP totals for both teams (from ESPN matchup data, needed for rate stat leverage)

**Process:**

**Step 1 — Classify all 10 categories by matchup state:**

Status labels (used consistently throughout):
- `winning_big`: large gap relative to days remaining, very unlikely to flip
- `winning_close`: small gap that could flip with a bad day
- `losing_close`: small gap that could close with a good day
- `losing_big`: large gap unlikely to close

**Thresholds for counting stats** (K, QS, R, TB, RBI, SB, SVHD):
- Gap = `abs(yours - theirs)`
- Expected daily swing = category-specific constant:
  - K: ~6 per day (across all SP starts), QS: ~1.5/day, SVHD: ~1/day
  - R: ~4/day, TB: ~8/day, RBI: ~4/day, SB: ~0.5/day
- `gap_in_days = gap / expected_daily_swing`
- `winning_big`: leading AND `gap_in_days > days_remaining * 0.8`
- `winning_close`: leading AND `gap_in_days <= days_remaining * 0.8`
- `losing_close`: trailing AND `gap_in_days <= days_remaining * 0.8`
- `losing_big`: trailing AND `gap_in_days > days_remaining * 0.8`

**Thresholds for rate stats** (ERA, WHIP, OBP):
- ERA: `winning_close` if gap < 0.30, `winning_big` if gap >= 0.30
- WHIP: `winning_close` if gap < 0.08, `winning_big` if gap >= 0.08
- OBP: `winning_close` if gap < 0.008, `winning_big` if gap >= 0.008
- (Same thresholds apply to losing side, inverted)
- **Low-IP override:** If total team IP < 15 (early in matchup week), force ERA and WHIP to `winning_close` or `losing_close` regardless of gap — rate stats are too volatile with few innings to classify as "big"
- Note: rate stat gaps can widen or narrow quickly with few IP/PA, so these thresholds are intentionally conservative

**Tied categories (gap = 0):** Classify as `losing_close` — bias toward action. A tie is effectively a coin flip, and starting a pitcher gives you a chance to take the lead in K/QS while accepting rate stat risk.

**Step 2 — Compute pitching category leverage:**

Only 4 categories are affected by an SP start decision: **K, QS, ERA, WHIP**. (SVHD is unaffected by SP starts; hitting categories are irrelevant.)

For each of these 4 categories, compute a leverage score (0-1):
- `leverage = 0` if the category is `winning_big` or `losing_big` (outcome unlikely to change)
- `leverage = 1` if the category is `winning_close` or `losing_close` (outcome could swing)

Directional context:
- For K/QS: starting a pitcher **helps** (adds Ks and QS chances). Leverage is "positive" — starting is beneficial if losing_close, low-stakes if winning_big.
- For ERA/WHIP: starting a pitcher **risks** hurting (a bad outing raises ratios). Leverage is "negative" — starting is risky if winning_close.

**Step 3 — Decision matrix:**

Map (PitcherList tier, category context) to our recommendation using this matrix:

| PitcherList Tier | ERA/WHIP winning_close | K/QS losing_close | Default |
|---|---|---|---|
| strong_start (Start 7-10) | **start** (flag ratio risk) | **strong_start** | **strong_start** |
| start (Start 1-6) | **risky_start** | **start** | **start** |
| maybe (Maybe 1-6) | **sit** | **risky_start** | **sit** |
| sit (Sit 1-3) | **sit** | **sit** | **sit** |

Priority rules when ERA/WHIP and K/QS conflict:
- If ERA/WHIP `winning_close` AND K/QS `losing_close`: favor protecting ratios (downgrade one tier)
- If ERA/WHIP `winning_big` AND K/QS `losing_close`: favor chasing Ks (upgrade one tier)
- If all pitching cats `winning_big`: **safe_sit** regardless of PitcherList tier (protect all leads)

**Step 4 — Generate rationale string:**

Template-based rationale referencing the specific category context. Examples:
- "PitcherList Start-8 vs CIN. Protect your ERA lead (3.12 vs 3.45) — worth the start."
- "PitcherList Maybe-3 vs NYY. You're down 7 Ks with 2 days left — not enough upside to risk ERA."
- "Winning all pitching categories comfortably. Safe to sit and protect leads."

**Output:**
```json
{
  "matchup_summary": {
    "opponent": "Team Name",
    "categories": {
      "R": {"yours": 22, "theirs": 18, "status": "winning_close"},
      "TB": {"yours": 55, "theirs": 48, "status": "winning_close"},
      "RBI": {"yours": 20, "theirs": 15, "status": "winning_close"},
      "OBP": {"yours": 0.285, "theirs": 0.270, "status": "winning_close"},
      "SB": {"yours": 3, "theirs": 5, "status": "losing_close"},
      "K": {"yours": 45, "theirs": 38, "status": "winning_close"},
      "QS": {"yours": 3, "theirs": 2, "status": "winning_close"},
      "ERA": {"yours": 3.12, "theirs": 3.45, "status": "winning_close"},
      "WHIP": {"yours": 1.08, "theirs": 1.15, "status": "winning_close"},
      "SVHD": {"yours": 4, "theirs": 3, "status": "winning_close"}
    },
    "days_remaining": 4,
    "overall": "W8 - L1 - T1"
  },
  "recommendations": [
    {
      "pitcher_name": "Corbin Burnes",
      "matchup": "vs. LAD",
      "pitcherlist_tier": "strong_start",
      "pitcherlist_score": 8,
      "pitcherlist_raw": "Start-8",
      "our_recommendation": "start",
      "rationale": "PitcherList Start-8 vs LAD. ERA is close (3.12 vs 3.45) — slight ratio risk but K/QS upside worth it."
    }
  ],
  "off_day_pitchers": [
    {"pitcher_name": "Zack Wheeler"}
  ]
}
```

Note: `off_day_pitchers` lists SPs on the roster who are NOT in PitcherList's table for today. No `next_start` date is provided (would require a separate data source and is not worth the complexity).

#### 3. Credential Storage (migration — affects waivers, trades, start-sit)

**Current state:** Waivers and trades pages store `espn_s2`, `SWID`, `leagueId`, and `teamId` in localStorage (keys: `waiver_settings`, `trade_settings`). These are passed in POST body to API routes. This doesn't work across devices.

**New pattern — store on the League model:**

The Prisma `League` model already has a `settings` JSON field (`Json?` type). The existing data stores ESPN league config (`scoringSettings`, `rosterSettings`, `acquisitionSettings`, `currentMatchupPeriod`, etc.). Store credentials under a **nested `credentials` key** to avoid collision:

```json
{
  "scoringSettings": { ... },
  "rosterSettings": { ... },
  "credentials": {
    "espn_s2": "...",
    "swid": "...",
    "default_team_id": "5"
  }
}
```

This avoids a new table or migration.

**Settings UI:** Add a `/settings` page (or settings section on the league page) where the user enters ESPN credentials once. Saves to `league.settings.credentials` via a new API route `PUT /api/leagues/[leagueId]/credentials`.

**Merge semantics:** The credentials PUT endpoint must **merge** the `credentials` key into the existing `settings` JSON — never overwrite the whole object. Read current settings, set `settings.credentials = {...}`, write back.

**API route changes:**
- All API routes that need ESPN credentials (`waivers/recommendations`, `trades/suggestions`, `start-sit`) look up credentials from `league.settings.credentials` in the DB
- Remove `swid` and `espn_s2` from POST body requirements
- Only `leagueId` and `teamId` required from client

**Frontend migration for `/waivers` and `/trades`:**
- Remove localStorage read/write for credentials
- Keep league/team selection UI (read from URL params or saved preference)
- If no credentials found in DB for selected league, show setup prompt with link to `/settings`

**Implementation order:** Build credential storage first (it's a prerequisite for start-sit being phone-friendly), then build start-sit, then migrate waivers/trades.

#### 4. FastAPI Endpoint

**File:** `backend/api/routes.py` (extend existing)

```
POST /api/start-sit
```

PitcherList scraping happens in the Python backend (BeautifulSoup), so the Next.js route only passes ESPN data. The backend fetches and caches PitcherList data server-side.

Request body:
```json
{
  "roster_pitcher_names": ["Corbin Burnes", "Zack Wheeler", "Logan Webb"],
  "matchup_categories": { ... },
  "team_ip": {"yours": 35.1, "theirs": 32.0},
  "days_remaining": 4,
  "opponent_name": "Team Name",
  "today_date": "2026-03-25"
}
```

Response: the output structure described in section 2.

#### 5. Next.js API Route

**File:** `src/app/api/start-sit/route.ts` (new)

Orchestrates:
1. Look up ESPN credentials from `league.settings` in DB by league ID
2. Fetch user's roster from ESPN API (`getRosters()`) — filter to SPs (defaultPositionId 1)
3. Fetch current matchup scoreboard from ESPN API (new method `getMatchupScoreboard()` using `mMatchupScore` + `mScoreboard` views)
4. Extract: per-category totals for user's team and opponent, days remaining, opponent name, team IP totals
5. Forward SP names + matchup data to Python backend `POST /api/start-sit`
6. Return results to frontend

**New ESPN API method needed:** `ESPNApi.getMatchupScoreboard(leagueId, season, settings, matchupPeriodId)` — fetches `?view=mMatchupScore&view=mScoreboard`, filters `schedule` by `matchupPeriodId`, returns per-category totals for all teams in the current weekly matchup. The `matchupPeriodId` comes from `getLeague()` → `status.currentMatchupPeriod`.

#### 6. Frontend Page

**File:** `src/app/start-sit/page.tsx` (new)

**URL:** `/start-sit?league={leagueId}&team={teamId}`

**Default view: today's recommendations**

**Header area:**
- "Start/Sit — [Today's date]" with league name
- Current matchup summary bar: opponent name, overall record across all 10 categories (e.g., "W5 - L3 - T2")

**Category context strip:**
- Compact row showing the 4 pitching categories affected by SP decisions (K, QS, ERA, WHIP)
- Each shows: your value, opponent's value, status indicator color-coded by state
- SVHD shown separately as context-only (not affected by SP start/sit)
- Hitting categories shown in a collapsed/secondary row for full matchup awareness

**Recommendations table:**
- One row per SP who is a probable starter today (appears in PitcherList data)
- Columns: Pitcher name, Matchup (vs. team), PitcherList score (e.g., "Start-8"), Our recommendation, Rationale
- Color-coded recommendations: green shades for starts, yellow for risky/maybe, red for sits

**Off-day section:**
- SPs on roster who are NOT pitching today, shown muted below the main table

**Refresh button** to re-fetch latest data.

**Error states:**
- No credentials stored: "Set up ESPN credentials in Settings to use Start/Sit recommendations" with link
- PitcherList unavailable: Show matchup context, message "PitcherList data unavailable — cannot determine probable starters"
- No SPs starting today: Show matchup summary and "No SP starts today"

**Mobile-friendly:** Designed to be scannable on a phone screen. Recommendations stack vertically on narrow viewports with rationale below each pitcher card.

## Key Assumptions

- PitcherList continues publishing weekly Sit/Start articles with the current HTML table format
- ESPN `mMatchupScore` + `mScoreboard` views return per-category totals for H2H category leagues (confirmed via espn-api library source code)
- Name matching between PitcherList and our player DB works with the existing accent-stripping pattern
- PitcherList's weekly article covers all probable starters, so presence in the table = probable starter

## What This Does NOT Include

- RP start/sit decisions (closers/setup men have different considerations)
- Streaming recommendations (picking up free agent SPs for single starts)
- Historical tracking of recommendation accuracy
- Multi-league support (single league for now)
- Building our own matchup model (we rely on PitcherList for per-start quality)
- Future probable starter dates (only today's starters shown)

## Verification

1. **PitcherList scraper:** Verify we can fetch and parse the current week's Sit/Start article, extracting pitcher/opponent/tier/score per day
2. **ESPN matchup scoreboard:** Verify `mMatchupScore` + `mScoreboard` views return per-category totals for the current matchup period
3. **Category classification:** Given known matchup state (e.g., ERA gap of 0.20 with 3 days left), verify classification as `winning_close`
4. **Decision matrix:** Given PitcherList "Start-4" + ERA `winning_close`, verify output is `risky_start` with appropriate rationale
5. **Credential migration:** Verify waivers/trades/start-sit all work with DB-stored credentials, no localStorage needed
6. **Mobile:** Load `/start-sit` on phone, verify it's readable and usable
7. **End-to-end:** Open page, see today's SP recommendations with rationale that reflects current matchup state
