# Bench-Weight-Aware Trade Evaluation

**Date:** 2026-04-02
**Status:** Draft

## Problem

The trade engine simulates player swaps by always adding incoming players at weight 1.0 (assumed starter). This ignores three realities:

1. An incoming player might land on the bench (weight 0.25 for hitters)
2. Trading away a starter promotes a bench player to starter
3. The net roster reshuffling changes the true expected wins delta

The waiver wire engine already handles this correctly by re-running `optimize_hitter_lineup()` for each candidate. The trade engine should do the same.

Additionally, the trades UI shows no indication of whether a player is a starter or bench player, making it hard to judge a trade's real value.

## Design

### Backend: Re-optimize Lineups Post-Trade

**Current behavior (lines 231-244 of `trades.py`):**
```python
# Lightweight add/remove — no re-optimization
trial_my.remove_player(proj, my_weights.get(pid, 1.0))
trial_their.add_player(proj, 1.0)  # always assumes starter
```

**New behavior:** For each trade candidate, build the post-trade roster slot list and call `build_team_totals()`, which internally runs `optimize_hitter_lineup()` to determine correct starter/bench assignments.

Steps per candidate:
1. Copy my roster slot list; remove my outgoing player IDs, add their outgoing player IDs with a generic active slot (lineup_slot_id=0)
2. Copy their roster slot list; do the inverse swap
3. Call `build_team_totals(post_trade_my_roster, projections)` → get accurate totals and weights
4. Call `build_team_totals(post_trade_their_roster, projections)` → same for partner
5. Compute expected wins from the re-optimized totals

This replaces the current `add_player`/`remove_player` arithmetic with full roster re-optimization.

**Performance:** The z-score pre-filter (prunes obviously unfair trades) and the early-exit on `my_delta <= 0` remain. `optimize_hitter_lineup()` is a greedy assignment with no DB calls — microseconds per call. Worst case ~242K optimizer calls across all opponents, which is acceptable.

### API: Return Player Weights

Extend `TradePlayerInfo` with weight fields:

```python
@dataclass
class TradePlayerInfo:
    mlb_id: int
    name: str
    position: str
    total_zscore: float
    weight: float          # current weight on source team
    incoming_weight: float  # projected weight on destination team
```

- `my_players_out[].weight` — player's current weight on my roster (what I'm actually losing)
- `my_players_out[].incoming_weight` — weight the player would have on the partner's roster
- `their_players_out[].weight` — player's current weight on the partner's roster
- `their_players_out[].incoming_weight` — weight the player would have on my roster

### Frontend: Show Effective Contribution

In each trade card, next to each player, display:

1. **Role tag:** "Starter" or "Bench" based on current weight (weight < 1.0 = bench)
2. **Effective z-score:** For starters, show raw z-score (e.g., "Z: 3.2"). For bench players, show weighted value with annotation (e.g., "Z: 0.8 (bench)" where 3.2 × 0.25 = 0.8)
3. **Incoming role:** For players being received, show projected role on the receiving team using `incoming_weight` (e.g., "→ Starter" or "→ Bench")

This makes it clear when you're trading a bench player who would become a starter elsewhere (high value trade) or receiving a player who'd sit on your bench (lower value than raw z-score suggests).

### Pitcher Handling

Pitchers already get weight 1.0 for all non-IL slots (daily league model). No change needed — they'll always show as "Starter" and their weights won't change post-trade. The re-optimization only affects hitter lineup assignments.

## Files Changed

| File | Change |
|------|--------|
| `backend/analysis/trades.py` | Replace add/remove simulation with full `build_team_totals()` re-optimization; extend `TradePlayerInfo` with weight fields; pass weights through to response |
| `backend/analysis/trades.py` (`_suggestion_to_dict`) | Serialize new weight fields |
| `src/app/trades/page.tsx` | Display role tags and effective z-scores in trade cards |
| `src/app/api/trades/suggestions/route.ts` | Pass through new weight fields from backend response (no logic change) |

## Out of Scope

- Showing full roster reshuffling details (which bench player gets promoted) — too noisy for the trade card
- Changing the fairness score formula — still based on raw z-score sums, not weighted
- Pitcher bench weight changes — pitchers are already weight 1.0 in daily leagues
