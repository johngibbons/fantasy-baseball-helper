# Waiver Recommendations — Stream Slot Exclusion & Same-Type Swaps

**Date:** 2026-04-20
**Status:** Design approved, pending implementation plan

## Problem

The waivers page currently ranks every hitter FA by a swap that drops the user's worst pitcher (Will Warren), because removing a pitcher with a bad projected ERA/WHIP produces a larger weighted-rate improvement than any hitter-for-hitter swap. This makes the top of the recommendations list nearly useless: 18 rows all proposing the same drop, with identical pitching stat deltas, masking the "which hitter is a real upgrade to my hitters" signal the user actually wants.

The root cause is a modeling gap: the user streams their worst SP slot, so Warren's bad projections won't actually drag their team down for the rest of the season — they'll be swapped to a different streamer within a day. The engine treats Warren as a permanent roster fixture whose stats the user can "escape" by adding an FA.

## Goal

Reframe the waivers page from "which FA swap maximizes expected wins across the entire roster" to **"which FAs are real upgrades to my core (non-streamed) roster."**

Out of scope: streamer pickup suggestions (handled by the start/sit page), multiple stream slots, applying stream-slot logic to opponent rosters, manual stream-slot override UI.

## Behavior Changes

Two orthogonal changes, both on by default, both user-toggleable:

1. **Stream slot auto-exclusion** — the worst-projection pitcher on the user's active roster is treated as replacement-level: excluded from baseline team totals and from drop candidates.
2. **Same-type drops default** — hitter FA rows show hitter drops only; pitcher FA rows show pitcher drops only. A second toggle reveals cross-type rows when the user wants rebalancing suggestions.

## Stream Slot Identification

Single stream slot, auto-detected per call:

- Consider only non-IL pitchers on the user's active roster (`lineup_slot_id < IL_SLOT_THRESHOLD` and `player_type == "pitcher"`).
- Pick the pitcher with the highest `overall_rank` (worst projection) from the `rankings` table.
- Tie-break by lowest `proj_ip` (fewer projected innings = more likely the churn slot).
- If there are zero eligible pitchers, no stream slot is flagged and the feature is a no-op.
- Recomputed on every `/api/waivers/recommendations` request — no persistence.

## Computation Effect

In `backend/analysis/waivers.py`:

- `build_team_totals` accepts an optional `stream_slot_id: Optional[int]` argument. When present, that player's weight is set to `0.0` (matching `IL_WEIGHT`). The player still appears in `weights` so the UI can show him, but his projections contribute nothing to the returned `TeamTotals`.
- `compute_waiver_recommendations` excludes `stream_slot_id` from `droppable_ids` so no recommendation proposes dropping him.
- Stream-slot logic applies to the user's team only. Opponent rosters are unchanged — a v1 limitation that keeps the change focused; downstream effect is a slightly pessimistic absolute `baseline_expected_wins` but accurate deltas for the user's own decisions.

## Same-Type Drop Logic

`compute_waiver_recommendations` accepts an optional `same_type_only: bool = True`:

- When `True`: for each FA, only iterate `droppable_ids` where `drop_proj.player_type == fa_proj.player_type`. The `best_drops` dict collapses to at most `{"same_type", "no_drop"}` entries — one recommendation row per FA (or two if an open roster slot makes "no drop" viable).
- When `False`: current behavior — track best drop per dropped-player type, emit one rec per type (possibly two rows per FA: same-type swap and cross-type swap).

## API Changes

`POST /api/waivers/recommendations` gains two optional fields:

```json
{
  "leagueId": "...",
  "teamId": "...",
  "excludeStreamSlot": true,
  "includeCrossType": false
}
```

Both default to the new behavior (`excludeStreamSlot: true`, `includeCrossType: false`) when omitted.

The response gains one new field:

```json
{
  "stream_slot_player": {
    "id": 12345,
    "name": "Will Warren",
    "position": "SP"
  },
  ...
}
```

Null when no stream slot was identified or `excludeStreamSlot` was false.

The Next.js route at `/api/waivers/recommendations` passes these through to the FastAPI endpoint unchanged.

## UI Changes (`src/app/waivers/page.tsx`)

Two new checkboxes rendered in the control row just above the position filter:

1. **`☑ Exclude stream slot`** — default checked. Label dynamically appends the auto-detected name once results load: `Exclude stream slot (Will Warren)`.
2. **`☐ Show cross-type swaps`** — default unchecked.

Both checkboxes trigger a refetch (`handleFetchRecommendations`) with updated request params. No client-side filtering — the engine's drop search genuinely changes, so we re-run it.

In the "My Roster" panel, the stream-slot player gains a small `STREAM` badge (muted orange, similar styling to slot labels) and his name is rendered slightly dimmed, so the user can see at a glance which player is being excluded.

## Data Flow

```
Frontend (page.tsx)
  POST /api/waivers/recommendations
       { leagueId, teamId, excludeStreamSlot, includeCrossType }
  ↓
Next.js route → FastAPI POST /waivers/recommendations (flags passed through)
  ↓
compute_waiver_recommendations(
    ..., exclude_stream_slot=True, same_type_only=True)
  ↓
  1. If exclude_stream_slot: identify_stream_slot(...) → stream_slot_id
  2. build_team_totals(roster, projections, stream_slot_id=stream_slot_id)
     → weight 0.0 for stream slot
  3. droppable_ids excludes stream_slot_id
  4. Inner drop loop respects same_type_only
  5. Response includes stream_slot_player payload
  ↓
Frontend renders recommendations table and STREAM badge on roster panel
```

## Testing

- **Unit — `identify_stream_slot`:** returns the pitcher with highest `overall_rank`; breaks ties by lowest `proj_ip`; returns `None` when no pitchers are active.
- **Unit — `build_team_totals` with stream slot:** totals equal those computed from the same roster with the stream-slot player physically removed (i.e., weight-0 behaves identically to exclusion).
- **Unit — `compute_waiver_recommendations(same_type_only=True)`:** no returned rec has `add.player_type != drop.player_type`.
- **Unit — stream-slot exclusion end-to-end:** the stream-slot player never appears as `drop_player` in any returned recommendation, regardless of `same_type_only`.
- **Manual/integration:** run against the user's actual 2026 league; confirm Warren is identified as stream slot, no longer appears as a drop, and the top-ranked hitter adds propose hitter-for-hitter swaps.

## Non-Goals / Future Work

- Multiple stream slots (some leagues churn 2 SPs or RPs). Add when first encountered.
- Manual stream-slot override UI. Add if auto-detect mis-identifies a prospect as the stream slot.
- Applying stream-slot exclusion to opponent rosters for a more accurate absolute baseline. Not needed for the "find upgrades" use case.
- Treating the stream slot as an average-streamer projection rather than zero. Zero is simpler and matches IL precedent; revisit if the pessimistic baseline causes mis-ranking.
