"""Tests for the projection blender and rankings pipeline."""
from backend.analysis.zscores import _blend_projection_rows


HITTER_FIELDS = [
    "proj_pa", "proj_runs", "proj_total_bases", "proj_rbi",
    "proj_stolen_bases", "proj_obp",
]


def _row(mlb_id, name, source, pa, runs=80, tb=250, rbi=70, sb=10, obp=0.340):
    """Build a projection row matching the shape returned by the SQL query."""
    return {
        "mlb_id": mlb_id,
        "full_name": name,
        "primary_position": "OF",
        "team": "ATL",
        "eligible_positions": "OF",
        "source": source,
        "proj_pa": pa, "proj_runs": runs, "proj_total_bases": tb,
        "proj_rbi": rbi, "proj_stolen_bases": sb, "proj_obp": obp,
    }


class TestBlendAuthoritativeSources:
    def test_no_filter_blends_all_sources(self):
        """authoritative_sources=None keeps the pre-filter behavior."""
        rows = [
            _row(1, "A", "atc",    pa=600),
            _row(1, "A", "steamer", pa=500),
            _row(2, "B", "steamer", pa=400),  # no atc, still included
        ]
        blended, n, _ = _blend_projection_rows(rows, HITTER_FIELDS, "hitter")
        ids = {r["mlb_id"] for r in blended}
        assert ids == {1, 2}
        assert n == 2

    def test_drops_players_missing_all_authoritative_sources(self):
        """A player with only preseason sources gets dropped when authoritative set is given."""
        rows = [
            _row(1, "HasATC",      "atc",     pa=600),
            _row(1, "HasATC",      "steamer", pa=500),
            _row(2, "StaleOnly",   "steamer", pa=550),
            _row(2, "StaleOnly",   "zips",    pa=480),
        ]
        blended, n, _ = _blend_projection_rows(
            rows, HITTER_FIELDS, "hitter",
            authoritative_sources={"atc", "thebatx"},
        )
        ids = {r["mlb_id"] for r in blended}
        assert ids == {1}, "Player with only preseason sources should be excluded"
        assert n == 1

    def test_keeps_player_with_any_authoritative_source(self):
        """One authoritative source is enough to keep a player in the blend."""
        rows = [
            _row(1, "HasTheBatX", "thebatx", pa=500),
            _row(1, "HasTheBatX", "zips",    pa=480),
        ]
        blended, _, _ = _blend_projection_rows(
            rows, HITTER_FIELDS, "hitter",
            authoritative_sources={"atc", "thebatx"},
        )
        assert len(blended) == 1
        assert blended[0]["mlb_id"] == 1

    def test_empty_authoritative_set_does_not_drop_everyone(self):
        """An empty set means 'no authoritative sources this refresh' — fall through to old behavior."""
        rows = [
            _row(1, "A", "steamer", pa=500),
            _row(2, "B", "zips",    pa=400),
        ]
        blended, _, _ = _blend_projection_rows(
            rows, HITTER_FIELDS, "hitter",
            authoritative_sources=set(),
        )
        ids = {r["mlb_id"] for r in blended}
        assert ids == {1, 2}, "Empty set should behave like None — don't silently drop everyone"
