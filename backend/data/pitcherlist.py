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

            # Find ALL rating cells in the row (tables may have two
            # pitcher/rating pairs per row: away and home)
            rating_indices = [
                i for i, text in enumerate(texts) if _RATING_RE.match(text)
            ]

            if not rating_indices:
                # This row may be a date separator — check first cell
                if texts and _looks_like_date(texts[0]):
                    current_date = texts[0]
                continue

            # Update current_date from the first cell if it looks like a date
            if _looks_like_date(texts[0]):
                current_date = texts[0]

            # Process each pitcher/rating pair in the row
            for rating_idx in rating_indices:
                raw_rating = texts[rating_idx]
                try:
                    tier, score = parse_rating(raw_rating)
                except ValueError:
                    continue

                # The pitcher name is the cell immediately before the rating
                pitcher_name = texts[rating_idx - 1] if rating_idx >= 1 else ""

                # The opponent/game: for the first pair, it's 2 cells before
                # the rating; for subsequent pairs, reuse the same game cell
                if rating_idx >= 2 and not _RATING_RE.match(texts[rating_idx - 2]):
                    opponent = texts[rating_idx - 2]
                else:
                    # Reuse opponent from the first pair (e.g. home pitcher)
                    opponent = results[-1]["opponent"] if results else ""

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


def discover_article_urls() -> list[str]:
    """Fetch pitcherlist.com homepage and find all Sit/Start article URLs.

    Looks for anchor tags whose visible text contains "sit", "start", and
    whose href contains "sit-start" (case-insensitive).  Returns multiple
    URLs when more than one week's article is linked from the homepage.

    Returns:
        List of absolute URL strings (may be empty).
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
        return []

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    urls: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True).lower()
        # Require "sit-start" in the URL path to skip nav/hub links
        if "sit-start" in href and "sit" in text and "start" in text:
            if href.startswith("http"):
                url = href
            else:
                url = PITCHERLIST_HOME.rstrip("/") + "/" + href.lstrip("/")
            if url not in seen:
                seen.add(url)
                urls.append(url)

    return urls


def discover_latest_article_url() -> Optional[str]:
    """Fetch pitcherlist.com homepage and find the latest Sit/Start article URL.

    Returns:
        Absolute URL string, or None if not found.
    """
    urls = discover_article_urls()
    return urls[0] if urls else None


def _fetch_and_parse_url(url: str) -> list[dict]:
    """Fetch a single PitcherList article and parse its tables.

    Args:
        url: Absolute URL of the article.

    Returns:
        List of parsed ranking dicts (see parse_sit_start_tables).
    """
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

    return parse_sit_start_tables(html)


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

    rankings = _fetch_and_parse_url(url)
    _cache[week_key] = (now, rankings)
    return rankings


def fetch_all_available_rankings() -> list[dict]:
    """Fetch rankings from ALL Sit/Start articles linked on the homepage.

    When a matchup period spans two calendar weeks, PitcherList may have
    articles for both weeks on the homepage.  This function discovers and
    fetches all of them, deduplicating by (pitcher_name, date).

    Returns:
        Combined list of parsed ranking dicts across all articles.
    """
    import time

    cache_key = "_all_articles"
    now = time.time()
    if cache_key in _cache:
        ts, data = _cache[cache_key]
        if now - ts < _CACHE_TTL_SECONDS:
            logger.debug("PitcherList all-articles cache hit")
            return data

    urls = discover_article_urls()
    if not urls:
        logger.warning("Could not discover any PitcherList article URLs")
        return []

    combined: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for url in urls:
        rankings = _fetch_and_parse_url(url)
        for entry in rankings:
            key = (entry["pitcher_name"], entry["date"])
            if key not in seen:
                seen.add(key)
                combined.append(entry)

    _cache[cache_key] = (now, combined)
    return combined


# ── Name normalization & date matching ────────────────────────────────────────


def _normalize(name: str) -> str:
    """Strip accents and lowercase a player name for fuzzy matching."""
    nfkd = unicodedata.normalize("NFKD", name)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


def _name_matches(pl_name: str, roster_name: str) -> bool:
    """Check if a PitcherList abbreviated name matches a full roster name.

    Handles cases like "J. Soriano" matching "Jose Soriano" by comparing
    the last name exactly and checking if the first initial matches.
    Also handles exact normalized matches.
    """
    norm_pl = _normalize(pl_name)
    norm_roster = _normalize(roster_name)

    # Exact match
    if norm_pl == norm_roster:
        return True

    pl_parts = norm_pl.split()
    roster_parts = norm_roster.split()
    if len(pl_parts) < 2 or len(roster_parts) < 2:
        return False

    # Compare last names (everything after first token)
    pl_last = " ".join(pl_parts[1:])
    roster_last = " ".join(roster_parts[1:])
    if pl_last != roster_last:
        return False

    # Check if PL first part is an initial (e.g. "j." or "j")
    pl_first = pl_parts[0].rstrip(".")
    roster_first = roster_parts[0]
    if len(pl_first) == 1 and roster_first.startswith(pl_first):
        return True

    # Check if one first name is a prefix of the other (e.g. "Matt" / "Matthew")
    # Require at least 3 chars to avoid false positives
    shorter = min(pl_first, roster_first, key=len)
    longer = max(pl_first, roster_first, key=len)
    if len(shorter) >= 3 and longer.startswith(shorter):
        return True

    return False


def _parse_entry_date(entry_date: str) -> tuple[int, int] | None:
    """Extract (month, day) from a human-readable date like 'Wednesday 3/25'."""
    m = re.search(r"(\d{1,2})/(\d{1,2})", entry_date)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _parse_iso_date(iso_date: str) -> tuple[int, int] | None:
    """Extract (month, day) from an ISO date like '2026-03-25'."""
    try:
        parts = iso_date.split("-")
        return int(parts[1]), int(parts[2])
    except (IndexError, ValueError):
        return None


def _dates_match(target: str, entry_date: str) -> bool:
    """Check whether an ISO date string matches a day-of-week date string.

    Args:
        target: ISO date like "2026-03-25".
        entry_date: Human-readable date like "Wednesday 3/25".

    Returns:
        True if month and day match.
    """
    t = _parse_iso_date(target)
    e = _parse_entry_date(entry_date)
    if t is None or e is None:
        return False
    return t == e


def _entry_date_is_after(entry_date: str, target: str) -> bool:
    """Check whether an entry date (e.g. 'Thursday 3/27') is strictly after an ISO date.

    Compares month/day only (safe within a baseball season).
    """
    e = _parse_entry_date(entry_date)
    t = _parse_iso_date(target)
    if e is None or t is None:
        return False
    return e > t


def _entry_date_is_on_or_before(entry_date: str, target: str) -> bool:
    """Check whether an entry date is on or before an ISO date.

    Compares month/day only (safe within a baseball season).
    """
    e = _parse_entry_date(entry_date)
    t = _parse_iso_date(target)
    if e is None or t is None:
        return False
    return e <= t


# ── Streamer article scraper ─────────────────────────────────────────────────

# Tier labels used in the PitcherList SP Streamer Ranks article
_STREAMER_TIER_MAP: dict[str, str] = {
    "auto start": "auto_start",
    "auto-start": "auto_start",
    "probably start": "probably_start",
    "probably-start": "probably_start",
    "questionable start": "questionable_start",
    "questionable-start": "questionable_start",
    "do not start": "do_not_start",
    "do-not-start": "do_not_start",
}

# Human-readable labels for display
_STREAMER_TIER_LABELS: dict[str, str] = {
    "auto_start": "Auto Start",
    "probably_start": "Prob. Start",
    "questionable_start": "Quest. Start",
    "do_not_start": "Do Not Start",
}

_STREAMER_DATE_RE = re.compile(
    r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+(\d{1,2}/\d{1,2})",
    re.IGNORECASE,
)


def discover_streamer_article_urls(max_articles: int = 2) -> list[str]:
    """Find SP Streamer Ranks article URLs on the PitcherList homepage.

    Looks for anchor tags whose href contains "starting-pitcher-streamer".
    Returns only the most recent articles (homepage lists them newest first).

    Args:
        max_articles: Maximum number of article URLs to return.

    Returns:
        List of absolute URL strings (may be empty).
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
        return []

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    urls: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True).lower()
        if "starting-pitcher-streamer" in href and "streamer" in text:
            if href.startswith("http"):
                url = href
            else:
                url = PITCHERLIST_HOME.rstrip("/") + "/" + href.lstrip("/")
            if url not in seen:
                seen.add(url)
                urls.append(url)
                if len(urls) >= max_articles:
                    break

    return urls


def parse_streamer_tables(html: str) -> list[dict]:
    """Parse HTML tables from a PitcherList SP Streamer Ranks article.

    These articles have daily tables with columns: Rank, Pitcher, Matchup,
    Rostership.  Pitchers are grouped by tier headers within the table
    (Auto Start, Probably Start, Questionable Start, Do Not Start).

    Uses document-order scanning to associate date headings (e.g.
    "Friday 4/3 Starting Pitcher Streamer Rankings") with their
    immediately following ranking table.

    Args:
        html: Full HTML of the article page.

    Returns:
        List of dicts with keys:
            pitcher_name, opponent, date, rank, tier_label, mapped_tier,
            rostership, raw
    """
    from bs4 import BeautifulSoup, NavigableString

    soup = BeautifulSoup(html, "html.parser")
    results: list[dict] = []

    # Walk ALL elements in document order, pairing dates with tables
    table_dates: dict[int, str] = {}  # table id → date string
    last_date = ""

    for el in soup.descendants:
        if isinstance(el, NavigableString):
            m = _STREAMER_DATE_RE.search(str(el))
            if m:
                last_date = f"{m.group(1).capitalize()} {m.group(2)}"
        elif hasattr(el, "name") and el.name == "table":
            table_dates[id(el)] = last_date

    for table in soup.find_all("table"):
        # Skip non-ranking tables (e.g. matchup quality grids)
        first_row = table.find("tr")
        if not first_row:
            continue
        header_texts = [c.get_text(strip=True).lower() for c in first_row.find_all(["td", "th"])]
        if "rank" not in header_texts:
            continue

        current_date = table_dates.get(id(table), "")
        current_tier = ""

        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if not cells:
                continue

            texts = [c.get_text(strip=True) for c in cells]

            # Skip header rows
            if any(t.lower() in ("rank", "pitcher", "matchup", "rostership") for t in texts):
                continue

            # Check for tier header row: typically ['', 'Auto Start', '', '']
            non_empty = [t for t in texts if t]
            if non_empty:
                tier_match = _match_streamer_tier(non_empty[0].lower())
                if tier_match and len(non_empty) <= 2:
                    current_tier = tier_match
                    continue

            # Parse pitcher data row: [rank, pitcher_name, opponent, rostership]
            if len(texts) < 3:
                continue

            rank_val = None
            pitcher_name = ""
            opponent = ""
            rostership = ""

            for idx, text in enumerate(texts):
                if rank_val is None and text.isdigit():
                    rank_val = int(text)
                    if idx + 1 < len(texts):
                        pitcher_name = texts[idx + 1]
                    if idx + 2 < len(texts):
                        opponent = texts[idx + 2]
                    if idx + 3 < len(texts):
                        rostership = texts[idx + 3]
                    break

            if not pitcher_name or rank_val is None:
                continue

            mapped_tier = current_tier or "questionable_start"
            raw_label = _STREAMER_TIER_LABELS.get(mapped_tier, mapped_tier)

            results.append({
                "pitcher_name": pitcher_name,
                "opponent": opponent,
                "date": current_date,
                "rank": rank_val,
                "tier_label": raw_label,
                "mapped_tier": mapped_tier,
                "rostership": rostership,
                "raw": raw_label,
            })

    return results


def _match_streamer_tier(text: str) -> str:
    """Check if text matches a known streamer tier label.

    Returns:
        Mapped tier string (e.g. "auto_start") or empty string.
    """
    text = text.strip().lower()
    # Direct match
    if text in _STREAMER_TIER_MAP:
        return _STREAMER_TIER_MAP[text]
    # Check if the text contains a tier label (for rows with extra text)
    for label, mapped in _STREAMER_TIER_MAP.items():
        if label in text and len(text) < len(label) + 15:
            return mapped
    return ""


def fetch_streamer_rankings() -> list[dict]:
    """Fetch and cache SP Streamer Ranks from all available articles.

    Returns:
        Combined list of parsed streamer ranking dicts, deduplicated
        by (pitcher_name, date).
    """
    import time

    cache_key = "_streamer_articles"
    now = time.time()
    if cache_key in _cache:
        ts, data = _cache[cache_key]
        if now - ts < _CACHE_TTL_SECONDS:
            logger.debug("Streamer rankings cache hit")
            return data

    urls = discover_streamer_article_urls()
    if not urls:
        logger.warning("Could not discover any SP Streamer article URLs")
        return []

    combined: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for url in urls:
        rankings = _fetch_and_parse_streamer_url(url)
        for entry in rankings:
            key = (entry["pitcher_name"], entry["date"])
            if key not in seen:
                seen.add(key)
                combined.append(entry)

    _cache[cache_key] = (now, combined)
    logger.info("Fetched %d streamer rankings from %d articles", len(combined), len(urls))
    return combined


def _fetch_and_parse_streamer_url(url: str) -> list[dict]:
    """Fetch a single SP Streamer Ranks article and parse its tables."""
    import urllib.request

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (fantasy-baseball-helper/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to fetch SP Streamer article %s: %s", url, exc)
        return []

    return parse_streamer_tables(html)


def get_streaming_options(
    all_rostered_names: list[str],
    target_date: str,
    matchup_end_date: str | None = None,
) -> list[dict]:
    """Find unrostered pitchers from the PitcherList SP Streamer Ranks article.

    Uses the dedicated daily streaming article (separate from Sit/Start) which
    ranks all SPs by day with tiers: Auto Start, Probably Start, Questionable
    Start, Do Not Start.  Falls back to the Sit/Start article if the streaming
    article is unavailable.

    Args:
        all_rostered_names: Names of all rostered players across the league.
        target_date: ISO date string like "2026-03-25".
        matchup_end_date: ISO date of last day of matchup period.

    Returns:
        List of dicts sorted by rank (best first), each with:
            pitcher_name, opponent, date, tier, score, raw
    """
    if not all_rostered_names:
        return []

    # Try the dedicated streaming article first
    streamer_rankings = fetch_streamer_rankings()

    if streamer_rankings:
        return _filter_streamers_from_streamer_article(
            streamer_rankings, all_rostered_names, target_date, matchup_end_date
        )

    # Fallback: use Sit/Start article data
    logger.info("Streamer article unavailable, falling back to Sit/Start data")
    return _filter_streamers_from_sit_start(
        all_rostered_names, target_date, matchup_end_date
    )


def _filter_streamers_from_streamer_article(
    rankings: list[dict],
    all_rostered_names: list[str],
    target_date: str,
    matchup_end_date: str | None,
) -> list[dict]:
    """Filter streamer article rankings to unrostered pitchers in date range."""
    _STREAMABLE_TIERS = {"auto_start", "probably_start", "questionable_start"}

    streamers: list[dict] = []
    for entry in rankings:
        if entry.get("mapped_tier") not in _STREAMABLE_TIERS:
            continue

        # Filter by date: on or after today, on or before matchup end
        if not _dates_match(target_date, entry["date"]) and not _entry_date_is_after(entry["date"], target_date):
            continue
        if matchup_end_date and not _entry_date_is_on_or_before(entry["date"], matchup_end_date):
            continue

        # Check if pitcher is rostered
        is_rostered = any(
            _name_matches(entry["pitcher_name"], name)
            for name in all_rostered_names
        )
        if is_rostered:
            continue

        streamers.append({
            "pitcher_name": entry["pitcher_name"],
            "opponent": entry.get("opponent", ""),
            "date": entry.get("date", ""),
            "tier": entry["mapped_tier"],
            "score": entry.get("rank", 99),
            "raw": entry.get("raw", ""),
        })

    # Sort by date (chronological), then rank ascending within each date
    def _sort_key(s: dict) -> tuple:
        parsed = _parse_entry_date(s["date"])
        date_key = parsed if parsed else (99, 99)
        return (date_key, s["score"])

    streamers.sort(key=_sort_key)
    return streamers


def _filter_streamers_from_sit_start(
    all_rostered_names: list[str],
    target_date: str,
    matchup_end_date: str | None,
) -> list[dict]:
    """Fallback: filter Sit/Start article data for streaming options."""
    if matchup_end_date:
        all_rankings = fetch_all_available_rankings()
    else:
        all_rankings = fetch_weekly_rankings()

    _STREAMABLE_TIERS = {"strong_start", "start", "maybe"}

    streamers: list[dict] = []
    for entry in all_rankings:
        if entry.get("mapped_tier") not in _STREAMABLE_TIERS:
            continue

        if not _dates_match(target_date, entry["date"]) and not _entry_date_is_after(entry["date"], target_date):
            continue
        if matchup_end_date and not _entry_date_is_on_or_before(entry["date"], matchup_end_date):
            continue

        is_rostered = any(
            _name_matches(entry["pitcher_name"], name)
            for name in all_rostered_names
        )
        if is_rostered:
            continue

        streamers.append({
            "pitcher_name": entry["pitcher_name"],
            "opponent": entry.get("opponent", ""),
            "date": entry.get("date", ""),
            "tier": entry["mapped_tier"],
            "score": entry.get("score", 0),
            "raw": entry.get("raw", ""),
        })

    def _sort_key(s: dict) -> tuple:
        parsed = _parse_entry_date(s["date"])
        date_key = parsed if parsed else (99, 99)
        return (date_key, -s["score"])

    streamers.sort(key=_sort_key)
    return streamers


def get_rankings_for_date(
    target_date: str,
    roster_pitcher_names: list[str],
    matchup_end_date: str | None = None,
) -> tuple[list, list, list]:
    """Filter cached rankings by date and roster membership.

    Args:
        target_date: ISO date string like "2026-03-25".
        roster_pitcher_names: List of pitcher names on the user's roster.
        matchup_end_date: ISO date string of last day of matchup period.
            When provided, fetches all available PitcherList articles
            (spanning multiple weeks) and caps upcoming starts at this date.

    Returns:
        Three lists: (todays_starters, upcoming_starts, off_day_pitchers)
            - todays_starters: roster pitchers with an entry on target_date
            - upcoming_starts: roster pitchers with entries on future dates
              (up to matchup_end_date)
            - off_day_pitchers: roster pitchers with no entry at all
    """
    # When matchup_end_date is provided, fetch all available articles
    # (may span multiple calendar weeks); otherwise just the current week.
    if matchup_end_date:
        all_rankings = fetch_all_available_rankings()
    else:
        all_rankings = fetch_weekly_rankings()

    todays_starters: list[dict] = []
    upcoming_starts: list[dict] = []
    matched_names: set[str] = set()

    for entry in all_rankings:
        for roster_name in roster_pitcher_names:
            if not _name_matches(entry["pitcher_name"], roster_name):
                continue

            matched_names.add(roster_name)

            if _dates_match(target_date, entry["date"]):
                todays_starters.append({**entry, "roster_name": roster_name})
            elif _entry_date_is_after(entry["date"], target_date):
                # Cap at matchup end date if provided
                if matchup_end_date and not _entry_date_is_on_or_before(entry["date"], matchup_end_date):
                    break
                upcoming_starts.append({**entry, "roster_name": roster_name})
            # else: past date — skip
            break

    off_day_pitchers: list[dict] = [
        {"pitcher_name": name}
        for name in roster_pitcher_names
        if name not in matched_names
    ]

    return todays_starters, upcoming_starts, off_day_pitchers
