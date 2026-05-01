"""Tests for ESPN historical season fetcher."""

from __future__ import annotations

from unittest.mock import patch, MagicMock
from backend.data.espn_history import (
    fetch_season_matchup_history,
    parse_matchup_response,
    MatchupRecord,
    ESPN_STAT_ID_TO_CAT,
)


class TestParseMatchupResponse:
    def test_extracts_records_per_team_side(self):
        """Each home/away pair becomes two MatchupRecord rows."""
        fake_response = {
            "schedule": [
                {
                    "matchupPeriodId": 5,
                    "home": {
                        "teamId": 10,
                        "cumulativeScore": {
                            "scoreByStat": {
                                "20": {"score": 28.0},  # R
                                "8": {"score": 92.0},   # TB
                                "21": {"score": 31.0},  # RBI
                                "23": {"score": 3.0},   # SB
                                "17": {"score": 0.350}, # OBP
                                "48": {"score": 54.0},  # K
                                "63": {"score": 4.0},   # QS
                                "47": {"score": 3.277}, # ERA
                                "41": {"score": 1.266}, # WHIP
                                "83": {"score": 5.0},   # SVHD
                            },
                        },
                        "pointsByScoringPeriod": {"30": 1, "31": 1, "32": 1, "33": 1, "34": 1, "35": 1, "36": 1},
                    },
                    "away": {
                        "teamId": 7,
                        "cumulativeScore": {
                            "scoreByStat": {
                                "20": {"score": 33.0},
                                "8": {"score": 105.0},
                                "21": {"score": 28.0},
                                "23": {"score": 7.0},
                                "17": {"score": 0.335},
                                "48": {"score": 79.0},
                                "63": {"score": 5.0},
                                "47": {"score": 5.326},
                                "41": {"score": 1.500},
                                "83": {"score": 3.0},
                            },
                        },
                        "pointsByScoringPeriod": {"30": 1, "31": 1, "32": 1, "33": 1, "34": 1, "35": 1, "36": 1},
                    },
                },
            ],
        }
        records = parse_matchup_response(fake_response)
        assert len(records) == 2  # one home, one away
        home = next(r for r in records if r.team_id == 10)
        assert home.matchup_period_id == 5
        assert home.period_days == 7
        assert home.cats["R"] == 28.0
        assert home.cats["OBP"] == 0.350
        assert home.cats["ERA"] == 3.277

    def test_skips_matchups_with_empty_score_by_stat(self):
        """Future/in-progress matchups have no scoreByStat — skip them."""
        fake_response = {
            "schedule": [
                {
                    "matchupPeriodId": 1,
                    "home": {"teamId": 1, "cumulativeScore": {"scoreByStat": {}}, "pointsByScoringPeriod": {}},
                    "away": {"teamId": 2, "cumulativeScore": {"scoreByStat": {}}, "pointsByScoringPeriod": {}},
                },
            ],
        }
        records = parse_matchup_response(fake_response)
        assert records == []


class TestFetchSeasonMatchupHistory:
    def test_calls_espn_with_correct_url_and_returns_parsed_records(self):
        with patch("backend.data.espn_history.urllib.request.urlopen") as urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b'{"schedule": [{"matchupPeriodId": 1, "home": {"teamId": 1, "cumulativeScore": {"scoreByStat": {"20": {"score": 50.0}}}, "pointsByScoringPeriod": {"1": 1, "2": 1, "3": 1, "4": 1, "5": 1, "6": 1, "7": 1}}, "away": {"teamId": 2, "cumulativeScore": {"scoreByStat": {"20": {"score": 45.0}}}, "pointsByScoringPeriod": {"1": 1, "2": 1, "3": 1, "4": 1, "5": 1, "6": 1, "7": 1}}}]}'
            urlopen.return_value.__enter__.return_value = mock_resp

            records = fetch_season_matchup_history(
                league_id="77166", season=2025, swid="X", espn_s2="Y",
            )

            urlopen.assert_called_once()
            req = urlopen.call_args[0][0]
            url = req.full_url if hasattr(req, "full_url") else req
            assert "seasons/2025" in url
            assert "leagues/77166" in url
            assert "view=mMatchup" in url
            assert "scoringPeriodId=" in url
            cookie = req.get_header("Cookie")
            assert "swid=X" in cookie
            assert "espn_s2=Y" in cookie
            assert len(records) == 2  # one home, one away
            assert records[0].cats["R"] == 50.0


def test_espn_stat_id_map_covers_all_ten_cats():
    """ESPN_STAT_ID_TO_CAT must include all 10 H2H cats."""
    assert set(ESPN_STAT_ID_TO_CAT.values()) == {
        "R", "TB", "RBI", "SB", "OBP",
        "K", "QS", "ERA", "WHIP", "SVHD",
    }
