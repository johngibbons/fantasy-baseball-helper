import pytest
from unittest.mock import patch, MagicMock
from backend.analysis.bench_contributions import parse_schedule_response


class TestScheduleParsing:
    def test_parses_dates_and_teams(self):
        """parse_schedule_response extracts date -> set of team abbrevs."""
        fake_response = {
            "dates": [
                {
                    "date": "2026-04-01",
                    "games": [
                        {
                            "gameType": "R",
                            "status": {"abstractGameCode": "S"},
                            "teams": {
                                "home": {"team": {"id": 147}},  # NYY
                                "away": {"team": {"id": 111}},  # BOS
                            },
                        },
                    ],
                },
                {
                    "date": "2026-04-02",
                    "games": [
                        {
                            "gameType": "R",
                            "status": {"abstractGameCode": "S"},
                            "teams": {
                                "home": {"team": {"id": 119}},  # LAD
                                "away": {"team": {"id": 137}},  # SF
                            },
                        },
                    ],
                },
            ]
        }
        schedule = parse_schedule_response(fake_response)
        assert schedule["2026-04-01"] == {"NYY", "BOS"}
        assert schedule["2026-04-02"] == {"LAD", "SF"}

    def test_skips_non_regular_season_games(self):
        fake_response = {
            "dates": [
                {
                    "date": "2026-04-01",
                    "games": [
                        {
                            "gameType": "E",  # Exhibition
                            "status": {"abstractGameCode": "S"},
                            "teams": {
                                "home": {"team": {"id": 147}},
                                "away": {"team": {"id": 111}},
                            },
                        },
                    ],
                },
            ]
        }
        schedule = parse_schedule_response(fake_response)
        assert schedule.get("2026-04-01", set()) == set()

    def test_skips_finished_games(self):
        fake_response = {
            "dates": [
                {
                    "date": "2026-04-01",
                    "games": [
                        {
                            "gameType": "R",
                            "status": {"abstractGameCode": "F"},
                            "teams": {
                                "home": {"team": {"id": 147}},
                                "away": {"team": {"id": 111}},
                            },
                        },
                    ],
                },
            ]
        }
        schedule = parse_schedule_response(fake_response)
        assert schedule.get("2026-04-01", set()) == set()
