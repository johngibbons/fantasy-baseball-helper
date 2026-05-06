# Waiver Wire Recommendation Engine — Design Spec

## Context

The fantasy baseball helper currently supports pre-draft projections, draft optimization, and post-draft evaluation. Once the season starts, there's no tooling to help with in-season roster management. The user plays in an ESPN H2H categories league with FAAB ($100 budget, continuous daily waivers at 4 AM ET, 7 pickups per matchup). They want to know which free agents will improve their expected wins over the rest of the season, using ATC DC (RoS) projections from FanGraphs as the projection source.

## Goal

Build a waiver wire recommendation page that shows:
1. A ranked list of the best available free agents by expected wins improvement
2. Optimal drop/add swap pairs with net delta expected wins
3. Suggested FAAB bid amounts for each recommendation

The valuation uses the existing MCW/expected-wins framework (compute_rank + win_prob_from_rank) applied to rest-of-season projected category totals across all league teams.

## League Settings (ESPN)

- H2H Categories, 10 categories
- FAAB: $100 budget, continuous, daily waivers at 4 AM ET
- 7 acquisitions per matchup
- Tiebreaker: reset weekly to inverse standings order
- Daily lineups, lock at game time
- Roster: C, 1B, 2B, 3B, SS, 3 OF, 2 UTIL, 3 SP, 2 RP, 2 P, 8 Bench (25 total)

## Architecture

### Data Flow

```
1. ESPN API → all league rosters + free agent list
2. FanGraphs API → ATC DC (RoS) projections (batting + pitching)
3. Resolve ESPN player IDs → mlbamid via name matching (see Player ID Resolution below)
4. Compute each team's projected RoS category totals
5. For each free agent × each droppable roster player:
     new_totals = my_totals - drop_projection + add_projection
     delta_wins = new_expected_wins - current_expected_wins
6. Rank by best delta_wins, compute FAAB bid suggestions
7. Return ranked recommendations via API
8. Display on /waivers frontend page
```

### Component Breakdown

#### 1. ESPN Free Agent Fetcher

**File:** `src/lib/espn-api.ts` (extend existing EspnApi class)

Add `getFreeAgents()` method:
- ESPN API endpoint: `GET /apis/v3/games/flb/seasons/{season}/segments/0/leagues/{leagueId}?view=kona_player_info`
- Use `x-fantasy-filter` header with `"filterStatus": {"value": ["FREEAGENT"]}` (following the pattern in `fetch_espn_adp` at `projections.py:1124-1131`)
- Return player ESPN ID, fullName, position, eligibility
- Also use existing `getRosters()` to get all teams' rosters (returns ESPN IDs + names)

**File:** `src/app/api/leagues/[leagueId]/free-agents/route.ts` (new Next.js API route)
- Proxy ESPN free agent data for the Python backend to consume

#### 1b. Player ID Resolution

**Problem:** ESPN uses its own player IDs. FanGraphs projections key on `mlbamid` (MLB Stats API). The `players` table has `mlb_id` (mlbamid) but no `espn_id` column.

**Solution:** Name-based matching, consistent with the existing `fetch_espn_adp()` pattern in `projections.py:1083-1170`:
- Strip accents from ESPN `fullName`, look up against `players.full_name`
- Handle edge cases: suffixes (Jr., II), accented characters (already handled by existing `strip_accents()`)
- For unmatched players, log a warning and skip (they won't appear in recommendations)
- ~250 players per league need resolution (25 roster spots x 10 teams + free agents); cache the mapping per session

#### 2. ATC DC Projection Source

**File:** `backend/data/projections.py` (modify existing)

- The FanGraphs API type parameter for ATC DC (RoS) is not confirmed. Implementation should:
  1. Try `"atcdc"` first
  2. Fall back to `"ratcdc"`, `"rfangraphsdc"`, `"atc"` with additional params
  3. Log which type string works so we can hardcode it going forward
- Make the type string configurable via env var `FANGRAPHS_ROS_TYPE` (default `"atcdc"`) so it can be changed without a code deploy
- Fetch batting (`stats=bat`) and pitching (`stats=pit`) projections
- Store in `projections` table with source = `"atcdc"`
- During season: use ATC DC as primary projection source for waiver recommendations (separate from the draft projection blend)

#### 3. Waiver Valuation Engine

**File:** `backend/analysis/waivers.py` (new)

Core function: `compute_waiver_recommendations()`

Input:
- `my_roster`: list of player IDs on user's team
- `all_rosters`: dict of team_id → list of player IDs for all league teams
- `free_agents`: list of player IDs available
- `projections`: dict of player_id → category projections (from ATC DC)
- `remaining_faab`: float

Process:
1. **Compute team totals from raw stats**: For each team, sum RoS projections across rostered players. Use raw component stats, NOT z-scores:
   - **Counting stats** (R, TB, RBI, SB, K, QS, SVHD): direct sums
   - **OBP**: team_OBP = (total_H + total_BB + total_HBP) / (total_AB + total_BB + total_HBP + total_SF)
   - **ERA**: team_ERA = (total_ER * 9) / total_IP
   - **WHIP**: team_WHIP = (total_H_allowed + total_BB_allowed) / total_IP
   - Store component stats alongside computed rates so swaps can be done by adjusting components
2. **Compute baseline expected wins**: Using `compute_rank()` and `win_prob_from_rank()` from `scoring_model.py`, calculate current expected wins.
   - **ERA/WHIP inversion**: For these categories, lower is better. Negate values before passing to `compute_rank()` (which assumes higher = better).
3. **Evaluate each free agent**: For each free agent with projections:
   a. Compute their projected raw stat contributions
   b. For each droppable player on user's roster (bench/IL players first, then starters with lower value):
      - Adjust component stats: subtract drop player's raw stats, add free agent's raw stats
      - Recompute rate stats (OBP, ERA, WHIP) from updated components
      - Recompute expected wins with new totals
      - `delta_wins = new_expected_wins - baseline_expected_wins`
   c. Record the best drop candidate (highest delta_wins) for this free agent
   d. **Two-way players**: If either the drop or add player has both batting AND pitching projections, adjust both hitting and pitching category totals
4. **Rank all free agents** by their best delta_wins descending
5. **Compute FAAB bids** (see below)

Reuse from existing codebase:
- `compute_rank()` from `backend/simulation/scoring_model.py` (line 72)
- `win_prob_from_rank()` from `backend/simulation/scoring_model.py` (line 66)
- `analyze_category_standings()` from `backend/simulation/scoring_model.py` (line 103) for category impact display
- Position eligibility from `backend/simulation/player_pool.py`
- Name matching / accent stripping from `backend/data/projections.py`

#### 4. FAAB Bid Recommender

**File:** `backend/analysis/waivers.py` (same file as valuation)

Function: `compute_faab_bids()`

Logic:
- Normalize delta_wins values across all recommendations (0 to 1 scale)
- Top recommendation gets up to `remaining_faab * 0.4` (cap at 40% of remaining budget for any single player)
- Scale down proportionally for lower-ranked players
- Apply a minimum threshold: if delta_wins < 0.01 (negligible improvement), suggest $0
- Round to nearest dollar

This is intentionally simple — FAAB bidding is inherently game-theoretic and a rough guide is more useful than false precision.

#### 5. FastAPI Endpoint

**File:** `backend/api/routes.py` (extend existing)

```
POST /api/waivers/recommendations
```

Request body:
```json
{
  "my_roster": [{"player_id": 12345, "position": "SS", ...}],
  "all_rosters": {"team_1": [...], "team_2": [...]},
  "free_agents": [{"player_id": 67890, "name": "...", "position": "SS"}],
  "remaining_faab": 85,
  "season": 2026
}
```

Response:
```json
{
  "baseline_expected_wins": 5.2,
  "recommendations": [
    {
      "rank": 1,
      "add_player": {"id": 67890, "name": "Player A", "position": "SS"},
      "drop_player": {"id": 11111, "name": "Player B", "position": "3B"},
      "delta_expected_wins": 0.15,
      "suggested_faab_bid": 12,
      "category_impact": {
        "R": +0.03, "TB": +0.05, "RBI": +0.02, "OBP": +0.01, "SB": +0.04,
        "K": 0, "QS": 0, "ERA": 0, "WHIP": 0, "SVHD": 0
      }
    }
  ]
}
```

#### 6. Frontend Page

**File:** `src/app/waivers/page.tsx` (new)

Layout:
- **Header**: "Waiver Wire Recommendations" with league name, current FAAB remaining
- **Baseline card**: Your team's current expected wins (e.g., "5.2 / 10 categories")
- **Recommendations table**:
  - Columns: Rank, Add (player + position), Drop (player + position), Delta Wins, FAAB Bid, Category Impact (mini sparkline or colored cells)
  - Sortable by delta wins or FAAB bid
  - Filterable by position (show only SS-eligible free agents, etc.)
- **Refresh button**: Re-syncs ESPN data and recalculates
- **"Add only" toggle**: Show best free agents without requiring a drop (for when roster has open slots)

Data fetching: React Query to call the Next.js API route, which orchestrates ESPN data fetch + Python backend call.

**File:** `src/app/api/waivers/recommendations/route.ts` (new Next.js API route)

Orchestrates:
1. Fetch free agents from ESPN (via espn-api.ts)
2. Fetch all rosters from ESPN (via espn-api.ts)
3. Get user's FAAB remaining from ESPN
4. Forward to Python backend `POST /api/waivers/recommendations`
5. Return results to frontend

## Key Assumptions

- ATC DC (RoS) projections are available via FanGraphs API — exact type parameter (`"atcdc"` or variant) to be verified at runtime with fallback to standard ATC
- ESPN API exposes free agents via the `kona_player_info` view with `filterStatus: FREEAGENT` header
- Player matching between ESPN and the projections DB uses name-based resolution (same as existing `fetch_espn_adp` pattern) — there is no ESPN ID column in the DB
- Regarding prospects: ATC DC naturally accounts for expected call-ups through its depth chart playing time adjustments — no special prospect logic needed
- Players on IL slots (ESPN `lineupSlotId` 13) are deprioritized as drop candidates but not excluded

## What This Does NOT Include (Future Work)

- Weekly matchup-aware streaming recommendations
- Trade analysis
- Automated FAAB bidding
- Historical waiver performance tracking
- Prospect-specific scouting beyond what ATC DC projects

## Verification

1. **Unit test the valuation engine**: Given known projections and rosters, verify delta_wins computation matches manual calculation
2. **Test ESPN free agent fetch**: Verify the API returns actual free agents for the user's league
3. **Test ATC DC fetch**: Verify FanGraphs returns projections with the `atcdc` type parameter (or identify correct parameter)
4. **End-to-end**: Load the /waivers page, verify it shows ranked recommendations with reasonable FAAB bids
5. **Sanity check**: Top recommendations should be players who help weak categories, not players who pad already-strong ones
