# Draft Model: Bench Contribution & Streaming Update

## Background & Findings

A full-season Monte Carlo daily lineup simulation (`sweep_bench_contributions.py`) was built to empirically measure bench player contribution rates. Key findings:

### Bench Contribution Rates (Empirical vs Current Model)

| Role | Current Model | Empirical | Why |
|------|--------------|-----------|-----|
| Bench SP | 0.45 | **~0.95** | Projections are full-season totals that already account for start frequency (~33 starts/162 games). With 7 pitcher slots (SP×3, RP×2, P×2), there's almost always room on start days. The 0.45 was wrong — it double-counted the start frequency penalty. |
| Bench RP | 0.15 | **~0.95** | Same logic — RP projections are season totals. RPs with 4 roster slots almost never get squeezed out. |
| Bench Hitter | 0.20 | **~0.25** | Hitter projections assume ~150 games. Bench hitters only fill in on rest days (~25% of games). Slightly higher than 0.20 because some bench hitters (like multi-position players) get more playing time. |

### Streaming Value

With 10 add/drop transactions per week, streaming replacement-level SPs through bench pitcher slots generates massive pitching value:

| Streams/week | Extra K | Extra QS | ERA impact | WHIP impact |
|-------------|---------|----------|------------|-------------|
| 3 | +287 | +21.5 | +0.38 | +0.06 |
| 6 | +380 | +28.5 | +0.44 | +0.07 |
| 10 | +399 | +29.9 | +0.45 | +0.07 |

3 streams/week is the sweet spot — massive K/QS gain with moderate ERA/WHIP cost, leaving 7 transactions for real waiver moves.

### Implications for Draft Strategy

1. **Late-round SPs are value-destroying.** A rank-350 SP projected for ~80 K occupies a slot that streaming would fill with ~280 K. The draft should stop drafting SPs once anchored starters are covered.
2. **Bench hitters are expensive.** They lose ~75% of their projected value. The starter/bench gap is enormous for hitters but nearly zero for pitchers.
3. **The optimal composition is ~12 hitters, ~10 drafted pitchers, 2-3 streaming slots left open.**

---

## What Needs to Change

### Phase 1: Fix Evaluation Model (bench contribution rates)

**Problem:** The evaluation model computes team totals using wrong bench contribution rates. Since `optimize_model.py` maximizes expected wins from these evaluations, all coefficient tuning is optimizing toward a wrong target.

**Files to modify:**
- `backend/simulation/config.py` — Update default bench contribution rates
- `backend/simulation/draft_engine.py` — Bench contributions applied at lines 147-158 and 365-376
- `backend/simulation/rollout.py` — Bench contributions at lines 145-151

**Changes:**
```python
# config.py — update defaults
PITCHER_BENCH_CONTRIBUTION: float = 0.95  # was 0.45
RP_BENCH_CONTRIBUTION: float = 0.95       # was 0.15
HITTER_BENCH_CONTRIBUTION: float = 0.25   # was 0.20
```

No code changes needed in `draft_engine.py` or `rollout.py` — they already read these values from config. Just updating the defaults fixes the evaluation.

**Validation:** Run `sweep_composition.py` before and after the change. The optimal composition should shift toward fewer pitchers (since bench pitchers are now valued at nearly 100%, the marginal value of the Nth pitcher drops).

### Phase 2: Add Streaming Value to Evaluation

**Problem:** The evaluation model scores a draft outcome with 25 filled roster slots identically whether those slots are all drafted players or whether 2-3 are left empty for streaming. In reality, empty pitcher slots used for streaming are worth ~280 K and ~21 QS per season (at 3 streams/week).

**Files to modify:**
- `backend/simulation/evaluate.py` — Add streaming bonus to team totals for empty pitcher slots
- `backend/simulation/config.py` — Add streaming-related config parameters

**Approach:** After the draft completes, for each team, count how many pitcher roster slots are unfilled (or filled with very low-ranked SPs below a threshold). For each such "streaming slot," add replacement-level per-start stats × estimated streams/week to the team's category totals before computing win probabilities.

**New config parameters:**
```python
# Streaming model for draft evaluation
STREAMS_PER_WEEK: int = 3              # Expected streaming transactions per week
STREAMING_SP_THRESHOLD: int = 300      # Overall rank below which an SP is "streamable" (would be dropped for streaming)
# Per-start replacement-level stats (from bench_contributions.py analysis)
STREAMING_IP_PER_START: float = 5.56   # 100 IP / 18 starts
STREAMING_K_PER_START: float = 4.44    # 80 K / 18 starts
STREAMING_QS_PER_START: float = 0.33   # 6 QS / 18 starts
STREAMING_ERA: float = 4.50
STREAMING_WHIP: float = 1.35
```

**Implementation in `evaluate.py`:**
1. After computing team totals from the draft, identify streaming slots: bench pitcher slots filled by SPs ranked worse than `STREAMING_SP_THRESHOLD`, or unfilled pitcher slots
2. Compute streaming starts per season: `STREAMS_PER_WEEK × 26 weeks` (approximate season)
3. Add streaming counting stats (K, QS) to team totals
4. Blend streaming ERA/WHIP with roster ERA/WHIP (IP-weighted)
5. Then compute win probabilities as before

**Key decision:** Should ALL teams get streaming credit, or just "my" team? Recommendation: all teams, since opponents also stream. This keeps the competitive landscape accurate.

### Phase 3: Fix Pick-Selection Bench Penalty

**Problem:** The bench penalty in `scoring_model.py:full_player_score()` (lines 648-657) already differentiates pitchers and hitters, but the logic needs updating:

**Current logic:**
```python
if has_starting_need == 0 and draft_progress > 0.15:
    if player.player_type == "pitcher":
        saturation = min(1.0, bench_pitcher_count / 3)
        floor = 0.65 - saturation * 0.30
        scale = 0.35 + saturation * 0.28
        score *= max(floor, 1 - draft_progress * scale)
    else:
        score *= max(0.35, 1 - draft_progress * config.BENCH_PENALTY_RATE)
```

**Issues:**
1. The pitcher bench penalty softens for the first 3 bench pitchers (assuming streaming value), but doesn't account for the fact that bench pitchers contribute ~95% vs bench hitters at ~25%. The penalty should be MUCH lighter for pitchers.
2. After 3 bench pitchers, the penalty ramps up sharply — but it should ramp up even MORE, because those slots would be better used for streaming than for a bad drafted SP.
3. The hitter bench penalty (`BENCH_PENALTY_RATE = 0.58`) should be higher — bench hitters lose ~75% of their value.

**Proposed changes:**
```python
if has_starting_need == 0 and draft_progress > 0.15:
    if player.player_type == "pitcher":
        # First 3 bench pitchers: minimal penalty (they contribute ~95% of their stats)
        # After that: steep penalty (slot is better used for streaming)
        if bench_pitcher_count < 3:
            score *= max(0.80, 1 - draft_progress * 0.15)
        else:
            # Streaming slot is worth ~280K — this SP needs to beat that
            score *= max(0.15, 1 - draft_progress * 0.85)
    else:
        # Bench hitters lose ~75% of value
        score *= max(0.25, 1 - draft_progress * config.BENCH_PENALTY_RATE)
```

The exact coefficients should be re-tuned by `optimize_model.py` after Phases 1 and 2 are in place.

### Phase 4: Re-tune Model Coefficients

**Problem:** With the evaluation model now correctly valuing bench contributions and streaming, the pick-selection coefficients (MCW_WEIGHT, VONA weights, BENCH_PENALTY_RATE, etc.) need re-optimization.

**File:** `optimize_model.py`

**Changes:**
1. Add `BENCH_PENALTY_RATE` to the Optuna search space (already there, range 0.2-1.0)
2. Consider adding the pitcher bench penalty parameters to the search space (the saturation ramp coefficients)
3. Run optimization: `python3 optimize_model.py --trials 200 --sims-per-trial 20 --seed 42 --validate 500`
4. Compare results to pre-change baseline

**Expected outcome:** The optimizer should find:
- Lower `BENCH_PENALTY_RATE` for hitters (or the same — it's already being tuned)
- The draft should naturally draft fewer total pitchers because streaming fills the gap
- Expected wins should increase because the model is now optimizing toward a more accurate evaluation

---

## Execution Order

1. **Phase 1** first — fixes the foundation (evaluation). Quick change, just update 3 constants.
2. **Phase 2** next — adds streaming to evaluation. This is the biggest code change.
3. **Phase 3** — fix pick selection. Benefits from Phases 1-2 being in place.
4. **Phase 4** — re-tune. Must come last since it depends on all other changes.

Run `sweep_composition.py --sims 500 --seed 42` after each phase to see how the optimal composition shifts.

---

## Key Files Reference

| File | Role | Lines of Interest |
|------|------|-------------------|
| `backend/simulation/config.py` | All config defaults | Lines 23-28 (bench contribution rates) |
| `backend/simulation/draft_engine.py` | Applies bench weights to team totals during draft | Lines 147-158 (keepers), 365-376 (draft picks) |
| `backend/simulation/rollout.py` | Applies bench weights in rollout evaluation | Lines 145-151 |
| `backend/simulation/evaluate.py` | Scores draft outcomes (expected wins) | Full file — add streaming here |
| `backend/simulation/scoring_model.py` | Pick selection scoring with bench penalty | Lines 648-657 (bench penalty) |
| `optimize_model.py` | Bayesian optimization of coefficients | Lines 70-80 (search space) |
| `sweep_composition.py` | Tests different roster compositions | Full file — use for validation |
| `sweep_bench_contributions.py` | The bench contribution simulation we built | Full file — source of empirical data |
| `backend/analysis/bench_contributions.py` | Core simulation engine with streaming | Full file — `replacement_level_per_start_stats()` for streaming constants |

## Data From Empirical Analysis

These numbers come from running `sweep_bench_contributions.py` against the user's actual ESPN roster (league 77166, team 8) with 200 Monte Carlo iterations:

**Roster: 12 hitters, 12 pitchers (2 bench hitters, 8 bench SPs, 0 bench RPs, 4 starting RPs)**

Per-player contribution rates:
- Starting hitters (ranks 5-106): 86-100% contribution
- Bench hitters (Semien rank 124, Ward rank 95): 17-40% contribution, average 28%
- Starting RPs (ranks 24-178): 99-100% contribution
- Bench SPs (ranks 82-367): 13-21% contribution (this is START FREQUENCY, not bench penalty — projections already account for this, so effective contribution is ~95% of projected stats)

Streaming results (composition x streaming grid):
- Current roster + 0 streams: 567 K, 13.7 QS baseline
- Current roster + 3 streams: +287 K, +21.5 QS (sweet spot)
- Current roster + 10 streams: +399 K, +29.9 QS (diminishing returns, worse ERA/WHIP)
- +1 hitter / -1 pitcher changes: +1.5 R, +3.7 TB, -15 K (negligible vs streaming)
