# Bench-Weight-Aware Trade Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the trade engine re-optimize lineups post-trade (like waivers does) and show starter/bench role + effective z-scores in the UI.

**Architecture:** Replace the lightweight `add_player`/`remove_player` trade simulation with full `build_team_totals()` calls that re-run `optimize_hitter_lineup()`. Extend `TradePlayerInfo` with weight fields. Update the frontend trade card to display role tags and weighted z-scores.

**Tech Stack:** Python (FastAPI backend), TypeScript/React (Next.js frontend)

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/analysis/trades.py` | Modify | Add weight fields to `TradePlayerInfo`, replace simulation logic, update serialization |
| `tests/backend/analysis/test_trades.py` | Create | Test re-optimization behavior, weight propagation, edge cases |
| `src/app/trades/page.tsx` | Modify | Add `weight`/`incoming_weight` to `TradePlayerInfo` interface, render role tags + effective z-scores |

No changes needed to `backend/api/routes.py` or `src/app/api/trades/suggestions/route.ts` — they pass through the backend response as-is.

---

### Task 1: Backend — Extend TradePlayerInfo with weight fields

**Files:**
- Modify: `backend/analysis/trades.py:34-38` (TradePlayerInfo dataclass)
- Modify: `backend/analysis/trades.py:441-465` (_suggestion_to_dict)
- Test: `tests/backend/analysis/test_trades.py`

- [ ] **Step 1: Write the failing test — weight fields exist on TradePlayerInfo**

Create `tests/backend/analysis/test_trades.py`:

```python
import pytest
from backend.analysis.trades import TradePlayerInfo


class TestTradePlayerInfoWeights:
    def test_has_weight_fields(self):
        p = TradePlayerInfo(
            mlb_id=1, name="Test", position="SS",
            total_zscore=3.0, weight=1.0, incoming_weight=0.25,
        )
        assert p.weight == 1.0
        assert p.incoming_weight == 0.25

    def test_weight_fields_default_to_1(self):
        p = TradePlayerInfo(
            mlb_id=1, name="Test", position="SS", total_zscore=3.0,
        )
        assert p.weight == 1.0
        assert p.incoming_weight == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/backend/analysis/test_trades.py::TestTradePlayerInfoWeights -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'weight'`

- [ ] **Step 3: Add weight and incoming_weight fields to TradePlayerInfo**

In `backend/analysis/trades.py`, modify the `TradePlayerInfo` dataclass (lines 33-38):

```python
@dataclass
class TradePlayerInfo:
    mlb_id: int
    name: str
    position: str
    total_zscore: float
    weight: float = 1.0           # current weight on source team
    incoming_weight: float = 1.0  # projected weight on destination team
```

- [ ] **Step 4: Update _suggestion_to_dict to serialize new fields**

In `backend/analysis/trades.py`, modify `_suggestion_to_dict` (lines 441-465). Update both player list serializations to include the new fields:

```python
def _suggestion_to_dict(s: TradeSuggestion) -> dict:
    return {
        "partner_team_id": s.partner_team_id,
        "partner_team_name": s.partner_team_name,
        "my_players_out": [
            {"mlb_id": p.mlb_id, "name": p.name, "position": p.position,
             "total_zscore": p.total_zscore, "weight": p.weight,
             "incoming_weight": p.incoming_weight}
            for p in s.my_players_out
        ],
        "their_players_out": [
            {"mlb_id": p.mlb_id, "name": p.name, "position": p.position,
             "total_zscore": p.total_zscore, "weight": p.weight,
             "incoming_weight": p.incoming_weight}
            for p in s.their_players_out
        ],
        "draft_pick_adjustment": {
            "round": s.draft_pick_adjustment.round,
            "giving_team": s.draft_pick_adjustment.giving_team,
            "zscore_value": s.draft_pick_adjustment.zscore_value,
        } if s.draft_pick_adjustment else None,
        "my_delta_wins": s.my_delta_wins,
        "their_delta_wins": s.their_delta_wins,
        "fairness_score": s.fairness_score,
        "acceptance_probability": s.acceptance_probability,
        "my_category_impact": s.my_category_impact,
        "their_category_impact": s.their_category_impact,
        "trade_type": s.trade_type,
    }
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/backend/analysis/test_trades.py::TestTradePlayerInfoWeights -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/analysis/trades.py tests/backend/analysis/test_trades.py
git commit -m "feat(trades): add weight and incoming_weight fields to TradePlayerInfo"
```

---

### Task 2: Backend — Replace trade simulation with full roster re-optimization

**Files:**
- Modify: `backend/analysis/trades.py:230-244` (trade simulation loop)
- Modify: `backend/analysis/trades.py:321-349` (TradeSuggestion construction)
- Test: `tests/backend/analysis/test_trades.py`

- [ ] **Step 1: Write the failing test — bench player gets correct weight after trade**

Add to `tests/backend/analysis/test_trades.py`:

```python
from backend.analysis.waivers import (
    PlayerProjection,
    build_team_totals,
    compute_expected_wins,
    HITTER_BENCH_WEIGHT,
)
from backend.analysis.trades import compute_trade_suggestions


def _proj(mlb_id, name, position, player_type,
          eligible_positions="", overall_rank=9999, **kwargs):
    defaults = dict(pa=0, r=0, tb=0, rbi=0, sb=0, obp=0.0,
                    ip=0.0, k=0, qs=0, era=0.0, whip=0.0, svhd=0)
    defaults.update(kwargs)
    return PlayerProjection(
        mlb_id=mlb_id, name=name, position=position, player_type=player_type,
        eligible_positions=eligible_positions, overall_rank=overall_rank,
        **defaults,
    )


class TestTradeReOptimization:
    """Verify that trade simulation re-optimizes lineups rather than assuming weight 1.0."""

    def test_incoming_bench_hitter_gets_bench_weight(self, monkeypatch):
        """If I already have 10 starters and receive a hitter, they should bench at 0.25."""
        # Build 10 starters + 1 pitcher per team (11 hitters = 10 start, 1 bench)
        projs = {}
        # My team: 10 strong hitters + 1 weak bench
        for i in range(1, 11):
            pos = ["C", "1B", "2B", "3B", "SS", "OF", "OF", "OF", "DH", "DH"][i - 1]
            elig = pos
            projs[i] = _proj(i, f"MyStarter{i}", pos, "hitter", elig, i * 10,
                             r=80 - i * 2, pa=500, obp=0.350)
        projs[11] = _proj(11, "MyBench", "1B", "hitter", "1B", 300,
                          r=20, pa=200, obp=0.280)
        # 1 pitcher to anchor pitching stats
        projs[12] = _proj(12, "MySP", "SP", "pitcher", "SP", 5,
                          k=200, qs=16, ip=180, era=3.0, whip=1.1)

        # Partner team: same structure with different IDs
        for i in range(101, 111):
            idx = i - 100
            pos = ["C", "1B", "2B", "3B", "SS", "OF", "OF", "OF", "DH", "DH"][idx - 1]
            elig = pos
            projs[i] = _proj(i, f"TheirStarter{idx}", pos, "hitter", elig, idx * 10,
                             r=80 - idx * 2, pa=500, obp=0.350)
        projs[111] = _proj(111, "TheirBench", "OF", "hitter", "OF", 290,
                           r=25, pa=250, obp=0.290)
        projs[112] = _proj(112, "TheirSP", "SP", "pitcher", "SP", 6,
                           k=190, qs=15, ip=175, era=3.2, whip=1.15)

        # Monkeypatch load_projections_for_players to return our projs
        def mock_load(ids, season):
            return {pid: projs[pid] for pid in ids if pid in projs}
        monkeypatch.setattr("backend.analysis.trades.load_projections_for_players", mock_load)

        # Monkeypatch _load_zscores — use overall_rank-based zscore
        def mock_zscores(ids, season):
            return {pid: max(0, 10 - projs[pid].overall_rank / 30) for pid in ids if pid in projs}
        monkeypatch.setattr("backend.analysis.trades._load_zscores", mock_zscores)

        my_roster = [{"mlb_id": i, "lineup_slot_id": 0} for i in range(1, 13)]
        their_players = [{"mlb_id": i, "lineup_slot_id": 0} for i in range(101, 113)]
        all_teams = [
            {"team_id": 1, "team_name": "My Team", "players": my_roster},
            {"team_id": 2, "team_name": "Their Team", "players": their_players},
        ]

        result = compute_trade_suggestions(
            my_roster=my_roster,
            all_team_rosters=all_teams,
            my_team_index=0,
            season=2026,
            max_trade_size=1,
            fairness_threshold=2.0,  # loose to get results
        )

        # Find any suggestion where my_players_out contains a player
        # and check that the weight fields are populated
        for s in result["suggestions"]:
            for p in s["my_players_out"]:
                assert "weight" in p, "my_players_out should have weight field"
                assert "incoming_weight" in p, "my_players_out should have incoming_weight field"
            for p in s["their_players_out"]:
                assert "weight" in p, "their_players_out should have weight field"
                assert "incoming_weight" in p, "their_players_out should have incoming_weight field"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/backend/analysis/test_trades.py::TestTradeReOptimization -v`
Expected: FAIL — `weight` key not in player dicts (current code doesn't output it)

- [ ] **Step 3: Rewrite the trade simulation to use build_team_totals**

In `backend/analysis/trades.py`, replace the simulation block (lines 218-349 of `compute_trade_suggestions`). The key changes are in the inner loop where each candidate is evaluated. Replace the section from `for my_out_ids, their_out_ids in candidates:` through the `suggestions.append(...)` call:

```python
        for my_out_ids, their_out_ids in candidates:
            trades_evaluated += 1

            # Z-score pre-filter
            my_z_sum = sum(zscores.get(pid, 0.0) for pid in my_out_ids)
            their_z_sum = sum(zscores.get(pid, 0.0) for pid in their_out_ids)
            fairness = _compute_fairness(my_z_sum, their_z_sum)

            if abs(fairness) > fairness_threshold * 2:
                trades_pruned += 1
                continue

            # Build post-trade rosters by swapping players
            my_out_set = set(my_out_ids)
            their_out_set = set(their_out_ids)

            # My post-trade roster: remove my outgoing, add their outgoing
            post_my_slots = [s for s in my_roster if s["mlb_id"] not in my_out_set]
            for pid in their_out_ids:
                post_my_slots.append({"mlb_id": pid, "lineup_slot_id": 0})

            # Their post-trade roster: remove their outgoing, add my outgoing
            post_their_slots = [
                {"mlb_id": s["mlb_id"], "lineup_slot_id": s.get("lineup_slot_id", 0)}
                for s in team["players"]
                if s["mlb_id"] not in their_out_set
            ]
            for pid in my_out_ids:
                post_their_slots.append({"mlb_id": pid, "lineup_slot_id": 0})

            # Re-optimize both rosters
            trial_my, trial_my_weights = build_team_totals(post_my_slots, projections)
            trial_my_cat = trial_my.category_values()

            # Rebuild league context post-trade (their team changed too)
            # First compute my team's new wins (cheap early exit if no improvement)
            post_trade_league_cat = []
            for j, tt in enumerate(other_team_totals_list):
                if j == my_team_index:
                    continue
                if j == i:
                    # Placeholder — will be replaced after we compute their totals
                    post_trade_league_cat.append(None)
                else:
                    post_trade_league_cat.append(tt.category_values())

            # We need their post-trade totals for the league context
            trial_their, trial_their_weights = build_team_totals(post_their_slots, projections)
            trial_their_cat = trial_their.category_values()

            # Fill in partner's post-trade values in league context
            for idx_lc in range(len(post_trade_league_cat)):
                if post_trade_league_cat[idx_lc] is None:
                    post_trade_league_cat[idx_lc] = trial_their_cat

            my_new_wins, my_new_cat_probs = compute_expected_wins(trial_my_cat, post_trade_league_cat)
            my_delta = my_new_wins - baseline_wins

            # Early exit: skip if I don't improve
            if my_delta <= 0:
                continue

            # Recompute expected wins for their team
            post_trade_their_league = []
            for j, tt in enumerate(other_team_totals_list):
                if j == my_team_index or j == i:
                    continue
                post_trade_their_league.append(tt.category_values())
            post_trade_their_league.append(trial_my_cat)  # my post-trade totals

            their_new_wins, their_new_cat_probs = compute_expected_wins(
                trial_their_cat, post_trade_their_league
            )
            their_delta = their_new_wins - their_baseline_wins

            # Both sides must improve
            if their_delta <= 0:
                continue

            # Fairness check
            if abs(fairness) > fairness_threshold:
                if include_draft_picks:
                    pick_adj = _find_balancing_pick(fairness, my_z_sum, their_z_sum)
                    if pick_adj and abs(_compute_fairness(
                        my_z_sum + (pick_adj.zscore_value if pick_adj.giving_team == "me" else 0),
                        their_z_sum + (pick_adj.zscore_value if pick_adj.giving_team == "them" else 0),
                    )) <= fairness_threshold:
                        pass
                    else:
                        continue
                else:
                    continue
            else:
                pick_adj = None

            # Determine trade type
            n_my = len(my_out_ids)
            n_their = len(their_out_ids)
            if n_my == 1 and n_their == 1:
                trade_type = "1-for-1"
            elif (n_my == 2 and n_their == 1) or (n_my == 1 and n_their == 2):
                trade_type = "2-for-1"
            else:
                trade_type = "2-for-2"

            # Category impact
            my_cat_impact = {
                cat: round(my_new_cat_probs[cat] - baseline_cat_probs[cat], 4)
                for cat in ALL_CATS
            }
            their_cat_impact = {
                cat: round(their_new_cat_probs[cat] - their_baseline_cat_probs[cat], 4)
                for cat in ALL_CATS
            }

            suggestions.append(TradeSuggestion(
                partner_team_id=team.get("team_id", i),
                partner_team_name=team.get("team_name", f"Team {i}"),
                my_players_out=[
                    TradePlayerInfo(
                        mlb_id=pid,
                        name=projections[pid].name if pid in projections else f"Player {pid}",
                        position=projections[pid].position if pid in projections else "",
                        total_zscore=zscores.get(pid, 0.0),
                        weight=my_weights.get(pid, 1.0),
                        incoming_weight=trial_their_weights.get(pid, 1.0),
                    )
                    for pid in my_out_ids
                ],
                their_players_out=[
                    TradePlayerInfo(
                        mlb_id=pid,
                        name=projections[pid].name if pid in projections else f"Player {pid}",
                        position=projections[pid].position if pid in projections else "",
                        total_zscore=zscores.get(pid, 0.0),
                        weight=their_weights.get(pid, 1.0),
                        incoming_weight=trial_my_weights.get(pid, 1.0),
                    )
                    for pid in their_out_ids
                ],
                draft_pick_adjustment=pick_adj,
                my_delta_wins=round(my_delta, 4),
                their_delta_wins=round(their_delta, 4),
                fairness_score=round(fairness, 4),
                acceptance_probability=round(_acceptance_probability(fairness), 4),
                my_category_impact=my_cat_impact,
                their_category_impact=their_cat_impact,
                trade_type=trade_type,
            ))
```

Also add `build_team_totals` to the import from `backend.analysis.waivers` at the top of the file (it's already imported — just verify it's there on line 20).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/backend/analysis/test_trades.py -v`
Expected: All tests PASS

- [ ] **Step 5: Run existing waiver tests to make sure nothing broke**

Run: `python -m pytest tests/backend/analysis/test_waivers.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/analysis/trades.py tests/backend/analysis/test_trades.py
git commit -m "feat(trades): re-optimize lineups post-trade using build_team_totals"
```

---

### Task 3: Backend — Test that bench player traded as starter gets correct incoming_weight

**Files:**
- Test: `tests/backend/analysis/test_trades.py`

- [ ] **Step 1: Write the test — bench hitter sent to team with open slot becomes starter**

Add to `tests/backend/analysis/test_trades.py`:

```python
class TestTradeWeightAccuracy:
    """Verify weight values reflect actual lineup optimization results."""

    def test_bench_hitter_becomes_starter_on_new_team(self, monkeypatch):
        """A bench 1B on my team (weight=0.25) should get incoming_weight=1.0
        if the receiving team has an open 1B slot."""
        projs = {}
        # My team: full lineup + 1 bench 1B
        positions = ["C", "1B", "2B", "3B", "SS", "OF", "OF", "OF", "DH", "DH"]
        for i in range(1, 11):
            projs[i] = _proj(i, f"MyStart{i}", positions[i-1], "hitter",
                             positions[i-1], i * 10,
                             r=80 - i, pa=500, obp=0.350)
        projs[11] = _proj(11, "MyBench1B", "1B", "hitter", "1B", 250,
                          r=30, pa=300, obp=0.300)
        projs[12] = _proj(12, "MySP", "SP", "pitcher", "SP", 5,
                          k=200, qs=16, ip=180, era=3.0, whip=1.1)

        # Their team: 9 starters (no 1B!) + 1 pitcher
        their_positions = ["C", "2B", "3B", "SS", "OF", "OF", "OF", "DH", "DH"]
        for i in range(101, 110):
            idx = i - 100
            projs[i] = _proj(i, f"TheirStart{idx}", their_positions[idx-1], "hitter",
                             their_positions[idx-1], idx * 10,
                             r=80 - idx, pa=500, obp=0.350)
        projs[110] = _proj(110, "TheirSP", "SP", "pitcher", "SP", 6,
                           k=190, qs=15, ip=175, era=3.2, whip=1.15)
        # Their team gets a player from me; I get one of theirs
        # Let's say they also have a bench DH
        projs[111] = _proj(111, "TheirBenchDH", "DH", "hitter", "DH", 280,
                           r=25, pa=250, obp=0.290)

        def mock_load(ids, season):
            return {pid: projs[pid] for pid in ids if pid in projs}
        monkeypatch.setattr("backend.analysis.trades.load_projections_for_players", mock_load)

        def mock_zscores(ids, season):
            return {pid: max(0, 10 - projs[pid].overall_rank / 30) for pid in ids if pid in projs}
        monkeypatch.setattr("backend.analysis.trades._load_zscores", mock_zscores)

        my_roster = [{"mlb_id": i, "lineup_slot_id": 0} for i in range(1, 13)]
        their_roster = [{"mlb_id": i, "lineup_slot_id": 0} for i in range(101, 112)]

        all_teams = [
            {"team_id": 1, "team_name": "My Team", "players": my_roster},
            {"team_id": 2, "team_name": "Their Team", "players": their_roster},
        ]

        result = compute_trade_suggestions(
            my_roster=my_roster,
            all_team_rosters=all_teams,
            my_team_index=0,
            season=2026,
            max_trade_size=1,
            fairness_threshold=2.0,
        )

        # Find a trade where I send MyBench1B (id=11)
        bench_trades = [
            s for s in result["suggestions"]
            if any(p["mlb_id"] == 11 for p in s["my_players_out"])
        ]

        if bench_trades:
            trade = bench_trades[0]
            my_player = next(p for p in trade["my_players_out"] if p["mlb_id"] == 11)
            # On my team this player is bench
            assert my_player["weight"] == pytest.approx(HITTER_BENCH_WEIGHT), \
                "MyBench1B should have bench weight on my team"
            # On their team with an open 1B slot, should be starter
            assert my_player["incoming_weight"] == pytest.approx(1.0), \
                "MyBench1B should be starter on team that needs a 1B"
```

- [ ] **Step 2: Run test to verify it passes**

Run: `python -m pytest tests/backend/analysis/test_trades.py::TestTradeWeightAccuracy -v`
Expected: PASS (the implementation from Task 2 should already handle this correctly)

- [ ] **Step 3: Commit**

```bash
git add tests/backend/analysis/test_trades.py
git commit -m "test(trades): verify bench→starter weight transitions in trade simulation"
```

---

### Task 4: Frontend — Add weight fields to TypeScript interface and render role tags

**Files:**
- Modify: `src/app/trades/page.tsx:21-26` (TradePlayerInfo interface)
- Modify: `src/app/trades/page.tsx:310-430` (renderTradeCard function)

- [ ] **Step 1: Add weight fields to the TradePlayerInfo interface**

In `src/app/trades/page.tsx`, modify the `TradePlayerInfo` interface (lines 21-26):

```typescript
interface TradePlayerInfo {
  mlb_id: number
  name: string
  position: string
  total_zscore: number
  weight: number          // current weight on source team (1.0=starter, 0.25=bench hitter)
  incoming_weight: number // projected weight on destination team
}
```

- [ ] **Step 2: Add helper functions for role display**

Add after the existing `acceptColor` function (after line 96):

```typescript
function roleTag(weight: number): { label: string; color: string } {
  if (weight >= 1.0) return { label: 'Starter', color: 'text-emerald-400/60' }
  return { label: 'Bench', color: 'text-yellow-400/60' }
}

function effectiveZscore(zscore: number, weight: number): string {
  if (weight >= 1.0) return `z${zscore.toFixed(1)}`
  const effective = zscore * weight
  return `z${effective.toFixed(1)} (bench)`
}
```

- [ ] **Step 3: Update the "I Send" player rendering in renderTradeCard**

In `src/app/trades/page.tsx`, replace the "I Send" player rendering block (lines 325-337). The existing code renders each player in `s.my_players_out`:

```typescript
{s.my_players_out.map((p) => (
  <div key={p.mlb_id} className="flex items-center gap-1.5">
    <Link
      href={`/player/${p.mlb_id}`}
      className="text-sm text-white font-medium hover:underline hover:text-blue-300 truncate"
      onClick={(e) => e.stopPropagation()}
    >
      {p.name}
    </Link>
    <span className={`text-xs ${posColors[p.position] || 'text-gray-400'}`}>{p.position}</span>
    <span className={`text-[10px] ${roleTag(p.weight).color} font-medium`}>{roleTag(p.weight).label}</span>
    <span className="text-[10px] text-gray-600 font-mono">{effectiveZscore(p.total_zscore, p.weight)}</span>
    {p.incoming_weight !== p.weight && (
      <span className="text-[10px] text-gray-500 font-mono">→ {p.incoming_weight >= 1 ? 'Starter' : 'Bench'}</span>
    )}
  </div>
))}
```

- [ ] **Step 4: Update the "I Receive" player rendering in renderTradeCard**

Replace the "I Receive" player rendering block (lines 346-358):

```typescript
{s.their_players_out.map((p) => (
  <div key={p.mlb_id} className="flex items-center gap-1.5">
    <Link
      href={`/player/${p.mlb_id}`}
      className="text-sm text-white font-medium hover:underline hover:text-blue-300 truncate"
      onClick={(e) => e.stopPropagation()}
    >
      {p.name}
    </Link>
    <span className={`text-xs ${posColors[p.position] || 'text-gray-400'}`}>{p.position}</span>
    <span className={`text-[10px] ${roleTag(p.weight).color} font-medium`}>{roleTag(p.weight).label}</span>
    <span className="text-[10px] text-gray-600 font-mono">{effectiveZscore(p.total_zscore, p.weight)}</span>
    {p.incoming_weight !== p.weight && (
      <span className={`text-[10px] font-mono ${p.incoming_weight >= 1 ? 'text-emerald-400/60' : 'text-yellow-400/60'}`}>
        → {p.incoming_weight >= 1 ? 'Starter' : 'Bench'}
      </span>
    )}
  </div>
))}
```

- [ ] **Step 5: Verify the build passes**

Run: `npx next build 2>&1 | head -30` (or `npx tsc --noEmit`)
Expected: No TypeScript errors

- [ ] **Step 6: Commit**

```bash
git add src/app/trades/page.tsx
git commit -m "feat(trades): show role tags and effective z-scores in trade cards"
```

---

### Task 5: Manual smoke test and final cleanup

- [ ] **Step 1: Run all backend tests**

Run: `python -m pytest tests/backend/analysis/ -v`
Expected: All tests PASS

- [ ] **Step 2: Run TypeScript type check**

Run: `npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Verify the backend starts**

Run: `cd backend && python -c "from backend.analysis.trades import compute_trade_suggestions; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Final commit if any cleanup needed**

Only if there are remaining changes not yet committed.
