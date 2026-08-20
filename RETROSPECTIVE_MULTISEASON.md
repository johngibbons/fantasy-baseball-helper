# Multi-Season Backtest: Keeper Outcomes, 2016–2025

**Status:** Phases 0–6 complete — every phase in the plan.
**Plan:** `docs/superpowers/plans/2026-08-17-multi-season-backtest.md`
**Builds on:** `RETROSPECTIVE_2026.md`

---

## Summary

**The keeper model works, and now we know it rather than suspect it.**

The 2026 retrospective measured keepers on 40 decisions and found the surplus
sign agreed with the outcome 70% of the time — on that sample, barely
distinguishable from a coin flip. Extending the same evaluation across nine
seasons takes the sample to **360 decisions**, and the result holds:

| | 2026 alone | 2016–2025 |
|---|---|---|
| Keeper decisions | 40 | **360** |
| Beat what their round returned | 70% | **73.3%** (95% CI 68.9–77.8) |
| Control: ordinary picks beating their round | not measured | **51.9%** (n=1,848) |

The control is what makes the headline readable. Value within a round is
right-skewed, so an ordinary pick clears its round's mean about half the time.
Keepers clear it 73.3% of the time — **21 points above the null, far outside the
confidence interval.** Keeping is a real edge, worth **+2.33 SGP per decision**
(CI +1.93 to +2.75) over letting the player go and drafting that round normally.

Phase 5 then tested whether the 2026 ADP findings replicate. **Two of three do,
and the third reverses**: the residual-spread law holds across six seasons
(σ = 11.13 + 0.161 × adp against 2026's 6.55 + 0.158), but per-manager
reach/wait does not survive multi-season measurement — a manager varies more
between his own seasons (30.5 picks) than managers differ from each other
(28.2). That contradicts `RETROSPECTIVE_2026.md` recommendation 5 and is the
second finding here that changes what should ship.

Phase 6 then split the 2026 over-dispersion finding in two. Over twelve seasons
of regenerated projections, **pitchers over-disperse in every single season**
(mean slope 0.699 against 2026's 0.722 from a completely different forecaster),
which points at the valuation engine rather than any one projection source.
**Hitters do not** — mean 0.885, and above 1 in two seasons. Shrinkage should
be applied per pool, confidently for pitchers and cautiously for hitters,
rather than as one constant for both.

Phase 4 measured the value-at-pick curve. **The curve is stable enough to fit**
— a logarithmic shape, `value ≈ 2.37 − 1.68 × ln(round)` — and
`expectedValueAtRound` overstates the baseline in every season, so the app
understates keeper surplus. But **the size of that bias is much smaller than a
first reading suggests, and the two numbers involved must not be confused**;
see [the correction below](#a-correction-two-different-errors).

Three more results, all with the sample to support them:

1. **Value above replacement is a league constant.** Between 134 and 142
   players cleared replacement in *every* season from 2010 to 2025, while the
   league rosters 250. 2026's 139 sits mid-range. The 2026 retrospective's
   "44% of rostered spots hold below-replacement players" holds at 44.7%
   (range 43.2–46.4, sd 0.9).
2. **Multi-season keepers hold up.** Year 3 keepers beat their round 77.1% of
   the time at a mean cost of round 7.8, against 74.5% for year 1 at round
   15.6, with essentially identical surplus. Paying five rounds more per season
   neither gains nor loses ground.
3. **`KEEPER_HISTORY` in `src/lib/draft-history.ts` is wrong**, in 29 field
   disagreements and 22 fabricated 2026 rows. Where the league's own keeper
   doctrine can adjudicate, the workbook obeys it 12 times and the curated file
   **zero**. This is the one finding that needs a code change.

---

## What was measured, and against what

A keeper decision is judged against **what that round actually returned in that
season, excluding other keepers**. That is the real alternative: let the player
go, and draft the round normally. Realized value runs through the same SGP
engine that builds the draft board (`backend/analysis/retro/expost.py`), with
the playing-time discount off — realized volume is a fact, not a risk — and
denominators pinned so all nine seasons share one scale.

Two method choices are worth stating because each moves the number:

**Keepers are excluded from the comparison curve.** Keepers sit inside the
rounds they cost, so judging them against a round average that includes keepers
compares them partly against themselves. Both curves are stored; the analysis
uses the non-keeper one.

**No preseason board exists before 2026.** The app did not exist and no archived
projections do either, so *"did the model say keep?"* cannot be asked of these
seasons. The `prior_*` fields in the artifact are a decision-time baseline — the
player's production the previous season, which is what every manager actually
had in February. That baseline's sign agreed with the outcome **71.7%** of the
time (CI 67.2–76.1). It is **not** the app's board and must not be reported as
one.

---

## Detail

### The effect is not an artifact of thin baselines

Managers park keepers in the cheapest rounds — 43 of 360 keepers cost round 25 —
and those rounds are left with only two or three non-keeper picks to average.
That is a noisy thing to be measured against, so the result is split by how many
picks formed each comparison:

| Comparison baseline | n | Beat rate | Mean surplus |
|---|---|---|---|
| < 5 non-keeper picks | 79 | 70.9% | +2.00 |
| ≥ 5 non-keeper picks | 281 | 74.0% | +2.43 |

Close enough that the headline does not rest on the thin rounds.

### Season to season

| Season | Keepers | Beat rate |
|---|---|---|
| 2016 | 40 | 70.0% |
| 2017 | 40 | **82.5%** |
| 2018 | 40 | 67.5% |
| 2019 | 40 | 77.5% |
| 2020 | 40 | **60.0%** |
| 2022 | 40 | 70.0% |
| 2023 | 40 | 77.5% |
| 2024 | 40 | 77.5% |
| 2025 | 40 | 77.5% |

Eight of nine land between 67.5% and 82.5%. The low outlier is 2020 — the
60-game COVID season, where small samples make every projection worse. On n=40
per season, that spread is what the 2026 confidence interval predicted; it is
the reason a single season could not answer this question.

### Keeping longer keeps working

| Seasons kept | n | Mean round cost | Mean surplus | 95% CI | Beat rate |
|---|---|---|---|---|---|
| 1 | 204 | 15.6 | +2.41 | +1.88 to +2.93 | 74.5% |
| 2 | 74 | 12.8 | +2.40 | +1.53 to +3.35 | 73.0% |
| 3 | 35 | 7.8 | +2.46 | +1.16 to +3.75 | 77.1% |

The cost escalation is doing its job. A year-3 keeper costs roughly eight rounds
more than a year-1 keeper and returns the same surplus to within a hundredth of
an SGP, which says the five-rounds-per-season rule is priced about right rather
than generous. There is no decay to correct for.

### Surplus barely varies with round cost, and that result is pool-sensitive

Regressing realized surplus on round cost gives a slope of **+0.057 SGP per
round** (CI +0.006 to +0.109, R² 0.013). Read literally, the interval excludes
zero and cheap late-round keepers are slightly better value than expensive
early ones.

It should not be read literally. The same regression over the narrower
drafted-only pool gives +0.048 with a CI of [−0.013, +0.107] — flat. A finding
that changes significance between two defensible pool definitions is not a
finding, and the magnitude settles it either way: +0.057 across the 24 rounds
of spread is 1.4 SGP, against keeper surpluses that range over 25 SGP.
**Reported as no effect**, with the sensitivity noted because it would be easy
to rediscover and over-read.

### Best and worst decisions

| | Season | Cost | Surplus |
|---|---|---|---|
| Gunnar Henderson (Tim Riker) | 2024 | R20, yr 2 | **+13.13** |
| Charlie Blackmon (John Gibbons) | 2017 | R10, yr 3 | +12.83 |
| Cody Bellinger (Harris Cook) | 2019 | R18, yr 2 | +12.32 |
| James Wood (Matt Wayne) | 2025 | R25, yr 1 | +11.36 |
| … | | | |
| José Miranda (Jason McComb) | 2023 | R25, yr 1 | −9.07 |
| Ronald Acuña (Jason McComb) | 2024 | R1, yr 1 | **−11.79** |

### Managers look different, but not measurably so

Mean surplus per manager runs from John Gibbons at +3.30 to Jason McComb at
+0.83 — a spread that looks like a story. Every manager's interval overlaps its
neighbours, and the two extremes separate only on a knife edge (Gibbons's floor
+2.10 against McComb's ceiling +2.04). That margin also flips sign depending on
which player pool the board is built over.

**Reported as no finding.** A gap that survives only at the third decimal place
and reverses under a defensible change of pool is noise. On 28–36 decisions per
manager this sample cannot see keeper skill even if it exists — unlike the ADP
reach/wait result in `RETROSPECTIVE_2026.md`, which was a 46-pick spread over
hundreds of picks.

---

## Phase 4 — the value-at-pick curve

### The curve is stable enough to fit

Every keeper surplus the app shows depends on `expectedValueAtRound` in
`src/app/keepers/page.tsx`. Whether that can be replaced by a fitted empirical
curve comes down to one question: do seasons agree with each other more closely
than picks within a round vary?

| | SGP |
|---|---|
| Between-season spread of a round's mean (mean over rounds) | **1.31** |
| Within-round spread of individual picks (mean over rounds) | **3.25** |
| Ratio | **0.41** |

They do, by a factor of about 2.5. The curve is a real signal sitting inside
pick-level noise, not an artifact redrawn each year. The worst round is 25
(between-season sd 2.18), which is also the shallowest.

The caveat is that seasons agree on the *level* better than on the fine
ordering: pairwise Spearman between season curves averages **+0.53** (range
+0.05 to +0.85 over 91 pairs). Rounds 8–20 are close enough together that their
year-to-year ordering shuffles. That argues for fitting a smooth curve rather
than using a per-round lookup table.

### The shape is logarithmic

| Shape | RMSE against the pooled curve |
|---|---|
| **Logarithmic** | **0.221** |
| Quadratic | 0.335 |
| Linear | 0.564 |

`value ≈ 2.37 − 1.68 × ln(round)`, and the shapes are separable (RMSE spread
0.34). Steep early, flattening late — the shape a value curve is usually
assumed to have, now measured rather than assumed.

### <a name="a-correction-two-different-errors"></a>`expectedValueAtRound` is biased high — but by how much depends on which question you ask

The rank-linear assumption evaluated against what rounds actually returned:

| Round | Pooled actual | Rank-linear error |
|---|---|---|
| 1 | +2.47 | **+3.19** |
| 5 | −0.32 | +2.83 |
| 10 | −1.62 | +2.55 |
| 15 | −2.77 | +2.61 |
| 20 | −2.35 | +1.32 |
| 25 | −3.19 | +1.45 |

The error is positive at **every** round, averaging **+2.2 SGP** and largest
early.

**That +2.2 is not the app's bias, and an earlier draft of this document said
it was.** The correction matters, because acting on the wrong figure would
overshoot by roughly a factor of five.

Two different quantities are in play:

| | What it compares | Size |
|---|---|---|
| **Realized-units gap** | "the R×10-th best player" vs *what round R actually returned* | **+2.2 SGP** |
| **Board-units gap** | "the R×10-th best player" vs *the mean projected value of round R* | **+0.26 SGP** (2026, THE BAT X) |

The app computes surplus as *projected player value minus
`expectedValueAtRound(projected board)`* — both terms in projected units. So
the quantity that governs it is the **board-units** gap, and on the 2026 board
that is +0.26 SGP over rounds 1–8 (+0.68 over all 25). Small.

The realized-units gap is a real and interesting number, but it measures
something else entirely: the distance between "the Nth best player" and "what
teams actually got with the Nth pick" is **the cost of collective drafting
error**, about 2 SGP per pick. It is a fact about the league, not a bug in the
app.

Measured on Phase 6's regenerated boards, the board-units error is positive in
all eleven seasons — so the *direction* holds — but its size depends on the
projection model:

| Board | Rounds 1–8 error |
|---|---|
| THE BAT X (2026) | **+0.26** |
| Trend model (2013–2025, pooled) | **+1.47** |

The trend model is the weaker forecaster (ρ 0.639 against THE BAT X's 0.741 in
2026), and its board is shaped differently, so the gap is wider. The shipped
board uses a commercial source, which puts the honest estimate nearer the low
end.

**What this means for shipping.** Replacing `expectedValueAtRound` with the
fitted curve is a *real but modest* improvement, not the large one this document
previously claimed, and the correction has to be derived on the board the app
actually builds. A curve fitted to realized values would deflate the baseline
by ~2 SGP while player values stayed in projected units — a unit mismatch that
would systematically **overstate** surplus and be worse than the status quo.

### Value above replacement is a league constant

| Season | Pool | Above replacement | Rostered spots below replacement |
|---|---|---|---|
| 2010 | 1,250 | 135 | 46.0% |
| 2014 | 1,325 | 138 | 44.8% |
| 2018 | 1,378 | 138 | 44.8% |
| 2020 | 1,299 | 137 | 45.2% |
| 2022 | 1,497 | 140 | 44.0% |
| 2025 | 1,475 | 140 | 44.0% |
| *2026 (retrospective)* | *1,358* | *139* | *44%* |

Across fourteen seasons the count above replacement sits between **134 and
142**, and the share of rostered spots holding below-replacement players is
**44.7%** (range 43.2–46.4, sd 0.9). The pool itself grew by 20% over the
period; the number of genuinely rosterable players did not move.

So the 2026 finding is a league constant, not an artifact, and the strategic
reading in `RETROSPECTIVE_2026.md` stands: the league rosters 250 players when
fewer than 145 are worth rostering, so early picks are worth more than the
board's spread suggests and late picks are close to lottery tickets.

**Honesty about what is mechanical here.** Replacement level is defined by
roster demand, which is fixed at ten teams and a fixed slot structure, so this
number is anchored by construction and could not have landed anywhere. What is
genuinely measured is that it does not drift — not with pool size, not across
the pre- and post-universal-DH eras, not through the 60-game 2020 season.

---

## Phase 5 — does the 2026 ADP work replicate?

Five seasons carry both a draft and an ESPN top-300 sheet: 2017, 2020, 2023,
2024, 2025. The ranking stands in for draft-day ADP, and is better than a
generic ADP feed in one respect — it is the list this league actually drafted
from.

**Two of the three 2026 findings replicate strongly. The third reverses.**

### Residual spread by band — replicates

| ADP band | n | measured σ (pooled) | 2026 σ |
|---|---|---|---|
| 0–50 | 139 | **11.2** | 6.5 |
| 50–100 | 195 | **21.5** | 17.1 |
| 100–150 | 219 | **40.6** | 31.9 |
| 150–200 | 183 | **41.3** | 40.3 |
| 200+ | 212 | **44.5** | 37.8 |

Same shape, and the fitted slope is nearly identical:

- **2017–2025 pooled:** σ = 11.13 + **0.1607** × adp
- **2026:** σ = 6.55 + **0.1580** × adp

Uncertainty grows about fourfold from the top of the board to the deep rounds.
The slope replicating to three decimals across six seasons and two independent
measurements is about as strong as this dataset gets.

`variable_py` — the `10 + 0.1 × adp` formula sitting switched off in
`config.py` behind `USE_VARIABLE_SIGMA` — is the **best-fitting model in all
five seasons**, as it was in 2026. The case for re-opening that rejection is
now six seasons deep rather than one.

### The keeper adjustment undershoots by the same amount — replicates

Raw residuals run −15 to −25 picks: with ~40 players off the board, everyone
else goes markedly earlier than their bare rank. Subtracting keepers ranked
above each player removes nearly all of it:

| Season | Raw mean | Keeper-adjusted mean |
|---|---|---|
| 2020 | −25.3 | **+7.4** |
| 2024 | −20.7 | **+7.8** |
| 2025 | −20.1 | **+9.6** |
| 2023 | −20.5 | **+11.2** |
| 2017 | −15.3 | +20.7 |
| *2026* | *−38.7* | *+9.2* |

Four of five seasons land between +7.4 and +11.2 against 2026's +9.2. The
adjustment is directionally right and slightly undershooting, by a consistent
and now well-measured margin.

### Manager reach/wait — does NOT replicate

This is the one to act on, because it points the opposite way from
`RETROSPECTIVE_2026.md` recommendation 5.

| | picks |
|---|---|
| Spread between managers (pooled 2017–2025) | 28.2 |
| Mean spread *within* a manager across seasons | **30.5** |

A manager varies as much from year to year as managers differ from each other.
The identities do not carry either: Tim Riker was 2026's hardest reacher at
−42.5, and sits mid-pack at +2.2 across 2017–2025; Harris Cook was 2026's
biggest waiter and is also mid-pack here.

**So the 2026 per-manager residuals should not be fed into
`draft_engine._opponent_pick`.** They measured one season of a quantity that
moves by ~30 picks a season. The 46-pick spread that looked like a clean signal
in 2026 is within the range a single manager covers between two seasons. The
underlying model change — that opponents are not uniform noise around ADP — may
still be right, but per-manager constants estimated from one season are not the
way to express it.

### Market versus realized

"Board versus market" cannot be reproduced before 2026, because it needs a
projection board and none exists. The answerable question is how well the
preseason market predicted realized value — the bar any board must clear:

| Season | 2017 | 2020 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|
| Spearman ρ | 0.47 | 0.35 | 0.46 | 0.38 | 0.45 |

The market lands around ρ ≈ 0.40–0.47, with 2020's short season the worst. For
scale, `RETROSPECTIVE_2026.md` measured THE BAT X at ρ = 0.741 for hitters and
0.610 for pitchers against realized value — but over a different pool and
against a per-pool board rather than a single mixed ranking, so the two are not
directly comparable and the gap should not be read as the app's edge.

---

## Phase 6 — does the engine over-disperse in every season?

The 2026 retrospective's largest measured effect was that the board spreads
players ~25% further apart than reality: a calibration slope of 0.759 for
hitters and 0.722 for pitchers, from one season. Twelve seasons of regenerated
projections say **yes for pitchers, emphatically; for hitters, weakly.**

| Pool | Mean slope (ex-2020) | Seasons below 1 | 2026 (THE BAT X) |
|---|---|---|---|
| **Pitchers** | **0.699** (range 0.625–0.823) | **11 / 11** | 0.722 |
| Hitters | 0.885 (range 0.804–1.049) | 9 / 11 | 0.759 |

**Read the caveat before the numbers.** No archived preseason projections exist
before 2026, so these are regenerated with `generate_projections_from_stats` —
the app's own weighted, age-adjusted three-season average. That model scored
0.639 rank correlation for hitters in 2026 against THE BAT X's 0.741. **These
are the trend model's slopes, not THE BAT X's**, and this is not a replication
of the 2026 figure.

What it *is* good for is the thing the plan wanted separated: telling
"the projections over-disperse" apart from "the SGP conversion over-disperses".

**For pitchers the answer is now fairly clear.** A completely different
projection model, over twelve seasons, lands at 0.699 against THE BAT X's 0.722
in 2026 — same direction, near-identical magnitude, every single season below
1. Two unrelated forecasters producing the same dispersion error points at the
shared component: the valuation engine, not the forecast. Shrinkage for
pitchers is well supported.

**For hitters it is not.** The trend model averages 0.885 and *exceeds* 1 in
2022 and 2023 — no over-dispersion at all in those years. THE BAT X's 0.759 in
2026 is well outside this model's usual range, which is consistent with a good
part of the 2026 hitter figure being specific to that source and season rather
than structural. The shrinkage recommendation should be applied to pitchers
with confidence and to hitters cautiously, ideally re-derived per pool rather
than using one shrinkage constant for both.

**2020 is excluded from the means** and reported separately: over 60 games the
slope collapses to 0.316 for hitters and 0.232 for pitchers. That is the sample
size, not the model.

Two further limits worth carrying:

- **The pool is wider than the app's board** — 1,000–1,700 hitters against the
  ~660 THE BAT X covers. A wider pool contains more easy-to-rank bad players,
  which inflates rank correlation and can flatten a regression slope. The
  cross-model comparison above is therefore directional, not exact.
- **The trend model is not the shipped board.** `RETROSPECTIVE_2026.md`
  recommends retiring `trend` from valuation precisely because it is worse.
  Nothing here argues for its return; it is used only as an independent second
  opinion on dispersion.

Lookahead — the trap that would make all of this meaningless — is guarded by
`tests/backend/analysis/test_projection_scoping.py`, which generates a season
with and without its own and later seasons present and requires identical
output. The scoping was already correct. The test did catch a second, subtler
leak: the generator selected on `is_active = 1`, i.e. today's roster, which
would have run every historical backtest over only the players who turned out
to have long careers.

---

## The data, and what Phase 0 found

`backend/scripts/history_import.py` extracts the 72-sheet workbook into
committed JSON under `backend/data/fixtures/league_history/`. Nothing is
repaired; 31 remaining parse issues are recorded in `manifest.json`, and every
one has been checked and is real data rather than parser failure.

| Season | Picks | Owners | Rounds | Layout |
|---|---|---|---|---|
| 2010 | 156 | 12* | 16 | positional |
| 2011 | 168 | 12* | 18 | positional |
| 2012 | 180 | 10 | 19 | positional |
| 2013 | 190 | 10 | 20 | positional |
| 2014 | 200 | **8** | 25 | positional |
| 2016–2017 | 250 | 10 | 25–27 | positional |
| 2018–2025 | 250 | 10 | 25–27 | numbered |

\* franchise-name aliases, not real teams — see below.

Four things the plan did not anticipate:

**The 2015 draft is not missing.** It was pasted below the keeper table on the
`2015 Keepers` sheet, as was 2016's. Neither is a full draft — both hold only
the ~40 slots keepers consumed — so they are stored as `pick_slots` inside
`keepers_YYYY.json` rather than as drafts. **2021 is genuinely missing**, and
that is why 2021 has no keeper row here.

**The league was not always ten teams of 25 rounds.** 2014 was an eight-team
league; rounds ran 16 to 20 from 2010 to 2013. Any pre-2016 analysis has to read
the roster shape from the manifest rather than assume it.

**Supplemental rounds were being misattributed.** A bare `Supplemental` heading
carries no round number, and attributing its picks to the preceding round made
every season from 2016 to 2025 appear to have an overfull round 25. Fixed;
supplemental picks are flagged and excluded from round-shape checks.

**Pre-2014 franchise names need a mapping table before those seasons are
usable.** `Atlanta Bombers (from Jeff Goldblum)` is the Bombers making a traded
pick, now split into `acquired_from` — that alone took 2010 from 28 apparent
owners to 12. The residue is aliasing (`Armada` / `Mid-Atlantic Armada`,
`Long island Toast` / `Long Island Toast`). Player-level analysis is unaffected;
manager-level analysis of 2010–2011 is not yet safe.

### Name resolution came out far better than expected

The plan expected resolution to degrade with age — 100% for 2025 down to 69% for
2018 — and warned that a partially resolved season is a biased season, because
the players who fail to resolve are systematically the older ones.

Resolving against **each season's own MLB roster** (`sports/1/players?season=`)
rather than the current `players` table removes the problem entirely:

| | 2018 | 2020 | worst season | all sixteen |
|---|---|---|---|---|
| Against `players` (as planned) | 69% | 90% | — | — |
| Against that season's roster | **99.6%** | **99.6%** | 98.8% (2011) | ≥ 98.8% |

Every season clears the 90% floor by a wide margin, so none is excluded. Three
further passes matter:

- **Same-season name collisions are broken by the draft sheet's position
  column.** This is what separates the two Will Smiths (a catcher and a
  reliever) and the three Luis Garcias.
- **A player absent all season is resolved from an adjacent season** — Gerrit
  Cole in 2025, Trevor Bauer in 2022 — so his pick is valued at **zero** rather
  than dropped. Dropping them would make every draft look better than it was.
- **Roster rows are deduplicated by `mlb_id`.** The adjacent-season fallback
  concatenates two rosters, so anyone who played both arrives twice and reads
  as a same-name collision. That bug dropped exactly three keepers — Tatis in
  2022, Edwin Díaz in 2023, Eury Pérez in 2024 — every one of them a player who
  missed his entire season. A failure-biased exclusion of three in 360 moved
  the headline by less than a point, but it is the precise bias this phase
  exists to avoid, so it is guarded by a test.

The 15 names still unresolved league-wide are genuine: same-name pairs the
position column cannot split (Luis García ×3), players who never appeared in
the season they were drafted for (Forrest Whitley, Andrew Painter), and two
mid-career name changes (Leo Núñez, Felipe Rivero).

There is deliberately **no "unique last name in this season" matching pass.** It
is tempting and wrong: it mapped Gerrit Cole onto Zach Cole and Pete
Crow-Armstrong onto Shawn Armstrong. A mis-resolution is invisible downstream —
the player simply carries someone else's season — so the bar is set at the point
where failing to resolve is the safer error.

---

## The one thing that needs fixing in code

`KEEPER_HISTORY` in `src/lib/draft-history.ts` drives what the app shows on the
keepers page. Against the workbook it has:

- **22 fabricated 2026 entries.** Gunnar Henderson, Michael Harris II, Spencer
  Strider, Julio Rodríguez and others are listed as 2026 keepers with round cost
  and seasons-kept **identical to their 2025 row**. The 2026 Keepers sheet does
  not list them as keepers at all. The 2026 rows appear to have been copied
  forward from 2025 rather than recorded.
- **Seven historical manager relabellings.** Zac Gallen, Tyler Glasnow and
  Fernando Tatis Jr. for 2023–2024 are attributed to Russell Berry, who did not
  join the league until 2026. Those seasons were Chris Herbst's.
- **Round-cost and seasons-kept drift.** Tarik Skubal's 2026 cost is recorded as
  R19/yr2; the sheet says R14/yr3, which is what the doctrine requires
  (19 − 5 = 14). Ketel Marte, Paul Skenes, Bryan Woo, Jackson Chourio,
  Lawrence Butler and others show the same one-season lag.

Where the league's doctrine can adjudicate — cost drops five rounds per extra
season, floored at round 1 — the **workbook obeys it 12 times and the curated
file zero.** The workbook is the authority.

The workbook is wrong in exactly one place found so far: the 2023 sheet spells
Eric Mercado as "Eric Mercardo".

Full detail in `keeper_history_crosscheck.json`, reproducible with
`python -m backend.scripts.history_crosscheck`.

---

## How to reproduce

```bash
# Phase 0 — extract the workbook (not in git; 7.5 MB, 72 sheets)
.venv/bin/python -m backend.scripts.history_import \
    --workbook ~/Downloads/"2026 Juiced Fantasy Baseball Draft.xlsx"

# Phase 1 — resolve names against each season's own MLB roster
.venv/bin/python -m backend.scripts.history_resolve
.venv/bin/python -m backend.scripts.history_crosscheck

# Phase 2 — backfill realized stats, quality starts derived from game logs
.venv/bin/python -m backend.scripts.history_backfill_stats

# Phase 4 prerequisite — the FULL pool, not just draftees (two calls a season,
# plus game logs for the ~370 pitchers a season who started a game)
.venv/bin/python -m backend.scripts.history_backfill_pool

# Phases 3 and 4
.venv/bin/python -m backend.scripts.history_keepers
.venv/bin/python -m backend.scripts.history_value_curve

# Phase 5 — market baseline (needs the ranking names resolved first)
.venv/bin/python -m backend.scripts.history_resolve_rankings
.venv/bin/python -m backend.scripts.history_market

# Phase 6 — regenerated projections (excludes 2026: its trend rows feed the
# Layer D comparison in RETROSPECTIVE_2026.md)
.venv/bin/python -m backend.scripts.history_valuation
```

Artifacts land in `backend/data/fixtures/league_history/`. The two backfills are
the slow steps and the only ones needing the network beyond the roster cache.
Every analysis step is deterministic and can be re-run to byte-identical output
— which was not true until the hash-seed bug described below was fixed.

---

## Limits

- **These decisions were not made by the app.** It did not exist before 2026.
  This measures ten managers' keeper judgement, which is a useful human
  baseline and a different question from whether the software helps. The 2026
  season is the only one where both can be asked, and it is *not* included here
  — its Draft tab is an empty template, so 2026 keepers remain covered only by
  `RETROSPECTIVE_2026.md`.
- **Quality starts are derived, not reported.** MLB's season endpoint does not
  expose them. They come from game logs, and one transient DNS failure during
  the first backfill silently zeroed a pitcher's QS before the season was
  re-run — worth watching for, since a zero in one of four pitcher categories
  is invisible in aggregate.
- **Realized value ≠ what a manager could have known.** The 73.3% says keeping
  worked, not that it was predictable. The prior-season baseline at 71.7% is the
  closest available answer to the predictability question, and it is a weak
  model.
- **One league, ten teams.** Nine seasons of the same ten managers is not nine
  independent samples of "how keepers work in general".
- **2021 has no draft or keeper sheet**, and 2015's draft is only its keeper
  slots. Neither season contributes a keeper row.

## What to do next

Every phase in the plan is complete. Three things follow from it, in order of
confidence:

1. **Apply shrinkage per pool, not globally.** Implemented behind
   `ValuationConfig.hitter_shrinkage` / `pitcher_shrinkage`, defaulting to 1.0
   so no board changes until a caller opts in. Phase 6's clearest result:
   pitchers over-disperse in 11 of 11 seasons at 0.699, closely matching 2026's
   0.722 from an unrelated forecaster, so the effect is in the engine rather
   than the source. Hitters average 0.885 and exceed 1 twice.

   **The two factors must be measured on the same board.** What rebalances
   hitters against pitchers is the *ratio* of the factors, so pairing the trend
   model's hitter slope with THE BAT X's pitcher slope measures the gap between
   two forecasters, not calibration. That mistake gives a ratio of 1.22 and
   moves 13 pitchers out of the top 100; the pair measured on the same 2026
   board gives 1.05 and moves 3. Recommended values are therefore both from
   THE BAT X 2026 — hitters 0.759, pitchers 0.722 — with the multi-season work
   serving as evidence *about* those numbers rather than a source for them.

   Note what shrinkage cannot do: the transform is monotonic, so it never
   reorders a pool. Hitters rank against hitters exactly as before. It changes
   the hitter/pitcher interleave and the size of every value difference, which
   is what keeper surplus, VONA and urgency are built from.
2. **Re-open `USE_VARIABLE_SIGMA`.** The residual-spread law now holds across
   six seasons (σ = 11.13 + 0.161 × adp against 2026's 6.55 + 0.158). But the
   2026 caveat stands: it was rejected on *simulated draft outcomes*, a
   different question from availability-model calibration, so the simulation
   experiment needs re-running rather than the flag simply flipping.
3. **Replace `expectedValueAtRound` with the fitted curve — modest, and easy to
   get backwards.** The baseline is too high in every season, so the app does
   understate keeper surplus, but on the shipped board the bias is ~0.26 SGP
   over the early rounds, not the 2.2 an earlier draft of this document
   reported. Derive the correction on the projected board. Fitting the curve to
   *realized* values would deflate the baseline while player values stayed
   projected — a unit mismatch that overstates surplus and is worse than doing
   nothing.

And one thing not to do: **do not feed the 2026 per-manager ADP residuals into
the opponent model.** Phase 5 shows managers vary more between their own seasons
than they differ from each other.
