"""Tests for rolling-window stat aggregation."""

import pandas as pd
import pytest

from backend.data.rolling_stats import (
    aggregate_batting_window,
    aggregate_pitching_window,
)


def test_aggregate_batting_window_sums_counting_stats():
    df = pd.DataFrame([
        {"mlb_id": 100, "G": 5, "PA": 22, "AB": 18, "H": 7, "2B": 2, "3B": 0,
         "HR": 2, "R": 4, "RBI": 6, "SB": 1, "BB": 3, "SO": 4, "HBP": 1, "SF": 0},
        {"mlb_id": 100, "G": 3, "PA": 14, "AB": 12, "H": 4, "2B": 1, "3B": 0,
         "HR": 1, "R": 3, "RBI": 2, "SB": 0, "BB": 2, "SO": 3, "HBP": 0, "SF": 0},
    ])
    out = aggregate_batting_window(df)
    row = out[100]
    assert row["games"] == 8
    assert row["pa"] == 36
    assert row["ab"] == 30
    assert row["h"] == 11
    assert row["hr"] == 3
    assert row["r"] == 7
    assert row["rbi"] == 8
    assert row["sb"] == 1
    assert row["bb"] == 5
    assert row["k"] == 7
    assert row["hbp"] == 1
    assert row["sf"] == 0


def test_aggregate_batting_window_computes_rate_stats():
    df = pd.DataFrame([
        {"mlb_id": 100, "G": 1, "PA": 10, "AB": 8, "H": 4, "2B": 1, "3B": 0,
         "HR": 1, "R": 2, "RBI": 3, "SB": 0, "BB": 2, "SO": 2, "HBP": 0, "SF": 0},
    ])
    out = aggregate_batting_window(df)
    row = out[100]
    # batting_avg = 4/8 = .500
    assert row["batting_avg"] == pytest.approx(0.500)
    # OBP = (4 + 2 + 0) / (8 + 2 + 0 + 0) = 6/10 = .600
    assert row["obp"] == pytest.approx(0.600)
    # singles = 4 - 1 - 0 - 1 = 2
    # TB = 2 + 2*1 + 3*0 + 4*1 = 2 + 2 + 0 + 4 = 8
    assert row["total_bases"] == 8
    # SLG = 8/8 = 1.000
    assert row["slg"] == pytest.approx(1.000)
    # OPS = .600 + 1.000 = 1.600
    assert row["ops"] == pytest.approx(1.600)


def test_aggregate_batting_window_skips_unknown_ids():
    df = pd.DataFrame([
        {"mlb_id": None, "G": 1, "PA": 4, "AB": 4, "H": 1, "2B": 0, "3B": 0,
         "HR": 0, "R": 0, "RBI": 0, "SB": 0, "BB": 0, "SO": 1, "HBP": 0, "SF": 0},
    ])
    out = aggregate_batting_window(df)
    assert out == {}


def test_aggregate_pitching_window_sums_and_rates():
    df = pd.DataFrame([
        {"mlb_id": 200, "G": 2, "GS": 2, "IP": 12.0, "SO": 14, "BB": 3, "H": 9,
         "ER": 3, "HR": 1, "SV": 0, "HLD": 0, "QS": 1},
        {"mlb_id": 200, "G": 1, "GS": 1, "IP": 6.0, "SO": 7, "BB": 1, "H": 4,
         "ER": 1, "HR": 0, "SV": 0, "HLD": 0, "QS": 1},
    ])
    out = aggregate_pitching_window(df)
    row = out[200]
    assert row["games"] == 3
    assert row["games_started"] == 3
    assert row["ip"] == pytest.approx(18.0)
    assert row["k"] == 21
    assert row["bb"] == 4
    assert row["h_allowed"] == 13
    assert row["er"] == 4
    assert row["hr_allowed"] == 1
    assert row["quality_starts"] == 2
    # ERA = (4 * 9) / 18 = 2.00
    assert row["era"] == pytest.approx(2.00)
    # WHIP = (13 + 4) / 18 = .944
    assert row["whip"] == pytest.approx(17 / 18)
    # K/9 = 21 * 9 / 18 = 10.5
    assert row["k_per_9"] == pytest.approx(10.5)
    # BB/9 = 4 * 9 / 18 = 2.0
    assert row["bb_per_9"] == pytest.approx(2.0)
