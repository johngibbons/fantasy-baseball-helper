"""Tests for MLB Stats API helpers that need real parsing logic."""

from __future__ import annotations

import pytest

from backend.data.mlb_api import (
    count_quality_starts,
    parse_innings_pitched,
)


class TestParseInningsPitched:
    def test_partial_innings_are_thirds_not_tenths(self):
        """MLB writes 6 and 1/3 innings as "6.1"."""
        assert parse_innings_pitched("6.1") == pytest.approx(6 + 1 / 3)
        assert parse_innings_pitched("5.2") == pytest.approx(5 + 2 / 3)
        assert parse_innings_pitched("6.0") == 6.0

    def test_whole_innings(self):
        assert parse_innings_pitched("7") == 7.0
        assert parse_innings_pitched(7) == 7.0

    def test_missing_and_malformed_values_are_zero(self):
        assert parse_innings_pitched(None) == 0.0
        assert parse_innings_pitched("") == 0.0
        assert parse_innings_pitched("abc") == 0.0


def game(started=1, innings="6.0", earned=3):
    return {"stat": {"gamesStarted": started, "inningsPitched": innings,
                     "earnedRuns": earned}}


class TestCountQualityStarts:
    def test_six_innings_and_three_earned_runs_qualifies(self):
        assert count_quality_starts([game(innings="6.0", earned=3)]) == 1

    def test_just_short_of_six_innings_does_not(self):
        # 5 2/3 innings — parsing "5.2" as a plain float would also fail this,
        # but for the wrong reason; the thirds conversion is what makes it exact.
        assert count_quality_starts([game(innings="5.2", earned=0)]) == 0

    def test_four_earned_runs_does_not(self):
        assert count_quality_starts([game(innings="7.0", earned=4)]) == 0

    def test_relief_appearances_never_count(self):
        assert count_quality_starts([game(started=0, innings="6.0", earned=0)]) == 0

    def test_counts_across_a_season(self):
        log = [
            game(innings="7.0", earned=1),   # yes
            game(innings="6.1", earned=3),   # yes
            game(innings="5.1", earned=1),   # no  — too short
            game(innings="6.0", earned=5),   # no  — too many runs
            game(started=0, innings="2.0", earned=0),  # no — relief
        ]
        assert count_quality_starts(log) == 2

    def test_empty_and_malformed_logs_are_safe(self):
        assert count_quality_starts([]) == 0
        assert count_quality_starts([{"stat": {}}]) == 0
        assert count_quality_starts([{}]) == 0
        assert count_quality_starts([game(earned="n/a")]) == 0
