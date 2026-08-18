# Multi-Season Backtest: Keeper Outcomes, 2016–2025

**Status:** Phases 0–3 complete. Phases 4–6 (value-at-pick curve, ADP
replication, regenerated projections) are unblocked but not run.
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
| Beat what their round returned | 70% | **72.5%** (95% CI 68.1–76.9) |
| Control: ordinary picks beating their round | not measured | **50.1%** (n=1,848) |

The control is what makes the headline readable. Value within a round is
right-skewed, so an ordinary pick clears its round's mean about half the time.
Keepers clear it 72.5% of the time — **22 points above the null, far outside the
confidence interval.** Keeping is a real edge, worth **+2.86 SGP per decision**
(CI +2.36 to +3.36) over letting the player go and drafting that round normally.

Three secondary results, all with the sample to support them:

1. **Surplus does not vary with round cost.** Slope +0.048 SGP per round, CI
   [−0.013, +0.107] — flat. The round-cost model is not mispriced at either end.
2. **Multi-season keepers hold up.** Year 3 keepers beat their round 74.3% of
   the time at a mean cost of round 7.8, against 73.5% for year 1 at round 15.6.
   Paying five rounds more per season neither gains nor loses ground.
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
had in February. That baseline's sign agreed with the outcome **68.9%** of the
time (CI 64.4–73.6). It is **not** the app's board and must not be reported as
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
| < 5 non-keeper picks | 79 | 72.2% | +2.50 |
| ≥ 5 non-keeper picks | 281 | 72.6% | +2.96 |

Identical. The headline does not depend on the thin rounds.

### Season to season

| Season | Keepers | Beat rate |
|---|---|---|
| 2016 | 40 | 70.0% |
| 2017 | 40 | 77.5% |
| 2018 | 40 | 67.5% |
| 2019 | 40 | 77.5% |
| 2020 | 40 | **57.5%** |
| 2022 | 40 | 70.0% |
| 2023 | 40 | **80.0%** |
| 2024 | 40 | 75.0% |
| 2025 | 40 | 77.5% |

Seven of nine land between 67.5% and 77.5%. The two outliers are 2020 — the
60-game COVID season, where small samples make every projection worse — and
2023. On n=40 per season, that spread is what the 2026 confidence interval
predicted; it is the reason a single season could not answer this question.

### Keeping longer keeps working

| Seasons kept | n | Mean round cost | Mean surplus | 95% CI | Beat rate |
|---|---|---|---|---|---|
| 1 | 204 | 15.6 | +2.95 | +2.30 to +3.58 | 73.5% |
| 2 | 74 | 12.8 | +2.79 | +1.65 to +3.98 | 73.0% |
| 3 | 35 | 7.8 | +3.27 | +1.70 to +4.87 | 74.3% |

The cost escalation is doing its job. A year-3 keeper costs roughly eight rounds
more than a year-1 keeper and returns the same surplus within the confidence
intervals, which says the five-rounds-per-season rule is priced about right
rather than generous. There is no decay to correct for.

### Best and worst decisions

| | Season | Cost | Surplus |
|---|---|---|---|
| Shane Bieber (Harris Cook) | 2020 | R12, yr 1 | **+17.05** |
| Cody Bellinger (Harris Cook) | 2019 | R18, yr 2 | +15.24 |
| Charlie Blackmon (John Gibbons) | 2017 | R10, yr 3 | +14.64 |
| Gunnar Henderson (Tim Riker) | 2024 | R20, yr 2 | +14.48 |
| … | | | |
| Alek Manoah (David Rotatori) | 2023 | R19, yr 2 | −9.28 |
| Ronald Acuña (Jason McComb) | 2024 | R1, yr 1 | **−12.21** |

### Managers look different, but not measurably so

Mean surplus per manager runs from John Gibbons at +3.95 to Jason McComb at
+0.82 — a spread that looks like a story and is not one. Every manager's
confidence interval overlaps the next, and the extremes overlap too (Gibbons
+2.26 to +5.59; McComb −0.80 to +2.31). On 28–36 decisions each, **this is
noise, and is reported as no finding.**

That is the opposite of the ADP reach/wait result in `RETROSPECTIVE_2026.md`,
which was a 46-pick spread measured over hundreds of picks. Keeper skill, if it
exists here, is smaller than this sample can see.

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

# Phase 3 — keeper outcomes
.venv/bin/python -m backend.scripts.history_keepers
```

Artifacts land in `backend/data/fixtures/league_history/`. Phase 2 is the only
slow step (~4,800 player-seasons) and the only one that needs the network for
anything but the roster cache.

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
- **Realized value ≠ what a manager could have known.** The 72.5% says keeping
  worked, not that it was predictable. The prior-season baseline at 68.9% is the
  closest available answer to the predictability question, and it is a weak
  model.
- **One league, ten teams.** Nine seasons of the same ten managers is not nine
  independent samples of "how keepers work in general".
- **2021 has no draft or keeper sheet**, and 2015's draft is only its keeper
  slots. Neither season contributes a keeper row.

## What is now unblocked

Phases 4–6 need no new extraction. The value-at-pick curve is already computed
and stored per season in `keeper_outcomes.json` (`value_curve` and
`value_curve_excluding_keepers`), which is most of Phase 4. The ESPN top-300
sheets for 2017, 2020, 2021, 2023, 2024, 2025 and 2026 are parsed into
`rankings_YYYY.json` for Phase 5. Phase 6 remains the one carrying real risk,
and the plan's warning stands: **a regenerated projection scoped to its own
season produces a spectacular backtest that means nothing, and looks entirely
normal.** Write the failing test first.
