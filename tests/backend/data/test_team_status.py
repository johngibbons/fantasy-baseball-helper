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
