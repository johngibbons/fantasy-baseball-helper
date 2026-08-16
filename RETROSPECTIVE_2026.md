# 2026 Season Retrospective: Projections vs. Actuals

**Status:** provisional — computed 2026-08-15, at 77% of the regular season.
Re-run after 2026-09-27 with `python3 -m backend.scripts.retro_all --season 2026
--refresh-actuals` for final numbers. Every artifact carries an `as_of` header,
so the two runs are directly comparable.

**Method.** Realized 2026 stats are fed through the same SGP engine that built
the draft board, so "what we thought a player was worth" and "what he was
actually worth" are the same unit and can be subtracted. Both boards are
computed over an identical player pool with identical pinned denominators.
Details and caveats in [Method and limits](#method-and-limits).

---

## Summary

The draft model is not where the error is.

Every tunable in the valuation model — category weights, playing-time
discounts, the streaming bonus, replacement level, the pitcher normalizer —
moves ranking accuracy by less than 0.006 Spearman. The draft picks themselves
were within 1.1 SGP of strict best-available off our own board. What remains is
projection error, and there the board is measurably over-confident: it spreads
players about 25% further apart than reality does.

Three things are worth changing for 2027, in order of confidence:

1. **Shrink projected values toward the mean** by roughly 25%. Largest measured
   effect in the whole retrospective.
2. **Fix the ADP availability model.** Both shipped versions are wrong, and the
   one the live draft board uses is the worst of the three.
3. **Stay on a commercial projection source** (THE BAT X or Steamer). The
   in-house `trend` and `statcast_adjusted` models are clearly behind, and
   blending does not help.

---

## Layer A — Did the valuation model predict realized value?

| | Hitters | Pitchers |
|---|---|---|
| Spearman ρ | 0.741 (95% CI 0.705–0.775) | 0.614 (0.562–0.660) |
| Kendall τ | 0.543 | 0.436 |
| Calibration slope | **0.759** | **0.722** |
| R² | 0.570 | 0.379 |
| Top-25 hit rate | 36% | 36% |
| Top-100 hit rate | 57% | 49% |

### The board is over-dispersed

The calibration slope is the headline. Regressing realized value on projected
value gives 0.76 for hitters and 0.72 for pitchers — near-identical across two
independently computed pools, which is what makes it look structural rather
than noise. The board separates players more than the season does.

The same thing shows up by segment. Hitters projected for 550+ PA came in 1.79
SGP *below* their projection on average; hitters projected under 200 PA came in
0.88 *above*. That is textbook regression to the mean, and the fix is shrinkage
rather than any change to how categories are weighted.

### The tunables are inert

Each row rebuilds the preseason board with one assumption changed and rescores
it against the fixed realized objective. Significance is a paired bootstrap on
the difference in rank correlation.

| Change | Δρ hitters | Δρ pitchers | Verdict |
|---|---|---|---|
| Equal category weights | −0.0022 | −0.0091 | slightly worse (hitters only) |
| No playing-time discount | +0.0062 | −0.0036 | no effect |
| `FULL_CREDIT_PA` 500 → 300 | **+0.0038** | — | slightly better |
| `FULL_CREDIT_PA` 500 → 650 | −0.0005 | — | no effect |
| `FULL_CREDIT_IP_SP` 140 → 100 | — | −0.0036 | no effect |
| Streaming bonus off | 0.0000 | −0.0022 | no effect |
| Replacement level off entirely | +0.0012 | −0.0037 | no effect |
| Pitcher normalizer 1.25 → 1.0 | +0.0020 (combined board) | | no effect |
| Pitcher normalizer 1.25 → 1.6 | −0.0080 (combined board) | | worse |

Two notes on reading this. The confidence intervals are tight (typically
±0.005), so this is not a power problem — the effects really are that small.
And the pitcher normalizer does nothing *within* a pool; it only rescales
pitchers against hitters, so it is evaluated on the combined board.

`FULL_CREDIT_PA = 300` is the only clear improvement available, and it is worth
+0.004 Spearman. That is the ceiling on tuning this model.

### Category weights, measured rather than assumed

`zscores.py:52-70` describes its correlation matrix as "approximate". Measured
against 2025's 190 team-weeks (`backend/data/fixtures/category_weights_2025.json`):

| Pair | Assumed | Measured |
|---|---|---|
| K–QS | +0.30 | **+0.64** |
| K–ERA | +0.35 | **+0.07** |
| K–WHIP | +0.30 | +0.06 |
| TB–OBP | +0.30 | +0.55 |
| R–OBP | +0.40 | +0.59 |
| ERA–WHIP | +0.70 | +0.78 |

Several assumptions are well off. The derived weights still land within 0.06 of
the shipped values, because the 0.6 dampening and the normalization absorb most
of the error — which is consistent with the ablation showing the weights barely
matter. SB and SVHD remain the most independent categories, as assumed.

Note for anyone recomputing this: ERA and WHIP are scored low-is-better, so raw
weekly totals must be flipped into "more is better" space first. Otherwise a
good pitching week reads as QS and ERA moving in opposition (QS–ERA measures
−0.40 unoriented).

---

## Layer B — Were the picks good?

Holding the other nine teams to the players they actually took and re-picking
only our slots:

| Strategy | Realized SGP | vs actual |
|---|---|---|
| **Our actual picks** | −35.3 | — |
| Strict best-available off the board | −36.4 | **−1.1** |
| Follow ADP | −145.5 | −110.2 |
| Perfect foresight | +79.7 | +115.0 |

We captured essentially everything our board could give us. The board itself
was worth **110 SGP over drafting by ADP** — the clearest measure of what the
app buys. The remaining 115 SGP to the ceiling is projection error, not
decision error.

Mean board regret across all 210 picks was −1.5 to −3.5 SGP per pick by team,
i.e. teams routinely passed on the best player our reconstruction ranked. Some
of that is genuine disagreement (they drafted off ATC, we reconstructed from
THE BAT X), not error.

### Value is far more concentrated than the board assumes

**Only 139 of 1,358 players cleared replacement level in realized terms, while
the league rosters 250.** Roughly 44% of rostered spots held below-replacement
players. Combined with the round-by-round curve — round 1 returned 1.03 SGP
against an assumed 4.69, and rounds 4, 7, 10 and 11 returned *negative* mean
value — the implication for strategy is that early picks matter more than the
board's spread suggests and late picks are close to lottery tickets.

---

## Layer C — ADP, keepers, and the value of a pick

### The availability model is wrong, and the board's version is the worst

Residual spread by ADP band, over 200 picks with genuine draft-day ADP:

| ADP band | n | measured σ | flat 18 | board (`6 + adp/250*6`) | rejected (`10 + 0.1*adp`) |
|---|---|---|---|---|---|
| 0–50 | 24 | 6.5 | 18.0 | 6.7 | 13.0 |
| 50–100 | 33 | 17.1 | 18.0 | 7.8 | 17.3 |
| 100–150 | 30 | 31.9 | 18.0 | 8.9 | 22.2 |
| 150–200 | 43 | 40.3 | 18.0 | 10.1 | 27.2 |
| 200+ | 70 | 37.8 | 18.0 | 11.8 | 34.1 |
| | | **mean abs error** | 13.67 | **17.73** | **6.61** |

Uncertainty grows sixfold from the top of the board to the middle rounds. The
best fit is `σ = 6.55 + 0.158 × adp`.

The winner is the formula sitting switched off in `config.py` behind
`USE_VARIABLE_SIGMA`, rejected in `SCORING_IMPROVEMENTS.md` §6 on simulation
evidence. The formula the live draft board actually uses has the right shape
but tops out near 12 where reality reaches 40.

Being careful about what this shows: the *availability model* is miscalibrated.
It does not follow that flipping `USE_VARIABLE_SIGMA` improves drafts — that
earlier rejection measured simulated draft outcomes, a different question. But
it was rejected using a model of ADP noise we now know to be wrong, so the
experiment is worth re-running.

### The keeper adjustment is about three-quarters right

With 40 players off the board, everyone else went **38.7 picks earlier** than
redraft ADP. Subtracting keepers ranked above each player removes all but 9.2
picks of that bias — directionally correct, slightly undershooting.

### Managers are not interchangeable

Mean residual runs from Tim Riker at −42.5 (reaches hard) to Harris Cook at
+3.9 (waits). A 46-pick spread that `draft_engine._opponent_pick` currently
treats as uniform noise around ADP.

### Keepers

28 of 40 keepers beat what their round actually returned; the board's surplus
sign agreed with the outcome 70% of the time. Best: Pete Crow-Armstrong (+10.6),
James Wood (+10.0), Jacob Misiorowski (+8.3). Worst: Roman Anthony (−7.8),
Spencer Jones (−5.7), Cal Raleigh (−4.3).

The rank-linear assumption in `expectedValueAtRound` holds up reasonably in
*board* terms (within ~0.5 SGP for the first eight rounds), so keeper surplus
numbers are not badly biased. What it misses is the level: realized value per
round is far below projected value per round.

---

## Layer D — Which projection source?

Scored in SGP space over the intersection of players every source covers, with
pinned denominators.

**Hitters** (569 shared players)

| Source | Covers | ρ | Volume r | Rate r |
|---|---|---|---|---|
| THE BAT X | 660 | **0.741** | 0.774 | 0.527 |
| Steamer | 4186 | 0.735 | 0.769 | 0.563 |
| trend (in-house) | 666 | 0.639 | 0.674 | 0.427 |
| statcast_adjusted (in-house) | 666 | 0.637 | 0.674 | 0.436 |
| ZiPS | 1903 | 0.533 | 0.548 | 0.568 |
| blend (all) | — | 0.710 | | |
| blend (FanGraphs) | — | 0.709 | | |

**Pitchers** (608 shared players)

| Source | Covers | ρ | Volume r | Rate r |
|---|---|---|---|---|
| THE BAT X | 698 | **0.610** | 0.746 | 0.394 |
| Steamer | 5161 | 0.578 | 0.749 | 0.418 |
| ZiPS | 1838 | 0.543 | 0.621 | 0.295 |
| statcast_adjusted | 802 | 0.490 | 0.614 | 0.171 |
| trend | 802 | 0.478 | 0.614 | 0.113 |
| blend (FanGraphs) | — | 0.606 | | |

THE BAT X leads both pools, though a paired bootstrap cannot separate it from
Steamer on hitters. The in-house models are clearly behind — 0.10 for hitters,
0.12 for pitchers. **Blending never beats the best single source**, which
supports the ATC-only direction taken in `8947e0c`.

Splitting the error: playing time is forecast far better than per-unit rate
(volume r ≈ 0.77 vs rate r ≈ 0.53 for hitters; 0.75 vs 0.39 for pitchers). The
remaining headroom is in rate projection, not injury modelling — the opposite
of what we assumed going in.

---

## Recommendations for 2027

**High confidence**

1. **Apply shrinkage to the draft board.** Slope 0.72–0.76 means projected
   values should be pulled toward the pool mean by roughly a quarter before
   ranking. `backend/analysis/shrinkage.py` already implements the conjugate
   update. This is the only change with a large measured effect.
2. **Keep using THE BAT X or Steamer; retire `trend` and `statcast_adjusted`
   from valuation.** They are meaningfully worse and add nothing to a blend.
3. **Snapshot the board on draft day.** Already implemented — see the draft-day
   checklist in `docs/operations.md`. This retrospective needed a reconstruction
   because the 2026 board was overwritten in place.

**Worth testing, not yet worth shipping**

4. **Re-open the variable-ADP-sigma question** with `σ = 6.55 + 0.158 × adp`,
   and make the two implementations agree afterwards. The parity fixture
   (`backend/data/fixtures/draft_scoring_parity.json`) will hold them together.
5. **Feed measured manager tendencies into the opponent model.** The per-manager
   residuals in `adp_calibration.json` are a direct upgrade over the
   hand-curated `MANAGER_PROFILES`.
6. **`FULL_CREDIT_PA = 300`** — the only tunable change that measurably helped,
   worth +0.004 Spearman.

**Explicitly not worth doing**

7. Retuning category weights. Measured and shipped values agree within 0.06,
   and dropping them entirely costs 0.002 Spearman.
8. Retuning the MCW/VONA/urgency coefficients against this season. One realized
   season and eleven free parameters would overfit, and Layer B shows pick
   selection was already within 1.1 SGP of optimal given the board.
9. Reworking replacement level or the pitcher normalizer. Both are inert.

---

## Method and limits

**How to reproduce**

```bash
python3 -m backend.scripts.retro_all --season 2026 --refresh-actuals
```

Artifacts land in `backend/data/fixtures/retro_2026/`. Stage 0
(`retro_snapshot.py`) captures production draft state and draft-day ADP and is
run separately, once.

**Limits worth keeping in mind**

- **This is 77% of a season.** Counting-stat SGP scales with playing time while
  rate-stat SGP does not, so all level comparisons use a pace-adjusted board.
  The uncorrected slope reads 0.586 rather than 0.759 and would overstate
  over-dispersion badly. Rank metrics are unaffected.
- **The preseason board is a reconstruction.** The ATC board the draft actually
  used was overwritten before anyone thought to keep it. THE BAT X stands in.
  Rank-correlated, but not the same numbers.
- **The model that drafted is not the model in `main`.** The Optuna coefficients
  landed 2026-04-02, after the March draft. See the header of `SCORING_MODEL.md`.
- **Rosters are draft-day only.** No waivers, no trades. This is why predicted
  category wins rank us 8th while we are in the playoffs — in-season management
  is doing real work that none of these layers can see.
- **One season, one league.** Ten teams, 250 picks. Differences smaller than
  the reported confidence intervals should not be acted on.

**Data quality notes**

- MLB's season-stats endpoint does not expose quality starts; it is derived from
  game logs. Before that fix every pitcher had a zero in one of four starter
  categories, and the ex-post pitcher board had no starter in its top five.
- ESPN's ADP export pads undrafted players with a synthetic tail (260.0 for
  1,143 players). Those are excluded from calibration.
- `draft_state["picks"]` is a Map dumped to an array, so its positions are
  insertion order, not pick numbers. Only `pickLog[].pickIndex` and keeper round
  costs are authoritative — 203 of 211 entries disagreed.
