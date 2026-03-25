# Start/Sit SP Recommendations — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a mobile-friendly start/sit recommendation page for starting pitchers that combines PitcherList rankings with weekly H2H matchup context.

**Architecture:** Three layers — (1) PitcherList scraper fetches weekly pitcher rankings, (2) optimization engine classifies matchup state and adjusts recommendations based on category leverage and remaining weekly exposure, (3) Next.js orchestration route ties ESPN matchup data to Python backend. Credential migration stores ESPN auth in DB so it works across devices.

**Tech Stack:** Python/FastAPI backend, Next.js frontend, BeautifulSoup for scraping, Prisma/PostgreSQL for credential storage, ESPN Fantasy API for matchup data.

**Spec:** `docs/superpowers/specs/2026-03-25-start-sit-sp-recommendations-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `backend/data/pitcherlist.py` | Create | PitcherList weekly scraper — discover article, parse HTML tables, cache by week |
| `backend/analysis/start_sit.py` | Create | Optimization engine — classify categories, compute exposure, apply decision matrix, generate rationale |
| `backend/api/routes.py` | Modify (append) | Add `POST /api/start-sit` endpoint |
| `src/lib/espn-api.ts` | Modify (append) | Add `getMatchupScoreboard()` method |
| `src/app/api/leagues/[leagueId]/credentials/route.ts` | Create | PUT endpoint to store/retrieve ESPN credentials in league.settings |
| `src/app/api/start-sit/route.ts` | Create | Next.js orchestration — fetch ESPN data, call Python backend |
| `src/app/start-sit/page.tsx` | Create | Frontend page — matchup summary, recommendations, upcoming starts |
| `src/components/Navigation.tsx` | Modify | Add Start/Sit nav link |
| `src/app/waivers/page.tsx` | Modify | Remove localStorage credentials, use DB-stored credentials |
| `src/app/trades/page.tsx` | Modify | Remove localStorage credentials, use DB-stored credentials |
| `src/app/api/waivers/recommendations/route.ts` | Modify | Read credentials from DB instead of POST body |
| `src/app/api/trades/suggestions/route.ts` | Modify | Read credentials from DB instead of POST body |
| `tests/backend/test_start_sit.py` | Create | Unit tests for optimization engine |
| `tests/backend/test_pitcherlist.py` | Create | Unit tests for PitcherList scraper/parser |

---

## Task 1: Credential Storage API

Store ESPN credentials in the League model's existing `settings` JSON field under a `credentials` key. This is a prerequisite for all subsequent tasks.

**Files:**
- Create: `src/app/api/leagues/[leagueId]/credentials/route.ts`

- [ ] **Step 1: Create the credentials API route**

```typescript
// src/app/api/leagues/[leagueId]/credentials/route.ts
import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ leagueId: string }> }
) {
  const { leagueId } = await params
  const league = await prisma.league.findUnique({ where: { id: leagueId } })
  if (!league) {
    return NextResponse.json({ error: 'League not found' }, { status: 404 })
  }
  const settings = league.settings as any
  const credentials = settings?.credentials || null
  // Don't expose full espn_s2 — just indicate if credentials are set
  return NextResponse.json({
    has_credentials: !!(credentials?.espn_s2 && credentials?.swid),
    default_team_id: credentials?.default_team_id || null,
  })
}

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ leagueId: string }> }
) {
  const { leagueId } = await params
  const body = await request.json()
  const { espn_s2, swid, default_team_id } = body

  if (!espn_s2 || !swid) {
    return NextResponse.json(
      { error: 'Missing required fields: espn_s2, swid' },
      { status: 400 }
    )
  }

  const league = await prisma.league.findUnique({ where: { id: leagueId } })
  if (!league) {
    return NextResponse.json({ error: 'League not found' }, { status: 404 })
  }

  // Merge credentials into existing settings (never overwrite the whole object)
  const existingSettings = (league.settings as any) || {}
  const updatedSettings = {
    ...existingSettings,
    credentials: { espn_s2, swid, default_team_id: default_team_id || null },
  }

  await prisma.league.update({
    where: { id: leagueId },
    data: { settings: updatedSettings },
  })

  return NextResponse.json({ ok: true })
}
```

- [ ] **Step 2: Manually test the credentials endpoint**

Start the dev server and test with curl:
```bash
# Replace LEAGUE_ID with an actual league ID from your DB
curl -X PUT http://localhost:3000/api/leagues/LEAGUE_ID/credentials \
  -H 'Content-Type: application/json' \
  -d '{"espn_s2": "test_token", "swid": "{test_swid}", "default_team_id": "5"}'

# Verify it was stored
curl http://localhost:3000/api/leagues/LEAGUE_ID/credentials
```

Expected: PUT returns `{"ok": true}`, GET returns `{"has_credentials": true, "default_team_id": "5"}`

- [ ] **Step 3: Commit**

```bash
git add src/app/api/leagues/\[leagueId\]/credentials/route.ts
git commit -m "Add credentials storage API route for ESPN auth"
```

---

## Task 2: ESPN Matchup Scoreboard Method

Add a method to the ESPN API client to fetch current matchup category totals.

**Files:**
- Modify: `src/lib/espn-api.ts` (append new method)

- [ ] **Step 1: Add `getMatchupScoreboard` to ESPNApi**

Append to `src/lib/espn-api.ts`, inside the `ESPNApi` class, after the `testConnection` method:

```typescript
  static async getMatchupScoreboard(
    leagueId: string,
    season: string,
    settings: ESPNLeagueSettings,
    matchupPeriodId: number,
  ): Promise<{
    schedule: Array<{
      matchupPeriodId: number
      home: { teamId: number; cumulativeScore?: { scoreByStat?: Record<string, { score: number; result: string }> } }
      away: { teamId: number; cumulativeScore?: { scoreByStat?: Record<string, { score: number; result: string }> } }
    }>
  }> {
    const url = `https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb/seasons/${season}/segments/0/leagues/${leagueId}?view=mMatchupScore&view=mScoreboard`

    const response = await fetch(url, {
      headers: this.getHeaders(settings),
    })

    if (!response.ok) {
      throw new Error(`ESPN API error: ${response.status} - ${response.statusText}`)
    }

    const data = await response.json()
    // Filter to current matchup period
    const schedule = (data.schedule || []).filter(
      (m: any) => m.matchupPeriodId === matchupPeriodId
    )

    return { schedule }
  }
```

- [ ] **Step 2: Test the new method with a debug route**

Create a temporary test by adding a quick log call or test route. Verify the response shape by checking that `scoreByStat` contains numeric keys and `{score, result}` values. Log the stat IDs to confirm the mapping for our 10 categories.

```bash
# Can test by temporarily calling from an existing route or creating a quick script
```

- [ ] **Step 3: Commit**

```bash
git add src/lib/espn-api.ts
git commit -m "Add ESPN matchup scoreboard method for H2H category totals"
```

---

## Task 3: PitcherList Scraper

Build the scraper that discovers and parses the weekly Sit/Start article.

**Files:**
- Create: `backend/data/pitcherlist.py`
- Create: `tests/backend/test_pitcherlist.py`

- [ ] **Step 1: Create test directory structure**

```bash
mkdir -p tests/backend
touch tests/__init__.py tests/backend/__init__.py
```

- [ ] **Step 2: Write parser tests with sample HTML**

```python
# tests/backend/test_pitcherlist.py
"""Tests for PitcherList Sit/Start article parser."""

import pytest
from backend.data.pitcherlist import parse_sit_start_tables, map_tier

# Sample HTML fragment mimicking PitcherList table structure
SAMPLE_TABLE_HTML = """
<table>
<thead><tr><th>Date</th><th>Game</th><th>Pitcher</th><th>Rating</th></tr></thead>
<tbody>
<tr><td>Wednesday 3/25</td><td>LAD @ CIN</td><td>Corbin Burnes</td><td>Start-8</td></tr>
<tr><td>Wednesday 3/25</td><td>NYY @ BOS</td><td>Gerrit Cole</td><td>Maybe-4</td></tr>
<tr><td>Wednesday 3/25</td><td>COL @ SF</td><td>Logan Webb</td><td>Sit-2</td></tr>
<tr><td>Thursday 3/26</td><td>ARI @ MIL</td><td>Zack Wheeler</td><td>Start-9</td></tr>
</tbody>
</table>
"""


class TestParseSitStartTables:
    def test_parses_pitcher_entries(self):
        entries = parse_sit_start_tables(SAMPLE_TABLE_HTML)
        assert len(entries) == 4

    def test_extracts_pitcher_name(self):
        entries = parse_sit_start_tables(SAMPLE_TABLE_HTML)
        names = [e["pitcher_name"] for e in entries]
        assert "Corbin Burnes" in names
        assert "Gerrit Cole" in names

    def test_extracts_tier_and_score(self):
        entries = parse_sit_start_tables(SAMPLE_TABLE_HTML)
        burnes = next(e for e in entries if e["pitcher_name"] == "Corbin Burnes")
        assert burnes["raw"] == "Start-8"
        assert burnes["tier"] == "Start"
        assert burnes["score"] == 8

    def test_extracts_opponent(self):
        entries = parse_sit_start_tables(SAMPLE_TABLE_HTML)
        burnes = next(e for e in entries if e["pitcher_name"] == "Corbin Burnes")
        assert "CIN" in burnes["opponent"] or "LAD" in burnes["opponent"]

    def test_extracts_date(self):
        entries = parse_sit_start_tables(SAMPLE_TABLE_HTML)
        burnes = next(e for e in entries if e["pitcher_name"] == "Corbin Burnes")
        assert "3/25" in burnes["date"]


class TestMapTier:
    def test_strong_start(self):
        assert map_tier("Start", 8) == "strong_start"
        assert map_tier("Start", 10) == "strong_start"

    def test_start(self):
        assert map_tier("Start", 6) == "start"
        assert map_tier("Start", 1) == "start"

    def test_maybe(self):
        assert map_tier("Maybe", 4) == "maybe"

    def test_sit(self):
        assert map_tier("Sit", 2) == "sit"
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd /Users/jgibbons/code/fantasy-baseball-helper
python -m pytest tests/backend/test_pitcherlist.py -v
```

Expected: ImportError — `backend.data.pitcherlist` doesn't exist yet.

- [ ] **Step 4: Implement the PitcherList parser**

```python
# backend/data/pitcherlist.py
"""PitcherList Sit/Start article scraper and parser."""

from __future__ import annotations

import logging
import re
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# In-memory cache: {week_key: {"entries": [...], "fetched_at": timestamp}}
_cache: dict[str, dict] = {}
CACHE_TTL_SECONDS = 6 * 3600  # 6 hours


def map_tier(tier: str, score: int) -> str:
    """Map PitcherList tier+score to our recommendation tiers."""
    if tier == "Start" and score >= 7:
        return "strong_start"
    elif tier == "Start":
        return "start"
    elif tier == "Maybe":
        return "maybe"
    else:
        return "sit"


def parse_rating(raw: str) -> tuple[str, int]:
    """Parse a rating string like 'Start-8' into ('Start', 8)."""
    match = re.match(r"(Start|Maybe|Sit)-(\d+)", raw.strip())
    if match:
        return match.group(1), int(match.group(2))
    return "Maybe", 1  # fallback


def parse_sit_start_tables(html: str) -> list[dict]:
    """Parse PitcherList Sit/Start HTML tables into structured entries.

    Returns list of dicts with keys: pitcher_name, opponent, date, tier, score, raw, mapped_tier
    """
    soup = BeautifulSoup(html, "html.parser")
    entries = []

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all(["td", "th"])
            if len(cells) < 4:
                continue

            cell_texts = [c.get_text(strip=True) for c in cells]

            # Skip header rows
            if cell_texts[0].lower() in ("date", "day", ""):
                continue

            # Look for a rating pattern (Start-N, Maybe-N, Sit-N) in any cell
            rating_cell = None
            rating_idx = None
            for i, text in enumerate(cell_texts):
                if re.match(r"(Start|Maybe|Sit)-\d+", text):
                    rating_cell = text
                    rating_idx = i
                    break

            if not rating_cell:
                continue

            # Heuristic column mapping — the rating cell tells us where things are
            # Typical: Date | Game/Matchup | Pitcher | Rating
            # But column order may vary; we identify by content
            date_text = cell_texts[0]
            pitcher_name = cell_texts[rating_idx - 1] if rating_idx > 0 else cell_texts[-2]
            opponent = cell_texts[1] if len(cell_texts) > 2 else ""

            tier, score = parse_rating(rating_cell)

            entries.append({
                "pitcher_name": pitcher_name,
                "opponent": opponent,
                "date": date_text,
                "tier": tier,
                "score": score,
                "raw": rating_cell,
                "mapped_tier": map_tier(tier, score),
            })

    return entries


def discover_latest_article_url() -> Optional[str]:
    """Find the URL of the latest PitcherList Sit/Start article.

    Searches the PitcherList homepage/category pages for the most recent
    article with 'Sit/Start' in the title.
    """
    search_urls = [
        "https://www.pitcherlist.com",
    ]

    for base_url in search_urls:
        try:
            resp = requests.get(base_url, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            for link in soup.find_all("a", href=True):
                text = link.get_text(strip=True).lower()
                href = link["href"]
                if "sit" in text and "start" in text and "week" in text:
                    if href.startswith("/"):
                        href = f"https://www.pitcherlist.com{href}"
                    logger.info(f"Discovered PitcherList article: {href}")
                    return href
        except Exception as e:
            logger.warning(f"Failed to search {base_url}: {e}")

    logger.error("Could not discover PitcherList Sit/Start article")
    return None


def fetch_weekly_rankings(week_key: str | None = None) -> list[dict]:
    """Fetch and parse the current week's PitcherList Sit/Start rankings.

    Args:
        week_key: Cache key (e.g., "2026-W13"). If None, auto-generates from current date.

    Returns:
        List of pitcher ranking entries, or empty list if scraping fails.
    """
    import datetime

    if week_key is None:
        today = datetime.date.today()
        week_key = f"{today.year}-W{today.isocalendar()[1]:02d}"

    # Check cache
    cached = _cache.get(week_key)
    if cached and (time.time() - cached["fetched_at"]) < CACHE_TTL_SECONDS:
        logger.info(f"PitcherList cache hit for {week_key}")
        return cached["entries"]

    # Discover and fetch article
    url = discover_latest_article_url()
    if not url:
        return []

    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to fetch PitcherList article {url}: {e}")
        return []

    entries = parse_sit_start_tables(resp.text)
    logger.info(f"Parsed {len(entries)} pitcher entries from PitcherList")

    if entries:
        _cache[week_key] = {"entries": entries, "fetched_at": time.time()}

    return entries


def get_rankings_for_date(
    target_date: str, roster_pitcher_names: list[str]
) -> tuple[list[dict], list[dict], list[dict]]:
    """Get today's recommendations, upcoming starts, and off-day pitchers.

    Args:
        target_date: Date string like "2026-03-25" or "3/25"
        roster_pitcher_names: List of pitcher names on user's roster

    Returns:
        (todays_starters, upcoming_starts, off_day_pitchers)
    """
    all_entries = fetch_weekly_rankings()
    if not all_entries:
        return [], [], []

    # Normalize roster names for matching (accent-stripping for names like Jose Berrios)
    import unicodedata

    def _normalize(name: str) -> str:
        nfkd = unicodedata.normalize("NFKD", name)
        return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()

    roster_names_norm = {_normalize(n): n for n in roster_pitcher_names}

    # Separate entries into today vs future
    todays = []
    upcoming = []

    for entry in all_entries:
        entry_norm = _normalize(entry["pitcher_name"])
        if entry_norm not in roster_names_norm:
            continue

        # Simple date matching — check if target_date appears in the entry date
        # PitcherList dates are like "Wednesday 3/25" or "3/25"
        entry_date = entry["date"]
        is_today = _dates_match(target_date, entry_date)

        if is_today:
            todays.append(entry)
        else:
            upcoming.append(entry)

    # Off-day: roster pitchers not appearing in any entry
    all_matched_norm = {_normalize(e["pitcher_name"]) for e in todays + upcoming}
    off_day = [
        {"pitcher_name": name}
        for name in roster_pitcher_names
        if _normalize(name) not in all_matched_norm
    ]

    return todays, upcoming, off_day


def _dates_match(target: str, entry_date: str) -> bool:
    """Check if a target date (2026-03-25) matches an entry date (Wednesday 3/25)."""
    import datetime

    # Parse target date
    try:
        if "-" in target:
            dt = datetime.datetime.strptime(target, "%Y-%m-%d")
        else:
            dt = datetime.datetime.strptime(target, "%m/%d")
        month_day = f"{dt.month}/{dt.day}"
    except ValueError:
        month_day = target

    return month_day in entry_date
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
python -m pytest tests/backend/test_pitcherlist.py -v
```

Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/data/pitcherlist.py tests/
git commit -m "Add PitcherList Sit/Start scraper with parser and tests"
```

---

## Task 4: Start/Sit Optimization Engine

The core logic — classify categories, compute exposure, apply decision matrix.

**Files:**
- Create: `backend/analysis/start_sit.py`
- Create: `tests/backend/test_start_sit.py`

- [ ] **Step 1: Write category classification tests**

```python
# tests/backend/test_start_sit.py
"""Tests for the start/sit optimization engine."""

import pytest
from backend.analysis.start_sit import (
    classify_category,
    compute_ratio_exposure,
    decide_recommendation,
    generate_rationale,
    compute_start_sit_recommendations,
)


class TestClassifyCategory:
    """Test matchup state classification for all category types."""

    def test_counting_stat_winning_big(self):
        # K: yours=60, theirs=30, gap=30, daily_swing=6, gap_in_days=5
        # days_remaining=4, threshold=4*0.8=3.2. 5 > 3.2 -> winning_big
        assert classify_category("K", 60, 30, days_remaining=4) == "winning_big"

    def test_counting_stat_winning_close(self):
        # K: yours=45, theirs=38, gap=7, daily_swing=6, gap_in_days=1.17
        # days_remaining=4, threshold=3.2. 1.17 < 3.2 -> winning_close
        assert classify_category("K", 45, 38, days_remaining=4) == "winning_close"

    def test_counting_stat_losing_close(self):
        # K: yours=38, theirs=45
        assert classify_category("K", 38, 45, days_remaining=4) == "losing_close"

    def test_counting_stat_losing_big(self):
        # K: yours=20, theirs=50, gap=30, gap_in_days=5, threshold=3.2
        assert classify_category("K", 20, 50, days_remaining=4) == "losing_big"

    def test_tied_is_losing_close(self):
        assert classify_category("K", 40, 40, days_remaining=4) == "losing_close"

    def test_rate_stat_era_winning_close(self):
        # ERA gap = 0.20 < 0.30 threshold
        assert classify_category("ERA", 3.12, 3.32, days_remaining=4, team_ip=40) == "winning_close"

    def test_rate_stat_era_winning_big(self):
        # ERA gap = 0.50 >= 0.30 threshold
        assert classify_category("ERA", 3.00, 3.50, days_remaining=4, team_ip=40) == "winning_big"

    def test_rate_stat_low_ip_override(self):
        # ERA gap = 0.50 (normally winning_big) but IP < 15 -> force winning_close
        assert classify_category("ERA", 3.00, 3.50, days_remaining=4, team_ip=10) == "winning_close"

    def test_era_lower_is_better(self):
        # ERA: yours=3.50, theirs=3.00. You have worse ERA -> losing
        assert classify_category("ERA", 3.50, 3.00, days_remaining=4, team_ip=40) == "losing_close"

    def test_whip_classification(self):
        # WHIP gap = 0.05 < 0.08 -> winning_close
        assert classify_category("WHIP", 1.10, 1.15, days_remaining=4, team_ip=40) == "winning_close"


class TestComputeRatioExposure:
    def test_many_starts(self):
        # 5 starts -> ratio_exposure = 5/5 = 1.0
        assert compute_ratio_exposure(total_starts_remaining=5) == 1.0

    def test_few_starts(self):
        # 2 starts -> 2/5 = 0.4
        assert compute_ratio_exposure(total_starts_remaining=2) == 0.4

    def test_one_start(self):
        # 1 start -> 1/5 = 0.2
        assert compute_ratio_exposure(total_starts_remaining=1) == 0.2

    def test_capped_at_one(self):
        # 8 starts -> capped at 1.0
        assert compute_ratio_exposure(total_starts_remaining=8) == 1.0


class TestDecideRecommendation:
    def test_strong_start_default(self):
        cats = {"K": "winning_big", "QS": "winning_big", "ERA": "winning_big", "WHIP": "winning_big"}
        # All winning_big -> safe_sit
        assert decide_recommendation("strong_start", cats, ratio_exposure=0.5) == "safe_sit"

    def test_strong_start_era_close_low_exposure(self):
        cats = {"K": "winning_big", "QS": "winning_big", "ERA": "winning_close", "WHIP": "winning_big"}
        # ERA winning_close + low exposure -> start (downgraded from strong_start)
        assert decide_recommendation("strong_start", cats, ratio_exposure=0.2) == "start"

    def test_strong_start_era_close_high_exposure(self):
        cats = {"K": "winning_big", "QS": "winning_big", "ERA": "winning_close", "WHIP": "winning_big"}
        # ERA winning_close but high exposure -> default column -> strong_start
        assert decide_recommendation("strong_start", cats, ratio_exposure=0.9) == "strong_start"

    def test_start_era_close_low_exposure(self):
        cats = {"K": "winning_big", "QS": "winning_big", "ERA": "winning_close", "WHIP": "winning_close"}
        # Start + ERA close + low exposure -> risky_start
        assert decide_recommendation("start", cats, ratio_exposure=0.3) == "risky_start"

    def test_maybe_k_losing_close(self):
        cats = {"K": "losing_close", "QS": "losing_close", "ERA": "winning_big", "WHIP": "winning_big"}
        # Maybe + K losing_close -> risky_start
        assert decide_recommendation("maybe", cats, ratio_exposure=0.5) == "risky_start"

    def test_sit_always_sit(self):
        cats = {"K": "losing_close", "QS": "losing_close", "ERA": "losing_big", "WHIP": "losing_big"}
        assert decide_recommendation("sit", cats, ratio_exposure=0.5) == "sit"


class TestGenerateRationale:
    def test_includes_pitcherlist_raw(self):
        rationale = generate_rationale(
            pitcherlist_raw="Start-8", opponent="CIN",
            recommendation="start", cats={"ERA": "winning_close"},
            ratio_exposure=0.8, starts_remaining=4,
        )
        assert "Start-8" in rationale
        assert "CIN" in rationale

    def test_safe_sit_rationale(self):
        rationale = generate_rationale(
            pitcherlist_raw="Start-6", opponent="MIA",
            recommendation="safe_sit", cats={"ERA": "winning_big"},
            ratio_exposure=0.2, starts_remaining=1,
        )
        assert "protect" in rationale.lower() or "safe" in rationale.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/backend/test_start_sit.py -v
```

Expected: ImportError — `backend.analysis.start_sit` doesn't exist yet.

- [ ] **Step 3: Implement the optimization engine**

```python
# backend/analysis/start_sit.py
"""Start/Sit optimization engine for starting pitchers.

Combines PitcherList per-start ratings with weekly H2H matchup context
to produce adjusted recommendations with category-aware rationale.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Expected daily swings per counting stat category (for a full league)
DAILY_SWING = {
    "K": 6.0, "QS": 1.5, "SVHD": 1.0,
    "R": 4.0, "TB": 8.0, "RBI": 4.0, "SB": 0.5,
}

# Rate stat gap thresholds for close vs big
RATE_THRESHOLDS = {
    "ERA": 0.30,
    "WHIP": 0.08,
    "OBP": 0.008,
}

# Categories where lower is better
LOWER_IS_BETTER = {"ERA", "WHIP"}

# Minimum IP before rate stats can be classified as "big"
MIN_IP_FOR_BIG = 15.0

# Pitching categories affected by SP start decisions
SP_AFFECTED_CATS = {"K", "QS", "ERA", "WHIP"}


def classify_category(
    cat: str,
    yours: float,
    theirs: float,
    days_remaining: int,
    team_ip: float = 50.0,
) -> str:
    """Classify a category's matchup state.

    Returns one of: winning_big, winning_close, losing_close, losing_big
    """
    # For lower-is-better cats, flip the comparison
    if cat in LOWER_IS_BETTER:
        # Lower is better: you're "winning" if yours < theirs
        gap = theirs - yours
    else:
        gap = yours - theirs

    # Tied -> losing_close (bias toward action)
    if gap == 0:
        return "losing_close"

    leading = gap > 0
    abs_gap = abs(gap)

    if cat in RATE_THRESHOLDS:
        # Rate stat classification
        threshold = RATE_THRESHOLDS[cat]

        # Low-IP override: can't classify rate stats as "big" with few innings
        if cat in ("ERA", "WHIP") and team_ip < MIN_IP_FOR_BIG:
            return "winning_close" if leading else "losing_close"

        if abs_gap >= threshold:
            return "winning_big" if leading else "losing_big"
        else:
            return "winning_close" if leading else "losing_close"
    else:
        # Counting stat classification
        daily_swing = DAILY_SWING.get(cat, 4.0)
        gap_in_days = abs_gap / daily_swing
        threshold = days_remaining * 0.8

        if gap_in_days > threshold:
            return "winning_big" if leading else "losing_big"
        else:
            return "winning_close" if leading else "losing_close"


def compute_ratio_exposure(total_starts_remaining: int) -> float:
    """Compute ratio exposure (0-1) based on remaining SP starts this week."""
    return min(1.0, total_starts_remaining / 5.0)


def decide_recommendation(
    pitcherlist_tier: str,
    cat_states: dict[str, str],
    ratio_exposure: float,
) -> str:
    """Apply the decision matrix to produce a recommendation.

    Args:
        pitcherlist_tier: One of strong_start, start, maybe, sit
        cat_states: Dict of SP-affected category -> state (only K, QS, ERA, WHIP)
        ratio_exposure: 0-1 float from compute_ratio_exposure()

    Returns one of: strong_start, start, risky_start, sit, safe_sit
    """
    # Check if all pitching cats are winning_big -> safe_sit
    if all(s == "winning_big" for s in cat_states.values()):
        return "safe_sit"

    era_state = cat_states.get("ERA", "winning_big")
    whip_state = cat_states.get("WHIP", "winning_big")
    k_state = cat_states.get("K", "winning_big")
    qs_state = cat_states.get("QS", "winning_big")

    era_whip_close = era_state == "winning_close" or whip_state == "winning_close"
    k_qs_losing_close = k_state == "losing_close" or qs_state == "losing_close"

    # Determine which decision matrix column to use
    use_ratio_protect = False
    if era_whip_close:
        if ratio_exposure <= 0.4:
            use_ratio_protect = True
        elif ratio_exposure < 0.8:
            use_ratio_protect = True  # apply but note in rationale
        # else: high exposure, use default column

    # Decision matrix
    matrix = {
        "strong_start": {"ratio_protect": "start", "k_chase": "strong_start", "default": "strong_start"},
        "start": {"ratio_protect": "risky_start", "k_chase": "start", "default": "start"},
        "maybe": {"ratio_protect": "sit", "k_chase": "risky_start", "default": "sit"},
        "sit": {"ratio_protect": "sit", "k_chase": "sit", "default": "sit"},
    }

    tier_row = matrix.get(pitcherlist_tier, matrix["maybe"])

    if use_ratio_protect:
        base = tier_row["ratio_protect"]
    elif k_qs_losing_close and not era_whip_close:
        base = tier_row["k_chase"]
    else:
        base = tier_row["default"]

    # Conflict resolution: ERA close AND K losing close
    if era_whip_close and k_qs_losing_close:
        if ratio_exposure >= 0.8:
            # Can't protect anyway, chase Ks
            base = tier_row["k_chase"]
        else:
            # Favor protecting ratios (downgrade one tier from k_chase)
            base = tier_row["ratio_protect"]

    return base


def generate_rationale(
    pitcherlist_raw: str,
    opponent: str,
    recommendation: str,
    cats: dict[str, str],
    ratio_exposure: float,
    starts_remaining: int,
) -> str:
    """Generate a human-readable rationale string."""
    if recommendation == "safe_sit":
        return "Winning all pitching categories comfortably. Safe to sit and protect leads."

    parts = [f"{pitcherlist_raw} vs {opponent}."]

    era_state = cats.get("ERA", "winning_big")
    whip_state = cats.get("WHIP", "winning_big")
    k_state = cats.get("K", "winning_big")

    era_whip_close = era_state == "winning_close" or whip_state == "winning_close"
    k_losing = k_state in ("losing_close", "losing_big")

    if era_whip_close and ratio_exposure >= 0.8:
        parts.append(f"ERA/WHIP close but {starts_remaining} starts left this week — can't protect ratios anyway.")
    elif era_whip_close and ratio_exposure <= 0.4:
        remaining_text = "last start of the week" if starts_remaining <= 1 else f"only {starts_remaining} starts left"
        parts.append(f"ERA/WHIP close and {remaining_text}.")
        if recommendation in ("sit", "risky_start"):
            parts.append("Protect the ratio lead.")
    elif era_whip_close:
        parts.append(f"ERA/WHIP close with {starts_remaining} more starts — some ratio risk ahead.")

    if k_losing and recommendation in ("start", "strong_start", "risky_start"):
        parts.append("Chasing Ks/QS upside.")

    if recommendation == "risky_start":
        parts.append("Borderline — league-dependent call.")

    return " ".join(parts)


def compute_start_sit_recommendations(
    roster_pitcher_names: list[str],
    matchup_categories: dict[str, dict[str, float]],
    team_ip: dict[str, float],
    days_remaining: int,
    opponent_name: str,
    today_date: str,
    matchup_end_date: str,
) -> dict:
    """Main entry point — compute start/sit recommendations.

    Args:
        roster_pitcher_names: Names of SPs on user's roster
        matchup_categories: {cat: {yours: float, theirs: float}} for all 10 cats
        team_ip: {yours: float, theirs: float}
        days_remaining: Days left in matchup period
        opponent_name: Opponent team name
        today_date: "2026-03-25"
        matchup_end_date: "2026-03-29"

    Returns:
        Full response dict matching the spec output schema.
    """
    from backend.data.pitcherlist import get_rankings_for_date

    # Step 1: Classify all 10 categories
    cat_states = {}
    my_ip = team_ip.get("yours", 50.0)
    for cat, vals in matchup_categories.items():
        cat_states[cat] = classify_category(
            cat, vals["yours"], vals["theirs"],
            days_remaining=days_remaining,
            team_ip=my_ip,
        )

    # Get PitcherList data
    todays_starters, upcoming_starts, off_day_pitchers = get_rankings_for_date(
        today_date, roster_pitcher_names
    )

    # Step 2: Compute remaining exposure
    starts_today = len(todays_starters)
    starts_after_today = len(upcoming_starts)
    total_starts = starts_today + starts_after_today
    ratio_exposure = compute_ratio_exposure(total_starts)

    # Step 3-4: SP-affected categories only
    sp_cat_states = {c: cat_states[c] for c in SP_AFFECTED_CATS if c in cat_states}

    # Generate recommendations for today's starters
    recommendations = []
    for entry in todays_starters:
        rec = decide_recommendation(entry["mapped_tier"], sp_cat_states, ratio_exposure)
        rationale = generate_rationale(
            pitcherlist_raw=entry["raw"],
            opponent=entry["opponent"],
            recommendation=rec,
            cats=sp_cat_states,
            ratio_exposure=ratio_exposure,
            starts_remaining=total_starts,
        )
        recommendations.append({
            "pitcher_name": entry["pitcher_name"],
            "matchup": f"vs. {entry['opponent']}",
            "pitcherlist_tier": entry["mapped_tier"],
            "pitcherlist_score": entry["score"],
            "pitcherlist_raw": entry["raw"],
            "our_recommendation": rec,
            "rationale": rationale,
        })

    # Build matchup summary
    cat_summary = {}
    for cat, vals in matchup_categories.items():
        cat_summary[cat] = {
            "yours": vals["yours"],
            "theirs": vals["theirs"],
            "status": cat_states[cat],
        }

    # Count overall W/L/T from raw values (not classification — ties are gap=0)
    wins = 0
    losses = 0
    ties = 0
    for cat, vals in matchup_categories.items():
        yours, theirs = vals["yours"], vals["theirs"]
        if cat in LOWER_IS_BETTER:
            if yours < theirs:
                wins += 1
            elif yours > theirs:
                losses += 1
            else:
                ties += 1
        else:
            if yours > theirs:
                wins += 1
            elif yours < theirs:
                losses += 1
            else:
                ties += 1

    return {
        "matchup_summary": {
            "opponent": opponent_name,
            "categories": cat_summary,
            "days_remaining": days_remaining,
            "overall": f"W{wins} - L{losses} - T{ties}",
            "starts_today": starts_today,
            "starts_remaining_after_today": starts_after_today,
            "ratio_exposure": round(ratio_exposure, 2),
        },
        "upcoming_starts": [
            {
                "date": e["date"],
                "pitcher_name": e["pitcher_name"],
                "opponent": e["opponent"],
                "pitcherlist_raw": e["raw"],
            }
            for e in upcoming_starts
        ],
        "recommendations": recommendations,
        "off_day_pitchers": off_day_pitchers,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/backend/test_start_sit.py -v
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/analysis/start_sit.py tests/backend/test_start_sit.py
git commit -m "Add start/sit optimization engine with category classification and decision matrix"
```

---

## Task 5: FastAPI Endpoint

Wire the optimization engine into the backend API.

**Files:**
- Modify: `backend/api/routes.py` (append endpoint)

- [ ] **Step 1: Add the start-sit endpoint to routes.py**

Append to the end of `backend/api/routes.py`:

```python
# ── Start/Sit Recommendations ──


class StartSitRequest(BaseModel):
    roster_pitcher_names: list[str]
    matchup_categories: dict[str, dict[str, float]]
    team_ip: dict[str, float]
    days_remaining: int
    opponent_name: str
    today_date: str
    matchup_end_date: str


@router.post("/start-sit")
def start_sit_recommendations(req: StartSitRequest):
    """Compute start/sit recommendations for today's SP matchups."""
    from backend.analysis.start_sit import compute_start_sit_recommendations

    return compute_start_sit_recommendations(
        roster_pitcher_names=req.roster_pitcher_names,
        matchup_categories=req.matchup_categories,
        team_ip=req.team_ip,
        days_remaining=req.days_remaining,
        opponent_name=req.opponent_name,
        today_date=req.today_date,
        matchup_end_date=req.matchup_end_date,
    )
```

- [ ] **Step 2: Verify the endpoint loads**

```bash
# Start the FastAPI backend and check the endpoint is registered
cd /Users/jgibbons/code/fantasy-baseball-helper
python -c "from backend.api.routes import router; print([r.path for r in router.routes])"
```

Expected: `/api/start-sit` appears in the route list.

- [ ] **Step 3: Commit**

```bash
git add backend/api/routes.py
git commit -m "Add POST /api/start-sit FastAPI endpoint"
```

---

## Task 6: Next.js Orchestration Route

The route that fetches ESPN data, calls the Python backend, and returns results.

**Files:**
- Create: `src/app/api/start-sit/route.ts`

- [ ] **Step 1: Create the start-sit API route**

```typescript
// src/app/api/start-sit/route.ts
import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/prisma'
import { ESPNApi } from '@/lib/espn-api'

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000'

// ESPN stat IDs -> our category names (verify with test API call)
// These are the stat IDs used in scoreByStat for H2H categories scoring
// Keys are strings in the ESPN response
const ESPN_STAT_MAP: Record<string, string> = {
  // Will be populated after verifying with a real API call.
  // Placeholder mapping based on espn-api library:
  '20': 'R',
  '5': 'RBI',
  '11': 'SB',
  '17': 'OBP',
  '48': 'K',
  '63': 'QS',
  '47': 'ERA',
  '41': 'WHIP',
  // TB and SVHD need verification
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json()
    const { leagueId, teamId, season = '2026' } = body

    if (!leagueId || !teamId) {
      return NextResponse.json(
        { error: 'Missing required fields: leagueId, teamId' },
        { status: 400 },
      )
    }

    // Look up credentials from DB
    const league = await prisma.league.findUnique({ where: { id: leagueId } })
    if (!league) {
      return NextResponse.json({ error: 'League not found' }, { status: 404 })
    }

    const leagueSettings = league.settings as any
    const credentials = leagueSettings?.credentials
    if (!credentials?.espn_s2 || !credentials?.swid) {
      return NextResponse.json(
        { error: 'ESPN credentials not configured. Set them up in Settings.' },
        { status: 400 },
      )
    }

    const espnSettings = { swid: credentials.swid, espn_s2: credentials.espn_s2 }

    // Fetch league info to get currentMatchupPeriod
    const leagueData = await ESPNApi.getLeague(league.externalId, season, espnSettings)
    const matchupPeriod = leagueData.status?.currentMatchupPeriod
      || leagueData.currentMatchupPeriod
      || 1

    // Fetch roster and matchup scoreboard in parallel
    const [rosters, scoreboard] = await Promise.all([
      ESPNApi.getRosters(league.externalId, season, espnSettings),
      ESPNApi.getMatchupScoreboard(league.externalId, season, espnSettings, matchupPeriod),
    ])

    const myTeamId = parseInt(teamId)

    // Find user's matchup in the schedule
    const myMatchup = scoreboard.schedule.find(
      (m) => m.home.teamId === myTeamId || m.away.teamId === myTeamId
    )

    if (!myMatchup) {
      return NextResponse.json(
        { error: 'Could not find your matchup for this week' },
        { status: 404 },
      )
    }

    // Determine which side is ours
    const isHome = myMatchup.home.teamId === myTeamId
    const mySide = isHome ? myMatchup.home : myMatchup.away
    const theirSide = isHome ? myMatchup.away : myMatchup.home

    // Extract category totals from scoreByStat
    const myStats = mySide.cumulativeScore?.scoreByStat || {}
    const theirStats = theirSide.cumulativeScore?.scoreByStat || {}

    const matchupCategories: Record<string, { yours: number; theirs: number }> = {}
    for (const [statId, catName] of Object.entries(ESPN_STAT_MAP)) {
      matchupCategories[catName] = {
        yours: myStats[statId]?.score ?? 0,
        theirs: theirStats[statId]?.score ?? 0,
      }
    }

    // Extract IP totals (ESPN stat ID for IP needs verification)
    // IP is commonly stat ID 34 or can be derived
    const teamIp = {
      yours: myStats['34']?.score ?? 0,
      theirs: theirStats['34']?.score ?? 0,
    }

    // Get SP names from roster (defaultPositionId 1 = SP)
    const myRosterEntries = rosters[myTeamId] || []
    const spNames = myRosterEntries
      .filter((entry) => entry.player?.defaultPositionId === 1)
      .map((entry) => entry.player?.fullName || '')
      .filter(Boolean)

    // Get opponent team name
    const teams = await ESPNApi.getTeams(league.externalId, season, espnSettings)
    const opponentTeam = teams.find((t) => t.id === theirSide.teamId)
    const opponentName = opponentTeam
      ? [opponentTeam.location, opponentTeam.nickname].filter(Boolean).join(' ')
      : `Team ${theirSide.teamId}`

    const today = new Date()
    const todayStr = today.toISOString().split('T')[0]

    // Compute days remaining from ESPN scoring period data
    // ESPN's latestScoringPeriod tells us where we are in the season;
    // finalScoringPeriod for the matchup is in the schedule entry.
    // Fallback: estimate from day of week (Mon-Sun matchup periods)
    const dayOfWeek = today.getDay()
    const daysRemaining = dayOfWeek === 0 ? 0 : 7 - dayOfWeek

    const endDate = new Date(today)
    endDate.setDate(endDate.getDate() + daysRemaining)
    const endDateStr = endDate.toISOString().split('T')[0]

    // Call Python backend
    const backendResponse = await fetch(`${BACKEND_URL}/api/start-sit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        roster_pitcher_names: spNames,
        matchup_categories: matchupCategories,
        team_ip: teamIp,
        days_remaining: daysRemaining,
        opponent_name: opponentName,
        today_date: todayStr,
        matchup_end_date: endDateStr,
      }),
    })

    if (!backendResponse.ok) {
      const errorText = await backendResponse.text()
      console.error('Backend error:', errorText)
      return NextResponse.json(
        { error: `Backend error: ${backendResponse.status}` },
        { status: 502 },
      )
    }

    const result = await backendResponse.json()
    return NextResponse.json(result)
  } catch (error: any) {
    console.error('Start/sit error:', error)
    return NextResponse.json(
      { error: error.message || 'Failed to compute recommendations' },
      { status: 500 },
    )
  }
}
```

- [ ] **Step 2: Verify the route compiles**

```bash
cd /Users/jgibbons/code/fantasy-baseball-helper
npx tsc --noEmit src/app/api/start-sit/route.ts 2>&1 | head -20
```

Note: TypeScript may not type-check in isolation. Verify by loading the dev server.

- [ ] **Step 3: Commit**

```bash
git add src/app/api/start-sit/route.ts
git commit -m "Add Next.js orchestration route for start/sit recommendations"
```

---

## Task 7: Frontend Page

Build the start/sit page UI.

**Files:**
- Create: `src/app/start-sit/page.tsx`
- Modify: `src/components/Navigation.tsx` (add nav link)

- [ ] **Step 1: Add Start/Sit to navigation**

In `src/components/Navigation.tsx`, add the nav item after Trades:

Change:
```typescript
  { href: '/trades', label: 'Trades' },
  { href: '/players', label: 'Player Search' },
```
To:
```typescript
  { href: '/trades', label: 'Trades' },
  { href: '/start-sit', label: 'Start/Sit' },
  { href: '/players', label: 'Player Search' },
```

- [ ] **Step 2: Create the start-sit page**

```tsx
// src/app/start-sit/page.tsx
'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'

interface League {
  id: string
  name: string
  platform: string
  season: string
  externalId?: string
}

interface Team {
  id: string
  externalId: string
  name: string
}

interface CategoryInfo {
  yours: number
  theirs: number
  status: string
}

interface MatchupSummary {
  opponent: string
  categories: Record<string, CategoryInfo>
  days_remaining: number
  overall: string
  starts_today: number
  starts_remaining_after_today: number
  ratio_exposure: number
}

interface Recommendation {
  pitcher_name: string
  matchup: string
  pitcherlist_tier: string
  pitcherlist_score: number
  pitcherlist_raw: string
  our_recommendation: string
  rationale: string
}

interface UpcomingStart {
  date: string
  pitcher_name: string
  opponent: string
  pitcherlist_raw: string
}

interface StartSitResults {
  matchup_summary: MatchupSummary
  recommendations: Recommendation[]
  upcoming_starts: UpcomingStart[]
  off_day_pitchers: Array<{ pitcher_name: string }>
}

const PITCHING_CATS = ['K', 'QS', 'ERA', 'WHIP']
const HITTING_CATS = ['R', 'TB', 'RBI', 'OBP', 'SB']

const statusColors: Record<string, string> = {
  winning_big: 'text-emerald-400 bg-emerald-500/15',
  winning_close: 'text-emerald-300',
  losing_close: 'text-red-300',
  losing_big: 'text-red-400 bg-red-500/15',
}

const recColors: Record<string, string> = {
  strong_start: 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30',
  start: 'bg-emerald-500/10 text-emerald-400',
  risky_start: 'bg-yellow-500/15 text-yellow-300 border border-yellow-500/30',
  sit: 'bg-red-500/10 text-red-400',
  safe_sit: 'bg-blue-500/10 text-blue-400',
}

const recLabels: Record<string, string> = {
  strong_start: 'Strong Start',
  start: 'Start',
  risky_start: 'Risky Start',
  sit: 'Sit',
  safe_sit: 'Safe Sit',
}

function formatCatValue(cat: string, val: number): string {
  if (cat === 'ERA') return val.toFixed(2)
  if (cat === 'WHIP') return val.toFixed(2)
  if (cat === 'OBP') return val.toFixed(3)
  return String(Math.round(val))
}

function statusLabel(s: string): string {
  return s.replace('_', ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

export default function StartSitPage() {
  const [leagues, setLeagues] = useState<League[]>([])
  const [teams, setTeams] = useState<Team[]>([])
  const [selectedLeague, setSelectedLeague] = useState('')
  const [selectedTeam, setSelectedTeam] = useState('')
  const [hasCredentials, setHasCredentials] = useState<boolean | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [results, setResults] = useState<StartSitResults | null>(null)
  const [showHitting, setShowHitting] = useState(false)

  // Load leagues
  useEffect(() => {
    fetch('/api/leagues')
      .then((r) => (r.ok ? r.json() : []))
      .then((data) => {
        setLeagues(data)
        // Auto-select first league
        if (data.length > 0) {
          setSelectedLeague(data[0].id)
        }
      })
      .catch(() => {})
  }, [])

  // Check credentials when league changes
  useEffect(() => {
    if (!selectedLeague) return
    setHasCredentials(null)
    fetch(`/api/leagues/${selectedLeague}/credentials`)
      .then((r) => r.json())
      .then((data) => {
        setHasCredentials(data.has_credentials)
        if (data.default_team_id) {
          setSelectedTeam(data.default_team_id)
        }
      })
      .catch(() => setHasCredentials(false))
  }, [selectedLeague])

  // Load teams when league changes
  useEffect(() => {
    if (!selectedLeague) return
    fetch(`/api/leagues/${selectedLeague}/credentials`)
      .then((r) => r.json())
      .then(async (credData) => {
        if (!credData.has_credentials) return
        // Fetch teams
        const teamsResp = await fetch(
          `/api/leagues/${selectedLeague}/teams?season=2026`
        )
        if (teamsResp.ok) {
          const teamsData = await teamsResp.json()
          setTeams(teamsData.teams || teamsData || [])
        }
      })
      .catch(() => {})
  }, [selectedLeague, hasCredentials])

  const fetchRecommendations = async () => {
    if (!selectedLeague || !selectedTeam) return
    setLoading(true)
    setError(null)
    try {
      const resp = await fetch('/api/start-sit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          leagueId: selectedLeague,
          teamId: selectedTeam,
        }),
      })
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}))
        throw new Error(data.error || `Error ${resp.status}`)
      }
      setResults(await resp.json())
    } catch (err: any) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  // Auto-fetch when team is selected
  useEffect(() => {
    if (selectedLeague && selectedTeam && hasCredentials) {
      fetchRecommendations()
    }
  }, [selectedLeague, selectedTeam, hasCredentials])

  const today = new Date().toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  })

  return (
    <div className="min-h-screen bg-[#0d1117] text-gray-200">
      <div className="max-w-3xl mx-auto px-4 py-6">
        {/* Header */}
        <div className="mb-6">
          <h1 className="text-xl font-bold text-white">Start/Sit — {today}</h1>
          {results && (
            <p className="text-sm text-gray-400 mt-1">
              vs. {results.matchup_summary.opponent} &middot;{' '}
              <span className="text-white font-medium">{results.matchup_summary.overall}</span>
              {' '}&middot; {results.matchup_summary.days_remaining} days left
            </p>
          )}
        </div>

        {/* League/Team selector (compact) */}
        {(!results || error) && (
          <div className="flex gap-3 mb-4">
            <select
              className="bg-[#161b22] border border-white/10 rounded px-2 py-1.5 text-sm text-gray-300 flex-1"
              value={selectedLeague}
              onChange={(e) => setSelectedLeague(e.target.value)}
            >
              <option value="">Select league</option>
              {leagues.map((l) => (
                <option key={l.id} value={l.id}>{l.name}</option>
              ))}
            </select>
            <select
              className="bg-[#161b22] border border-white/10 rounded px-2 py-1.5 text-sm text-gray-300 flex-1"
              value={selectedTeam}
              onChange={(e) => setSelectedTeam(e.target.value)}
            >
              <option value="">Select team</option>
              {teams.map((t) => (
                <option key={t.externalId} value={t.externalId}>{t.name}</option>
              ))}
            </select>
          </div>
        )}

        {/* No credentials */}
        {hasCredentials === false && (
          <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-4 text-sm text-yellow-300">
            ESPN credentials not configured.{' '}
            <Link href="/settings" className="underline font-medium">Set up in Settings</Link>
          </div>
        )}

        {/* Loading */}
        {loading && (
          <div className="text-center py-12 text-gray-500">Loading recommendations...</div>
        )}

        {/* Error */}
        {error && (
          <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 text-sm text-red-300 mb-4">
            {error}
          </div>
        )}

        {/* Results */}
        {results && !loading && (
          <>
            {/* Category Context Strip — Pitching */}
            <div className="bg-[#161b22] rounded-lg border border-white/[0.06] p-3 mb-4">
              <div className="text-xs text-gray-500 mb-2 font-medium uppercase tracking-wider">
                Pitching Categories
              </div>
              <div className="grid grid-cols-4 gap-2">
                {PITCHING_CATS.map((cat) => {
                  const info = results.matchup_summary.categories[cat]
                  if (!info) return null
                  return (
                    <div key={cat} className="text-center">
                      <div className="text-xs text-gray-500 mb-0.5">{cat}</div>
                      <div className={`text-sm font-medium ${statusColors[info.status] || ''} rounded px-1 py-0.5`}>
                        {formatCatValue(cat, info.yours)}
                      </div>
                      <div className="text-xs text-gray-600">
                        vs {formatCatValue(cat, info.theirs)}
                      </div>
                    </div>
                  )
                })}
              </div>
              {/* SVHD context */}
              {results.matchup_summary.categories['SVHD'] && (
                <div className="mt-2 text-xs text-gray-500 text-center">
                  SVHD: {Math.round(results.matchup_summary.categories['SVHD'].yours)} vs{' '}
                  {Math.round(results.matchup_summary.categories['SVHD'].theirs)}
                  <span className="ml-1 text-gray-600">(not affected by SP starts)</span>
                </div>
              )}
              {/* Hitting toggle */}
              <button
                onClick={() => setShowHitting(!showHitting)}
                className="mt-2 text-xs text-gray-500 hover:text-gray-400 w-full text-center"
              >
                {showHitting ? 'Hide' : 'Show'} hitting categories
              </button>
              {showHitting && (
                <div className="grid grid-cols-5 gap-2 mt-2 pt-2 border-t border-white/[0.06]">
                  {HITTING_CATS.map((cat) => {
                    const info = results.matchup_summary.categories[cat]
                    if (!info) return null
                    return (
                      <div key={cat} className="text-center">
                        <div className="text-xs text-gray-500 mb-0.5">{cat}</div>
                        <div className={`text-xs ${statusColors[info.status] || ''} rounded px-0.5`}>
                          {formatCatValue(cat, info.yours)}
                        </div>
                        <div className="text-xs text-gray-600">vs {formatCatValue(cat, info.theirs)}</div>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>

            {/* Exposure info */}
            <div className="text-xs text-gray-500 mb-3 px-1">
              {results.matchup_summary.starts_today} start{results.matchup_summary.starts_today !== 1 ? 's' : ''} today
              {results.matchup_summary.starts_remaining_after_today > 0 && (
                <> &middot; {results.matchup_summary.starts_remaining_after_today} more this week</>
              )}
            </div>

            {/* Recommendations */}
            {results.recommendations.length > 0 ? (
              <div className="space-y-3 mb-6">
                {results.recommendations.map((rec, i) => (
                  <div
                    key={i}
                    className="bg-[#161b22] rounded-lg border border-white/[0.06] p-4"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-medium text-white text-sm">{rec.pitcher_name}</span>
                          <span className="text-xs text-gray-500">{rec.matchup}</span>
                          <span className="text-xs text-gray-500">{rec.pitcherlist_raw}</span>
                        </div>
                        <p className="text-xs text-gray-400 mt-1.5 leading-relaxed">{rec.rationale}</p>
                      </div>
                      <span className={`shrink-0 text-xs font-medium px-2.5 py-1 rounded-full ${recColors[rec.our_recommendation] || ''}`}>
                        {recLabels[rec.our_recommendation] || rec.our_recommendation}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="bg-[#161b22] rounded-lg border border-white/[0.06] p-6 text-center text-gray-500 text-sm mb-6">
                No SP starts today.
              </div>
            )}

            {/* Upcoming starts */}
            {results.upcoming_starts.length > 0 && (
              <div className="mb-6">
                <div className="text-xs text-gray-500 font-medium uppercase tracking-wider mb-2 px-1">
                  {results.upcoming_starts.length} more start{results.upcoming_starts.length !== 1 ? 's' : ''} this week
                </div>
                <div className="bg-[#161b22] rounded-lg border border-white/[0.06] divide-y divide-white/[0.06]">
                  {results.upcoming_starts.map((s, i) => (
                    <div key={i} className="flex items-center justify-between px-4 py-2.5 text-sm">
                      <div>
                        <span className="text-gray-300">{s.pitcher_name}</span>
                        <span className="text-gray-600 ml-2">vs {s.opponent}</span>
                      </div>
                      <div className="text-xs text-gray-500">
                        <span className="mr-2">{s.date}</span>
                        <span>{s.pitcherlist_raw}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Off-day pitchers */}
            {results.off_day_pitchers.length > 0 && (
              <div className="mb-6">
                <div className="text-xs text-gray-500 font-medium uppercase tracking-wider mb-2 px-1">
                  No starts scheduled
                </div>
                <div className="text-xs text-gray-600 px-1">
                  {results.off_day_pitchers.map((p) => p.pitcher_name).join(', ')}
                </div>
              </div>
            )}

            {/* Refresh button */}
            <div className="text-center">
              <button
                onClick={fetchRecommendations}
                disabled={loading}
                className="text-xs text-gray-500 hover:text-gray-400 px-3 py-1.5 rounded border border-white/10 hover:border-white/20"
              >
                Refresh
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Verify page loads in dev server**

```bash
# Start both backend and frontend, navigate to /start-sit
# Should show league/team selectors at minimum
```

- [ ] **Step 4: Commit**

```bash
git add src/app/start-sit/page.tsx src/components/Navigation.tsx
git commit -m "Add start/sit frontend page with matchup context and recommendations"
```

---

## Task 8: Migrate Waivers to DB Credentials

Remove localStorage credentials from the waivers flow.

**Files:**
- Modify: `src/app/api/waivers/recommendations/route.ts`
- Modify: `src/app/waivers/page.tsx`

- [ ] **Step 1: Update waivers API route to read credentials from DB**

In `src/app/api/waivers/recommendations/route.ts`, change lines 30-39:

Replace:
```typescript
    const body = await request.json()
    const { leagueId, teamId, swid, espn_s2, season = '2026' } = body

    if (!leagueId || !teamId || !swid || !espn_s2) {
      return NextResponse.json(
        { error: 'Missing required fields: leagueId, teamId, swid, espn_s2' },
        { status: 400 },
      )
    }

    const league = await prisma.league.findUnique({
      where: { id: leagueId },
    })

    if (!league) {
      return NextResponse.json({ error: 'League not found' }, { status: 404 })
    }

    const settings = { swid, espn_s2 }
```

With:
```typescript
    const body = await request.json()
    const { leagueId, teamId, season = '2026' } = body

    if (!leagueId || !teamId) {
      return NextResponse.json(
        { error: 'Missing required fields: leagueId, teamId' },
        { status: 400 },
      )
    }

    const league = await prisma.league.findUnique({
      where: { id: leagueId },
    })

    if (!league) {
      return NextResponse.json({ error: 'League not found' }, { status: 404 })
    }

    const leagueSettings = league.settings as any
    const credentials = leagueSettings?.credentials
    if (!credentials?.espn_s2 || !credentials?.swid) {
      return NextResponse.json(
        { error: 'ESPN credentials not configured. Set them up in Settings.' },
        { status: 400 },
      )
    }

    const settings = { swid: credentials.swid, espn_s2: credentials.espn_s2 }
```

- [ ] **Step 2: Update waivers frontend to remove localStorage credentials**

In `src/app/waivers/page.tsx`:

1. Remove the `loadSettings()` and `saveSettings()` functions (lines 94-106)
2. Remove `swid` and `espnS2` state variables (lines 113-114)
3. Remove credential input fields from the form
4. Update the API call to not send `swid`/`espn_s2` in the POST body
5. Add a check for stored credentials via the `/api/leagues/[id]/credentials` endpoint
6. If no credentials, show a message with link to `/settings`

This is a larger UI change. The key principle: the page should only need `leagueId` and `teamId` — no credential fields visible to the user.

- [ ] **Step 3: Test the waivers page still works**

Load `/waivers`, select a league and team (credentials should come from DB). Verify recommendations load.

- [ ] **Step 4: Commit**

```bash
git add src/app/api/waivers/recommendations/route.ts src/app/waivers/page.tsx
git commit -m "Migrate waivers page to DB-stored credentials"
```

---

## Task 9: Migrate Trades to DB Credentials

Same pattern as waivers migration.

**Files:**
- Modify: `src/app/api/trades/suggestions/route.ts`
- Modify: `src/app/trades/page.tsx`

- [ ] **Step 1: Update trades API route to read credentials from DB**

In `src/app/api/trades/suggestions/route.ts`, apply the same pattern as Task 8 Step 1:

Replace the credential extraction from `body` with DB lookup from `league.settings.credentials`.

Change:
```typescript
    const {
      leagueId, teamId, swid, espn_s2,
      season = '2026',
      ...
    } = body

    if (!leagueId || !teamId || !swid || !espn_s2) {
```

To:
```typescript
    const {
      leagueId, teamId,
      season = '2026',
      ...
    } = body

    if (!leagueId || !teamId) {
```

And replace `const settings = { swid, espn_s2 }` with the DB credential lookup (same as Task 8).

- [ ] **Step 2: Update trades frontend to remove localStorage credentials**

Same pattern as waivers — remove credential state/form, check DB for credentials, show setup prompt if missing.

- [ ] **Step 3: Test the trades page still works**

Load `/trades`, verify trade suggestions load with DB-stored credentials.

- [ ] **Step 4: Commit**

```bash
git add src/app/api/trades/suggestions/route.ts src/app/trades/page.tsx
git commit -m "Migrate trades page to DB-stored credentials"
```

---

## Task 10: ESPN Stat ID Verification & End-to-End Test

Verify the ESPN stat ID mapping and test the full flow.

**Files:**
- Modify: `src/app/api/start-sit/route.ts` (fix stat ID mapping if needed)

- [ ] **Step 1: Create a debug endpoint to log ESPN scoreByStat keys**

Add a temporary debug route or log statement in the start-sit route that logs the raw `scoreByStat` object from ESPN. This reveals the exact stat IDs for your league.

- [ ] **Step 2: Make a test API call and capture the stat ID mapping**

Call the start-sit endpoint with your real league/team data. Inspect the logs to see which stat IDs map to which categories. Update `ESPN_STAT_MAP` in `src/app/api/start-sit/route.ts` with the verified mapping.

Pay special attention to:
- TB (total bases) — may not be a direct stat ID, might need to compute
- SVHD (saves + holds) — may be two separate stat IDs that need summing
- IP (innings pitched) — needed for the `team_ip` field

- [ ] **Step 3: Fix any mapping issues and test end-to-end**

Load `/start-sit` on desktop and phone. Verify:
- Matchup summary shows correct category totals
- Category states (winning_close, etc.) match your intuition
- PitcherList data loads (may need to be during season for actual data)
- Recommendations have rationale that references category context

- [ ] **Step 4: Remove debug logging, commit final state**

```bash
git add -A
git commit -m "Verify ESPN stat ID mapping and complete end-to-end integration"
```

---

## Task 11: Settings Page for Credential Entry

Create a simple settings page where credentials are entered once.

**Files:**
- Create: `src/app/settings/page.tsx`

- [ ] **Step 1: Create the settings page**

Simple form: league selector, ESPN S2 token field, SWID field, default team selector, save button. Calls `PUT /api/leagues/[leagueId]/credentials`. Shows success/error feedback.

Follow the visual style of existing pages (dark theme, `bg-[#0d1117]`, similar form styling to waivers).

- [ ] **Step 2: Test saving and loading credentials**

1. Navigate to `/settings`
2. Select a league, paste ESPN credentials, select default team
3. Save — verify success
4. Navigate to `/start-sit` — verify it auto-loads without credential prompts
5. Load `/start-sit` on phone — verify it works

- [ ] **Step 3: Commit**

```bash
git add src/app/settings/page.tsx
git commit -m "Add settings page for one-time ESPN credential setup"
```
