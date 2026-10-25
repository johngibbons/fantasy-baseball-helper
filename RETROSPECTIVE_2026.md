# 2026 Season Retrospective: Projections vs. Actuals

**Status:** final — full regular season, actuals as of 2026-09-27. Supersedes
the provisional version computed 2026-08-15 at 77% of the season; what moved
between the two is listed in [What changed since August](#what-changed-since-august).
League results (final standings, weekly category results, and a second season
of category weights) were added 2026-10-24.

**Method.** Realized 2026 stats are fed through the same SGP engine that built
the draft board, so "what we thought a player was worth" and "what he was
actually worth" are the same unit and can be subtracted. Both boards are
computed over an identical player pool with identical pinned denominators.
Details and caveats in [Method and limits](#method-and-limits).

---

## Summary

The draft model is not where the error is.

No tunable in the valuation model — category weights, playing-time discounts,
the streaming bonus, replacement level, the pitcher normalizer — improves
ranking accuracy beyond noise. The largest gain on offer is +0.006 Spearman and
its interval includes zero; every change that does clear noise makes the board
*worse*. The draft picks themselves were within 2.0 SGP of strict best-available
off our own board. What remains is projection error, and there the board is
measurably over-confident: it spreads players about 25% further apart than
reality does, in both pools equally.

The app's edge over the market was real but modest. Drafting strictly off the
board would have beaten drafting by ADP by **12.8 SGP**, against a 125 SGP gap
between ADP and perfect foresight — the board captured about a tenth of what
was available. The August draft of this document put that edge at 110 SGP; that
figure came from a bug in the ADP counterfactual and is withdrawn.

The season went better than the draft. Draft-day rosters ranked us eighth of
ten; we finished sixth in the regular season and third after the playoffs.

What to change for 2027, in order of confidence:

1. **Variable ADP sigma — shipped 2026-10-24.** The board and the simulator
   now use the measured `6.55 + 0.158 × adp`. The case is calibration: the
   board's availability percentages were two to four times overconfident past
   the top 50. The simulation shows no effect on draft outcomes either way.
2. **Stay on a commercial projection source** (THE BAT X or Steamer). The
   in-house `trend` and `statcast_adjusted` models are clearly behind, and
   blending does not help.
3. **Leave shrinkage off.** The over-dispersion is real, but on the final
   numbers both pools need the same correction, which reorders nothing. The
   draft sweep found no effect either.

---

## What changed since August

Most numbers moved by less than their confidence interval. Five things changed
what the document says:

| | August (77%) | Final | Consequence |
|---|---|---|---|
| Board vs. drafting by ADP (our team) | +110.2 SGP | **+12.8 SGP** | August figure was a bug; edge is modest |
| Pitcher calibration slope | 0.722 | **0.748** | Pools now match hitters (0.745); per-pool shrinkage is moot |
| `FULL_CREDIT_PA = 300` | +0.0038, significant | +0.0032, **inside noise** | No longer recommended |
| Equal category weights, pitchers | −0.009, inside noise | **−0.018, significant** | Shipped weights measurably help |
| Keepers beating their round | 28 of 40 | 27 of 40 | Aaron Judge's injury; sign agreement 70% → 68% |

**The ADP bug.** The counterfactual scored ADP as `-adp` and gave players with
no ADP a default of 0 — above every real ADP. So "follow ADP" drafted the 74
pool players with no ADP first: our simulated ADP roster was Juan Soto, then
Nick Raquet, Chris Roycroft and Angel Perdomo. Fixed in
`backend/scripts/retro_draft.py`, with a test that fails on the old behaviour.

**The pace adjustment held up.** The August run corrected counting stats for
the 23% of the season still to play. Its estimates were within 0.014 (hitters)
and 0.026 (pitchers) of the final slopes; uncorrected, they would have been off
by 0.16.

---

## Layer A — Did the valuation model predict realized value?

| | Hitters | Pitchers |
|---|---|---|
| Spearman ρ | 0.739 (95% CI 0.701–0.775) | 0.613 (0.561–0.662) |
| Kendall τ | 0.544 | 0.436 |
| Calibration slope | **0.745** | **0.748** |
| R² | 0.569 | 0.387 |
| Top-25 hit rate | 40% | 32% |
| Top-100 hit rate | 59% | 52% |

### The board is over-dispersed

The calibration slope is the headline. Regressing realized value on projected
value gives 0.745 for hitters and 0.748 for pitchers — two independently
computed pools landing within 0.003 of each other, which is what makes it look
structural rather than noise. The board separates players more than the season
does.

The same thing shows up by segment. Hitters projected for 550+ PA came in 1.81
SGP *below* their projection on average; hitters projected under 200 PA came in
1.06 *above*. Pitchers projected for 170+ IP came in 2.03 below. That is
textbook regression to the mean.

Because the two slopes are equal, the correction would be the same factor in
both pools. Shrinkage is monotonic, so it never reorders a pool; with equal
factors it barely changes how hitters interleave with pitchers either. That is
consistent with the draft sweep in `SCORING_IMPROVEMENTS.md` §9, which found no
effect — its "uniform 0.74, both pools" row is effectively the final
measurement. What over-dispersion does mean in practice: read a projected gap of
4 SGP between two players as roughly 3 SGP of real gap.

### No tunable improves the board

Each row rebuilds the preseason board with one assumption changed and rescores
it against the fixed realized objective. Significance is a paired bootstrap on
the difference in rank correlation.

| Change | Δρ hitters | Δρ pitchers | Verdict |
|---|---|---|---|
| Equal category weights | **−0.0021** | **−0.0176** | worse, both pools |
| No playing-time discount | +0.0062 | −0.0031 | no effect |
| `FULL_CREDIT_PA` 500 → 300 | +0.0032 | — | no effect |
| `FULL_CREDIT_PA` 500 → 650 | −0.0005 | — | no effect |
| `FULL_CREDIT_IP_SP` 140 → 100 | — | −0.0036 | no effect |
| Streaming bonus off | 0.0000 | +0.0023 | no effect |
| Streaming bonus doubled (0.7 → 1.4) | 0.0000 | **−0.0290** | worse |
| Replacement level off entirely | +0.0013 | **−0.0060** | worse (pitchers) |
| Pitcher normalizer 1.25 → 1.0 | +0.0014 (combined board) | | no effect |
| Pitcher normalizer 1.25 → 1.6 | **−0.0084** (combined board) | | worse |

Two notes on reading this. The confidence intervals are tight (typically
±0.005 for hitters, ±0.01 for pitchers), so this is not a power problem — the
improvements really are that small. And the pitcher normalizer does nothing
*within* a pool; it only rescales pitchers against hitters, so it is evaluated
on the combined board.

The shipped values sit at or near the best this model can do. Every significant
result is a move away from them making things worse.

### Category weights, measured rather than assumed

`zscores.py:52-70` describes its correlation matrix as "approximate". Each
season of league results gives 190 team-weeks to measure it against
(`backend/data/fixtures/category_weights_2025.json` and `_2026.json`):

| Pair | Assumed | 2025 | 2026 |
|---|---|---|---|
| K–QS | +0.30 | **+0.64** | **+0.63** |
| K–ERA | +0.35 | **+0.07** | **+0.13** |
| K–WHIP | +0.30 | +0.06 | +0.12 |
| TB–OBP | +0.30 | +0.55 | +0.56 |
| R–OBP | +0.40 | +0.59 | +0.55 |
| ERA–WHIP | +0.70 | +0.78 | +0.80 |

Several assumptions are well off, and the two seasons agree on where. The
weights derived from them:

| | R | TB | RBI | SB | OBP | K | QS | ERA | WHIP | SVHD |
|---|---|---|---|---|---|---|---|---|---|---|
| Shipped | 0.92 | 0.95 | 0.96 | 1.15 | 1.02 | 1.02 | 0.98 | 0.95 | 0.97 | 1.14 |
| Measured 2025 | 0.94 | 0.93 | 0.98 | 1.10 | 0.98 | 0.99 | 0.96 | 1.01 | 1.02 | 1.08 |
| Measured 2026 | 0.95 | 0.95 | 0.96 | 1.06 | 0.99 | 1.02 | 0.97 | 1.00 | 1.01 | 1.08 |

The two measurements agree within 0.05 in every category. The shipped weights
differ from both in the same direction: SB and SVHD are boosted further than
measured, and ERA and WHIP are discounted where measurement puts them at 1.0.

Swapping the measured weights into the preseason board makes it slightly
*worse*. Pitchers lose 0.006–0.007 of rank correlation (significant for the 2026
weights and for the two-season mean); hitters move inside noise. One check
was needed before believing that. The realized target is itself valued with the
shipped weights, so a weight ablation could just be rewarding agreement with the
target. It is not: with the target rebuilt using equal or measured weights, the
shipped board still ranks pitchers best. It beats equal weights by 0.013–0.018
under every target, all significant.

So the shipped weights earn their keep, but not by encoding the weekly
correlations better than a measurement does. Leave them as they are.

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
| **Our actual picks** | −37.5 | — |
| Strict best-available off the board | −35.5 | **+2.0** |
| Follow ADP | −48.3 | −10.8 |
| Perfect foresight | +76.5 | +114.0 |

We captured nearly everything our board could give us: strict best-available
would have gained 2.0 SGP over 21 picks. The board beat drafting by ADP by
**12.8 SGP**; our actual picks beat it by 10.8. The remaining 114 SGP to the
ceiling is projection error, not decision error.

The league-wide version, where all ten teams follow one rule, makes the same
point more starkly:

| Strategy (all teams) | League realized SGP |
|---|---|
| What the league actually did | −274.0 |
| Everyone drafts off our board | −283.0 |
| Everyone follows ADP | −288.1 |
| Everyone has perfect foresight | +137.8 |

The board's ordering beats the market's by about 5 SGP across the whole league,
and the league's actual, human drafting beat both. One draft, so none of this
carries an interval, but it does not support the idea that the board is a large
edge over a well-informed market. It is a small one.

Mean board regret across all 210 picks was −1.5 to −3.5 SGP per pick by team,
i.e. teams routinely passed on the best player our reconstruction ranked. Some
of that is genuine disagreement (they drafted off ATC, we reconstructed from
THE BAT X), not error.

Our drafted players returned −38.4 SGP, eighth of ten. Predicted weekly category
wins from draft-day rosters also rank us eighth (3.78).

### The team model against the real season

The season went better than the draft. We finished the regular season sixth
(89–86–5 in categories, the last playoff seed). In the playoffs we beat the
3-seed 7–3, lost the semifinal 2–8 to the 2-seed, and won the third-place
game 6–3. Final standings are in `retro_2026/final_standings.json`.

The team model is what `optimize_model.py` maximizes: rank-based category win
probabilities, from each draft-day roster valued on realized production. It is
scored here against every team's actual share of the 18 regular-season weeks
won, per category (`retro_2026/actual_win_rates.json`):

| Final | Seed | Team | Predicted wins/week | Actual | Above the fit |
|---|---|---|---|---|---|
| 1 | 1 | 1 | 4.89 | 5.81 | +0.84 |
| 2 | 2 | 6 | 6.22 | 5.81 | +0.40 |
| **3** | **6** | **8 (us)** | **3.78** | **5.08** | **+0.49** |
| 4 | 4 | 2 | 6.78 | 5.58 | 0.00 |
| 5 | 3 | 3 | 7.44 | 5.67 | −0.14 |
| 6 | 5 | 4 | 5.33 | 5.39 | +0.28 |
| 7 | 8 | 5 | 6.44 | 4.39 | −1.09 |
| 8 | 7 | 7 | 4.33 | 4.86 | +0.08 |
| 9 | 10 | 10 | 2.89 | 3.69 | −0.61 |
| 10 | 9 | 9 | 1.89 | 3.72 | −0.25 |

The model gets the order roughly right and the scale badly wrong.

- **Order: Spearman 0.60 across the ten teams.** That is real signal, but ten
  teams cannot pin it down; the 95% interval runs from about zero to 0.9.
- **Scale: slope 0.33.** A one-win gap in predicted weekly wins became a
  third of a win in practice. Rank-based probabilities treat first place in a
  category as a certain weekly win. Real weeks are noisy, and every team's
  actual rate landed between 3.7 and 5.8.
- **By category,** the ordering held for SB (ρ 0.96), QS (0.87), WHIP (0.81),
  R and TB (0.71, 0.70), and failed for RBI (0.22) and ERA (0.17). ERA and WHIP
  were nearly coin flips week to week: no team won more than 61% or fewer than
  39% of them.

Two things the table cannot separate. Rosters here are draft-day only, so
waivers, trades and streaming all land in the residual; K (ρ 0.42) is the
category where streaming should matter most. And the residual includes plain
luck. We beat the fit by half a win a week, second only to the champion. That
fits in-season management doing real work, but it does not prove it.

For `optimize_model.py`, the scale error matters less than it looks.
Comparing two drafts on the same over-wide scale preserves their order. What
it does do is reward winning a category by a hair as much as by a mile. That
is a possible reason to try a σ-based win probability, which `matchup.py`
already implements, if the coefficients are ever re-tuned. Nothing here shows
it would change a pick.

### Value is far more concentrated than the board assumes

**Only 142 of 1,358 players cleared replacement level in realized terms, while
the league rosters 250.** 43% of rostered spots held below-replacement players.
The multi-season backtest puts this at 134–142 in every season since 2010, so it
is a league constant rather than a 2026 quirk.

The round-by-round curve says the same. Round 1 returned 1.67 SGP against an
assumed 4.69. Only six rounds returned positive mean value — 1, 2, 3, 5, 6 and
8 — and every round from 9 on was negative. Early picks matter more than the
board's spread suggests; late picks are close to lottery tickets.

---

## Layer C — ADP, keepers, and the value of a pick

ADP calibration compares draft-day ADP with where players were actually taken,
so it does not depend on realized stats and is unchanged from August.

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

The formula the live draft board used had the right shape but topped out near
12 where reality reaches 40. Since August, the multi-season backtest found the
same slope across six seasons (`σ = 11.13 + 0.161 × adp`).

**Shipped 2026-10-24.** `USE_VARIABLE_SIGMA` is on, with this fit, in both the
simulator and the board, and the parity fixture now covers availability. A
simulated gain of ~0.1 wins, reported in August, turned out to measure a change
to the simulated opponents rather than to our model; with the league held
fixed, sigma makes no measurable difference to simulated drafts
(`SCORING_IMPROVEMENTS.md` §6). It shipped because the percentages the board
shows are now calibrated against a real draft. The same change fixed a normal
CDF that understated tail availability by about a fifth.

### The keeper adjustment is about three-quarters right

With 40 players off the board, everyone else went **38.7 picks earlier** than
redraft ADP. Subtracting keepers ranked above each player removes all but 9.2
picks of that bias — directionally correct, slightly undershooting. Four of five
earlier seasons land between +7.4 and +11.2.

### Manager tendencies do not carry over

Mean residual in 2026 ran from Tim Riker at −42.5 (reaches hard) to Harris Cook
at +3.9 (waits). The August version of this document recommended feeding that
into the opponent model. The multi-season backtest reversed it: a manager varies
more between his own seasons (30.5 picks) than managers differ from each other
(28.2), and neither 2026 extreme is an extreme over 2017–2025.

### Keepers

27 of 40 keepers beat what their round actually returned; the board's surplus
sign agreed with the outcome 68% of the time. Best: Pete Crow-Armstrong (+11.8),
James Wood (+7.5), Jacob Misiorowski (+7.4). Worst: Aaron Judge (−6.5, 66 games),
Roman Anthony (−6.2), Spencer Jones (−2.9).

Ours: Jackson Chourio (+4.8) and Nick Kurtz (+1.9) beat their rounds; Lawrence
Butler (−0.1) roughly broke even; Juan Soto (−2.0, 111 games) did not.

67.5% sits inside the 60–82.5% range of single seasons in the multi-season
backtest, whose nine-season rate is 73.3% against a 51.9% control. Forty
decisions cannot separate a good keeper year from an average one.

The rank-linear assumption in `expectedValueAtRound` holds up in *board* terms:
within 0.61 SGP for each of the first eight rounds, 0.26 on average, so keeper
surplus numbers are not badly biased. What it misses is the level: realized
value per round is far below projected value per round, which is the cost of
collective drafting error rather than an app bug.

---

## Layer D — Which projection source?

Scored in SGP space over the intersection of players every source covers, with
pinned denominators.

**Hitters** (569 shared players)

| Source | Covers | ρ | Volume r | Rate r |
|---|---|---|---|---|
| THE BAT X | 660 | **0.740** | 0.767 | 0.525 |
| Steamer | 4186 | 0.734 | 0.764 | 0.549 |
| trend (in-house) | 666 | 0.627 | 0.660 | 0.379 |
| statcast_adjusted (in-house) | 666 | 0.625 | 0.660 | 0.419 |
| ZiPS | 1903 | 0.545 | 0.558 | 0.545 |
| blend (all) | — | 0.709 | | |
| blend (FanGraphs) | — | 0.715 | | |

**Pitchers** (608 shared players)

| Source | Covers | ρ | Volume r | Rate r |
|---|---|---|---|---|
| THE BAT X | 698 | **0.607** | 0.742 | 0.450 |
| Steamer | 5161 | 0.569 | 0.743 | 0.432 |
| ZiPS | 1838 | 0.547 | 0.629 | 0.325 |
| statcast_adjusted | 802 | 0.490 | 0.619 | 0.210 |
| trend | 802 | 0.479 | 0.619 | 0.120 |
| blend (all) | — | 0.585 | | |
| blend (FanGraphs) | — | 0.604 | | |

THE BAT X leads both pools. A paired bootstrap cannot separate it from Steamer
on hitters, but can on pitchers (Δρ −0.011 to −0.066). The in-house models are
clearly behind — 0.11 for hitters, 0.12 for pitchers. **Blending never beats the
best single source**, which supports the ATC-only direction taken in `8947e0c`.

Splitting the error: playing time is forecast far better than per-unit rate
(volume r ≈ 0.77 vs rate r ≈ 0.53 for hitters; 0.74 vs 0.45 for pitchers). The
remaining headroom is in rate projection, not injury modelling — the opposite
of what we assumed going in.

---

## Recommendations for 2027

**Do**

1. **Enable `USE_VARIABLE_SIGMA`, and make the live draft board agree.**
   *Done 2026-10-24.* The availability model had the only measured, replicated
   error in the draft machinery, and the live board's `6 + adp/250*6` was the
   worst of the three formulas tested. Both now use `6.55 + 0.158 × adp`, held
   together by the parity fixture. The simulated benefit reported in August did
   not survive a corrected experiment; the fix is a calibration fix.
2. **Keep using THE BAT X or Steamer; retire `trend` and `statcast_adjusted`
   from valuation.** They are meaningfully worse and add nothing to a blend.
   THE BAT X is the better of the two for pitchers.
3. **Snapshot the board on draft day.** Already implemented — see the draft-day
   checklist in `docs/operations.md`. This retrospective still needed a
   reconstruction because the 2026 board was overwritten in place; 2027's
   should not.

**Measured, built, and left off**

4. **Shrinkage.** The board over-disperses by about a quarter, in both pools.
   `ValuationConfig.hitter_shrinkage` / `pitcher_shrinkage` implement the
   correction and default to 1.0. Leave them there: shrinkage cannot reorder a
   pool, the final slopes give the two pools the same factor, and the draft
   sweep found no effect.

**Not worth doing**

5. **Per-manager tendencies in the opponent model.** They do not persist
   between seasons.
6. **`FULL_CREDIT_PA = 300`.** Its gain shrank to +0.003 Spearman and no longer
   clears noise.
7. **Retuning category weights.** Two seasons of measurement agree with each
   other within 0.05, and swapping them in makes the board slightly worse. That
   holds even when the realized target is rebuilt with the measured weights.
8. **Retuning the MCW/VONA/urgency coefficients against this season.** One
   realized season and eleven free parameters would overfit, and pick selection
   was already within 2.0 SGP of optimal given the board.
9. **Reworking replacement level or the pitcher normalizer.** No change to
   either improves the board; removing replacement level hurts pitchers.

---

## Open questions

Nothing is blocked any more. Two loose ends for whoever picks this up next:

- **The team model's scale** (slope 0.33, [above](#the-team-model-against-the-real-season))
  matters only if the Optuna coefficients are re-tuned.
- **A second season of σ.** `sigma_calibration_2026.json` sits beside the 2025
  fixture that `matchup.py` ships. Within-week σ, which drives in-season win
  probabilities, moved 11% or less per category. Between-team σ, used only by
  the playoff-odds shrinkage, came out 22–76% wider in 2026 in seven
  categories. Two seasons disagreeing that much says the shipped 2025 values
  are a single, noisy estimate. Averaging the two is a reasonable default
  before next season. Nothing was changed here.

---

## Method and limits

**How to reproduce**

```bash
.venv/bin/python -m backend.scripts.retro_all --season 2026 \
    --refresh-actuals --as-of 2026-09-27
```

Artifacts land in `backend/data/fixtures/retro_2026/`. Two stages need
credentials and are run separately, once. Stage 0 (`retro_snapshot.py`) captures
production draft state and draft-day ADP. After the fantasy playoffs, the league
results need the ESPN cookies:

```bash
.venv/bin/python -m backend.scripts.retro_league_results --season 2026 \
    --league-id 77166 --swid '{...}' --espn-s2 '...'
.venv/bin/python -m backend.scripts.calibrate_category_sigma --season 2026 \
    --league-id 77166 --swid '{...}' --espn-s2 '...'
.venv/bin/python -m backend.scripts.calibrate_category_weights --season 2026 \
    --from-sigma-fixture backend/data/fixtures/sigma_calibration_2026.json
```

Their outputs are committed, and `retro_draft.py` reads
`actual_win_rates.json` when it is present, so the main command above needs no
credentials.

**Limits worth keeping in mind**

- **The preseason board is a reconstruction.** The ATC board the draft actually
  used was overwritten before anyone thought to keep it. THE BAT X stands in.
  Rank-correlated, but not the same numbers.
- **The model that drafted is not the model in `main`.** The Optuna coefficients
  landed 2026-04-02, after the March draft. See the header of `SCORING_MODEL.md`.
- **Rosters are draft-day only.** No waivers, no trades. Draft-day rosters rank
  us eighth on predicted category wins; we finished sixth in the regular season
  and third overall. In-season management probably did real work, and none of
  these layers can see it.
- **One season, one league.** Ten teams, 250 picks. Differences smaller than
  the reported confidence intervals should not be acted on, and the Layer B
  counterfactuals carry no interval at all. `RETROSPECTIVE_MULTISEASON.md`
  extends keepers, ADP and value-at-pick across up to fourteen seasons.

**Data quality notes**

- MLB's season-stats endpoint does not expose quality starts; they are derived
  from game logs. A failed game-log fetch used to be logged and stored as
  **zero QS** — the first final pull did this to 30 starters, including Dylan
  Cease and Yoshinobu Yamamoto, and the boards would have been built on it had
  two unrelated fetches not failed. It now fails the fetch, which is retried and
  then blocks the boards from being built. The August run and the 2009–2025
  backfill were checked and were not affected: every 15+ start season with zero
  QS was re-derived from its game log and is genuine — openers and short
  starters.
- The season line's innings were read as a plain float, so "64.1" (64⅓) was
  stored as 64.1. The history backfill parsed them correctly, so the same
  pitcher's row depended on which writer ran last. Both now use
  `parse_innings_pitched`.
- At 12 concurrent requests the MLB API dropped enough connections to fail 14
  of 1,358 fetches once QS doubled the calls per starter. The retro now refreshes
  at 4, which completed with none.
- ESPN's ADP export pads undrafted players with a synthetic tail (260.0 for
  1,143 players). Those are excluded from calibration. 74 pool players have no
  ADP at all; the counterfactual now ranks them last.
- `draft_state["picks"]` is a Map dumped to an array, so its positions are
  insertion order, not pick numbers. Only `pickLog[].pickIndex` and keeper round
  costs are authoritative — 203 of 211 entries disagreed.
