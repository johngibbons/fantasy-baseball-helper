"""Tests for draft-day ADP parsing/resolution and the frozen Phase 0 fixtures."""

from __future__ import annotations

import json
from pathlib import Path

from backend.analysis.retro.adp_import import (
    AdpEntry,
    PlayerRow,
    coverage_summary,
    parse_adp_csv,
    resolve_adp_entries,
)

FIXTURE_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "backend" / "data" / "fixtures" / "retro_2026"
)

SAMPLE_CSV = """,Player,Team,Elig. Pos.,Pos. Rank,ADP,,,
1,Shohei Ohtani,LAD,DH/SP,DH1,1.4,,,
2,Aaron Judge,NYY,OF/DH,OF1,2.3,,,
3,Tarik Skubal,DET,SP,SP1,5.8,,,
4,Jose Ramirez,CLE,3B,3B1,6.2,,,
5,Nobody Here,FA,,,,,,
6,Bad Adp,FA,OF,OF9,n/a,,,
"""


class TestParseAdpCsv:
    def test_parses_rows_and_splits_positions(self):
        entries = parse_adp_csv(SAMPLE_CSV)
        # The two malformed rows (no ADP, non-numeric ADP) are dropped.
        assert [e.name for e in entries] == [
            "Shohei Ohtani", "Aaron Judge", "Tarik Skubal", "Jose Ramirez",
        ]
        assert entries[0].positions == ("DH", "SP")
        assert entries[2].adp == 5.8
        assert entries[3].team == "CLE"

    def test_is_pitcher_only_when_every_position_is_a_pitching_slot(self):
        entries = {e.name: e for e in parse_adp_csv(SAMPLE_CSV)}
        # Two-way players are hitter-first, matching the zscores.py merge.
        assert entries["Shohei Ohtani"].is_pitcher is False
        assert entries["Tarik Skubal"].is_pitcher is True
        assert entries["Aaron Judge"].is_pitcher is False

    def test_empty_positions_are_not_pitchers(self):
        entry = AdpEntry(name="X", team="", positions=(), pos_rank="",
                         adp=1.0, row_index=0)
        assert entry.is_pitcher is False


class TestResolveAdpEntries:
    def _entry(self, name, adp, positions=("OF",)):
        return AdpEntry(name=name, team="", positions=positions,
                        pos_rank="", adp=adp, row_index=0)

    def test_matches_through_accents_and_suffixes(self):
        entries = [self._entry("Jose Ramirez", 6.2),
                   self._entry("Ronald Acuna Jr.", 12.0)]
        players = [
            PlayerRow(mlb_id=608070, full_name="José Ramírez",
                      player_type="hitter", overall_rank=4),
            PlayerRow(mlb_id=660670, full_name="Ronald Acuña Jr.",
                      player_type="hitter", overall_rank=20),
        ]
        result = resolve_adp_entries(entries, players)
        assert result.matched == {608070: 6.2, 660670: 12.0}
        assert result.unmatched == []

    def test_disambiguates_by_player_type(self):
        """A hitter ADP row must not match the same-named pitcher."""
        entries = [self._entry("Juan Soto", 8.0, positions=("OF",))]
        players = [
            PlayerRow(mlb_id=111, full_name="Juan Soto",
                      player_type="pitcher", overall_rank=5),
            PlayerRow(mlb_id=665742, full_name="Juan Soto",
                      player_type="hitter", overall_rank=9),
        ]
        result = resolve_adp_entries(entries, players)
        assert result.matched == {665742: 8.0}

    def test_prefers_ranked_player_on_collision(self):
        entries = [self._entry("Max Muncy", 228.1)]
        players = [
            PlayerRow(mlb_id=999999, full_name="Max Muncy",
                      player_type="hitter", overall_rank=None),
            PlayerRow(mlb_id=571970, full_name="Max Muncy",
                      player_type="hitter", overall_rank=180),
        ]
        result = resolve_adp_entries(entries, players)
        assert result.matched == {571970: 228.1}
        assert len(result.ambiguous) == 1
        assert result.ambiguous[0]["chosen_mlb_id"] == 571970

    def test_second_row_for_same_player_is_recorded_not_overwritten(self):
        """The earlier (better) ADP wins; the loser is reported, never dropped."""
        entries = [self._entry("Max Muncy", 228.1), self._entry("Max Muncy", 259.1)]
        players = [PlayerRow(mlb_id=571970, full_name="Max Muncy",
                             player_type="hitter", overall_rank=180)]
        result = resolve_adp_entries(entries, players)
        assert result.matched == {571970: 228.1}
        assert len(result.unmatched) == 1
        assert result.unmatched[0]["reason"] == "duplicate_mlb_id"

    def test_unknown_name_is_reported(self):
        result = resolve_adp_entries([self._entry("Nobody Atall", 300.0)], [])
        assert result.matched == {}
        assert result.unmatched[0]["reason"] == "no_name_match"

    def test_resolution_is_deterministic_across_candidate_order(self):
        entries = [self._entry("Same Name", 50.0)]
        a = PlayerRow(mlb_id=200, full_name="Same Name", player_type="hitter")
        b = PlayerRow(mlb_id=100, full_name="Same Name", player_type="hitter")
        assert (resolve_adp_entries(entries, [a, b]).matched
                == resolve_adp_entries(entries, [b, a]).matched)


class TestCoverageSummary:
    def test_counts_only_rows_inside_the_drafted_range(self):
        entries = [
            AdpEntry(name="Drafted", team="", positions=("OF",), pos_rank="",
                     adp=10.0, row_index=0),
            AdpEntry(name="Filler", team="", positions=("OF",), pos_rank="",
                     adp=259.9, row_index=1),
        ]
        result = resolve_adp_entries(entries, [])
        summary = coverage_summary(entries, result, adp_cutoff=250.0)
        assert summary["entries_in_range"] == 1
        assert summary["unmatched_in_range"] == 1
        assert summary["unmatched_in_range_names"] == ["Drafted"]


class TestFrozenPhase0Fixtures:
    """Guards the committed retrospective inputs (see backend/scripts/retro_snapshot.py)."""

    def test_draft_state_fixture_is_a_completed_draft(self):
        state = json.loads((FIXTURE_DIR / "draft_state_2026.json").read_text())
        assert len(state["picks"]) == 250
        assert len(state["pickLog"]) == 211
        assert len(state["keeperMlbIds"]) == 40
        assert len(state["pickTrades"]) == 9
        assert len(state["draftOrder"]) == 10
        assert state["myTeamId"] == 8
        assert state["currentPickIndex"] == 250

    def test_pick_log_entries_have_the_expected_shape(self):
        state = json.loads((FIXTURE_DIR / "draft_state_2026.json").read_text())
        team_ids = {entry["teamId"] for entry in state["pickLog"]}
        assert team_ids == set(state["draftOrder"])
        indices = [entry["pickIndex"] for entry in state["pickLog"]]
        assert len(indices) == len(set(indices)), "pick indices must be unique"
        assert all(0 <= i < 250 for i in indices)

    def test_draft_day_adp_covers_the_entire_drafted_range(self):
        """Every player who could plausibly have been drafted resolved to an mlb_id."""
        adp = json.loads((FIXTURE_DIR / f"adp_draftday_2026.json").read_text())
        assert adp["coverage"]["unmatched_in_range"] == 0
        assert adp["coverage"]["entries_in_range"] > 200
        ids = list(adp["adp_by_mlb_id"].keys())
        assert len(ids) == len(set(ids))
        assert len(ids) == adp["matched_count"]

    def test_every_rostered_player_has_draft_day_adp(self):
        """The join Layer B depends on: picks + keepers -> draft-day ADP.

        Coverage is currently complete (250/250), so this asserts exactly that
        rather than a tolerance — both inputs are frozen, so any regression here
        is a bug in resolution, not drift in the data.
        """
        state = json.loads((FIXTURE_DIR / "draft_state_2026.json").read_text())
        adp = json.loads((FIXTURE_DIR / "adp_draftday_2026.json").read_text())
        adp_ids = {int(k) for k in adp["adp_by_mlb_id"]}
        rostered = ({entry["mlbId"] for entry in state["pickLog"]}
                    | set(state["keeperMlbIds"]))
        missing = rostered - adp_ids
        assert not missing, (
            f"{len(missing)}/{len(rostered)} rostered players lack draft-day ADP: "
            f"{sorted(missing)[:10]}"
        )
