"""Phase 1: resolve workbook player names to MLB ids.

The `players` table is built from current rosters, so it degrades badly as a
lookup for older drafts — 2018 resolved at 69% against it, and the misses are
not random. They are the players who have since retired, which means a season
resolved at 69% is a season whose surviving sample is systematically younger
and better than the season actually was. Analysing that subset would bias every
result toward "keepers worked out", because the keepers who busted are exactly
the ones who left the league.

The fix is to resolve against the roster of *that season* rather than today's,
via `sports/1/players?season=YYYY` (~1,300 players per season, retired players
included). That also disambiguates names that belong to different players in
different eras, which a global lookup cannot do.

Matching runs in three passes of decreasing confidence, and anything below the
last one is reported unresolved rather than guessed:

  1.0  exact match on the normalized name
  0.95 last name plus a *compatible* first name (Vlad/Vladimir, Matt/Matthew)
  <0.9 difflib similarity on the full name, only when last names already agree

There is deliberately no "unique last name in this season" pass. It looks
attractive and is wrong often enough to matter: it mapped Gerrit Cole (who
missed 2025 entirely, so was absent from that roster) onto Zach Cole, and Pete
Crow-Armstrong onto Shawn Armstrong. A name the workbook records for a player
who never appeared that season *should* fail to resolve — that is information,
not a gap to paper over.

Where a season holds two players of the same name, the draft sheet's position
column breaks the tie. This is what separates the two Will Smiths (a catcher
and a reliever) and the three Luis Garcias.

Pure functions; the caller supplies the season's roster.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from backend.data.name_matching import normalize_name

# Below this share of names resolved, a season is excluded from analysis
# rather than analysed on a biased subset. See the module docstring.
DEFAULT_FLOOR = 0.90

# difflib ratio below which a last-name-agreeing candidate is still rejected.
FUZZY_CUTOFF = 0.82

# How close a surname must be to be worth considering at all. Loose enough for
# a doubled consonant (Zimmerman / Zimmermann), tight enough that unrelated
# surnames never enter the pool.
SURNAME_CUTOFF = 0.85

_PAREN_RE = re.compile(r"\(([^)]*)\)")
_PUNCT_RE = re.compile(r"[.'`]")

# Positions the workbook and MLB both use for pitchers. Everything else is a
# hitter for the purpose of breaking a same-name tie.
_PITCHER_POSITIONS = {"P", "SP", "RP"}

# First-name pairs that are the same person but too dissimilar for the string
# rules below. Kept deliberately short — each entry is a claim about a specific
# player, and a wrong entry is a silent mis-resolution.
_NICKNAMES = {
    frozenset({"mike", "michael"}),
    frozenset({"jacob", "jake"}),
    frozenset({"chad", "craig"}),      # "Chad Kimbrel" in the 2011 sheet
    frozenset({"dee", "devaris"}),     # Dee Gordon
    frozenset({"kike", "enrique"}),
}

# First names must share this many leading characters to count as compatible
# when neither is a prefix of the other.
_SHARED_PREFIX = 3


@dataclass(frozen=True)
class Candidate:
    """One person in a season's MLB roster."""

    mlb_id: int
    full_name: str
    primary_position: str | None = None
    birth_date: str | None = None


@dataclass(frozen=True)
class Resolution:
    name: str
    mlb_id: int | None
    matched_name: str | None
    confidence: float
    method: str

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "mlb_id": self.mlb_id,
            "matched_name": self.matched_name,
            "confidence": round(self.confidence, 3),
            "method": self.method,
        }


def name_variants(raw: str) -> list[str]:
    """Spellings of a workbook name worth trying, best first.

    The workbook carries hand-typed names with nicknames in parentheses
    ("Mr. Glass (Tatis)"), inconsistent punctuation ("JD" / "J.D."), and
    trailing suffix noise. Each variant is a *spelling* of the same person —
    never a different person — so trying several does not risk a false match.
    """
    variants: list[str] = []

    def add(value: str) -> None:
        cleaned = value.strip()
        if cleaned and cleaned not in variants:
            variants.append(cleaned)

    add(raw)
    # "Mr. Glass (Tatis)" — the parenthetical is the real name, the outside
    # text is a joke. Try both, parenthetical first.
    for inner in _PAREN_RE.findall(raw):
        add(inner)
    add(_PAREN_RE.sub("", raw))
    # "J.D. Martinez" and "JD Martinez" should collapse to the same key.
    add(_PUNCT_RE.sub("", raw))
    return variants


def _key(name: str) -> str:
    return _PUNCT_RE.sub("", normalize_name(name)).strip()


def _last_name(name: str) -> str:
    parts = _key(name).split()
    return parts[-1] if parts else ""


def _first_name(name: str) -> str:
    parts = _key(name).split()
    return parts[0] if parts else ""


def first_names_compatible(a: str, b: str) -> bool:
    """Could these two first names be the same person?

    Accepts the shortenings baseball rosters are full of (Mike/Michael,
    Pete/Peter, Tom/Tommy, Matt/Matthew) and the misspellings the workbook is
    full of (Freedie/Freddie, Alexi/Alexei), while rejecting the pairs that
    caused false matches: Josh/Jim, Jared/Jahmai, Edwin/Elias.
    """
    a, b = a.strip(), b.strip()
    if not a or not b:
        return False
    if a == b:
        return True
    if frozenset({a, b}) in _NICKNAMES:
        return True
    shorter, longer = sorted((a, b), key=len)
    if len(shorter) >= 3 and longer.startswith(shorter):
        return True
    if a[:_SHARED_PREFIX] == b[:_SHARED_PREFIX]:
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.7


def is_pitcher(position: str | None) -> bool:
    """Does this position string denote a pitcher?

    The workbook writes compound positions ("SP/RP", "C/1B"); a player counts
    as a pitcher only if every listed slot is one, so a two-way player is
    treated as a hitter rather than silently matching either side.
    """
    if not position:
        return False
    slots = [s.strip().upper() for s in re.split(r"[/,]", position) if s.strip()]
    return bool(slots) and all(s in _PITCHER_POSITIONS for s in slots)


@dataclass
class SeasonIndex:
    """Lookup structures over one season's roster."""

    by_key: dict[str, list[Candidate]]
    by_last: dict[str, list[Candidate]]
    names: list[str]
    by_name: dict[str, Candidate]

    @classmethod
    def build(cls, roster: list[Candidate]) -> SeasonIndex:
        by_key: dict[str, list[Candidate]] = {}
        by_last: dict[str, list[Candidate]] = {}
        by_name: dict[str, Candidate] = {}
        names: list[str] = []
        seen: set[int] = set()
        for person in roster:
            # The adjacent-season fallback concatenates two rosters, so anyone
            # who played both seasons arrives twice. Two rows with one mlb_id
            # are one person; left in, they make every such lookup read as an
            # ambiguous collision and drop the player. That silently excluded
            # exactly the keepers who missed a full season — Tatis in 2022,
            # Edwin Diaz in 2023, Eury Perez in 2024 — which is a failure-biased
            # exclusion, the thing this whole phase is trying to avoid.
            if person.mlb_id in seen:
                continue
            seen.add(person.mlb_id)
            by_key.setdefault(_key(person.full_name), []).append(person)
            # Index a hyphenated surname under each of its parts as well, so
            # the workbook's "Dee Gordon" still reaches Dee Strange-Gordon and
            # "Pete Crow Armstrong" reaches Pete Crow-Armstrong.
            surname = _last_name(person.full_name)
            for key in {surname, *surname.split("-")}:
                if key:
                    by_last.setdefault(key, []).append(person)
            by_name.setdefault(person.full_name, person)
            names.append(person.full_name)
        return cls(by_key, by_last, names, by_name)


def _narrow_by_position(pool: list[Candidate],
                        position_hint: str | None) -> list[Candidate]:
    """Keep only candidates on the same side of the pitcher/hitter line."""
    if position_hint is None or len(pool) < 2:
        return pool
    want = is_pitcher(position_hint)
    narrowed = [c for c in pool if is_pitcher(c.primary_position) == want]
    return narrowed or pool


def resolve_name(raw: str, index: SeasonIndex,
                 position_hint: str | None = None) -> Resolution:
    """Best match for one workbook name within one season's roster.

    `position_hint` is the position the workbook recorded for this pick. It is
    used only to break ties between same-named players, never to reject an
    otherwise unambiguous match — the workbook's positions are stale often
    enough that trusting them further would cost more than it gains.
    """
    for variant in name_variants(raw):
        key = _key(variant)
        if not key:
            continue

        exact = index.by_key.get(key)
        if exact:
            narrowed = _narrow_by_position(exact, position_hint)
            if len(narrowed) == 1:
                confidence = 1.0 if len(exact) == 1 else 0.95
                method = "exact" if len(exact) == 1 else "exact_by_position"
                return Resolution(raw, narrowed[0].mlb_id, narrowed[0].full_name,
                                  confidence, method)
            # Same name, same side of the pitcher/hitter line. The workbook
            # cannot tell them apart, so neither is chosen.
            return Resolution(raw, None, None, 0.0,
                              f"ambiguous_exact:{len(narrowed)}")

        surname = _last_name(variant)
        first = _first_name(variant)
        # A single-token variant is a surname on its own ("Tatis", from the
        # 2022 sheet's "Mr. Glass (Tatis)"). Accept it only when exactly one
        # player in the season carries that surname — the intent is
        # unambiguous in a way a disagreeing *full* name never is.
        if len(_key(variant).split()) == 1:
            solo = _narrow_by_position(index.by_last.get(surname, []),
                                       position_hint)
            if len(solo) == 1:
                return Resolution(raw, solo[0].mlb_id, solo[0].full_name,
                                  0.9, "surname_only")

        # Include near-miss surnames, or a one-letter slip hides the real
        # player entirely: "Jordan Zimmerman" would otherwise never see Jordan
        # Zimmermann and would settle for Ryan Zimmerman instead.
        near = difflib.get_close_matches(surname, list(index.by_last),
                                         n=3, cutoff=SURNAME_CUTOFF)
        pool = [c for key in dict.fromkeys([surname, *near])
                for c in index.by_last.get(key, [])]
        pool = _narrow_by_position(pool, position_hint)

        compatible = [c for c in pool
                      if first_names_compatible(first, _first_name(c.full_name))]
        if len(compatible) == 1:
            return Resolution(raw, compatible[0].mlb_id, compatible[0].full_name,
                              0.95, "last_plus_first")
        if len(compatible) > 1:
            return Resolution(raw, None, None, 0.0,
                              f"ambiguous_last_plus_first:{len(compatible)}")

        # Fuzzy on the full name, but only among people whose last name already
        # agrees — difflib alone happily maps "Chris Sale" onto "Chris Bassitt".
        close = difflib.get_close_matches(key, [_key(c.full_name) for c in pool],
                                          n=1, cutoff=FUZZY_CUTOFF)
        if close:
            match = next(c for c in pool if _key(c.full_name) == close[0])
            ratio = difflib.SequenceMatcher(None, key, close[0]).ratio()
            return Resolution(raw, match.mlb_id, match.full_name, ratio, "fuzzy")

    # Last resort: fuzzy across the whole season. The cutoff is high because
    # at this point the last name itself is suspect.
    key = _key(raw)
    pool = _narrow_by_position(list(index.by_name.values()), position_hint)
    close = difflib.get_close_matches(key, [_key(c.full_name) for c in pool],
                                      n=1, cutoff=0.9)
    if close:
        match = next(c for c in pool if _key(c.full_name) == close[0])
        ratio = difflib.SequenceMatcher(None, key, close[0]).ratio()
        return Resolution(raw, match.mlb_id, match.full_name, ratio, "fuzzy_global")

    return Resolution(raw, None, None, 0.0, "unresolved")


def resolve_season(names: list[str], roster: list[Candidate],
                   position_hints: dict[str, str] | None = None,
                   neighbours: list[list[Candidate]] | None = None
                   ) -> list[Resolution]:
    """Resolve every distinct name in a season against that season's roster.

    `neighbours` are the adjacent seasons' rosters, consulted only for names
    the season itself cannot resolve. Those are overwhelmingly players who were
    drafted but never appeared — injured for the year (Gerrit Cole 2025),
    suspended (Trevor Bauer 2022), or a prospect who did not debut. Naming them
    is strictly better than leaving them unresolved: the draft still spent a
    pick on them, and the ex-post board must value that pick at zero rather
    than drop it, or every season's draft looks better than it was.
    """
    index = SeasonIndex.build(roster)
    hints = position_hints or {}
    resolutions = [resolve_name(name, index, hints.get(name)) for name in names]

    if not neighbours:
        return resolutions

    fallback = SeasonIndex.build([c for roster in neighbours for c in roster])
    for position, resolution in enumerate(resolutions):
        if resolution.mlb_id is not None:
            continue
        found = resolve_name(resolution.name, fallback, hints.get(resolution.name))
        if found.mlb_id is not None:
            resolutions[position] = Resolution(
                found.name, found.mlb_id, found.matched_name,
                found.confidence, f"{found.method}_adjacent_season")
    return resolutions


def resolution_report(resolutions: list[Resolution],
                      floor: float = DEFAULT_FLOOR) -> dict:
    """Match rate for a season, and whether it clears the floor.

    `included` is the number the analysis should act on: a season below the
    floor is excluded outright, because its unresolved names are concentrated
    among older players.
    """
    total = len(resolutions)
    matched = [r for r in resolutions if r.mlb_id is not None]
    rate = len(matched) / total if total else 0.0
    by_method: dict[str, int] = {}
    for r in resolutions:
        by_method[r.method] = by_method.get(r.method, 0) + 1
    return {
        "names": total,
        "resolved": len(matched),
        "match_rate": round(rate, 4),
        "floor": floor,
        "included": total > 0 and rate >= floor,
        "by_method": dict(sorted(by_method.items())),
        "unresolved": sorted(r.name for r in resolutions if r.mlb_id is None),
    }
