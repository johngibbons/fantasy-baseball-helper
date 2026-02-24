# Historical Draft Data Improvements

Sourced from the league's master spreadsheet (2017–2025):
https://docs.google.com/spreadsheets/d/1DtC9isTCknEFil9A08416kgjF9oOLv6YxIp6R3ykldM

## Available Data

- 9 years of full draft results (250 picks/year): round, pick, manager, player, position, keeper flag, trade notes
- Keeper selections per year (player, round cost, seasons kept)
- Pick trades between managers
- Record book (championships, all-time standings, seasonal records)

---

## 1. Manager Draft Tendencies (high impact)

**Goal:** Show during the draft how each manager historically drafts — positional preferences, tendency to reach vs. take value, round-by-round patterns.

**How it helps:** The pick predictor currently uses a generic normal distribution around ESPN ADP (σ=18). With manager tendency data, it can factor in *who's picking next* and their positional preferences to give better availability estimates.

**Examples:**
- "Tim Riker historically drafts SP heavy in rounds 4–8"
- "Jason McComb tends to reach for closers"
- "Harris Cook prioritizes pitching early"

**Status:** Done — `src/lib/draft-history.ts` + tendencies panel on draft board. Shows manager labels, first SP/RP/C round averages, early-round position % bar chart, and position run alerts.

---

## 2. League-Specific Positional ADP (high impact)

**Goal:** Compute where each position typically gets drafted in *this league* rather than relying on ESPN general population ADP.

**How it helps:** This league drafts differently than the general population. Historical data can show "catchers typically go in rounds 8–12" or "there's usually a closer run in round 11." Improves the availability model in `pick-predictor.ts` and helps time position runs.

**Status:** Done — `LEAGUE_POS_ADP` data in `src/lib/draft-history.ts`. Sidebar "League Position Timing" grid highlights active position windows. Position badges have hover tooltips with league ADP info.

---

## 3. Keeper Cost Escalation Tracker (medium impact)

**Goal:** Show the full lifecycle of keepers — which players were worth keeping across multiple years, when escalating round cost made them unviable.

**How it helps:** The keeper page already does surplus value analysis, but historical data would show real examples from this league. Useful for evaluating 2026 keeper decisions.

**Status:** Done — `KEEPER_HISTORY` data in `src/lib/draft-history.ts` with `getKeeperHistory()` helper. Collapsible "Keeper History" panel in keepers page sidebar shows multi-year keeper lifecycles with escalating round costs, active keeper badges, and manager attribution.

---

## 4. "Draft History" Column on Draft Board (low effort)

**Goal:** Simple annotation on the draft board showing "Last drafted: Rd 3 (2025)" next to each player.

**How it helps:** Quick reality check against the model's ranking — see where a player actually went last year in this league.

**Status:** Done — `RECENT_DRAFT_HISTORY` map in `src/lib/draft-history.ts` with `getDraftHistory()` lookup and `normalizeName()` matching. Subtle "Rd X 'YY" annotation below player names on the draft board for ~300 players from 2023–2025 drafts.
