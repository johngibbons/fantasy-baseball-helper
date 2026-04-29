# tests/backend/analysis/test_performance.py

import pytest
from backend.analysis.performance import _compute_population_zscores
from backend.analysis.performance import _attach_delta_zscores


class TestComputePopulationZscores:
    def test_basic_zscores(self):
        # [1, 2, 3, 4, 5] → mean=3, population stddev=sqrt(2)
        result = _compute_population_zscores([1.0, 2.0, 3.0, 4.0, 5.0])
        std = 2.0 ** 0.5
        assert result[0] == pytest.approx(-2 / std)
        assert result[1] == pytest.approx(-1 / std)
        assert result[2] == pytest.approx(0.0)
        assert result[3] == pytest.approx(1 / std)
        assert result[4] == pytest.approx(2 / std)

    def test_none_passes_through_and_excluded_from_population(self):
        # Population is [1, 3]: mean=2, population stddev=1
        result = _compute_population_zscores([1.0, None, 3.0])
        assert result[0] == pytest.approx(-1.0)
        assert result[1] is None
        assert result[2] == pytest.approx(1.0)

    def test_stddev_zero_returns_zeros(self):
        # All identical → stddev=0 → every non-null returns 0
        assert _compute_population_zscores([5.0, 5.0, 5.0]) == [0.0, 0.0, 0.0]

    def test_single_non_null_returns_zero(self):
        # Population of one → stddev undefined → return 0 for non-null, None for null
        result = _compute_population_zscores([5.0, None, None])
        assert result == [0.0, None, None]

    def test_all_none_returns_all_none(self):
        assert _compute_population_zscores([None, None, None]) == [None, None, None]

    def test_empty_list_returns_empty(self):
        assert _compute_population_zscores([]) == []


class TestAttachDeltaZscores:
    def _hitter_rows(self):
        return [
            {"categories": {
                "r":   {"delta_volume": 5.0,  "delta_rate": 0.01},
                "obp": {"delta_volume": None, "delta_rate": 0.005},
            }},
            {"categories": {
                "r":   {"delta_volume": -5.0, "delta_rate": -0.01},
                "obp": {"delta_volume": None, "delta_rate": -0.005},
            }},
        ]

    def test_attaches_z_fields_under_each_cat(self):
        rows = self._hitter_rows()
        _attach_delta_zscores(rows, ["r", "obp"])
        for row in rows:
            for cat in ("r", "obp"):
                assert "delta_volume_z" in row["categories"][cat]
                assert "delta_rate_z" in row["categories"][cat]

    def test_volume_z_for_two_player_population(self):
        rows = self._hitter_rows()
        _attach_delta_zscores(rows, ["r", "obp"])
        # r.delta_volume = [5, -5] → mean=0, std=5 → zs = [1, -1]
        assert rows[0]["categories"]["r"]["delta_volume_z"] == pytest.approx(1.0)
        assert rows[1]["categories"]["r"]["delta_volume_z"] == pytest.approx(-1.0)

    def test_volume_z_is_none_when_delta_volume_is_none(self):
        rows = self._hitter_rows()
        _attach_delta_zscores(rows, ["r", "obp"])
        # OBP has no volume framing → all delta_volume are None → z stays None
        assert rows[0]["categories"]["obp"]["delta_volume_z"] is None
        assert rows[1]["categories"]["obp"]["delta_volume_z"] is None

    def test_inverted_categories_sign_flipped(self):
        # ERA: lower is better. Pre-flip z for [0.5, -0.5] is [1, -1].
        # After sign flip: [-1, 1] (lower ERA = positive z = good).
        rows = [
            {"categories": {"era": {"delta_volume": None, "delta_rate": 0.5}}},
            {"categories": {"era": {"delta_volume": None, "delta_rate": -0.5}}},
        ]
        _attach_delta_zscores(rows, ["era"])
        assert rows[0]["categories"]["era"]["delta_rate_z"] == pytest.approx(-1.0)
        assert rows[1]["categories"]["era"]["delta_rate_z"] == pytest.approx(1.0)

    def test_whip_inverted_same_as_era(self):
        rows = [
            {"categories": {"whip": {"delta_volume": None, "delta_rate": 0.1}}},
            {"categories": {"whip": {"delta_volume": None, "delta_rate": -0.1}}},
        ]
        _attach_delta_zscores(rows, ["whip"])
        assert rows[0]["categories"]["whip"]["delta_rate_z"] == pytest.approx(-1.0)
        assert rows[1]["categories"]["whip"]["delta_rate_z"] == pytest.approx(1.0)

    def test_non_inverted_category_not_flipped(self):
        # K: higher is better. Pre-flip z for [10, -10] is [1, -1] — no change.
        rows = [
            {"categories": {"k": {"delta_volume": 10.0, "delta_rate": 1.0}}},
            {"categories": {"k": {"delta_volume": -10.0, "delta_rate": -1.0}}},
        ]
        _attach_delta_zscores(rows, ["k"])
        assert rows[0]["categories"]["k"]["delta_volume_z"] == pytest.approx(1.0)
        assert rows[1]["categories"]["k"]["delta_volume_z"] == pytest.approx(-1.0)
        assert rows[0]["categories"]["k"]["delta_rate_z"] == pytest.approx(1.0)
        assert rows[1]["categories"]["k"]["delta_rate_z"] == pytest.approx(-1.0)

    def test_empty_rows(self):
        rows: list[dict] = []
        _attach_delta_zscores(rows, ["r"])
        assert rows == []
