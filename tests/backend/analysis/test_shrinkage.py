"""Tests for empirical Bayes shrinkage math."""

from __future__ import annotations

import math
import pytest

from backend.analysis.shrinkage import compute_shrinkage_weight


class TestComputeShrinkageWeight:
    def test_zero_periods_gives_zero_weight(self):
        assert compute_shrinkage_weight(W=0, sigma_within=10.0, sigma_between=5.0) == 0.0

    def test_zero_between_sigma_gives_zero_weight(self):
        assert compute_shrinkage_weight(W=10, sigma_within=10.0, sigma_between=0.0) == 0.0

    def test_negative_periods_treated_as_zero(self):
        assert compute_shrinkage_weight(W=-1, sigma_within=10.0, sigma_between=5.0) == 0.0

    def test_known_midrange_value(self):
        # σ_w=10, σ_b=5, W=4 → (25 * 4) / (25 * 4 + 100) = 100/200 = 0.5
        assert compute_shrinkage_weight(W=4, sigma_within=10.0, sigma_between=5.0) == pytest.approx(0.5)

    def test_large_W_approaches_one(self):
        w = compute_shrinkage_weight(W=10_000, sigma_within=10.0, sigma_between=5.0)
        assert w > 0.99

    def test_small_between_relative_to_within_gives_small_weight(self):
        # σ_b much smaller than σ_w → prior dominates even with many periods
        w = compute_shrinkage_weight(W=5, sigma_within=10.0, sigma_between=0.5)
        # (0.25 * 5) / (0.25 * 5 + 100) = 1.25 / 101.25 ≈ 0.0123
        assert w == pytest.approx(1.25 / 101.25, rel=1e-6)
