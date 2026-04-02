# Draft Model: Bench Contribution & Streaming Update — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the draft evaluation model's bench contribution rates (empirically wrong by 2-5×) and add streaming value for empty/weak bench pitcher slots, so the draft optimizer correctly values roster composition.

**Architecture:** The evaluation model operates entirely in z-score space (SGP-based). Team totals are accumulated z-scores from drafted players, weighted by bench contribution rates. Streaming value is computed by scaling replacement-level SP z-scores from the player pool by the ratio of streaming starts to projected starts, then replacing streamable bench SPs' contributions in `evaluate_draft`. The bench penalty in pick-selection (`scoring_model.py`) is then updated to match the new economics.

**Tech Stack:** Python 3.12, SQLite (player data), NumPy (z-score computation). No test framework exists — validation via sweep scripts.

---

## File Structure

| File | Role | Changes |
|------|------|---------|
| `backend/simulation/config.py` | All config defaults | Update bench rates, add streaming params |
| `backend/simulation/evaluate.py` | Post-draft evaluation | Add streaming z-score computation + application |
| `backend/simulation/rollout.py` | Rollout-based scoring | Update bench weight constants (reads from config, no code change) |
| `backend/simulation/scoring_model.py` | Pick-selection bench penalty | Rewrite bench penalty logic |
| `optimize_model.py` | Bayesian optimization | Pass config/players to evaluate_draft, add params |
| `simulate_draft.py` | CLI draft runner | Pass config/players to evaluate_draft |
| `sweep_composition.py` | Composition sweep | Pass config/players to evaluate_draft |
| `sweep_bench.py` | Bench contribution sweep | Pass config/players to evaluate_draft |
| `sweep_desperation.py` | Desperation sweep | Pass config/players to evaluate_draft |
| `sweep_mcw_strategy.py` | MCW strategy sweep | Pass config/players to evaluate_draft |

---

## Background (for context — do not skip)

A Monte Carlo daily lineup simulation empirically measured bench contribution rates:

| Role | Current Model | Empirical | Why |
|------|--------------|-----------|-----|
| Bench SP | 0.45 | **~0.95** | Projections are full-season totals already accounting for start frequency (~33 starts/162 games). With 7 pitcher slots, there's almost always room on start days. The 0.45 double-counted the start frequency penalty. |
| Bench RP | 0.15 | **~0.95** | Same logic — RP projections are season totals. RPs with 4 slots almost never get squeezed out. |
| Bench Hitter | 0.20 | **~0.25** | Hitter projections assume ~150 games. Bench hitters fill in on rest days (~25% of games). |

Streaming 3 replacement-level SPs/week through bench slots adds ~287 K and ~21.5 QS per season — far more than a drafted rank-350 SP (~80 K). This means late-round SPs destroy value by occupying a streaming slot.

### Key Technical Insight: Z-Score Scaling

The evaluation model works in z-score space (SGP-based). Z-scores are linear in both raw counting stats and IP volume:
- Counting: `zscore = raw_count / sgp_denominator × h2h_weight`
- Rate: `zscore = (league_avg - player_rate) × (IP / avg_team_IP) / sgp_denominator × h2h_weight`

Since streaming SPs have the same per-start profile as replacement-level SPs, streaming z-scores = replacement SP z-scores × (streaming_starts / replacement_SP_starts). This avoids needing to pass SGP denominators through the pipeline.

---

### Task 1: Update Bench Contribution Defaults

**Files:**
- Modify: `backend/simulation/config.py:23-28`

This is the foundation fix. The three bench contribution rates in `SimConfig` control how bench player z-scores are weighted in team totals across `draft_engine.py`, `rollout.py`, and `evaluate.py`. All three files already read these values from config — just updating the defaults fixes everything.

- [ ] **Step 1: Update the three bench contribution defaults**

In `backend/simulation/config.py`, change lines 23-28:

```python
    # Bench contribution rates (how much bench stats count toward team totals)
    # Empirically measured via full-season Monte Carlo daily lineup simulation.
    # Pitcher projections are season totals that already account for start frequency,
    # and with 7 pitcher slots there's almost always room on start days → ~95%.
    # Bench hitters only fill in on rest days → ~25%.
    PITCHER_BENCH_CONTRIBUTION: float = 0.95
    RP_BENCH_CONTRIBUTION: float = 0.95
    HITTER_BENCH_CONTRIBUTION: float = 0.25
```

- [ ] **Step 2: Verify the change compiles**

Run: `python3 -c "from backend.simulation.config import SimConfig; c = SimConfig(); print(c.PITCHER_BENCH_CONTRIBUTION, c.RP_BENCH_CONTRIBUTION, c.HITTER_BENCH_CONTRIBUTION)"`

Expected: `0.95 0.95 0.25`

- [ ] **Step 3: Commit**

```bash
git add backend/simulation/config.py
git commit -m "fix(eval): update bench contribution rates to empirical values

Bench SP: 0.45 → 0.95 (projections already account for start frequency)
Bench RP: 0.15 → 0.95 (same logic — season totals with ample slots)
Bench hitter: 0.20 → 0.25 (rest-day fill-in rate)

Based on full-season Monte Carlo daily lineup simulation results."
```

---

### Task 2: Add Streaming Config Parameters

**Files:**
- Modify: `backend/simulation/config.py`

Add config parameters that control the streaming model. These will be used by `evaluate_draft` in Task 4.

- [ ] **Step 1: Add streaming parameters to SimConfig**

In `backend/simulation/config.py`, add after the `HITTER_BENCH_CONTRIBUTION` line (after line 28):

```python
    # Streaming model — replacement-level SP streaming through bench slots
    STREAMS_PER_WEEK: int = 3              # weekly streaming transactions (sweet spot from analysis)
    STREAMING_WEEKS: int = 26              # approximate season length in weeks
    STREAMING_SP_THRESHOLD: int = 300      # overall_rank above which a bench SP is "streamable"
    STREAMING_REPL_SP_STARTS: int = 18     # replacement SP projected starts (~100 IP / 5.5)
```

- [ ] **Step 2: Verify**

Run: `python3 -c "from backend.simulation.config import SimConfig; c = SimConfig(); print(c.STREAMS_PER_WEEK, c.STREAMING_SP_THRESHOLD)"`

Expected: `3 300`

- [ ] **Step 3: Commit**

```bash
git add backend/simulation/config.py
git commit -m "feat(config): add streaming model parameters

STREAMS_PER_WEEK=3, STREAMING_SP_THRESHOLD=300, etc.
These control evaluate_draft's streaming value calculation."
```

---

### Task 3: Add `compute_streaming_zscores` Function

**Files:**
- Modify: `backend/simulation/evaluate.py`

This function computes the per-slot z-score contribution of a full season of streaming. It finds replacement-level SPs in the player pool and scales their z-scores by the ratio of streaming starts to projected starts.

- [ ] **Step 1: Add imports and the function**

In `backend/simulation/evaluate.py`, update the imports and add the function before `evaluate_draft`:

```python
"""Post-draft team evaluation: expected weekly category wins."""

from __future__ import annotations

from .config import SimConfig
from .player_pool import Player, ALL_CAT_KEYS, PITCHING_CAT_KEYS
from .scoring_model import compute_rank, win_prob_from_rank
from .draft_engine import DraftResult


def compute_streaming_zscores(players: list[Player], config: SimConfig) -> dict[str, float]:
    """Compute z-score bonus from one streaming slot over a full season.

    Finds replacement-level SPs near STREAMING_SP_THRESHOLD in the player pool,
    averages their per-category z-scores, then scales by the ratio of streaming
    starts (STREAMS_PER_WEEK × STREAMING_WEEKS) to a replacement SP's projected
    starts (STREAMING_REPL_SP_STARTS).

    Z-scores scale linearly for both counting stats (raw_count / sgp_denom) and
    rate stats ((league_avg - rate) × IP / avg_team_IP / sgp_denom) because
    streaming SPs have the same per-start profile as replacement SPs.

    Returns dict mapping cat_key → z-score (hitting cats are 0.0, SVHD is 0.0).
    """
    threshold = config.STREAMING_SP_THRESHOLD
    repl_sps = [
        p for p in players
        if p.player_type == "pitcher" and p.pitcher_role() == "SP"
        and threshold - 50 <= p.overall_rank <= threshold + 50
    ]
    result: dict[str, float] = {k: 0.0 for k in ALL_CAT_KEYS}
    if not repl_sps:
        return result

    # Average z-scores of replacement-level SPs
    for cat in PITCHING_CAT_KEYS:
        vals = [p.zscores.get(cat, 0.0) for p in repl_sps]
        result[cat] = sum(vals) / len(vals)

    # Scale: streaming adds many more starts than one replacement SP projects
    streaming_starts = config.STREAMS_PER_WEEK * config.STREAMING_WEEKS
    scale = streaming_starts / config.STREAMING_REPL_SP_STARTS

    for cat in PITCHING_CAT_KEYS:
        if cat == "zscore_svhd":
            result[cat] = 0.0  # Streamers don't earn saves/holds
        else:
            result[cat] *= scale

    return result
```

- [ ] **Step 2: Verify the function loads**

Run: `python3 -c "from backend.simulation.evaluate import compute_streaming_zscores; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Smoke-test with real data**

Run: `python3 -c "
from backend.simulation.config import SimConfig
from backend.simulation.player_pool import load_players
from backend.simulation.evaluate import compute_streaming_zscores
players = load_players()
config = SimConfig()
zs = compute_streaming_zscores(players, config)
print('Streaming z-scores per slot:')
for k, v in sorted(zs.items()):
    if v != 0.0:
        print(f'  {k}: {v:.3f}')
"`

Expected: Positive z-scores for zscore_k and zscore_qs (streaming adds K and QS). Negative z-scores for zscore_era and zscore_whip (streaming hurts rate stats — replacement-level ERA/WHIP is worse than average). zscore_svhd should be 0.0. Hitting categories should all be 0.0.

- [ ] **Step 4: Commit**

```bash
git add backend/simulation/evaluate.py
git commit -m "feat(eval): add compute_streaming_zscores function

Computes per-slot z-score contribution of streaming by scaling
replacement-level SP z-scores from the player pool by the ratio
of streaming starts to projected starts."
```

---

### Task 4: Add Streaming to `evaluate_draft`

**Files:**
- Modify: `backend/simulation/evaluate.py`

Update `evaluate_draft` to accept optional streaming z-scores and config, identify streamable bench SPs on my team, and replace their z-score contribution with streaming value.

The key logic: for each bench SP worse than `STREAMING_SP_THRESHOLD`, subtract their bench-weighted z-scores from my team totals and add the streaming z-scores. This captures the tradeoff: streaming gains massive K/QS but hurts ERA/WHIP.

Streaming is only applied to "my" team. Opponent teams' streaming is implicitly captured by the baseline — the evaluation measures the marginal value of MY streaming slots.

- [ ] **Step 1: Update `evaluate_draft` signature and add streaming logic**

Replace the entire `evaluate_draft` function in `backend/simulation/evaluate.py`:

```python
def evaluate_draft(
    result: DraftResult,
    num_teams: int,
    config: SimConfig | None = None,
    streaming_zscores: dict[str, float] | None = None,
) -> dict:
    """Evaluate a completed draft. Returns per-category win rates and total expected weekly wins.

    Unlike the draft-time model, evaluation counts ALL 10 categories (no punt skipping).

    If config and streaming_zscores are provided, replaces streamable bench SPs
    (overall_rank > STREAMING_SP_THRESHOLD) with streaming value on my team only.
    """
    # Copy my totals to avoid mutating shared state
    my_totals = dict(result.all_team_totals[result.my_slot])

    # Apply streaming: replace streamable bench SPs with streaming value
    streaming_slot_count = 0
    if config and streaming_zscores and result.bench_pitcher_count > 0:
        # Identify bench pitchers: sort my pitchers by rank, worst N are bench
        my_pitchers = sorted(
            [p for p in result.my_players if p.player_type == "pitcher"],
            key=lambda p: p.overall_rank,
        )
        bench_pitchers = my_pitchers[-result.bench_pitcher_count:]

        # Streamable = bench SPs worse than threshold
        streamable = [
            p for p in bench_pitchers
            if p.pitcher_role() == "SP"
            and p.overall_rank > config.STREAMING_SP_THRESHOLD
        ]
        streaming_slot_count = len(streamable)

        for sp in streamable:
            bench_weight = config.PITCHER_BENCH_CONTRIBUTION
            for cat_key in PITCHING_CAT_KEYS:
                # Remove this bench SP's weighted contribution
                my_totals[cat_key] -= sp.zscores.get(cat_key, 0.0) * bench_weight
                # Add streaming z-scores for this slot
                my_totals[cat_key] += streaming_zscores.get(cat_key, 0.0)

    cat_win_probs: dict[str, float] = {}
    for cat_key in ALL_CAT_KEYS:
        other_vals = [
            result.all_team_totals[t][cat_key]
            for t in range(num_teams)
            if t != result.my_slot
        ]
        other_vals.sort(reverse=True)
        rank = compute_rank(my_totals[cat_key], other_vals)
        cat_win_probs[cat_key] = win_prob_from_rank(rank, num_teams)

    expected_wins = sum(cat_win_probs.values())

    # Count hitters vs pitchers
    hitter_count = sum(1 for p in result.my_players if p.player_type == "hitter")
    pitcher_count = sum(1 for p in result.my_players if p.player_type == "pitcher")

    # First pitcher pick round
    first_pitcher_round = None
    for i, p in enumerate(result.my_players):
        if p.player_type == "pitcher":
            first_pitcher_round = i + 1  # 1-indexed
            break

    return {
        "expected_wins": expected_wins,
        "cat_win_probs": cat_win_probs,
        "hitter_count": hitter_count,
        "pitcher_count": pitcher_count,
        "first_pitcher_round": first_pitcher_round,
        "bench_pitcher_count": result.bench_pitcher_count,
        "sp_count": result.sp_count,
        "rp_count": result.rp_count,
        "streaming_slot_count": streaming_slot_count,
    }
```

- [ ] **Step 2: Verify it compiles (backward-compatible — config/streaming are optional)**

Run: `python3 -c "from backend.simulation.evaluate import evaluate_draft; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/simulation/evaluate.py
git commit -m "feat(eval): add streaming value to evaluate_draft

For my team, identifies bench SPs worse than STREAMING_SP_THRESHOLD,
removes their bench-weighted z-scores, and adds streaming z-scores.
Backward-compatible: config and streaming_zscores are optional params."
```

---

### Task 5: Update All Callers of `evaluate_draft`

**Files:**
- Modify: `sweep_composition.py`
- Modify: `sweep_bench.py`
- Modify: `sweep_desperation.py`
- Modify: `sweep_mcw_strategy.py`
- Modify: `simulate_draft.py`
- Modify: `optimize_model.py`

Each caller needs to:
1. Compute streaming z-scores once (before the simulation loop)
2. Pass `config` and `streaming_zscores` to `evaluate_draft`

The pattern is identical for all callers. I'll show each file's changes explicitly.

- [ ] **Step 1: Update `sweep_composition.py`**

In `sweep_composition.py`, add the import and update `run_config`:

At line 18, change:
```python
from backend.simulation.evaluate import evaluate_draft
```
to:
```python
from backend.simulation.evaluate import evaluate_draft, compute_streaming_zscores
```

Update the `run_config` function to compute streaming z-scores and pass them through:

```python
def run_config(
    label: str,
    target_sp: int | None,
    target_rp: int | None,
    max_hitters: int | None,
    players: list,
    num_sims: int,
    seed: int | None,
    num_teams: int,
) -> list[dict]:
    config = SimConfig(TARGET_SP=target_sp, TARGET_RP=target_rp, MAX_HITTERS=max_hitters)
    streaming_zscores = compute_streaming_zscores(players, config)
    sims_per_slot = num_sims // num_teams
    results: list[dict] = []
    rng = random.Random(seed)

    for slot in range(num_teams):
        for _ in range(sims_per_slot):
            draft = simulate_draft(players, slot, config, rng)
            ev = evaluate_draft(draft, num_teams, config=config, streaming_zscores=streaming_zscores)
            ev["my_slot"] = slot
            results.append(ev)

    return results
```

- [ ] **Step 2: Update `sweep_bench.py`**

In `sweep_bench.py`, add the import at line 17:

```python
from backend.simulation.evaluate import evaluate_draft, compute_streaming_zscores
```

Find the simulation loop (around line 40-52). Before the loop, add streaming computation. The existing code creates `config` (or uses default `SimConfig()`). After config creation, add:

```python
    streaming_zscores = compute_streaming_zscores(players, config)
```

Then update the `evaluate_draft` call (around line 49):

```python
                ev = evaluate_draft(draft, num_teams, config=config, streaming_zscores=streaming_zscores)
```

- [ ] **Step 3: Update `sweep_desperation.py`**

In `sweep_desperation.py`, add the import at line 28:

```python
from backend.simulation.evaluate import evaluate_draft, compute_streaming_zscores
```

Before the simulation loop, compute streaming z-scores from the config used in that sweep. Each config variant creates its own `SimConfig` — compute `streaming_zscores = compute_streaming_zscores(players, config)` after each config is created, and pass to `evaluate_draft`:

```python
            ev = evaluate_draft(draft, num_teams, config=config, streaming_zscores=streaming_zscores)
```

- [ ] **Step 4: Update `sweep_mcw_strategy.py`**

In `sweep_mcw_strategy.py`, add the import at line 20:

```python
from backend.simulation.evaluate import evaluate_draft, compute_streaming_zscores
```

Before the simulation loop, after config creation, add:

```python
    streaming_zscores = compute_streaming_zscores(players, config)
```

Update the `evaluate_draft` call (around line 59):

```python
                ev = evaluate_draft(draft, num_teams, config=config, streaming_zscores=streaming_zscores)
```

- [ ] **Step 5: Update `simulate_draft.py`**

In `simulate_draft.py`, add the import at line 24:

```python
from simulation.evaluate import evaluate_draft, compute_streaming_zscores
```

Note: `simulate_draft.py` uses `from simulation.` (not `from backend.simulation.`) because it runs from the `backend/` directory. Check the existing import style and match it.

Before the simulation loop, after loading players and creating config:

```python
    streaming_zscores = compute_streaming_zscores(players, config)
```

Update the `evaluate_draft` call (around line 56):

```python
            evaluation = evaluate_draft(draft_result, num_teams, config=config, streaming_zscores=streaming_zscores)
```

- [ ] **Step 6: Update `optimize_model.py`**

In `optimize_model.py`, add the import at line 31:

```python
from simulation.evaluate import evaluate_draft, compute_streaming_zscores
```

In the `run_sims` function, compute streaming z-scores once before the loop:

```python
def run_sims(
    players: list[Player],
    config: SimConfig,
    n_sims_per_slot: int,
    seed: int,
    keepers: list[KeeperEntry] | None = None,
) -> list[dict]:
    num_teams = config.NUM_TEAMS
    streaming_zscores = compute_streaming_zscores(players, config)
    results: list[dict] = []
    rng = random.Random(seed)
    for slot in range(num_teams):
        for _ in range(n_sims_per_slot):
            sim_seed = rng.randint(0, 2**31)
            sim_rng = random.Random(sim_seed)
            draft_result = simulate_draft(players, slot, config, sim_rng, keepers=keepers)
            evaluation = evaluate_draft(draft_result, num_teams, config=config, streaming_zscores=streaming_zscores)
            evaluation["my_slot"] = slot
            results.append(evaluation)
    return results
```

- [ ] **Step 7: Verify all scripts still load**

Run each to confirm no import errors:

```bash
python3 -c "import sweep_composition" && \
python3 -c "import sweep_bench" && \
python3 -c "import sweep_mcw_strategy" && \
cd backend && python3 -c "import simulate_draft" && cd .. && \
cd backend && python3 -c "import optimize_model" && cd ..
```

Expected: No errors. (Some scripts use relative imports from `backend/`, adjust `cd` as needed.)

- [ ] **Step 8: Commit**

```bash
git add sweep_composition.py sweep_bench.py sweep_desperation.py sweep_mcw_strategy.py simulate_draft.py optimize_model.py
git commit -m "feat(eval): pass streaming zscores through all evaluate_draft callers

Each caller now computes streaming z-scores once before the sim loop
and passes config + streaming_zscores to evaluate_draft."
```

---

### Task 6: Validate Phase 1+2 with Composition Sweep

**Files:**
- None (read-only validation)

Run the composition sweep before and after changes to measure impact.

- [ ] **Step 1: Run baseline sweep (before changes were committed, use git stash if needed, or compare against prior output)**

If you haven't already captured baseline numbers, note the current `sweep_composition.py` output from the last run. If not available, this step documents expectations.

Expected baseline (approximate from prior runs):
- Unconstrained: ~5.2-5.4 wins/week
- Best config typically has 12-14 hitters

- [ ] **Step 2: Run the sweep with new model**

Run: `python3 sweep_composition.py --sims 200 --seed 42`

Expected changes vs baseline:
- **Higher absolute win numbers** (bench pitchers now contribute ~95% instead of ~45%, so teams are stronger)
- **Streaming slots should appear** in the output (the new `streaming_slot_count` field)
- **Optimal composition may shift** toward fewer drafted pitchers since streaming fills the gap

- [ ] **Step 3: Verify streaming slots are being counted**

Run: `python3 -c "
import random
from backend.simulation.config import SimConfig
from backend.simulation.player_pool import load_players
from backend.simulation.draft_engine import simulate_draft
from backend.simulation.evaluate import evaluate_draft, compute_streaming_zscores

players = load_players()
config = SimConfig()
streaming_zscores = compute_streaming_zscores(players, config)
rng = random.Random(42)
draft = simulate_draft(players, 0, config, rng)
ev = evaluate_draft(draft, 10, config=config, streaming_zscores=streaming_zscores)
print(f'Streaming slots: {ev[\"streaming_slot_count\"]}')
print(f'Bench pitchers: {ev[\"bench_pitcher_count\"]}')
print(f'Expected wins: {ev[\"expected_wins\"]:.3f}')
"`

Expected: `streaming_slot_count` > 0 (most drafts produce some bench SPs worse than rank 300).

- [ ] **Step 4: Commit validation notes**

No code changes needed. If the numbers look wrong, debug before proceeding.

---

### Task 7: Fix Pick-Selection Bench Penalty

**Files:**
- Modify: `backend/simulation/scoring_model.py:648-657`

The bench penalty in `full_player_score()` needs to reflect the new economics:
- First 2-3 bench pitchers: minimal penalty (they contribute ~95% of stats)
- Beyond 3 bench pitchers: steep penalty (slot is better used for streaming — streaming one slot adds ~280 K worth of z-score value)
- Bench hitters: heavier penalty (they lose ~75% of value)

- [ ] **Step 1: Update the bench penalty block**

In `backend/simulation/scoring_model.py`, replace lines 648-657:

```python
    # Bench penalty — pitcher-aware with streaming economics
    # Bench pitchers contribute ~95% of stats, so first few get minimal penalty.
    # Beyond 3 bench pitchers, the slot is more valuable for streaming
    # (streaming one slot adds ~280K worth of z-score value per season).
    if has_starting_need == 0 and draft_progress > 0.15:
        if player.player_type == "pitcher":
            if bench_pitcher_count < 3:
                # First 3 bench pitchers: light penalty (high contribution rate)
                score *= max(0.80, 1 - draft_progress * 0.15)
            else:
                # Beyond 3: steep penalty (streaming slot is more valuable)
                score *= max(0.15, 1 - draft_progress * 0.85)
        else:
            # Bench hitters lose ~75% of value
            score *= max(0.25, 1 - draft_progress * config.BENCH_PENALTY_RATE)
```

- [ ] **Step 2: Verify it compiles**

Run: `python3 -c "from backend.simulation.scoring_model import full_player_score; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/simulation/scoring_model.py
git commit -m "fix(scoring): update bench penalty for streaming economics

First 3 bench pitchers: light penalty (95% contribution rate).
Beyond 3: steep penalty (slot better used for streaming ~280K/season).
Bench hitters: heavier penalty reflecting ~75% value loss."
```

---

### Task 8: Validate Phase 3 with Composition Sweep

**Files:**
- None (read-only validation)

- [ ] **Step 1: Run the sweep**

Run: `python3 sweep_composition.py --sims 200 --seed 42`

Compare to Task 6 output. Expected:
- Slight shift in optimal composition (the draft should draft fewer late-round SPs now because the bench penalty beyond 3 is steeper)
- Expected wins should be similar or slightly higher (better composition decisions)
- `bench_pitcher_count` in unconstrained config should be lower than before

- [ ] **Step 2: Sanity check a single draft**

Run: `python3 -c "
import random
from backend.simulation.config import SimConfig
from backend.simulation.player_pool import load_players
from backend.simulation.draft_engine import simulate_draft
from backend.simulation.evaluate import evaluate_draft, compute_streaming_zscores

players = load_players()
config = SimConfig()
streaming_zscores = compute_streaming_zscores(players, config)
rng = random.Random(42)
draft = simulate_draft(players, 0, config, rng)
ev = evaluate_draft(draft, 10, config=config, streaming_zscores=streaming_zscores)
print(f'Hitters: {ev[\"hitter_count\"]}, Pitchers: {ev[\"pitcher_count\"]}')
print(f'SPs: {ev[\"sp_count\"]}, RPs: {ev[\"rp_count\"]}')
print(f'Bench pitchers: {ev[\"bench_pitcher_count\"]}, Streaming slots: {ev[\"streaming_slot_count\"]}')
print(f'Expected wins: {ev[\"expected_wins\"]:.3f}')
for cat, prob in sorted(ev[\"cat_win_probs\"].items()):
    print(f'  {cat}: {prob:.3f}')
"`

Check that the draft produces a reasonable composition (12-14 hitters, reasonable SP/RP split, some streaming slots).

---

### Task 9: Add Streaming Params to Optimizer Search Space

**Files:**
- Modify: `optimize_model.py:70-80`

Add `STREAMS_PER_WEEK` and `STREAMING_SP_THRESHOLD` to the Optuna search space so the optimizer can find the best streaming configuration.

- [ ] **Step 1: Update the `objective` function's config construction**

In `optimize_model.py`, update the `SimConfig` construction in `objective()` (around line 70):

```python
    config = SimConfig(
        MCW_WEIGHT=trial.suggest_float("MCW_WEIGHT", 4.0, 24.0),
        VONA_WEIGHT_MCW=trial.suggest_float("VONA_WEIGHT_MCW", 0.0, 4.0),
        VONA_WEIGHT_BPA=trial.suggest_float("VONA_WEIGHT_BPA", 0.0, 2.0),
        URGENCY_WEIGHT_MCW=trial.suggest_float("URGENCY_WEIGHT_MCW", 0.0, 2.0),
        URGENCY_WEIGHT_BPA=trial.suggest_float("URGENCY_WEIGHT_BPA", 0.0, 1.0),
        AVAILABILITY_DISCOUNT=trial.suggest_float("AVAILABILITY_DISCOUNT", 0.0, 1.0),
        BENCH_PENALTY_RATE=trial.suggest_float("BENCH_PENALTY_RATE", 0.2, 1.0),
        CONFIDENCE_START=trial.suggest_int("CONFIDENCE_START", 0, 60),
        CONFIDENCE_END=trial.suggest_int("CONFIDENCE_END", 40, 160),
        STREAMS_PER_WEEK=trial.suggest_int("STREAMS_PER_WEEK", 0, 6),
        STREAMING_SP_THRESHOLD=trial.suggest_int("STREAMING_SP_THRESHOLD", 200, 400),
    )
```

- [ ] **Step 2: Log streaming slot counts in trial attributes**

In `optimize_model.py`, after the existing `trial.set_user_attr` calls (around line 95), add:

```python
    streaming = [r.get("streaming_slot_count", 0) for r in results]
    trial.set_user_attr("avg_streaming_slots", sum(streaming) / len(streaming))
```

- [ ] **Step 3: Verify it loads**

Run: `cd backend && python3 -c "import optimize_model; print('OK')" && cd ..`

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add optimize_model.py
git commit -m "feat(optimize): add streaming params to Optuna search space

STREAMS_PER_WEEK (0-6) and STREAMING_SP_THRESHOLD (200-400) are now
tunable. Also logs avg_streaming_slots per trial for analysis."
```

---

### Task 10: Run Optimization

**Files:**
- None (execution only)

- [ ] **Step 1: Run a quick optimization to verify the pipeline works**

Run: `cd backend && python3 optimize_model.py --trials 20 --sims-per-trial 10 --seed 42 && cd ..`

Expected: Completes without errors. Check that:
- `avg_streaming_slots` appears in trial attributes
- `STREAMS_PER_WEEK` and `STREAMING_SP_THRESHOLD` appear in best params
- Expected wins are in a reasonable range (5-6 wins/week)

- [ ] **Step 2: Run full optimization**

Run: `cd backend && python3 optimize_model.py --trials 200 --sims-per-trial 20 --seed 42 && cd ..`

This takes a while. Expected outcome:
- Optimizer finds `STREAMS_PER_WEEK` ≈ 2-4 (sweet spot from empirical analysis)
- `STREAMING_SP_THRESHOLD` ≈ 250-350
- Overall expected wins should increase vs. pre-change baseline
- Average pitcher count per draft should decrease (streaming fills the gap)

- [ ] **Step 3: Update config defaults with optimized values**

After the optimization finishes, update `SimConfig` defaults with the best parameters found. Update ALL tuned parameters, not just the new streaming ones.

- [ ] **Step 4: Final validation sweep**

Run: `python3 sweep_composition.py --sims 500 --seed 42`

Compare against baseline. The optimized model should show:
- Higher expected wins across most compositions
- The optimal composition should have fewer total pitchers
- K and QS win rates should be higher (streaming adds massive counting stats)
- ERA/WHIP win rates may be slightly lower (streaming adds mediocre-rate IP)

- [ ] **Step 5: Commit optimized defaults**

```bash
git add backend/simulation/config.py
git commit -m "feat(config): update defaults with optimized coefficients

Post-streaming optimization results from 200 trials × 20 sims."
```

---

## Execution Notes

**Execution order matters.** Tasks 1-6 form Phase 1+2 (evaluation model fixes). Tasks 7-8 are Phase 3 (pick selection). Tasks 9-10 are Phase 4 (re-tuning). Each phase depends on the prior one being in place.

**If streaming z-scores look wrong** (Task 3 Step 3): Check that replacement-level SPs exist in the rank 250-350 range of the player pool. If the pool has few SPs in that range, widen the window in `compute_streaming_zscores` or adjust `STREAMING_SP_THRESHOLD`.

**If expected wins drop after streaming** (Task 6): The ERA/WHIP penalty from streaming may outweigh K/QS gains. This means either:
1. The streaming threshold is too aggressive (too many bad SPs getting streamed)
2. The scaling factor is too high
3. This is correct — and the optimizer in Task 9 will find the right balance

**The exact bench penalty coefficients in Task 7** (0.80, 0.15, 0.85, 0.25) are educated guesses. They will be refined by the optimizer in Task 9. Don't spend time hand-tuning them.
