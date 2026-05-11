import pytest
from backend.analysis.roster_health import compute_roster_value_z


def test_underperforming_hitter_ranks_below_overperforming():
    roster = [
        {"mlb_id": 1, "player_type": "hitter",
         "current": {"pa": 150, "r": 25, "tb": 60, "rbi": 25, "sb": 5, "obp": 0.380},
         "projected": {"pa": 600, "r": 80, "tb": 250, "rbi": 80, "sb": 12, "obp": 0.340}},
        {"mlb_id": 2, "player_type": "hitter",
         "current": {"pa": 140, "r": 10, "tb": 30, "rbi": 10, "sb": 0, "obp": 0.270},
         "projected": {"pa": 600, "r": 80, "tb": 250, "rbi": 80, "sb": 12, "obp": 0.340}},
    ]
    z = compute_roster_value_z(roster)
    assert z[1] > z[2]  # player 1 overperforming, player 2 underperforming


def test_pitcher_with_high_era_gets_negative_z():
    roster = [
        {"mlb_id": 3, "player_type": "pitcher",
         "current": {"ip": 40, "era": 3.20, "whip": 1.05, "k": 50, "qs": 4, "svhd": 0},
         "projected": {"ip": 180, "era": 3.80, "whip": 1.20, "k": 200, "qs": 18, "svhd": 0}},
        {"mlb_id": 4, "player_type": "pitcher",
         "current": {"ip": 42, "era": 5.50, "whip": 1.45, "k": 40, "qs": 2, "svhd": 0},
         "projected": {"ip": 180, "era": 3.80, "whip": 1.20, "k": 200, "qs": 18, "svhd": 0}},
    ]
    z = compute_roster_value_z(roster)
    assert z[3] > z[4]
