"""Tests for the PitcherList Sit/Start scraper."""

import pytest

from backend.data.pitcherlist import (
    _dates_match,
    _normalize,
    map_tier,
    parse_rating,
    parse_sit_start_tables,
)

# ── Sample HTML shared across table-parsing tests ─────────────────────────────

SAMPLE_HTML = """
<table>
<thead>
  <tr><th>Date</th><th>Game</th><th>Pitcher</th><th>Rating</th></tr>
</thead>
<tbody>
  <tr><td>Wednesday 3/25</td><td>LAD @ CIN</td><td>Corbin Burnes</td><td>Start-8</td></tr>
  <tr><td>Wednesday 3/25</td><td>NYY @ BOS</td><td>Gerrit Cole</td><td>Maybe-4</td></tr>
  <tr><td>Wednesday 3/25</td><td>COL @ SF</td><td>Logan Webb</td><td>Sit-2</td></tr>
  <tr><td>Thursday 3/26</td><td>ARI @ MIL</td><td>Zack Wheeler</td><td>Start-9</td></tr>
</tbody>
</table>
"""


# ── TestParseSitStartTables ────────────────────────────────────────────────────


class TestParseSitStartTables:
    def setup_method(self):
        self.entries = parse_sit_start_tables(SAMPLE_HTML)

    def test_correct_count(self):
        assert len(self.entries) == 4

    def test_pitcher_names(self):
        names = [e["pitcher_name"] for e in self.entries]
        assert "Corbin Burnes" in names
        assert "Gerrit Cole" in names
        assert "Logan Webb" in names
        assert "Zack Wheeler" in names

    def test_tier_and_score_extraction(self):
        by_name = {e["pitcher_name"]: e for e in self.entries}

        assert by_name["Corbin Burnes"]["tier"] == "Start"
        assert by_name["Corbin Burnes"]["score"] == 8

        assert by_name["Gerrit Cole"]["tier"] == "Maybe"
        assert by_name["Gerrit Cole"]["score"] == 4

        assert by_name["Logan Webb"]["tier"] == "Sit"
        assert by_name["Logan Webb"]["score"] == 2

        assert by_name["Zack Wheeler"]["tier"] == "Start"
        assert by_name["Zack Wheeler"]["score"] == 9

    def test_opponent_extraction(self):
        by_name = {e["pitcher_name"]: e for e in self.entries}

        assert by_name["Corbin Burnes"]["opponent"] == "LAD @ CIN"
        assert by_name["Gerrit Cole"]["opponent"] == "NYY @ BOS"
        assert by_name["Logan Webb"]["opponent"] == "COL @ SF"
        assert by_name["Zack Wheeler"]["opponent"] == "ARI @ MIL"

    def test_date_extraction(self):
        by_name = {e["pitcher_name"]: e for e in self.entries}

        assert by_name["Corbin Burnes"]["date"] == "Wednesday 3/25"
        assert by_name["Gerrit Cole"]["date"] == "Wednesday 3/25"
        assert by_name["Logan Webb"]["date"] == "Wednesday 3/25"
        assert by_name["Zack Wheeler"]["date"] == "Thursday 3/26"

    def test_mapped_tier_present(self):
        for entry in self.entries:
            assert "mapped_tier" in entry
            assert entry["mapped_tier"] in ("strong_start", "start", "maybe", "sit")

    def test_raw_field_preserved(self):
        by_name = {e["pitcher_name"]: e for e in self.entries}
        assert by_name["Corbin Burnes"]["raw"] == "Start-8"
        assert by_name["Zack Wheeler"]["raw"] == "Start-9"


# ── TestMapTier ───────────────────────────────────────────────────────────────


class TestMapTier:
    def test_strong_start(self):
        assert map_tier("Start", 8) == "strong_start"

    def test_start_boundary_low(self):
        assert map_tier("Start", 6) == "start"

    def test_start_boundary_high(self):
        # 7 is the threshold — Start-7 should be strong_start
        assert map_tier("Start", 7) == "strong_start"

    def test_maybe(self):
        assert map_tier("Maybe", 4) == "maybe"

    def test_sit(self):
        assert map_tier("Sit", 2) == "sit"

    def test_case_insensitive(self):
        assert map_tier("start", 9) == "strong_start"
        assert map_tier("MAYBE", 3) == "maybe"
        assert map_tier("SIT", 1) == "sit"


# ── TestParseRating ───────────────────────────────────────────────────────────


class TestParseRating:
    def test_parse_start(self):
        assert parse_rating("Start-8") == ("Start", 8)

    def test_parse_maybe(self):
        assert parse_rating("Maybe-4") == ("Maybe", 4)

    def test_parse_sit(self):
        assert parse_rating("Sit-2") == ("Sit", 2)

    def test_parse_with_whitespace(self):
        assert parse_rating("  Start-10  ") == ("Start", 10)

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_rating("Garbage")

        with pytest.raises(ValueError):
            parse_rating("Start")


# ── TestDatesMatch ────────────────────────────────────────────────────────────


class TestDatesMatch:
    def test_matching_date(self):
        assert _dates_match("2026-03-25", "Wednesday 3/25") is True

    def test_non_matching_date(self):
        assert _dates_match("2026-03-25", "Thursday 3/26") is False

    def test_different_month(self):
        assert _dates_match("2026-04-01", "Wednesday 3/25") is False

    def test_invalid_target(self):
        assert _dates_match("bad-date", "Wednesday 3/25") is False

    def test_invalid_entry(self):
        assert _dates_match("2026-03-25", "Wednesday") is False


# ── TestNormalize ─────────────────────────────────────────────────────────────


class TestNormalize:
    def test_strips_accents(self):
        assert _normalize("José Berríos") == "jose berrios"

    def test_lowercases(self):
        assert _normalize("Corbin Burnes") == "corbin burnes"

    def test_strips_whitespace(self):
        assert _normalize("  Zack Wheeler  ") == "zack wheeler"
