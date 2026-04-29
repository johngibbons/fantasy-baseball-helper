# tests/backend/analysis/test_performance.py

import pytest
from backend.analysis.performance import _compute_population_zscores


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
