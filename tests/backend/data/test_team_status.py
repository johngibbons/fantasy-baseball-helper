import datetime as dt
import pytest
from backend.data.team_status import parse_mlb_status_response

def test_active_player_with_team():
    response = {
        "people": [{
            "id": 693304,
            "fullName": "Nick Gonzales",
            "active": True,
            "currentTeam": {"abbreviation": "PIT"},
        }]
    }
    result = parse_mlb_status_response(response, mlb_id=693304)
    assert result == {
        "mlb_id": 693304,
        "current_team": "PIT",
        "status_code": "A",
        "is_on_il": False,
        "il_eta_date": None,
    }

def test_player_on_il_10_day():
    response = {
        "people": [{
            "id": 650402,
            "fullName": "Gleyber Torres",
            "active": True,
            "currentTeam": {"abbreviation": "DET"},
            "currentRosterStatus": "IL10",
        }]
    }
    result = parse_mlb_status_response(response, mlb_id=650402)
    assert result["current_team"] == "DET"
    assert result["status_code"] == "IL10"
    assert result["is_on_il"] is True

def test_missing_player_returns_none():
    response = {"people": []}
    assert parse_mlb_status_response(response, mlb_id=999999) is None

def test_derive_last_played_date_uses_max_game_date():
    # Caller passes a list of game-log entries from MLB Stats API gameLog endpoint
    game_log = [
        {"date": "2026-05-01", "stat": {"atBats": 4}},
        {"date": "2026-05-05", "stat": {"atBats": 3}},
        {"date": "2026-05-02", "stat": {"atBats": 4}},
    ]
    from backend.data.team_status import derive_last_played_date
    result = derive_last_played_date(game_log)
    assert result == dt.date(2026, 5, 5)

def test_derive_last_played_date_empty_returns_none():
    from backend.data.team_status import derive_last_played_date
    assert derive_last_played_date([]) is None


def test_upsert_player_status_writes_row():
    # Use a real sqlite for the schema, but mock the postgres-specific bits if any
    from backend.data import team_status
    from unittest.mock import MagicMock
    conn = MagicMock()
    record = {
        "mlb_id": 693304, "current_team": "PIT", "status_code": "A",
        "is_on_il": False, "il_eta_date": None,
    }
    team_status.upsert_player_status(conn, record, last_played=dt.date(2026, 5, 10))
    args = conn.execute.call_args.args
    assert "INSERT" in args[0]
    assert "ON CONFLICT" in args[0]
    # Bind values include record fields + last_played
    assert 693304 in args[1]
    assert "PIT" in args[1]
    assert dt.date(2026, 5, 10) in args[1]
