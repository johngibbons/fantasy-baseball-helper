"""Tests for MLB Stats API helpers that need real parsing logic."""

from __future__ import annotations

import asyncio

import pytest

from backend.data import mlb_api
from backend.data.mlb_api import (
    count_quality_starts,
    get_pitching_stats,
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


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, payload):
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, params=None):
        return _FakeResponse(self._payload)


class TestGetPitchingStats:
    def test_season_innings_are_parsed_as_thirds(self, monkeypatch):
        """The season line uses the same notation as the game log: "64.1" is
        64 and one third. Reading it as a float stored 64.1, and the retro
        then disagreed with rows written by the history backfill."""
        payload = {"stats": [{"splits": [{"stat": {
            "inningsPitched": "64.1", "gamesPlayed": 58, "era": "2.10",
            "whip": "0.98", "strikeOuts": 70,
        }}]}]}
        monkeypatch.setattr(mlb_api.httpx, "AsyncClient",
                            lambda: _FakeClient(payload))
        stats = asyncio.run(get_pitching_stats(686973, 2026))
        assert stats["innings_pitched"] == pytest.approx(64 + 1 / 3)

    def test_failed_game_log_is_an_error_not_zero_quality_starts(self, monkeypatch):
        """A starter whose game log could not be fetched must not come back
        with QS = 0 — the refresh would store it as if he never had one."""
        payload = {"stats": [{"splits": [{"stat": {
            "inningsPitched": "150.0", "gamesStarted": 26,
        }}]}]}
        monkeypatch.setattr(mlb_api.httpx, "AsyncClient",
                            lambda: _FakeClient(payload))

        async def unreachable(mlb_id, season):
            raise ConnectionError("All connection attempts failed")

        monkeypatch.setattr(mlb_api, "get_pitching_game_log", unreachable)
        with pytest.raises(ConnectionError):
            asyncio.run(get_pitching_stats(656302, 2026,
                                           include_quality_starts=True))
