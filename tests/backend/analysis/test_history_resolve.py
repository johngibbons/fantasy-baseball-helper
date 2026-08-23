"""Phase 1 name resolution.

The cases here are the ones that actually went wrong against the real
workbook. Each false-positive test names the wrong answer an earlier version
produced, because a mis-resolution is invisible downstream — the player simply
carries someone else's season.
"""

from __future__ import annotations

import pytest

from backend.analysis.history.resolve import (
    Candidate,
    SeasonIndex,
    first_names_compatible,
    is_pitcher,
    name_variants,
    resolution_report,
    resolve_name,
    resolve_season,
)


def index(*people: tuple[int, str, str]) -> SeasonIndex:
    return SeasonIndex.build([
        Candidate(mlb_id=i, full_name=name, primary_position=position)
        for i, name, position in people
    ])


class TestExactAndVariants:
    def test_exact_match(self):
        result = resolve_name("Mike Trout", index((1, "Mike Trout", "OF")))
        assert (result.mlb_id, result.confidence, result.method) == (1, 1.0, "exact")

    def test_accents_and_punctuation_are_normalized(self):
        board = index((1, "José Ramírez", "3B"), (2, "J.D. Martinez", "DH"))

        assert resolve_name("Jose Ramirez", board).mlb_id == 1
        assert resolve_name("JD Martinez", board).mlb_id == 2

    def test_parenthetical_nickname_resolves_to_the_real_name(self):
        """The 2022 sheet lists Tatis as `Mr. Glass (Tatis)`."""
        board = index((1, "Fernando Tatis Jr.", "OF"))
        assert resolve_name("Mr. Glass (Tatis)", board).mlb_id == 1

    def test_name_variants_tries_inside_and_outside_the_parentheses(self):
        assert "Tatis" in name_variants("Mr. Glass (Tatis)")
        assert "Mr. Glass" in name_variants("Mr. Glass (Tatis)")


class TestFirstNameCompatibility:
    @pytest.mark.parametrize("a,b", [
        ("mike", "michael"), ("pete", "peter"), ("vlad", "vladimir"),
        ("tom", "tommy"), ("matt", "matthew"), ("freedie", "freddie"),
        ("alexi", "alexei"), ("zach", "zack"), ("cory", "corey"),
        ("jacob", "jake"), ("kike", "enrique"),
    ])
    def test_accepts_shortenings_and_misspellings(self, a, b):
        assert first_names_compatible(a, b)

    @pytest.mark.parametrize("a,b", [
        ("josh", "jim"), ("jared", "jahmai"), ("edwin", "elias"),
        ("gerrit", "zach"), ("kutter", "jp"), ("wander", "maikel"),
    ])
    def test_rejects_the_pairs_that_caused_false_matches(self, a, b):
        assert not first_names_compatible(a, b)


class TestFalsePositivesThatOccurred:
    def test_absent_player_does_not_borrow_a_same_surname_stranger(self):
        """Gerrit Cole missed 2025 entirely, so he is not in that roster.

        An earlier "unique last name" pass matched him to Zach Cole. Failing to
        resolve is the correct answer: he produced nothing that season.
        """
        result = resolve_name("Gerrit Cole", index((1, "Zach Cole", "OF")), "SP")
        assert result.mlb_id is None
        assert result.method == "unresolved"

    def test_hyphenated_surname_is_reachable_from_its_parts(self):
        board = index((1, "Pete Crow-Armstrong", "OF"), (2, "Shawn Armstrong", "RP"))
        result = resolve_name("Pete Crow Armstrong", board, "OF")
        assert result.mlb_id == 1

    def test_near_miss_surname_finds_the_right_player(self):
        """`Jordan Zimmerman` must reach Zimmermann, not Ryan Zimmerman."""
        board = index((1, "Ryan Zimmerman", "3B"), (2, "Jordan Zimmermann", "SP"))
        assert resolve_name("Jordan Zimmerman", board).mlb_id == 2
        assert resolve_name("Ryan Zimmerman", board).mlb_id == 1


class TestAmbiguity:
    BOTH_SMITHS = ((1, "Will Smith", "C"), (2, "Will Smith", "RP"))

    def test_same_name_without_a_hint_is_left_unresolved(self):
        result = resolve_name("Will Smith", index(*self.BOTH_SMITHS))
        assert result.mlb_id is None
        assert result.method.startswith("ambiguous_exact")

    def test_position_breaks_the_tie(self):
        board = index(*self.BOTH_SMITHS)
        assert resolve_name("Will Smith", board, "RP").mlb_id == 2
        assert resolve_name("Will Smith", board, "C").mlb_id == 1

    def test_two_way_position_counts_as_a_hitter(self):
        assert is_pitcher("SP") and is_pitcher("SP/RP")
        assert not is_pitcher("SP/OF")   # Ohtani: valued on both boards
        assert not is_pitcher("C/1B")
        assert not is_pitcher(None)


class TestAdjacentSeasonFallback:
    def test_player_absent_all_season_is_named_from_a_neighbour(self):
        """Injured-all-year players still cost a draft pick.

        Naming them lets the ex-post board value that pick at zero rather than
        drop it, which would make every draft look better than it was.
        """
        roster = [Candidate(mlb_id=1, full_name="Zach Cole", primary_position="OF")]
        neighbour = [Candidate(mlb_id=2, full_name="Gerrit Cole",
                               primary_position="SP")]

        [result] = resolve_season(["Gerrit Cole"], roster,
                                  {"Gerrit Cole": "SP"}, [neighbour])
        assert result.mlb_id == 2
        assert result.method.endswith("_adjacent_season")

    def test_neighbour_is_not_consulted_when_the_season_already_matched(self):
        roster = [Candidate(mlb_id=1, full_name="Mike Trout", primary_position="OF")]
        neighbour = [Candidate(mlb_id=99, full_name="Mike Trout",
                               primary_position="OF")]

        [result] = resolve_season(["Mike Trout"], roster, {}, [neighbour])
        assert (result.mlb_id, result.method) == (1, "exact")


class TestReport:
    def test_season_below_the_floor_is_excluded(self):
        roster = [Candidate(mlb_id=1, full_name="Mike Trout")]
        names = ["Mike Trout"] + [f"Ghost {i}" for i in range(9)]

        report = resolution_report(resolve_season(names, roster), floor=0.90)
        assert report["resolved"] == 1
        assert report["match_rate"] == 0.1
        assert report["included"] is False
        assert len(report["unresolved"]) == 9

    def test_season_above_the_floor_is_included(self):
        roster = [Candidate(mlb_id=i, full_name=f"Player {i}") for i in range(10)]
        names = [f"Player {i}" for i in range(10)]

        report = resolution_report(resolve_season(names, roster), floor=0.90)
        assert report["match_rate"] == 1.0
        assert report["included"] is True


class TestDuplicateRosterRows:
    def test_the_same_person_twice_is_not_an_ambiguous_collision(self):
        """The adjacent-season fallback concatenates two rosters.

        Anyone who played both seasons arrives twice. Treating that as a
        same-name collision dropped precisely the keepers who missed a full
        season, which biases the sample toward decisions that worked out.
        """
        both_seasons = [
            Candidate(mlb_id=7, full_name="Fernando Tatis Jr.", primary_position="OF"),
            Candidate(mlb_id=7, full_name="Fernando Tatis Jr.", primary_position="OF"),
        ]
        result = resolve_name("Fernando Tatis Jr.", SeasonIndex.build(both_seasons))

        assert result.mlb_id == 7
        assert result.method == "exact"

    def test_genuinely_different_people_still_collide(self):
        board = index((1, "Will Smith", "C"), (2, "Will Smith", "RP"))
        assert resolve_name("Will Smith", board).mlb_id is None
