import datetime as dt
from unittest.mock import MagicMock

import pytest

from backend.data.team_status import (
    derive_last_played_date,
    parse_roster_entry,
    upsert_player_status,
)


def test_parse_active_player():
    entry = {
        "person": {"id": 693304, "fullName": "Nick Gonzales"},
        "status": {"code": "A", "description": "Active"},
    }
    result = parse_roster_entry(entry, team_abbrev="PIT")
    assert result == {
        "mlb_id": 693304,
        "current_team": "PIT",
        "status_code": "A",
        "is_on_il": False,
        "il_eta_date": None,
    }


def test_parse_d10_player_is_on_il():
    entry = {
        "person": {"id": 650402, "fullName": "Gleyber Torres"},
        "status": {"code": "D10", "description": "Injured 10-Day"},
    }
    result = parse_roster_entry(entry, team_abbrev="DET")
    assert result["status_code"] == "D10"
    assert result["is_on_il"] is True


def test_parse_d60_player_is_on_il():
    entry = {
        "person": {"id": 1, "fullName": "X"},
        "status": {"code": "D60", "description": "Injured 60-Day"},
    }
    assert parse_roster_entry(entry, team_abbrev="X")["is_on_il"] is True


def test_parse_legacy_il10_player_is_on_il():
    # Older API responses sometimes use IL-prefix codes
    entry = {
        "person": {"id": 2, "fullName": "Y"},
        "status": {"code": "IL10"},
    }
    assert parse_roster_entry(entry, team_abbrev="X")["is_on_il"] is True


def test_parse_lowercase_status_code():
    entry = {
        "person": {"id": 3, "fullName": "Z"},
        "status": {"code": "d10"},
    }
    # Should be upper-cased internally and detected as IL
    result = parse_roster_entry(entry, team_abbrev="X")
    assert result["status_code"] == "D10"
    assert result["is_on_il"] is True


def test_parse_missing_status_defaults_to_active():
    entry = {
        "person": {"id": 4, "fullName": "W"},
        # no status key at all
    }
    result = parse_roster_entry(entry, team_abbrev="X")
    assert result["status_code"] == "A"
    assert result["is_on_il"] is False


def test_parse_missing_person_id_returns_none():
    entry = {"person": {}, "status": {"code": "A"}}
    assert parse_roster_entry(entry, team_abbrev="X") is None


def test_derive_last_played_date_uses_max_game_date():
    game_log = [
        {"date": "2026-05-01", "stat": {"atBats": 4}},
        {"date": "2026-05-05", "stat": {"atBats": 3}},
        {"date": "2026-05-02", "stat": {"atBats": 4}},
    ]
    assert derive_last_played_date(game_log) == dt.date(2026, 5, 5)


def test_derive_last_played_date_empty_returns_none():
    assert derive_last_played_date([]) is None


def test_upsert_player_status_writes_row():
    conn = MagicMock()
    record = {
        "mlb_id": 693304, "current_team": "PIT", "status_code": "A",
        "is_on_il": False, "il_eta_date": None,
    }
    upsert_player_status(conn, record, last_played=dt.date(2026, 5, 10))
    args = conn.execute.call_args.args
    assert "INSERT" in args[0]
    assert "ON CONFLICT" in args[0]
    assert 693304 in args[1]
    assert "PIT" in args[1]
    assert dt.date(2026, 5, 10) in args[1]
