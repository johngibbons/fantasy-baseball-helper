# Scoring Model Improvements

Identified gaps and potential fixes, ordered by estimated impact.

---

## 1. MCW should weight lock/target categories differently

**Status**: Investigated — no change needed

**Problem**: The `detectStrategy` function classifies categories as lock/target/neutral/punt, but only "punt" changes MCW behavior (excluded from calculation). Lock and target are display-only labels.

If you're rank 2 in R with a 1.5 z-score gap below, MCW still gives full credit for players that improve R even though that category is essentially locked. The model will invest in a dominated category when the same player's VONA or normalized value makes them attractive for other reasons.

**Proposed fix**: Apply MCW multipliers by strategy:
- **Lock**: 0.5x MCW weight (diminishing returns — you're already winning)
- **Target**: 1.25x MCW weight (this is where marginal improvement flips matchups)
- **Neutral**: 1.0x (unchanged)
- **Punt**: 0x (unchanged)

**Sweep results** (seed=42):

| Lock | Target | 200 sims | 1000 sims |
|------|--------|----------|-----------|
| 1.0  | 1.0    | 8.89     | 8.87      |
| 0.5  | 1.25   | 8.91     | 8.87      |
| 0.5  | 1.0    | 8.91     | —         |
| 1.0  | 1.5    | 8.87     | —         |
| 0.25 | 1.5    | 8.86     | —         |

The proposed config (0.5/1.25) showed a directional advantage at 200 sims but converged to identical 8.87 at 1000 sims. The lock discount alone doesn't help at scale, and boosting target weight slightly hurts. MCW's fractional gap-closing credit already implicitly handles strategy — explicit multipliers add noise without improving outcomes.

**Conclusion**: No change to defaults. Infrastructure remains in place (`LOCK_MCW_WEIGHT`, `TARGET_MCW_WEIGHT` in SimConfig) for future experimentation.

**Files**: `src/lib/draft-optimizer.ts` (`computeMCW`), `backend/simulation/scoring_model.py` (backend MCW), `backend/simulation/config.py`

---

## 2. Urgency weight drops too low at full MCW confidence

**Status**: Investigated — no change needed

**Problem**: In the MCW formula, urgency weight is 0.02. In the BPA formula, it's 0.55. As confidence ramps to 1.0 (by round 8), urgency nearly disappears from the score.

A player who will definitely be gone before your next pick gets almost no urgency credit in mid-to-late rounds. VONA partially compensates (positional scarcity), but doesn't capture individual player urgency. You could have a mid-MCW player with elite efficiency who's a "now or never" pick, and the model undervalues it.

**Proposed fix**: Increase urgency weight in the MCW formula from 0.02 to 0.08-0.12. This keeps urgency meaningful at full confidence without letting it dominate MCW.

**Sweep results** (seed=42):

| Weight | 100 sims | 1000 sims |
|--------|----------|-----------|
| 0.02   | 8.93     | 8.87      |
| 0.06   | 8.94     | 8.86      |
| 0.10   | 8.92     | —         |
| 0.14   | 8.91     | —         |

At 1000 sims (SE ~0.019), the 0.01 difference between 0.02 and 0.06 is ~0.5 standard errors — not statistically significant. The direction even flipped between the 100-sim and 1000-sim runs. Window VONA likely already captures most of the scarcity signal that urgency was meant to address.

**Conclusion**: Current value of 0.02 is fine. No code change.

**Files**: `src/lib/draft-optimizer.ts` (`computeDraftScore`), `src/app/draft/page.tsx`, `backend/simulation/scoring_model.py`

---

## 3. VONA uses primary position only (ignores multi-eligibility)

**Status**: Done (committed `430103f`)

**Problem**: VONA is calculated at `getPositions()[0]` — the first listed position. A C/1B player gets VONA at C only. If C is deep but 1B is thin, the model misses that this player provides scarce 1B eligibility.

This systematically undervalues multi-position players' scarcity contribution. Especially affects C/1B, 2B/SS, and OF-eligible players who also qualify at a thin position.

**Fix applied**: Both backend and frontend now compute VONA at every eligible position and take the max. Extracted `_vona_at_position()` and `_window_vona_at_position()` helpers in `scoring_model.py`. Frontend `vonaMap` useMemo extracts `windowVonaAtPosition()` helper and iterates all positions.

**Files changed**: `backend/simulation/scoring_model.py`, `src/app/draft/page.tsx`

**Validation**: 50-sim run with window VONA: 8.98 expected wins, no regression. 10-sim quick check also clean.

---

## 4. Possible double-counting of category correlation discounts

**Status**: Investigated — no change needed

**Problem**: H2H correlation weights discount R/TB/RBI by ~4-8% in the valuation stage. This permanently reduces those players' Value and normalized value. Then MCW measures actual win probability changes per category, which implicitly accounts for correlation (winning R makes winning TB/RBI more likely in the same matchup).

During BPA-dominated early rounds (1-4), the correlation discount is baked into normalized value. Power hitters strong in R/TB/RBI get discounted in value AND tend to cluster together (lowering VONA). The effects compound.

**Sweep results** (200 sims, seed=42):

| H2H Scale | Description | Wins | StdDev |
|-----------|-------------|------|--------|
| 1.0 | Current weights | 8.89 | 0.59 |
| 0.5 | Halved | 8.90 | 0.61 |
| 0.0 | Removed entirely | 8.91 | 0.60 |

Category win rates and draft composition are virtually identical across all three configs. The double-counting is real in theory but negligible in practice — MCW handles correlation at draft time, making the valuation-stage discount redundant but not harmful.

**Conclusion**: No change needed. The weights aren't helping, but removing them doesn't help either. Not worth the disruption of regenerating all z-scores.

**Infrastructure added**: `rescale_h2h_weights()` in `player_pool.py` and `--h2h-weight-scale` CLI flag in `simulate_draft.py` for future testing.

**Files**: `backend/analysis/zscores.py` (`H2H_CATEGORY_WEIGHTS`), `backend/simulation/player_pool.py` (`rescale_h2h_weights`)

---

## 5. Recommendation zone threshold doesn't adapt to score distribution

**Status**: Done

**Problem**: The zone is defined as all players within 75% of the top score. If the #1 player is a massive outlier (score 10, next is 6), the zone is just 1 player. If scores are tightly clustered (top 20 all 5.0-5.5), the zone could be huge.

**Fix applied**: Replaced fixed 75% threshold with stddev-based adaptive zone. Computes stddev of the top ~15 scores, sets threshold at `topScore - stddev`. Zone size clamped to [3, 8] players. Tight clusters produce narrow zones; spread-out scores produce wider zones. Ties at the boundary are included.

**Files changed**: `src/app/draft/page.tsx` (`scoreRankMap` useMemo)

**Validation**: Visual inspection during mock drafts. TypeScript compiles clean (no new errors).

---

## 6. Opponent ADP sigma should vary by draft position

**Status**: Investigated — no change, variable sigma hurts

**Problem**: The opponent model and availability predictor both use a fixed sigma of 18 picks. In reality, early picks have less variance (consensus top 10) and late picks have much more (personal preference dominates).

**Proposed fix**: Use pick-dependent sigma: `sigma = 10 + 0.1 * ADP`. This gives sigma ~11 for ADP 10, ~18 for ADP 80, ~25 for ADP 150.

**Sweep results** (200 sims, seed=42):

| Sigma | Wins | StdDev |
|-------|------|--------|
| Fixed 18 (current) | 8.89 | 0.59 |
| Variable (10+0.1*ADP) | 8.77 | 0.63 |

Variable sigma is significantly worse (−0.12 wins, ~2.9 SE). Tighter sigma for early picks makes the simulated opponents more "correct" (closer to consensus), reducing exploitable variance. Higher sigma for late picks adds noise to our VONA/availability estimates. The fixed sigma=18 is a better model for our purposes — it represents realistic opponent variance across the full draft.

**Conclusion**: No change. Keep fixed sigma=18.

**Infrastructure added**: `USE_VARIABLE_SIGMA` config flag, `variable_adp_sigma()` helper in `scoring_model.py`, `--variable-sigma` CLI flag. Available for future experimentation with different formulas.

**Files**: `backend/simulation/config.py`, `backend/simulation/draft_engine.py`, `backend/simulation/scoring_model.py`

---

## 7. Roster fit is binary — no slot scarcity gradient

**Status**: Investigated — no change needed

**Problem**: Roster fit is 1 if the player fills any starting slot, 0 otherwise. No distinction between filling the last C slot (extremely constrained, only ~12 draftable catchers) vs. filling a UTIL slot (very flexible, anyone can go there).

**Proposed fix**: Weight roster fit by remaining capacity scarcity: `rosterFit = 1 / remaining_capacity` of the most constrained eligible slot. Last C slot → 1.0, one of 3 OF slots → 0.33.

**Sweep results** (200 sims, seed=42):

| Roster Fit | Wins | StdDev |
|------------|------|--------|
| Binary (current) | 8.89 | 0.59 |
| Scarcity gradient | 8.89 | 0.59 |

Identical outcomes. The `roster_fit * draft_progress` term is a small component of the total score, and VONA already captures positional scarcity more effectively. The gradient is more theoretically correct but doesn't move the needle.

**Conclusion**: No change to defaults. Infrastructure remains (`USE_SLOT_SCARCITY` flag, `slot_scarcity()` method on `RosterState`).

**Files**: `backend/simulation/roster.py`, `backend/simulation/config.py`, `backend/simulation/draft_engine.py`, `backend/simulation/scoring_model.py`

---

## 8. BPA formula overweights urgency in early rounds

**Status**: Investigated — no change, scaling hurts significantly

**Problem**: The BPA formula is `normalizedValue + VONA * 0.42 + urgency * 0.55`. Urgency 15 adds +8.25, which can override raw talent. In rounds 1-3 when BPA dominates, this could push the model to reach for "about to be taken" players when the talent pool is still deep and most top players will come back around.

**Proposed fix**: Scale urgency in the BPA formula by draft progress: `urgency * 0.55 * draftProgress`. This makes urgency less important early (when pool is deep) and more important later.

**Sweep results** (200 sims, seed=42):

| BPA Urgency | Wins | StdDev |
|-------------|------|--------|
| Full (current) | 8.89 | 0.59 |
| Scaled by progress | 8.57 | 0.75 |

Scaling BPA urgency is significantly worse (−0.32 wins, ~7.6 SE). Suppressing urgency in early rounds causes the model to miss "now or never" players who drop past ADP. The resulting drafts pick pitchers too early (round 1.5 vs 2.1), over-draft hitters (15.6 vs 15.1), and category win rates drop across the board (RBI .70 vs .81).

**Conclusion**: BPA urgency at 0.55 is calibrated correctly. Early-round urgency signals are valuable, not noise.

**Infrastructure added**: `SCALE_BPA_URGENCY` config flag, `--scale-bpa-urgency` CLI flag.

**Files**: `backend/simulation/scoring_model.py`, `backend/simulation/config.py`
