# Scoring Model: How Player Values and Draft Scores Work

This document explains the full pipeline from raw projections to the final draft score you see in the UI.

---

## 1. Player Valuation (the "Value" column)

The **Value** column shows `total_zscore` — a player's total Standings Gain Points (SGP) above replacement level. This is computed offline by `backend/analysis/zscores.py` and stored in the `rankings` table.

### 1.1 Projection Blending

Up to 5 projection sources per player are blended into a single projection using weighted averages:

- **thebatx** (THE BAT X): 0.40 for hitters, 0.30 for pitchers
- **steamer**: 0.30 for hitters, 0.40 for pitchers
- **zips**: 0.30 for both
- **trend**: A custom projection from recent performance trends (weight 0.20)
- **statcast_adjusted**: The trend projection refined with Statcast metrics (exit velo, barrel rate, xwOBA, etc.), blended 50/50 between trend and Statcast-implied values (weight 0.40)

Since `statcast_adjusted` is derived from `trend`, including both would double-count the trend signal. When a player has a `statcast_adjusted` row, the raw `trend` row is excluded from the blend. Players without Statcast data keep the raw `trend` source instead. Weights are normalized so the sources actually present for each player sum to 1.0.

### 1.2 SGP Conversion

Raw projected stats are converted to SGP — how many standings positions a player gains you in each category. SGP denominators come from historical league standings data (average gap between adjacent teams per category), with hardcoded fallbacks if no history exists.

**Counting stats** (R, TB, RBI, SB, K, QS, SVHD):
```
SGP = projected_stat / SGP_denominator
```

**Rate stats** (OBP, ERA, WHIP) use a marginal approach:
```
SGP = (player_rate - league_average) * (player_volume / avg_team_volume) / SGP_denominator
```
This correctly accounts for volume — a pitcher with a 3.00 ERA over 200 IP helps your team ERA more than the same ERA over 80 IP.

For ERA/WHIP (inverted), the formula flips direction so that lower = more positive SGP.

### 1.3 H2H Category Correlation Weights

In H2H categories, correlated stats provide overlapping win chances. The model applies weights derived from weekly correlation matrices:

| Category | Weight | Rationale |
|----------|--------|-----------|
| R        | 0.92   | Correlated with TB, RBI |
| TB       | 0.95   | Correlated with R, RBI |
| RBI      | 0.96   | Correlated with R, TB |
| **SB**   | **1.15** | Independent — unique win source |
| OBP      | 1.02   | Moderate correlations |
| K        | 1.02   | Moderate correlations |
| QS       | 0.98   | Correlated with ERA/WHIP |
| ERA      | 0.95   | Correlated with WHIP |
| WHIP     | 0.97   | Correlated with ERA |
| **SVHD** | **1.14** | Independent — unique win source |

Net effect: SB and SVHD get ~15% boosts; the R/TB/RBI cluster gets a ~4-8% discount.

### 1.4 Playing Time Risk Discount

Players with low projected playing time receive a linear discount on counting stats only:

- **Hitters**: Full credit at 500+ PA, linear ramp below that (e.g., 300 PA = 0.60x)
- **SP**: Full credit at 140+ IP
- **RP**: Full credit at 50+ IP

Rate stats (OBP, ERA, WHIP) are NOT discounted because the marginal formula already volume-weights them.

### 1.5 SP Streaming Constraint Bonus

SPs with proj ERA <= 4.00 and proj WHIP <= 1.25 get a +0.70 SGP bonus. These are "hold-and-start" pitchers — rosterable all season without burning acquisitions. This differentiates them from similarly-valued streamers.

### 1.6 Pitcher Category Normalization

Individual pitchers contribute to 4 categories (K/QS/ERA/WHIP for SP, K/SVHD/ERA/WHIP for RP) vs 5 for hitters. Since total_zscore is a sum of per-category SGPs, hitters have a structural advantage. Pitcher totals are scaled by **5/4 = 1.25** to normalize cross-type rankings. Two-way players (e.g., Ohtani) are NOT normalized since they already span all 10 categories.

### 1.7 Replacement Level Adjustment

The final step subtracts a position-specific replacement level so that the Value column reflects value **above replacement**, not raw SGP.

**Hitters**: A greedy draft simulation assigns the best players first to their scarcest eligible slot (respecting multi-position eligibility). The last player assigned to each slot defines replacement level. A hitter baseline (total demand across all hitter slots) acts as a floor.

**Pitchers**: Replacement levels are set at rank (slot_demand * num_teams) within each pool (SP/RP), with a pitcher baseline floor that accounts for flex P slots.

### 1.8 Live Recalculation

During the draft, as players are picked, the backend re-runs the entire z-score engine with drafted players excluded (`/draft/recalculate`). This recomputes league averages, SGP values, and replacement levels against the remaining player pool. The Value column updates accordingly.

---

## 2. Draft Score (the "Score" column)

The **Score** is a composite pick recommendation that combines multiple signals. It only appears once you've set your team and the draft is underway. Computed in `src/app/draft/page.tsx`.

### 2.1 Components

#### Normalized Value (BPA baseline)
Re-standardizes each player's per-category z-scores against the **remaining available pool**:
```
normalizedValue = sum((player_zscore[cat] - mean[cat]) / stdev[cat]) for each relevant category
```
This centers the scale so that "average available player" = 0, regardless of how much talent has been drafted.

#### VONA (Value Over Next Available) — Window-Based
Measures positional scarcity using availability-weighted replacement.

For each player's primary position, collects all other available players at that position. For each alternative, computes `P(still available at my next pick)` using a normal CDF model of ADP noise (sigma = 18 picks). Then computes:

```
expected_replacement = sum(value_i * P(i is best available if we wait))
VONA = my_value - expected_replacement
```

Where `P(i is best available)` = `P(all better alternatives are gone)` * `P(i is available)`.

High VONA means "this player's position dries up fast — take them now or lose the value."

#### Urgency
How likely the player is to be picked before your next turn:
```
urgency = clamp(picks_until_mine - (ADP - current_pick), 0, 15)
```
High urgency = player's ADP suggests they'll be gone before you pick again.

#### MCW (Marginal Category Wins)
The core standings-aware signal. For each of the 10 categories:

1. Compute your current rank and win probability vs. other teams
2. Simulate adding the player's z-scores to your totals
3. Compute new rank and win probability
4. MCW for that category = `winProb_after - winProb_before`

Punted categories (max 2, detected automatically) contribute 0 MCW.

**Fractional credit**: If adding a player closes a gap to the team above without overtaking, a convex credit `(gapClosed^1.5) * 0.55 / (numTeams - 1)` is awarded. The 1.5 exponent means closing 80% of a gap is worth much more than closing 20% — reflecting that weekly H2H variance will likely complete the overtake.

#### Roster Fit
Binary: 1 if the player fills a non-bench starting slot, 0 otherwise.

### 2.2 Score Formula

Two formulas are blended based on **standings confidence** (ramps from 0 at pick 40 to 1.0 at pick 81):

**MCW-based score** (when confidence > 0 and standings data exists):
```
score = MCW * 21.0 * confidence + VONA * 0.16 + urgency * 0.02 + rosterFit * draftProgress
```

**BPA score** (early draft / fallback):
```
score = normalizedValue + VONA * 0.42 + urgency * 0.55
```

**Blended**:
```
finalScore = mcwScore * confidence + bpaScore * (1 - confidence)
```

Early in the draft (rounds 1-4), the BPA formula dominates because standings aren't meaningful yet. By mid-draft, MCW takes over and the model picks players that actually move category win probabilities.

### 2.3 Post-Score Adjustments

These are multiplicative — they scale the score down for situational reasons.

#### Bench Penalty (pitcher-aware with saturation)

When a player would only fill a bench slot (`rosterFit == 0`) and draft progress > 15%:

**Pitchers** — softer penalty for the first ~3 bench pitchers (daily league streaming value), then saturates to full penalty:
```
saturation = min(1.0, bench_pitcher_count / 3)
floor = 0.65 - saturation * 0.30    // starts at 0.65, drops to 0.35
scale = 0.35 + saturation * 0.28    // starts at 0.35, rises to 0.63
score *= max(floor, 1 - draftProgress * scale)
```

At 0 bench pitchers: penalty floor = 0.65, scale = 0.35 (mild discount)
At 3+ bench pitchers: penalty floor = 0.35, scale = 0.63 (full hitter-like penalty)

**Hitters** — full flat penalty:
```
score *= max(0.35, 1 - draftProgress * 0.63)
```

This models daily league dynamics: bench SPs have streaming value (~2 starts/week swapped in on start days) and bench RPs fill P slots most days for counting stats, while bench hitters only cover rest days (~1-2 games/week).

### 2.4 Recommendation Zone

The top-scored player defines a threshold at 75% of its score. All players within that zone are highlighted as the "recommendation zone" — any of them are defensible picks.

---

## 3. Category Strategy Detection

After 6 picks, the model classifies each category:

| Strategy | Criteria | Effect |
|----------|----------|--------|
| **Lock** | Rank <= 2 and gap below >= 1.0 z-score | Category is won; MCW credit here is less impactful |
| **Punt** | Bottom rank(s) and gap above >= 3.0-4.5 z-score | Category excluded from MCW entirely (saves resources) |
| **Target** | Rank 3-8 | Categories where marginal improvement yields the most wins |
| **Neutral** | Everything else | Normal MCW weighting |

Max 2 punts enforced. Thresholds adapt to playoff format (6/10 spots = more forgiving = harder to justify punts).

---

## 4. Team Category Totals

When computing category standings (for MCW, projected standings, and category balance displays), bench players contribute a fraction of their z-scores:

| Player Type | Bench Contribution Rate |
|-------------|------------------------|
| **Pitchers** | **0.45** (streaming SPs, daily RP swaps) |
| **Hitters** | **0.20** (rest day coverage only) |

Starters contribute at 1.0. This split was validated via simulation sweep.

---

## 5. Tier Detection

Players are grouped into tiers using gap analysis on their Value:

1. Sort available players by Value descending
2. Compute gaps between consecutive values
3. Threshold = median(gaps) + 1 * stddev(gaps)
4. Each gap above the threshold starts a new tier (max 15 tiers)

Tiers with <= 2 remaining players are marked as urgent — that tier is about to disappear.

---

## 6. Simulation Engine (Backend)

The simulation (`backend/simulation/`) runs the same scoring model through a full 25-round snake draft to validate configurations:

- **My team**: Uses the full scoring pipeline (MCW + VONA + urgency + bench penalty)
- **Opponents**: Pick by ADP + Gaussian noise (sigma=18), with a penalty for bench-only picks (+15 effective ADP)
- **Evaluation**: Post-draft, computes expected weekly category wins by ranking each team's totals

The sweep script (`sweep_bench.py`) runs hundreds of simulations across different parameter configurations to empirically validate changes.

---

## 7. Known Gaps / Areas to Evaluate

- **Opponent model is ADP-only**: Real opponents have strategies (punt builds, position runs) that ADP + noise doesn't capture. This makes our win-rate estimates optimistic.
- **No weekly matchup variance**: MCW and evaluation use season totals, not weekly samples. In H2H, a team with high variance in a category can outperform its season rank.
- **No trade/waiver modeling**: Post-draft roster moves aren't modeled. The bench contribution rates are a static proxy for daily league lineup management.
- **Recalculation lag**: The z-score recalculation endpoint re-runs the full engine, which changes replacement levels as the pool shrinks. This is correct but means a player's Value can shift between picks as the pool changes.
- **Coefficient tuning**: The MCW weight (21.0), VONA weights (0.16/0.42), urgency weights (0.02/0.55), and bench penalty parameters were tuned via simulation sweeps but are not formally optimized (no gradient search or Bayesian optimization).
- **Category correlation weights are static**: The H2H weights assume fixed weekly correlations. In practice, correlations vary by roster composition (e.g., a team heavy on power hitters may have R/TB/RBI more correlated than average).
