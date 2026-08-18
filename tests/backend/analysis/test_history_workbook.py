"""Phase 0 parser: the three Draft-sheet layout eras and the keeper shapes.

The rows here are transcribed from the real workbook, one small block per
layout era, so a regression in column mapping shows up as a test failure rather
than as a season quietly losing its owners.
"""

from __future__ import annotations

from backend.analysis.history.workbook import (
    parse_draft_sheet,
    parse_keeper_sheet,
    parse_ranking_sheet,
    ranking_snapshot_date,
    split_owner,
    validate_draft,
)

# 2018-2026: an explicit `#` column.
NUMBERED_ROWS = [
    (None, "#", "Owner", "Player", "Position", "MLB Team", "Notes"),
    ("Round 1", None, None, None, None, None, None),
    (None, 1.0, "Harris Cook", "Bobby Witt Jr.", "SS", "KC", None),
    (None, 2, "Chris Herbst", "Jose Ramirez", "3B", "CLE", None),
    ("Round 2", None, None, None, None, None, None),
    (None, 3, "Chris Herbst", "Kyle Tucker", "OF", "CHC", "Keeper"),
    (None, 4, "Harris Cook", "Mookie Betts", "SS/OF", "LAD", None),
]

# 2025 shifts MLB Team and Notes right by one, leaving a spacer column.
SPACER_ROWS = [
    (None, "#", "Owner", "Player", "Position", None, "MLB Team", "Notes"),
    ("Round 1", None, None, None, None, None, None, None),
    (None, 1.0, "Harris Cook", "Bobby Witt Jr.", "SS", None, "KC", None),
    (None, 2, "Bryan Lewis", "Mookie Betts", "SS/OF", None, "LAD", "Keeper"),
]

# 2016-2017: `Owner` header, but the pick number shares column 0.
POSITIONAL_ROWS = [
    (None, "Owner", "Player", "Position", "MLB Team", "Notes"),
    ("Round 1", None, None, None, None, None),
    (1.0, "Jess Barron", "Clayton Kershaw", "SP", "LAD", "Keeper"),
    (2.0, "Jason McComb", "Madison Bumgarner", "SP", "SF", None),
]

# 2010-2014: no `Owner` header at all; the team label precedes Player.
FRANCHISE_ROWS = [
    (None, None, "Player", "Position", "MLB Team"),
    ("Round 1", None, None, None, None),
    (1.0, "Atlanta Bombers", "Tommy Hanson", "SP", "Atlanta Braves"),
    (2.0, "Miami Vice All-Stars", "Aaron Hill", "2B", "Toronto Blue Jays"),
    (3.0, "Atlanta Bombers (from Jeff Goldblum)", "Josh Hamilton", "OF",
     "Texas Rangers"),
]


def test_numbered_layout_maps_columns_by_label():
    parsed = parse_draft_sheet(NUMBERED_ROWS, 2024, "2024 Draft")

    assert parsed.variant == "numbered"
    assert [p["player_name"] for p in parsed.picks] == [
        "Bobby Witt Jr.", "Jose Ramirez", "Kyle Tucker", "Mookie Betts"]
    assert [p["owner"] for p in parsed.picks] == [
        "Harris Cook", "Chris Herbst", "Chris Herbst", "Harris Cook"]
    assert [p["round"] for p in parsed.picks] == [1, 1, 2, 2]
    assert [p["mlb_team"] for p in parsed.picks] == ["KC", "CLE", "CHC", "LAD"]
    assert parsed.picks[2]["notes"] == "Keeper"


def test_spacer_column_does_not_shift_team_and_notes():
    """2025 leaves an empty column between Position and MLB Team."""
    parsed = parse_draft_sheet(SPACER_ROWS, 2025, "2025 Draft")

    assert parsed.picks[0]["mlb_team"] == "KC"
    assert parsed.picks[1]["mlb_team"] == "LAD"
    assert parsed.picks[1]["notes"] == "Keeper"


def test_positional_layout_reads_pick_number_from_column_zero():
    parsed = parse_draft_sheet(POSITIONAL_ROWS, 2017, "2017 Draft")

    assert parsed.variant == "positional"
    assert [p["pick_number"] for p in parsed.picks] == [1, 2]
    assert [p["pick_number_source"] for p in parsed.picks] == ["sheet", "sheet"]
    assert parsed.picks[0]["owner"] == "Jess Barron"


def test_franchise_layout_infers_owner_column_without_a_header():
    parsed = parse_draft_sheet(FRANCHISE_ROWS, 2010, "2010 Draft")

    assert parsed.variant == "positional"
    assert [p["owner"] for p in parsed.picks] == [
        "Atlanta Bombers", "Miami Vice All-Stars", "Atlanta Bombers"]
    assert [p["player_name"] for p in parsed.picks] == [
        "Tommy Hanson", "Aaron Hill", "Josh Hamilton"]


def test_traded_pick_annotation_is_split_off_the_owner():
    """`(from X)` is a trade note, not a distinct franchise.

    Left attached it turned a ten-team league into 28 apparent owners.
    """
    assert split_owner("Atlanta Bombers (from Jeff Goldblum)") == (
        "Atlanta Bombers", "Jeff Goldblum")
    assert split_owner("Armada (via Dingleberries)") == ("Armada", "Dingleberries")
    assert split_owner("Harris Cook") == ("Harris Cook", None)

    parsed = parse_draft_sheet(FRANCHISE_ROWS, 2010, "2010 Draft")
    assert parsed.picks[2]["acquired_from"] == "Jeff Goldblum"
    assert parsed.owners == ["Atlanta Bombers", "Miami Vice All-Stars"]


def test_supplemental_rows_are_flagged_and_left_out_of_round_shape():
    """A bare `Supplemental` heading has no round number.

    Attributing its picks to the previous round is what made every season
    2016-2025 look like it had an overfull round 25.
    """
    rows = [
        (None, "#", "Owner", "Player", "Position", "MLB Team", "Notes"),
        ("Round 25", None, None, None, None, None, None),
        (None, 1, "Chris Herbst", "Mark Vientos", "3B", "NYM", "Keeper"),
        ("Supplemental", None, None, None, None, None, None),
        (None, 2, "Chris Herbst", "Reese Olson", "SP", "DET", None),
        ("Supplemental Round 26", None, None, None, None, None, None),
        (None, 3, "Eric Mercado", "Matt Kemp", "OF", "LAD", None),
    ]
    parsed = parse_draft_sheet(rows, 2025, "2025 Draft")

    assert [p["supplemental"] for p in parsed.picks] == [False, True, True]
    assert [p["round"] for p in parsed.picks] == [25, None, 26]
    # The lone round-25 pick must not be reported as an uneven round just
    # because the supplemental picks sit next to it.
    assert not any(i.kind == "uneven_rounds" for i in parsed.issues)


def test_unparsed_rows_are_reported_rather_than_dropped():
    rows = [
        (None, "#", "Owner", "Player", "Position", "MLB Team", "Notes"),
        ("Round 1", None, None, None, None, None, None),
        (None, 1, "Harris Cook", "Bobby Witt Jr.", "SS", "KC", None),
        (None, 2, "Philadelphia Dingleberries", None, "SP", "CIN", None),
    ]
    parsed = parse_draft_sheet(rows, 2010, "2010 Draft")

    assert len(parsed.picks) == 1
    kinds = {i.kind for i in parsed.issues}
    assert "row_without_player" in kinds
    detail = next(i for i in parsed.issues if i.kind == "row_without_player")
    assert detail.raw[2] == "Philadelphia Dingleberries"


def test_validate_draft_catches_scrambled_and_duplicated_picks():
    picks = [
        {"pick_number": 2, "round": 1, "owner": "A", "supplemental": False},
        {"pick_number": 1, "round": 1, "owner": "B", "supplemental": False},
        {"pick_number": 1, "round": 1, "owner": "B", "supplemental": False},
    ]
    kinds = {i.kind for i in validate_draft(picks, "sheet")}

    assert "picks_out_of_order" in kinds
    assert "duplicate_pick_numbers" in kinds


class TestKeeperSheets:
    HEADER_3 = ("Manager", "Keeper 1", "Round Forfeited", "Seasons Kept",
                "Keeper 2", "Round Forfeited", "Seasons Kept")
    HEADER_2 = ("Manager", "Keeper 1", "Round Forfeited",
                "Keeper 2", "Round Forfeited")

    def test_three_column_groups(self):
        rows = [
            self.HEADER_3,
            ("Harris Cook", "Tarik Skubal", 14.0, 3.0, "Bryan Woo", 12.0, 2.0),
        ]
        parsed = parse_keeper_sheet(rows, 2026, "2026 Keepers")

        assert parsed.variant == "manager_round_seasons"
        assert len(parsed.keepers) == 2
        assert parsed.keepers[0] == {
            "manager": "Harris Cook", "slot": 1, "player_name": "Tarik Skubal",
            "round_cost": 14, "round_cost_raw": 14.0,
            "seasons_kept": 3, "seasons_kept_raw": 3.0,
        }

    def test_two_column_groups_have_no_seasons_kept(self):
        """2015 and 2016 predate the Seasons Kept column.

        Assuming a width of three here shifts every round cost by a column.
        """
        rows = [
            self.HEADER_2,
            ("Jess Barron", "Clayton Kershaw", 1.0, "Corey Kluber", 2.0),
        ]
        parsed = parse_keeper_sheet(rows, 2016, "2016 Keepers")

        assert parsed.variant == "manager_round"
        assert [(k["player_name"], k["round_cost"]) for k in parsed.keepers] == [
            ("Clayton Kershaw", 1), ("Corey Kluber", 2)]
        assert all(k["seasons_kept"] is None for k in parsed.keepers)

    def test_ordinal_and_asterisked_round_costs(self):
        """2017 writes rounds as `1st`; 2022 marks an adjusted one `11*`."""
        rows = [
            self.HEADER_3,
            ("Jess Barron", "Clayton Kershaw", "1st", 3.0, "Corey Seager", "4th", 1.0),
            ("David Rotatori", "Pete Alonso", "11*", 2.0, "Ketel Marte", 20.0, 2.0),
        ]
        parsed = parse_keeper_sheet(rows, 2017, "2017 Keepers")

        assert [k["round_cost"] for k in parsed.keepers] == [1, 4, 11, 20]
        # The raw cell is preserved so the asterisk's meaning is not lost.
        assert parsed.keepers[2]["round_cost_raw"] == "11*"

    def test_non_numeric_seasons_kept_is_reported_not_guessed(self):
        rows = [
            self.HEADER_3,
            ("Tim Riker", "Nolan Arenado", 2.0, "final", "Freddie Freeman", 3.0, 2.0),
        ]
        parsed = parse_keeper_sheet(rows, 2018, "2018 Keepers")

        arenado = parsed.keepers[0]
        assert arenado["seasons_kept"] is None
        assert arenado["seasons_kept_raw"] == "final"
        assert any(i.kind == "unparsed_seasons_kept" for i in parsed.issues)

    def test_doctrine_text_ends_the_table(self):
        """The prose below the keeper table must not be read as managers.

        2015 and 2016 also paste a pick-slot table underneath, whose first
        column holds pick numbers.
        """
        rows = [
            self.HEADER_2,
            ("Jess Barron", "Clayton Kershaw", 1.0, "Corey Kluber", 2.0),
            (None, None, None, None, None),
            ("Keeper Doctrine", None, None, None, None),
            ("-If a player is retained for a 2nd season, the owner will forfeit "
             "the round pick the player was drafted in the year prior",
             None, None, None, None),
            ("Pick", "Owner", "Player", "Position", "MLB Team"),
            ("Round 1", None, None, None, None),
            (2.0, "Tim Riker", "Andrew McCutchen", "OF", "PIT"),
        ]
        parsed = parse_keeper_sheet(rows, 2016, "2016 Keepers")

        assert {k["manager"] for k in parsed.keepers} == {"Jess Barron"}
        # The pick-slot table is captured separately, not as keepers.
        assert [p["player_name"] for p in parsed.pick_slots] == ["Andrew McCutchen"]


class TestRankingSheets:
    def test_snapshot_date_from_sheet_name(self):
        assert ranking_snapshot_date("ESPN 300 2.2.25") == "2025-02-02"
        assert ranking_snapshot_date("ESPN300 2.26.24") == "2024-02-26"
        assert ranking_snapshot_date("ESPN 300 3.17.21") == "2021-03-17"
        assert ranking_snapshot_date("2017 ESPN Top 300") is None

    def test_split_first_and_last_name_columns(self):
        """The 2017 sheet spreads a name across two `Player` columns."""
        rows = [
            (None, "Player", "Player", "Team", "Age", "Elig. Pos", "Pos. Rank"),
            (1.0, "Mike", "Trout", "LAA", 25.0, "OF", "OF1"),
            (2.0, "Jose", "Altuve", "HOU", 26.0, "2B", "2B1"),
        ]
        parsed = parse_ranking_sheet(rows, "2017 ESPN Top 300", 2017)

        assert [r["player_name"] for r in parsed.rankings] == [
            "Mike Trout", "Jose Altuve"]
        assert [r["rank"] for r in parsed.rankings] == [1, 2]

    def test_rows_past_the_top_300_keep_a_null_rank(self):
        """Inventing a rank from sheet position would order them wrongly."""
        rows = [
            (" ", "Player", "Team", "Elig. Pos.", "Pos.\nRank", "Status"),
            (300.0, "Charlie Morton", "BAL", "SP", "SP85", "Available"),
            (None, "Jackson Jobe", "DET", "SP", None, "DRAFTED"),
        ]
        parsed = parse_ranking_sheet(rows, "ESPN 300 2.2.25", 2025)

        assert parsed.rankings[0]["rank"] == 300
        assert parsed.rankings[1]["rank"] is None
        assert parsed.rankings[1]["rank_source"] == "unranked"
        assert any(i.kind == "unranked_rows" for i in parsed.issues)
