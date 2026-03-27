# Weekly Matchup Projections — Design Spec

**Date:** 2026-03-26
**Status:** Draft

## Overview

A new `/matchup` page that shows projected category totals and projected win/loss outcome for the user's current weekly H2H matchup. Combines ESPN live actuals with RoS projection data (ATC DC) to produce a "where I am now + where I'll finish" view for each of the 10 scoring categories.

## Scoring Categories

- **Hitting (5):** R, TB, RBI, SB, OBP
- **Pitching (5):** K, QS, ERA, WHIP, SVHD

## Key Design Decisions

1. **Actuals-first with projection overlay** — Current ESPN actuals are the primary numbers. Projected finals add remaining-day projections on top.
2. **Games-remaining aware** — Uses MLB schedule API to determine how many games each player's real team has left in the matchup period.
3. **Rotation-aware for SPs** — Uses MLB probable pitchers API to identify which SPs will actually start. Only projects stats for SPs with expected starts.
4. **Optimal lineup modeling** — For remaining days, simulates the optimal daily lineup for both teams using the existing roster optimizer. Bench overflow contributes 0.
5. **Both teams play optimally** — Opponent projections also assume optimal daily lineup decisions.
6. **Headline score + per-category win probabilities** — Top-level "Projected: 6-3-1" score, with each category showing a win probability percentage.
7. **Player-level roster table** — Below the scoreboard, a table shows each player's remaining-week projected stats.

## Architecture

Follows the same three-tier pattern as waivers and start-sit:

```
Frontend (/matchup page)
  → Next.js API route (POST /api/matchup/projections)
    → Python backend (POST /api/matchup/projections)
```

### Frontend — `src/app/matchup/page.tsx`

- League/team selector persisted in localStorage (same pattern as waivers/start-sit)
- Calls `POST /api/matchup/projections` with `{ leagueId, teamId }`
- Renders three zones:
  1. **Header** — league/team selector, matchup period dates, days remaining
  2. **Category scoreboard** — 10 category cards with projected finals, current actuals, win probability bars
  3. **Roster projections table** — player-level remaining-week projections

### Next.js API Route — `src/app/api/matchup/projections/route.ts`

Orchestrates all data fetching, then forwards to Python backend.

**Steps:**
1. Validate ESPN credentials from DB (same as waivers/start-sit)
2. Fetch league info → `currentMatchupPeriod`
3. Fetch in parallel:
   - Matchup scoreboard (ESPN) → current actuals for both teams
   - Rosters for both teams (ESPN) → player names, positions, lineup slots
   - All team names (ESPN) → opponent display name
4. Determine matchup period date range (start/end dates)
5. Fetch in parallel:
   - MLB schedule for remaining days → team games remaining per MLB team
   - MLB probable pitchers for remaining days → which SPs are expected to start
6. Resolve ESPN player names → mlb_ids (reuse `resolve_espn_names_to_mlbid` pattern from waivers)
7. Forward to Python backend:
   - Both teams' rosters (with mlb_ids, positions, lineup slot ids)
   - Current actuals per category (from ESPN scoreboard)
   - Current actual IP and PA (from ESPN scoreboard)
   - Team schedule data (remaining games per MLB team)
   - Probable pitchers data
   - Matchup period metadata (days remaining, end date)

### Python Backend — `backend/analysis/matchup.py`

New module. Core projection engine.

**Inputs:**
```python
{
  "my_roster": [{ "mlb_id": int, "name": str, "position": str, "lineup_slot_id": int, "mlb_team": str }],
  "opponent_roster": [{ "mlb_id": int, "name": str, "position": str, "lineup_slot_id": int, "mlb_team": str }],
  "actuals": {
    "my": { "R": float, "TB": float, ..., "IP": float, "PA": float },
    "opponent": { "R": float, "TB": float, ..., "IP": float, "PA": float }
  },
  "team_games_remaining": { "NYY": 4, "LAD": 3, ... },
  "probable_pitchers": { "2026-03-27": [mlb_id, ...], "2026-03-28": [...], ... },
  "days_remaining": int,
  "season": str
}
```

**Processing:**

1. **Load RoS projections** from `rankings` table for all players on both rosters (same source as waivers: ATC DC).

2. **Compute remaining season games** per MLB team. Use the MLB schedule API to get total remaining regular season games for each team. This is the denominator for pro-rating.

3. **For each remaining day in the matchup period**, for each team:
   a. Determine which players have a game (check `team_games_remaining` by their `mlb_team`)
   b. For SPs: check if they appear in `probable_pitchers` for that date. If not, they don't pitch that day.
   c. RPs: available any day their team plays
   d. From the pool of available players, run roster optimization to determine the optimal starting lineup for that day
   e. For each starting player, compute per-game projections:
      - **Hitters:** `proj_stat_per_game = ros_proj_stat / ros_remaining_games_for_team`
      - **SPs (with a start):** `proj_stat_per_start = ros_proj_stat / ros_projected_starts` where `ros_projected_starts = round(proj_ip / 6)` (average ~6 IP per start; if the rankings table includes `proj_gs`, prefer that)
      - **RPs:** `proj_stat_per_game = ros_proj_stat / ros_remaining_games_for_team`

4. **Aggregate remaining-week projections** — sum per-game projections across all remaining days for each team.

5. **Compute projected finals:**
   - **Counting stats** (R, TB, RBI, SB, K, QS, SVHD): `projected_final = actual + remaining_projection`
   - **Rate stats** (OBP): `projected_final = (actual_OBP * actual_PA + proj_OBP * proj_PA) / (actual_PA + proj_PA)`
   - **Rate stats** (ERA): `projected_final = (actual_ERA * actual_IP + proj_ERA * proj_IP) / (actual_IP + proj_IP)` — equivalently, blend earned runs and innings
   - **Rate stats** (WHIP): same IP-weighted blending approach

6. **Compute per-category win probability:**
   - For each category, compute `margin = my_projected_final - opponent_projected_final`
   - For inverted categories (ERA, WHIP), flip the sign
   - Map margin to win probability using a sigmoid function calibrated to historical weekly variance:
     - `win_prob = 1 / (1 + exp(-margin / sigma))`
     - `sigma` values per category (approximate weekly standard deviations, to be tuned):
       - R: 5, TB: 10, RBI: 5, SB: 2, OBP: 0.015
       - K: 8, QS: 1.5, ERA: 1.0, WHIP: 0.15, SVHD: 2
   - Categories with `win_prob >= 0.6` → "winning" (green)
   - Categories with `win_prob <= 0.4` → "losing" (red)
   - Categories with `0.4 < win_prob < 0.6` → "toss-up" (yellow)

7. **Compute headline projected score:**
   - Count wins (win_prob >= 0.6), losses (win_prob <= 0.4), toss-ups (rest)
   - Overall win probability: product of independent category outcomes (or simpler: sum of win_probs / 10 as a heuristic)

**Output:**
```python
{
  "matchup_period": { "week": int, "start_date": str, "end_date": str, "days_remaining": int },
  "opponent_name": str,
  "projected_score": { "wins": int, "losses": int, "ties": int },
  "overall_win_probability": float,
  "categories": {
    "R": {
      "my_actual": float,
      "opponent_actual": float,
      "my_projected_final": float,
      "opponent_projected_final": float,
      "win_probability": float,
      "status": "winning" | "losing" | "tossup"
    },
    // ... all 10 categories
  },
  "my_roster_projections": [
    {
      "mlb_id": int,
      "name": str,
      "position": str,
      "games_remaining": int,  // or starts_remaining for SP
      "projected_stats": { "R": float, "TB": float, ... },
      "is_active": bool  // false if SP with no start this week
    }
  ]
}
```

## Roster Optimization for Daily Lineups

Reuse the existing roster optimizer logic. For each remaining day:

1. Filter roster to players whose MLB team has a game that day
2. For SPs, further filter to only those listed as probable pitcher for that day
3. Assign players to lineup slots to maximize projected counting stat contribution
4. Players who don't fit in a starting slot are benched (contribute 0)
5. For rate stats, only include PA/IP from starting players

The Python backend needs a lightweight roster optimizer. The existing TypeScript one (`src/lib/roster-optimizer.ts`) can be ported, or a simplified version used since we're optimizing per-day (fewer players available = simpler assignment).

### Lineup Slot Mapping

Same ESPN slot IDs used elsewhere:
- 0=C, 1=1B, 2=2B, 3=3B, 4=SS, 5=OF, 12=UTIL, 13=P, 14=SP, 15=RP
- 16=BE (bench), 17=IL

Active hitting slots: 0-5, 12
Active pitching slots: 13, 14, 15

## MLB API Endpoints

### Team Schedule (remaining games in matchup period)

```
GET https://statsapi.mlb.com/api/v1/schedule?sportId=1&startDate=YYYY-MM-DD&endDate=YYYY-MM-DD
```

Returns games per date. Count games per team within the matchup period's remaining dates.

### Probable Pitchers

```
GET https://statsapi.mlb.com/api/v1/schedule?sportId=1&startDate=YYYY-MM-DD&endDate=YYYY-MM-DD&hydrate=probablePitcher
```

Returns probable pitchers per game. Match pitcher mlb_ids against roster to determine which SPs have starts.

### Remaining Season Games (for pro-rating denominator)

```
GET https://statsapi.mlb.com/api/v1/schedule?sportId=1&startDate=YYYY-MM-DD&endDate=YYYY-09-28&teamId=XXX
```

Or compute from the standard 162-game schedule minus games already played. The MLB standings API provides games played per team:

```
GET https://statsapi.mlb.com/api/v1/standings?leagueId=103,104&season=2026
```

## Frontend UI

### Zone 1: Header

- League dropdown + team dropdown (localStorage-persisted, same as waivers)
- "Week 3 · Mon Mar 23 – Sun Mar 29"
- "4 days remaining"

### Zone 2: Matchup Scoreboard

**Projected score banner:**
- Centered display: `MY TEAM  6 - 3 - 1  OPPONENT`
- Team names below the labels
- "Projected Final · Win probability: 74%"

**Category cards (10 total, grouped Hitting / Pitching):**
- Left border colored by status (green/yellow/red)
- Category label + win probability percentage
- Projected finals head-to-head: `28 vs 22`
- Current actuals: `now: 18 vs 14`
- Win probability progress bar

### Zone 3: Roster Projections Table

**Hitters table:**
- Columns: Player, Pos, Games (remaining), R, TB, RBI, SB, OBP
- Sorted by lineup position

**Pitchers table:**
- Columns: Pitcher, Pos (SP/RP), GS (starts remaining), K, QS, ERA, WHIP, SVHD
- SPs with no start this week shown greyed out with "—" stats
- RPs show team games as their games count

**Footer note:** "Projections assume optimal daily lineup."

## Error Handling

- No ESPN credentials → redirect to settings (same as waivers)
- No matchup found (bye week, off-season) → display message
- Player not found in rankings/projections → exclude from projections, show as "no projection" in roster table
- MLB API unavailable → fall back to simple day-based pro-rating (Section 2 option B as degraded mode)

## Files to Create/Modify

**New files:**
- `src/app/matchup/page.tsx` — frontend page
- `src/app/api/matchup/projections/route.ts` — Next.js API route
- `backend/analysis/matchup.py` — Python projection engine
- `backend/api/matchup.py` — FastAPI endpoint

**Modified files:**
- `src/lib/espn-api.ts` — may need to expose additional scoreboard fields (actual IP, PA)
- `src/lib/mlb-api.ts` — add schedule + probable pitcher fetching if not already present
- `backend/api/__init__.py` or router setup — register new endpoint
- Nav component — add `/matchup` link

## Testing

- **Unit tests for projection math:** verify per-game pro-rating, rate stat blending, win probability sigmoid
- **Unit tests for roster optimization:** verify optimal lineup selection per day
- **Integration test:** mock ESPN + MLB API responses, verify end-to-end output structure
- **Manual verification:** compare projected finals against actual week-end results to tune sigma values
