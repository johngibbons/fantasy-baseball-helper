# Fantasy Baseball Helper - Modeling Improvements Plan

## Context

- 10-team H2H categories league (ESPN)
- Categories: R, TB, RBI, SB, OBP | K, QS, ERA, WHIP, SVHD
- Snake draft with keepers pre-assigned to round cost (up to 4 keepers, 3 seasons max)
- Weekly acquisition limit (constrains streaming)
- ~20 week regular season, top 6 of 10 make playoffs
- Real historical standings data available for SGP denominators

---

## Issue 1: Double-counting playing time for rate stats

**Status:** DONE
**Priority:** 1 (Critical)
**Impact:** High - systematically misvalues ~40% of players
**Complexity:** Low
**Files:** `backend/analysis/zscores.py:420-480`, `backend/analysis/zscores.py:593-604`

### Problem

The rate stat marginal approach already PA-weights OBP:

```python
obp_marginal = (obp_raw - league_obp) * (pa / avg_team_pa)
```

Then the playing time discount multiplies it again by `PA / 500`:

```python
confidence = min(1.0, p["proj_pa"] / FULL_CREDIT_PA)
p["zscore_obp"] = p["zscore_obp"] * confidence
```

A player with 300 PA gets `(300/600) * (300/500) = 0.30` of the impact a 500 PA player gets,
when it should be closer to `300/600 = 0.50`. This undervalues part-time hitters' OBP by ~40%.

The same double-counting affects pitchers: ERA and WHIP are IP-weighted in the marginal
calculation, then discounted again by `IP / full_credit_IP`.

### Fix

Skip the playing time discount for rate-stat z-score components. Only apply the confidence
factor to counting stats (R, TB, RBI, SB for hitters; K, QS, SVHD for pitchers).

---

## Issue 2: Pool-specific IP denominators inflate rate stat SGP

**Status:** DONE
**Priority:** 2 (Critical)
**Impact:** High - overvalues "ratio" pitchers by 1.4-3.4x
**Complexity:** Low
**Files:** `backend/analysis/zscores.py:548-565`

### Problem

The pitcher rate stat marginal uses pool-specific `avg_team_ip`:

```python
avg_team_ip = np.sum(ip) / NUM_TEAMS  # only SP IP or only RP IP
era_marginal = (league_era - era_raw) * (ip / avg_team_ip)
```

But the SGP denominator for ERA comes from **team-level** standings data (all pitchers combined).
A team's ERA is a weighted average of SP and RP ERA, with the weight being total IP.

By using only SP IP (~120/team) or only RP IP (~50/team) instead of total team IP (~170/team),
the marginal impact is overstated:

- SP: ERA/WHIP inflated by ~1.4x (`total_team_ip / sp_team_ip`)
- RP: ERA/WHIP inflated by ~3.4x (`total_team_ip / rp_team_ip`)

This systematically overvalues ERA/WHIP relative to K/QS/SVHD within each pool.

### Fix

Compute total pitcher IP across both pools before splitting into SP/RP, and pass the combined
`avg_team_ip` to each pool's rate stat marginal calculation.

---

## Issue 3: H2H category correlation weighting

**Status:** DONE
**Priority:** 3 (Critical)
**Impact:** High - overvalues R/TB/RBI cluster
**Complexity:** Medium
**Files:** `backend/analysis/zscores.py` (new correlation weighting layer)

### Problem

R, TB, and RBI are highly correlated (~0.7-0.8 among hitters). In H2H categories, winning R
strongly predicts winning TB and RBI in the same matchup. Three correlated categories provide
~2.2 "effective independent category wins," not 3.0. Meanwhile, SB and OBP are less correlated
with the power/run-production cluster.

The current model treats all 10 categories as equally independent, overvaluing the R/TB/RBI
cluster and undervaluing SB and OBP as diversification categories.

Similarly on the pitching side, ERA and WHIP are correlated (~0.6-0.7), while K is more
independent.

### Fix

Introduce a category correlation matrix computed from historical league data (or empirical
MLB weekly correlations). Apply a discount factor to correlated category clusters so that
the "effective SGP" for a player reflects the independent information their stats provide.

Approximate correlation-aware weights:
- R: 0.85 (correlated with TB/RBI)
- TB: 0.85 (correlated with R/RBI)
- RBI: 0.85 (correlated with R/TB)
- SB: 1.10 (largely independent)
- OBP: 1.05 (partially correlated with R cluster)
- K: 1.05 (partially independent from ERA/WHIP)
- QS: 0.95 (correlated with ERA)
- ERA: 0.90 (correlated with WHIP, QS)
- WHIP: 0.90 (correlated with ERA)
- SVHD: 1.10 (largely independent)

---

## Issue 4: Pitcher normalization scaling is a blunt instrument

**Status:** DONE
**Priority:** 4 (Major)
**Impact:** Medium - distorts cross-position comparisons
**Complexity:** Medium
**Files:** `backend/analysis/zscores.py:735-750`

### Problem

```python
target_pitcher_sum = hitter_value_sum * (pitcher_slots / hitter_slots)
scale = target_pitcher_sum / pitcher_value_sum
```

This scales all pitcher z-scores by a single multiplier so total pitcher value equals (7/10)
of total hitter value. After scaling, pitcher z-scores no longer represent actual SGP. The
7:10 ratio assumes per-slot value should be equal, but pitcher value is top-heavy while hitter
value is flatter.

### Fix

Use a unified replacement level framework where hitters and pitchers compete for the same
value-above-replacement pool. Set the zero line at the (hitter_slots + pitcher_slots) * 10
= 170th best player across all positions, then apply position-specific adjustments within that.

---

## Issue 5: Replacement level computed on primary position only

**Status:** DONE
**Priority:** 5 (Major)
**Impact:** Medium - misvalues positional scarcity
**Complexity:** Medium
**Files:** `backend/analysis/zscores.py:248-278`

### Problem

```python
for p in results:
    slot = POSITION_TO_SLOT.get(p["primary_position"], "UTIL")
    by_slot[slot].append(p["total_zscore"])
```

Multi-eligible players (e.g., "2B/SS/OF") are only counted in their primary position's
replacement pool. This makes thin positions (C, SS) look artificially scarce because
multi-eligible players who can fill those slots are counted elsewhere.

### Fix

Count each player in all position pools they're eligible for. When computing the replacement
level for a position, include all players who could fill that slot. Use a greedy assignment
algorithm (best player to scarcest position) to more accurately model how a draft actually
fills roster slots.

---

## Issue 6: Keeper surplus optimization ignores draft interaction

**Status:** DONE
**Priority:** 6 (Major)
**Impact:** Medium - suboptimal keeper decisions
**Complexity:** High
**Files:** `src/app/keepers/page.tsx:87-175`

### Problem

- **Round collisions:** Two keepers at round 3 should conflict (can't have two 3rd round picks).
  The optimizer doesn't check for this.
- **Other teams' keepers:** Players kept by other teams shrink the draft pool, changing expected
  value at each pick. If 30 high-value players are kept league-wide, non-keeper picks are weaker,
  making keeper surplus more valuable.
- **Category need:** The diversity bonus is weak (0.5 multiplier, 0.5 threshold). Should use
  the H2H marginal category framework.

### Fix

- Add round collision detection (no two keepers in the same round unless rules allow it).
- Adjust expected-value-at-round based on the depleted post-keeper player pool.
- Replace the diversity bonus with MCW-based keeper evaluation.

---

## Issue 7: Statcast OBP adjustment uses wrong scale

**Status:** DONE
**Priority:** 7 (Moderate)
**Impact:** Medium - ~20% error on OBP adjustments
**Complexity:** Low
**Files:** `backend/data/statcast_adjustments.py:126-131`

### Problem

```python
woba_diff = xwoba - actual_woba
obp_adjustment = woba_diff * BLEND
adj_obp = adj_obp + obp_adjustment
```

wOBA and OBP are on different scales (league avg wOBA ~.310, OBP ~.320). The approximate
conversion is `OBP_change ~ wOBA_change / 1.2`. The current code overstates OBP adjustments
by ~20%.

### Fix

Scale the wOBA-to-OBP conversion: `obp_adjustment = woba_diff * BLEND / WOBA_TO_OBP_SCALE`
where `WOBA_TO_OBP_SCALE ~ 1.2`.

---

## Issue 8: Trend projections don't account for age curves

**Status:** DONE
**Priority:** 8 (Moderate)
**Impact:** Low-Medium - affects ~15% of player pool
**Complexity:** Medium
**Files:** `backend/data/projections.py:331-490`

### Problem

The 50/30/20 weighting treats a 22-year-old breakout candidate the same as a 35-year-old
on decline. Young players' recent improvements are more likely to sustain; aging players'
declines are likely to accelerate.

### Fix

Add age-based weight adjustments to the trend projection:
- Age 22-26: upweight most recent season (60/25/15), apply small growth factor
- Age 27-31: standard weights (50/30/20)
- Age 32+: upweight most recent season (60/25/15), apply decline factor

---

## Issue 9: Projection blending uses equal weights

**Status:** DONE
**Priority:** 9 (Moderate)
**Impact:** Low-Medium - modest accuracy gain
**Complexity:** Low
**Files:** `backend/analysis/zscores.py:193-232`

### Problem

All projection sources are averaged equally. Research shows weighted blends outperform:
- THE BAT X: strongest for hitters
- Steamer: strongest for pitchers, most conservative
- ZiPS: best for young/breakout players

### Fix

Apply source-specific weights when blending:
- Hitters: THE BAT X 0.40, Steamer 0.30, ZiPS 0.30
- Pitchers: Steamer 0.40, THE BAT X 0.30, ZiPS 0.30

---

## Issue 10: MCW fractional credit is poorly calibrated

**Status:** DONE
**Priority:** 10 (Moderate)
**Impact:** Low - affects mid-draft decisions
**Complexity:** Low
**Files:** `src/lib/draft-optimizer.ts:232-246`

### Problem

```typescript
marginalWin = gapClosed * 0.3 / (numTeams - 1)
```

The 0.3 multiplier is arbitrary and likely too conservative. Closing 50% of a gap to the team
above provides substantial win probability improvement.

### Fix

Model the expected end-of-draft distribution and compute actual probability shift. As a simpler
fix, increase the fractional credit multiplier to ~0.5-0.6 based on empirical testing.

---

## Issue 11: Streaming constraint not reflected in pitcher valuation

**Status:** Not started
**Priority:** 11 (Minor)
**Impact:** Low - marginal adjustment
**Complexity:** Low
**Files:** `backend/analysis/zscores.py`

### Problem

Weekly acquisition limits constrain SP streaming. Pitchers you roster full-time become more
valuable relative to spot-start streamers. The model doesn't distinguish between "hold all
season" SP and "stream when matchup is good" SP.

### Fix

Add a small bonus to SP with consistently rosterable ERA/WHIP profiles (e.g., projected
ERA < 4.00 and WHIP < 1.25) since these provide value every week without burning transactions.

---

## Issue 12: Punt strategy thresholds are rigid

**Status:** Not started
**Priority:** 12 (Minor)
**Impact:** Low - matters late in draft
**Complexity:** Low
**Files:** `src/lib/draft-optimizer.ts:126-169`

### Problem

Punt/target/lock thresholds are hardcoded. With top-6 playoffs (more forgiving), punting is
riskier (starting 0-2 each week is costly when you only need to be average). Thresholds should
adapt to league format.

### Fix

Make thresholds configurable or compute from league structure:
- Top-6 playoffs: raise punt gap threshold from 3.0 to 4.0+
- Widen "target" zone to ranks 3-8 instead of 4-7
