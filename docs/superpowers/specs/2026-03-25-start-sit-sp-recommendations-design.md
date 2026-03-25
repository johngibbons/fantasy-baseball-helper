# Start/Sit SP Recommendations — Design Spec

## Context

The fantasy baseball helper has waiver wire recommendations and trade analysis, but no tooling for daily lineup decisions. The user plays in an ESPN H2H categories league with daily lineups that lock at game time. Currently they leave all SPs in their lineup without considering matchups or weekly category context. The app runs on Railway and needs to be accessible from any device (phone, desktop) without per-device credential setup.

## Goal

Build a start/sit recommendation page for starting pitchers that combines:
1. Per-start matchup quality (via PitcherList daily SP rankings)
2. Weekly matchup optimization (using current H2H category state to adjust recommendations)

The result: open `/start-sit` on your phone, see today's SP recommendations with context-aware rationale.

## League Settings (ESPN)

- H2H Categories, 10 categories (R, TB, RBI, OBP, SB, K, QS, ERA, WHIP, SVHD)
- Daily lineups, lock at game time
- Roster: C, 1B, 2B, 3B, SS, 3 OF, 2 UTIL, 3 SP, 2 RP, 2 P, 8 Bench (25 total)

## Architecture

### Data Sources

#### PitcherList Daily SP Rankings
- PitcherList publishes daily starting pitcher rankings — each probable starter gets a tier/score and start/sit recommendation
- Scrape/fetch daily rankings page, parse: pitcher name, opposing team, tier/score, start/sit call
- Match pitcher names to existing player database (same name-matching pattern used in waivers)
- Cache daily — rankings publish in the morning and don't change intraday

#### ESPN API (existing integration)
- User's roster: which SPs are on the team
- Today's probable pitchers: which SPs are actually starting today
- Current matchup category totals: user's stats vs opponent's stats for the current matchup period

### Component Breakdown

#### 1. PitcherList Scraper

**File:** `backend/data/pitcherlist.py` (new)

- Fetch PitcherList's daily SP rankings page
- Parse out: pitcher name, opposing team, tier/rank, start/sit recommendation
- Name-match pitchers to our player database using existing accent-stripping/matching patterns from `backend/data/projections.py`
- Cache results for the day (avoid re-scraping on every page load)
- Return structured data: list of `{pitcher_name, mlb_id, opponent, tier, pitcherlist_recommendation}`

#### 2. Start/Sit Optimization Engine

**File:** `backend/analysis/start_sit.py` (new)

**Input:**
- User's SP roster (from ESPN API)
- Today's probable starters (subset of roster SPs who are pitching today)
- Current matchup category totals (user vs opponent, for current matchup period)
- PitcherList daily rankings
- Days remaining in matchup period

**Process:**

1. **Classify each pitching category** (K, QS, ERA, WHIP) by matchup state:
   - Winning comfortably: large gap relative to days remaining
   - Winning close: small gap that a single start could erode
   - Losing close: small gap that a few good starts could close
   - Losing badly: large gap unlikely to close

2. **Compute category leverage:** For each category, how much does a single SP start matter?
   - ERA/WHIP: leverage depends on current IP total (fewer innings = more volatile = higher leverage)
   - K/QS: leverage is more linear (each start adds ~0-1 QS, ~4-8 Ks)

3. **Adjust PitcherList recommendation based on leverage:**
   - PitcherList "start" + ERA/WHIP winning tight → downgrade to "risky start" or "sit"
   - PitcherList "sit" + desperate for K/QS → upgrade to "speculative start"
   - PitcherList "start" + winning all pitching categories comfortably → "safe sit" (protect leads)
   - PitcherList "strong start" → rarely override, but flag risk if ratios are razor-thin

4. **Output per pitcher:** recommendation (strong start / start / risky start / sit / strong sit) + short rationale string explaining the category context

**Output:**
```json
{
  "matchup_summary": {
    "opponent": "Team Name",
    "categories": {
      "K": {"yours": 45, "theirs": 38, "status": "winning_close"},
      "QS": {"yours": 3, "theirs": 2, "status": "winning_close"},
      "ERA": {"yours": 3.12, "theirs": 3.45, "status": "winning_comfortable"},
      "WHIP": {"yours": 1.08, "theirs": 1.15, "status": "winning_close"}
    },
    "days_remaining": 4,
    "overall": "W5 - L3 - T2"
  },
  "recommendations": [
    {
      "pitcher_name": "Corbin Burnes",
      "matchup": "vs. LAD",
      "pitcherlist_tier": 2,
      "pitcherlist_recommendation": "start",
      "our_recommendation": "start",
      "rationale": "Strong arm in a tough matchup. You're up in ERA — slight risk but K/QS upside worth it."
    }
  ],
  "off_day_pitchers": [
    {"pitcher_name": "Zack Wheeler", "next_start": "2026-03-27"}
  ]
}
```

#### 3. Credential Storage (migration — affects waivers, trades, start-sit)

**Current state:** Waivers and trades pages read `espn_s2` and `SWID` from localStorage and pass them in API requests. This doesn't work across devices.

**New pattern:**

- **`league_credentials` table:** `league_id` (PK), `espn_s2`, `swid`, `updated_at`
- **Settings page or section:** One-time credential entry, saves to DB
- **API routes check DB:** When an API route needs ESPN credentials, look them up by league ID from the DB. No client-side credential passing.
- **Migrate `/waivers`, `/trades`, `/start-sit`:** Remove localStorage credential reads. Pages just need the league ID.
- **Fallback:** If no stored credentials found, prompt user to set them up with a clear message and link.

#### 4. FastAPI Endpoint

**File:** `backend/api/routes.py` (extend existing)

```
POST /api/start-sit
```

Request body:
```json
{
  "roster_pitchers": [{"mlb_id": 123, "name": "...", "is_probable_today": true}],
  "matchup_categories": {
    "K": {"yours": 45, "theirs": 38},
    "QS": {"yours": 3, "theirs": 2},
    "ERA": {"yours": 3.12, "theirs": 3.45},
    "WHIP": {"yours": 1.08, "theirs": 1.15}
  },
  "days_remaining": 4,
  "opponent_name": "Team Name"
}
```

Response: the output structure described in section 2.

#### 5. Next.js API Route

**File:** `src/app/api/start-sit/route.ts` (new)

Orchestrates:
1. Look up ESPN credentials from DB by league ID
2. Fetch user's roster from ESPN API
3. Fetch current matchup category totals from ESPN API
4. Determine which SPs are probable starters today
5. Forward to Python backend `POST /api/start-sit`
6. Return results to frontend

#### 6. Frontend Page

**File:** `src/app/start-sit/page.tsx` (new)

**Default view: today's recommendations**

**Header area:**
- "Start/Sit — [Today's date]" with league name
- Current matchup summary bar: opponent name, category wins/losses/ties at a glance (e.g., "W5 - L3 - T2")

**Category context strip:**
- Compact row showing each pitching-relevant category (K, QS, ERA, WHIP)
- Each shows: your value, opponent's value, status indicator (winning comfortable / winning tight / losing tight / losing badly)

**Recommendations table:**
- One row per SP who is a probable starter today
- Columns: Pitcher name, Matchup (vs. team), PitcherList tier, Our recommendation (strong start / start / risky start / sit / strong sit), Rationale
- Color-coded: green shades for starts, red shades for sits

**Off-day section:**
- SPs on roster who are NOT pitching today, shown muted below the main table

**Refresh button** to re-fetch latest data.

**No-pitchers-today state:** If none of your SPs are starting, show the matchup summary and a note like "No SP starts today."

**Mobile-friendly:** Designed to be scannable on a phone screen. Recommendations table should stack/scroll gracefully on narrow viewports.

## Key Assumptions

- PitcherList continues publishing daily SP rankings in a scrapeable format
- ESPN API exposes current matchup category totals (this needs verification — we know rosters and scores are available)
- Probable pitcher data is available from ESPN or can be cross-referenced with MLB API
- Name matching between PitcherList and our player DB works with the existing accent-stripping pattern

## What This Does NOT Include

- RP start/sit decisions (closers/setup men have different considerations)
- Streaming recommendations (picking up free agent SPs for single starts)
- Historical tracking of recommendation accuracy
- Multi-league support (single league for now)
- Building our own matchup model (we rely on PitcherList for per-start quality)

## Verification

1. **PitcherList scraper:** Verify we can fetch and parse today's rankings, matching names to our DB
2. **Category classification:** Given known matchup state, verify categories are correctly classified
3. **Recommendation adjustment:** Given PitcherList "start" + tight ERA, verify output downgrades to "risky start"
4. **Credential migration:** Verify waivers/trades/start-sit all work with DB-stored credentials, no localStorage needed
5. **Mobile:** Load `/start-sit` on phone, verify it's readable and usable
6. **End-to-end:** Open page, see today's SP recommendations with rationale that reflects current matchup state
