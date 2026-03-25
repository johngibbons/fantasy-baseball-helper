"""PitcherList Sit/Start article scraper.

Fetches and parses weekly Sit/Start articles from pitcherlist.com, which
contain HTML tables with pitcher names, opponents, game dates, and tiered
ratings (Start-N, Maybe-N, Sit-N).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Optional

logger = logging.getLogger(__name__)

# Simple in-process cache: {week_key: (timestamp, list[dict])}
_cache: dict[str, tuple[float, list[dict]]] = {}
_CACHE_TTL_SECONDS = 6 * 3600  # 6 hours

PITCHERLIST_HOME = "https://pitcherlist.com"

# Regex to detect a rating cell like "Start-8", "Maybe-4", "Sit-2"
_RATING_RE = re.compile(r"^(Start|Maybe|Sit)-(\d+)$", re.IGNORECASE)


# ── Tier helpers ──────────────────────────────────────────────────────────────


def map_tier(tier: str, score: int) -> str:
    """Map a PitcherList tier+score to our internal tier label.

    Args:
        tier: "Start", "Maybe", or "Sit" (case-insensitive).
        score: Numeric score associated with the tier.

    Returns:
        One of: "strong_start", "start", "maybe", "sit".
    """
    t = tier.strip().lower()
    if t == "start":
        return "strong_start" if score >= 7 else "start"
    if t == "maybe":
        return "maybe"
    # "sit" or anything else
    return "sit"


def parse_rating(raw: str) -> tuple[str, int]:
    """Parse a raw rating string like "Start-8" into ("Start", 8).

    Args:
        raw: Raw rating text from the article table.

    Returns:
        (tier_label, score) tuple.

    Raises:
        ValueError: If the string does not match the expected pattern.
    """
    m = _RATING_RE.match(raw.strip())
    if not m:
        raise ValueError(f"Cannot parse rating: {raw!r}")
    tier = m.group(1).capitalize()
    score = int(m.group(2))
    return tier, score


# ── HTML parsing ──────────────────────────────────────────────────────────────


def parse_sit_start_tables(html: str) -> list[dict]:
    """Parse HTML tables from a PitcherList Sit/Start article.

    Looks for <table> elements whose rows contain a rating cell matching the
    "Start-N / Maybe-N / Sit-N" pattern.  Extracts date context from rows
    that have a date cell (e.g. "Wednesday 3/25") and propagates it to
    subsequent pitcher rows until a new date appears.

    Args:
        html: Full HTML of the article page.

    Returns:
        List of dicts with keys:
            pitcher_name, opponent, date, tier, score, raw, mapped_tier
    """
    from bs4 import BeautifulSoup  # lazy import — optional dep at module level

    soup = BeautifulSoup(html, "html.parser")
    results: list[dict] = []

    for table in soup.find_all("table"):
        current_date = ""
        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if not cells:
                continue

            # Skip pure header rows (all <th>)
            if all(c.name == "th" for c in cells):
                continue

            texts = [c.get_text(strip=True) for c in cells]

            # Try to find a rating cell anywhere in the row
            rating_idx = None
            for i, text in enumerate(texts):
                if _RATING_RE.match(text):
                    rating_idx = i
                    break

            if rating_idx is None:
                # This row may be a date separator — check first cell
                if texts and _looks_like_date(texts[0]):
                    current_date = texts[0]
                continue

            # We have a rating cell.  Now resolve the other columns.
            # Expected column order (flexible): Date | Game | Pitcher | Rating
            # or some subset.  We identify by position relative to rating_idx.

            raw_rating = texts[rating_idx]
            try:
                tier, score = parse_rating(raw_rating)
            except ValueError:
                continue

            # Pitcher name: look for a non-date, non-game, non-rating cell
            # Heuristic: the cell just before the rating is the pitcher name,
            # the cell before that is the opponent/game, and the cell before
            # that (if it looks like a date) updates current_date.
            pitcher_name = ""
            opponent = ""

            # Work backwards from rating_idx
            before = [texts[i] for i in range(rating_idx)]

            if len(before) >= 1:
                pitcher_name = before[-1]
            if len(before) >= 2:
                opponent = before[-2]
            if len(before) >= 3 and _looks_like_date(before[-3]):
                current_date = before[-3]
            elif len(before) >= 3 and not _looks_like_date(before[-3]):
                # date may already be in current_date from a prior row
                pass
            # If the first column looks like a date, update current_date
            if before and _looks_like_date(before[0]):
                current_date = before[0]

            if not pitcher_name:
                continue

            mapped = map_tier(tier, score)
            results.append(
                {
                    "pitcher_name": pitcher_name,
                    "opponent": opponent,
                    "date": current_date,
                    "tier": tier,
                    "score": score,
                    "raw": raw_rating,
                    "mapped_tier": mapped,
                }
            )

    return results


def _looks_like_date(text: str) -> bool:
    """Return True if text looks like a day-of-week date, e.g. 'Wednesday 3/25'."""
    day_names = (
        "monday", "tuesday", "wednesday", "thursday",
        "friday", "saturday", "sunday",
    )
    lower = text.lower()
    return any(lower.startswith(d) for d in day_names)


# ── Discovery & fetching ──────────────────────────────────────────────────────


def discover_latest_article_url() -> Optional[str]:
    """Fetch pitcherlist.com homepage and find the latest Sit/Start article URL.

    Looks for anchor tags whose visible text contains "sit", "start", and
    "week" (case-insensitive).

    Returns:
        Absolute URL string, or None if not found.
    """
    import urllib.request

    try:
        req = urllib.request.Request(
            PITCHERLIST_HOME,
            headers={"User-Agent": "Mozilla/5.0 (fantasy-baseball-helper/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to fetch PitcherList homepage: %s", exc)
        return None

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True).lower()
        if "sit" in text and "start" in text and "week" in text:
            href = a["href"]
            if href.startswith("http"):
                return href
            return PITCHERLIST_HOME.rstrip("/") + "/" + href.lstrip("/")

    return None


def fetch_weekly_rankings(week_key: str | None = None) -> list[dict]:
    """Fetch and cache Sit/Start rankings for the given week.

    Args:
        week_key: ISO week string like "2026-W13".  If None, the current week
            is used.

    Returns:
        List of parsed ranking dicts (see parse_sit_start_tables).
    """
    import time
    from datetime import date

    if week_key is None:
        today = date.today()
        week_key = today.strftime("%Y-W%W")

    now = time.time()
    if week_key in _cache:
        ts, data = _cache[week_key]
        if now - ts < _CACHE_TTL_SECONDS:
            logger.debug("PitcherList cache hit for %s", week_key)
            return data

    url = discover_latest_article_url()
    if url is None:
        logger.warning("Could not discover PitcherList article URL")
        return []

    import urllib.request

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (fantasy-baseball-helper/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to fetch PitcherList article %s: %s", url, exc)
        return []

    rankings = parse_sit_start_tables(html)
    _cache[week_key] = (now, rankings)
    return rankings


# ── Name normalization & date matching ────────────────────────────────────────


def _normalize(name: str) -> str:
    """Strip accents and lowercase a player name for fuzzy matching."""
    nfkd = unicodedata.normalize("NFKD", name)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


def _dates_match(target: str, entry_date: str) -> bool:
    """Check whether an ISO date string matches a day-of-week date string.

    Args:
        target: ISO date like "2026-03-25".
        entry_date: Human-readable date like "Wednesday 3/25".

    Returns:
        True if month and day match.
    """
    # Extract month/day from target "YYYY-MM-DD"
    try:
        parts = target.split("-")
        t_month = int(parts[1])
        t_day = int(parts[2])
    except (IndexError, ValueError):
        return False

    # Extract month/day from entry_date "Weekday M/D"
    m = re.search(r"(\d{1,2})/(\d{1,2})", entry_date)
    if not m:
        return False
    e_month = int(m.group(1))
    e_day = int(m.group(2))

    return t_month == e_month and t_day == e_day


def get_rankings_for_date(
    target_date: str,
    roster_pitcher_names: list[str],
) -> tuple[list, list, list]:
    """Filter cached rankings by date and roster membership.

    Args:
        target_date: ISO date string like "2026-03-25".
        roster_pitcher_names: List of pitcher names on the user's roster.

    Returns:
        Three lists: (todays_starters, upcoming_starts, off_day_pitchers)
            - todays_starters: roster pitchers with an entry on target_date
            - upcoming_starts: roster pitchers with entries on future dates
            - off_day_pitchers: roster pitchers with no entry at all
    """
    all_rankings = fetch_weekly_rankings()

    normalized_roster = {_normalize(n): n for n in roster_pitcher_names}

    todays_starters: list[dict] = []
    upcoming_starts: list[dict] = []
    matched_names: set[str] = set()

    for entry in all_rankings:
        norm_pitcher = _normalize(entry["pitcher_name"])
        if norm_pitcher not in normalized_roster:
            continue

        original_name = normalized_roster[norm_pitcher]
        matched_names.add(_normalize(original_name))

        if _dates_match(target_date, entry["date"]):
            todays_starters.append({**entry, "roster_name": original_name})
        else:
            upcoming_starts.append({**entry, "roster_name": original_name})

    off_day_pitchers: list[dict] = [
        {"pitcher_name": name}
        for norm, name in normalized_roster.items()
        if norm not in matched_names
    ]

    return todays_starters, upcoming_starts, off_day_pitchers
