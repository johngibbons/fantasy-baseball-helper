# Trade Suggestion Engine - Design Spec

## Context

The app has waiver wire recommendations powered by MCW (expected wins delta) analysis. This feature extends the same approach to **trades** -- suggesting realistic trades to propose to other managers.

"Realistic" means:
- **Mutually beneficial**: both teams gain expected wins after the swap
- **Fair perceived value**: z-score parity with configurable threshold
- **Flexible structures**: 1-for-1, 2-for-1, 2-for-2, optionally with draft pick balancing

## Architecture

### Backend: `backend/analysis/trades.py`

Imports shared infrastructure from `backend/analysis/waivers.py`:
- `PlayerProjection`, `TeamTotals` (team stat aggregation with bench weighting)
- `resolve_espn_names_to_mlbid`, `load_projections_for_players`
- `player_weight` (bench/starter contribution weights)
- `compute_expected_wins` (MCW-based win probability)

From `backend/simulation/scoring_model.py`:
- `compute_rank`, `win_prob_from_rank`

### Core Algorithm

```
compute_trade_suggestions(my_roster, all_team_rosters, my_team_index, season, settings)
```

For each opponent team:
1. Build `TeamTotals` for my team and their team (reuse `player_weight` for bench/starter weighting)
2. Compute baseline expected wins for both teams
3. Generate candidate trades (1-for-1, 2-for-1, 2-for-2 based on `max_trade_size`)
4. For each candidate:
   - **Prune**: skip if z-score sums are outside fairness band
   - Copy both TeamTotals, swap players via `remove_player()`/`add_player()`
   - Recompute expected wins for both sides
   - **Early exit**: skip if my delta < 0
   - Keep if both deltas > 0 and fairness check passes
5. If `include_draft_picks` and trade is MCW-positive but z-score-lopsided, suggest pick compensation

### Pruning Strategy
- Cap tradeable players at top N by z-score per team (default 15)
- Exclude IL players from candidates
- Z-score sum pre-filter for multi-player trades
- Early exit when my delta < 0

### Fairness Model
```
fairness_score = (their_zscore_out - my_zscore_out) / max(avg_zscore, 1.0)
```
- Positive = I'm getting more value
- Configurable threshold (default 0.5)
- Acceptance probability derived from fairness score via sigmoid

### Draft Pick Model
Picks don't affect current-season MCW -- they're fairness balancers only:
- Round 1-3: high value (z-score equiv ~8/6/4.5)
- Round 4-8: medium (3.0 down to 1.0)
- Round 9+: negligible

### Data Structures

```python
@dataclass
class TradeSuggestion:
    partner_team_id: int
    partner_team_name: str
    my_players_out: list[TradePlayerInfo]
    their_players_out: list[TradePlayerInfo]
    draft_pick_adjustment: Optional[DraftPickAdjustment]
    my_delta_wins: float
    their_delta_wins: float
    fairness_score: float          # -1 to +1, 0 = perfectly fair
    acceptance_probability: float  # 0 to 1
    my_category_impact: dict[str, float]
    their_category_impact: dict[str, float]
    trade_type: str                # "1-for-1", "2-for-1", "2-for-2"
```

### FastAPI Endpoint

`POST /api/trades/suggestions` -- mirrors the waiver endpoint pattern.

Request: roster data, team index, season, trade settings.
Response: baseline wins + sorted trade suggestions + computation stats.

### Next.js Orchestration

`src/app/api/trades/suggestions/route.ts` -- mirrors waivers route:
1. Accept POST with leagueId, teamId, season, ESPN credentials, settings
2. Fetch all rosters + team names from ESPN
3. POST to Python backend
4. Merge mlb_ids for player detail links
5. Return results

### Frontend: `/trades`

Three tab views:
1. **Best Trades** -- all suggestions sorted by my_delta_wins desc
2. **By Partner** -- accordion grouped by opponent team
3. **By My Player** -- grouped by which of my players is traded

Config panel with sticky settings (same pattern as waivers):
- League/team selector with ESPN credentials
- Fairness threshold slider
- Max trade size toggle
- Include draft picks checkbox

## Files

### New
- `docs/superpowers/specs/2026-03-23-trade-suggestions-design.md` (this file)
- `backend/analysis/trades.py`
- `src/app/api/trades/suggestions/route.ts`
- `src/app/trades/page.tsx`

### Modified
- `backend/api/routes.py` -- add trade suggestions endpoint
- `backend/analysis/waivers.py` -- export `player_weight` (rename from `_player_weight`)
