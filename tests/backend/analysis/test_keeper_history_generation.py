"""KEEPER_HISTORY generation, and a guard against it drifting again.

The hand-maintained version drifted into 29 field disagreements, seven seasons
credited to a manager who had not joined the league, and 22 invented 2026 rows.
The point of generating it is that those become impossible rather than fixed
once, so the load-bearing test here is the last one: the checked-in TypeScript
must still equal what the fixtures produce.
"""

from __future__ import annotations

import re
from collections import Counter

from backend.scripts.generate_keeper_history import (
    TARGET,
    _ARRAY_RE,
    canonical_managers,
    collect,
    render,
)


class TestManagerCanonicalization:
    def test_a_single_season_typo_loses_to_the_correct_spelling(self):
        """The 2023 sheet spells Eric Mercado "Eric Mercardo" once."""
        counts = Counter({"Eric Mercado": 15, "Eric Mercardo": 1})
        mapping, merges = canonical_managers(counts)

        assert mapping["Eric Mercardo"] == "Eric Mercado"
        assert mapping["Eric Mercado"] == "Eric Mercado"
        assert ("Eric Mercardo", "Eric Mercado") in merges

    def test_handover_parentheticals_are_stripped(self):
        """2015 records the season a franchise changed hands."""
        counts = Counter({"Tim Riker": 10, "Tim Riker (Brian Martin)": 1,
                          "Matt Wayne": 10, "Matt Wayne (Cameron Rich)": 1})
        mapping, _ = canonical_managers(counts)

        assert mapping["Tim Riker (Brian Martin)"] == "Tim Riker"
        assert mapping["Matt Wayne (Cameron Rich)"] == "Matt Wayne"

    def test_shortenings_collapse_to_the_common_spelling(self):
        counts = Counter({"David Rotatori": 12, "Dave Rotatori": 2,
                          "Chris Herbst": 12, "Christopher Herbst": 1})
        mapping, _ = canonical_managers(counts)

        assert mapping["Dave Rotatori"] == "David Rotatori"
        assert mapping["Christopher Herbst"] == "Chris Herbst"

    def test_genuinely_different_managers_are_not_merged(self):
        counts = Counter({"Jess Barron": 10, "Jason McComb": 10,
                          "Bryan Lewis": 10, "Russell Berry": 3})
        mapping, merges = canonical_managers(counts)

        assert merges == []
        assert len(set(mapping.values())) == 4


class TestCollect:
    def test_only_the_leagues_managers_appear(self):
        """Eleven: ten seats, with Russell Berry replacing Chris Herbst in 2026."""
        _, meta = collect()
        assert len(meta["managers"]) == 11
        assert "Eric Mercardo" not in meta["managers"]
        assert {"Chris Herbst", "Russell Berry"} <= set(meta["managers"])

    def test_players_are_grouped_by_id_not_by_spelling(self):
        """The workbook spells Vladimir Guerrero Jr. three ways.

        Grouping by name splits one three-season keeper run into three
        single-season entries that the panel then never displays.
        """
        players, _ = collect()
        vlad = [p for p in players if "Guerrero" in p["playerName"]]

        assert len(vlad) == 1
        assert [e["year"] for e in vlad[0]["entries"]] == [2019, 2020, 2022]

    def test_every_player_kept_at_least_twice(self):
        players, _ = collect()
        assert players and all(len(p["entries"]) >= 2 for p in players)

    def test_entries_are_chronological(self):
        players, _ = collect()
        for player in players:
            years = [e["year"] for e in player["entries"]]
            assert years == sorted(years), player["playerName"]

    def test_round_costs_mostly_follow_the_keeper_doctrine_within_a_run(self):
        """Each extra season costs five rounds earlier, floored at round 1.

        Only checked inside an unbroken run: `seasonsKept` resets to 1 when a
        player is released and re-drafted, and the cost resets with it.

        Deliberately a rate rather than an absolute. The league grants real
        exceptions -- the 2022 sheet notes Pete Alonso moving from a 12 to an
        11 because the 12th-round pick had already been traded away, and Aaron
        Judge's 2020 cost is a round off the formula. Those belong to the
        league, not to this generator, so the invariant is that the doctrine
        describes nearly every transition rather than all of them.
        """
        players, _ = collect()
        checked, deviations = 0, []
        for player in players:
            for previous, entry in zip(player["entries"], player["entries"][1:]):
                if previous["seasonsKept"] is None or entry["seasonsKept"] is None:
                    continue   # 2015/2016 did not record it
                if entry["seasonsKept"] != previous["seasonsKept"] + 1:
                    continue   # a new run, not a continuation
                checked += 1
                if entry["roundCost"] != max(1, previous["roundCost"] - 5):
                    deviations.append(
                        f"{player['playerName']} {entry['year']}: "
                        f"{previous['roundCost']} -> {entry['roundCost']}")

        assert checked > 50, "doctrine check covered too few transitions"
        assert len(deviations) / checked < 0.1, (
            f"{len(deviations)}/{checked} transitions break the keeper "
            f"doctrine, more than the league's known exceptions: {deviations}")


class TestRender:
    def test_output_parses_back_to_the_same_entries(self):
        players, _ = collect()
        rendered = render(players)

        names = re.findall(r"playerName: '([^']+)'", rendered)
        assert len(names) == len(players)
        years = re.findall(r"year: (\d{4})", rendered)
        assert len(years) == sum(len(p["entries"]) for p in players)

    def test_apostrophes_in_a_name_are_escaped(self):
        rendered = render([{
            "mlb_id": 1, "playerName": "Ke'Bryan Hayes",
            "entries": [{"year": 2022, "manager": "Chris Herbst",
                         "roundCost": 25, "seasonsKept": 1},
                        {"year": 2023, "manager": "Chris Herbst",
                         "roundCost": 20, "seasonsKept": 2}],
        }])
        assert r"playerName: 'Ke\'Bryan Hayes'" in rendered


def test_checked_in_typescript_matches_the_fixtures():
    """The drift guard.

    If this fails, either the workbook fixtures changed or someone edited
    KEEPER_HISTORY by hand. Either way the fix is to re-run
    `python -m backend.scripts.generate_keeper_history`, not to edit the array.
    """
    players, _ = collect()
    match = _ARRAY_RE.search(TARGET.read_text())

    assert match is not None, f"KEEPER_HISTORY array not found in {TARGET}"
    assert match.group(0) == match.group(1) + render(players) + match.group(2), (
        "src/lib/draft-history.ts is out of sync with the league-history "
        "fixtures — re-run backend.scripts.generate_keeper_history"
    )
