"""Tests for the start/sit optimization engine."""

import pytest
from backend.analysis.start_sit import (
    classify_category,
    compute_ratio_exposure,
    decide_recommendation,
    generate_rationale,
)


class TestClassifyCategory:
    """Tests for classify_category()."""

    def test_counting_stat_winning_big(self):
        # K: 60 vs 30, 4 days remaining → gap=30, gap_in_days=30/6=5.0 > 4*0.8=3.2 → winning_big
        result = classify_category("K", yours=60, theirs=30, days_remaining=4)
        assert result == "winning_big"

    def test_counting_stat_winning_close(self):
        # K: 45 vs 38, 4 days remaining → gap=7, gap_in_days=7/6≈1.17 <= 4*0.8=3.2 → winning_close
        result = classify_category("K", yours=45, theirs=38, days_remaining=4)
        assert result == "winning_close"

    def test_counting_stat_losing_close(self):
        # K: 38 vs 45, 4 days remaining → gap=7, gap_in_days=7/6≈1.17 <= 3.2 → losing_close
        result = classify_category("K", yours=38, theirs=45, days_remaining=4)
        assert result == "losing_close"

    def test_counting_stat_losing_big(self):
        # K: 20 vs 50, 4 days remaining → gap=30, gap_in_days=30/6=5.0 > 3.2 → losing_big
        result = classify_category("K", yours=20, theirs=50, days_remaining=4)
        assert result == "losing_big"

    def test_tied_is_losing_close(self):
        # K: 40 vs 40 → gap=0, tied → losing_close (bias toward action)
        result = classify_category("K", yours=40, theirs=40, days_remaining=4)
        assert result == "losing_close"

    def test_rate_stat_era_winning_close(self):
        # ERA: 3.12 vs 3.32, IP=40 → gap=0.20 < 0.30 threshold → winning_close
        # ERA is lower-is-better: 3.12 < 3.32 so we're winning
        result = classify_category("ERA", yours=3.12, theirs=3.32, days_remaining=4, team_ip=40.0)
        assert result == "winning_close"

    def test_rate_stat_era_winning_big(self):
        # ERA: 3.00 vs 3.50, IP=40 → gap=0.50 >= 0.30 threshold → winning_big
        result = classify_category("ERA", yours=3.00, theirs=3.50, days_remaining=4, team_ip=40.0)
        assert result == "winning_big"

    def test_low_ip_override_forces_close(self):
        # ERA: 3.00 vs 3.50, IP=10 → would be winning_big but low-IP override forces winning_close
        result = classify_category("ERA", yours=3.00, theirs=3.50, days_remaining=4, team_ip=10.0)
        assert result == "winning_close"

    def test_era_lower_is_better(self):
        # ERA: 3.50 vs 3.00 → higher ERA is losing (lower is better)
        result = classify_category("ERA", yours=3.50, theirs=3.00, days_remaining=4, team_ip=40.0)
        assert result in ("losing_close", "losing_big")

    def test_whip_classification(self):
        # WHIP: 1.10 vs 1.15, IP=40 → gap=0.05 < 0.08 threshold, winning → winning_close
        result = classify_category("WHIP", yours=1.10, theirs=1.15, days_remaining=4, team_ip=40.0)
        assert result == "winning_close"


class TestComputeRatioExposure:
    """Tests for compute_ratio_exposure()."""

    def test_five_starts_is_one(self):
        assert compute_ratio_exposure(5) == 1.0

    def test_two_starts(self):
        assert abs(compute_ratio_exposure(2) - 0.4) < 1e-9

    def test_one_start(self):
        assert abs(compute_ratio_exposure(1) - 0.2) < 1e-9

    def test_eight_starts_capped_at_one(self):
        assert compute_ratio_exposure(8) == 1.0


class TestDecideRecommendation:
    """Tests for decide_recommendation()."""

    def test_all_winning_big_returns_safe_sit(self):
        cat_states = {
            "K": "winning_big",
            "QS": "winning_big",
            "ERA": "winning_big",
            "WHIP": "winning_big",
        }
        result = decide_recommendation("strong_start", cat_states, ratio_exposure=0.5)
        assert result == "safe_sit"

    def test_strong_start_era_close_low_exposure_returns_start(self):
        # ERA winning_close + low exposure (0.2) → ratio_protect column → start
        cat_states = {
            "K": "winning_big",
            "QS": "winning_big",
            "ERA": "winning_close",
            "WHIP": "winning_big",
        }
        result = decide_recommendation("strong_start", cat_states, ratio_exposure=0.2)
        assert result == "start"

    def test_strong_start_era_close_high_exposure_returns_strong_start(self):
        # ERA winning_close + high exposure (0.8) → default column → strong_start
        cat_states = {
            "K": "winning_big",
            "QS": "winning_big",
            "ERA": "winning_close",
            "WHIP": "winning_big",
        }
        result = decide_recommendation("strong_start", cat_states, ratio_exposure=0.8)
        assert result == "strong_start"

    def test_start_era_close_low_exposure_returns_risky_start(self):
        # start tier + ERA winning_close + low exposure → ratio_protect column → risky_start
        cat_states = {
            "K": "winning_big",
            "QS": "winning_big",
            "ERA": "winning_close",
            "WHIP": "winning_big",
        }
        result = decide_recommendation("start", cat_states, ratio_exposure=0.2)
        assert result == "risky_start"

    def test_maybe_k_losing_close_returns_risky_start(self):
        # maybe tier + K losing_close → k_chase column → risky_start
        cat_states = {
            "K": "losing_close",
            "QS": "winning_big",
            "ERA": "winning_big",
            "WHIP": "winning_big",
        }
        result = decide_recommendation("maybe", cat_states, ratio_exposure=0.5)
        assert result == "risky_start"

    def test_sit_always_returns_sit(self):
        # sit tier → always sit regardless of category state
        cat_states = {
            "K": "losing_close",
            "QS": "losing_close",
            "ERA": "winning_big",
            "WHIP": "winning_big",
        }
        result = decide_recommendation("sit", cat_states, ratio_exposure=0.2)
        assert result == "sit"


class TestGenerateRationale:
    """Tests for generate_rationale()."""

    def test_includes_pitcherlist_raw_and_opponent(self):
        cat_states = {
            "K": "winning_big",
            "QS": "winning_big",
            "ERA": "winning_big",
            "WHIP": "winning_big",
        }
        rationale = generate_rationale(
            pitcherlist_raw="Start-8",
            opponent="CIN",
            recommendation="start",
            pitcherlist_tier="start",
            cats=cat_states,
            ratio_exposure=0.8,
            starts_remaining=5,
        )
        assert "Start-8" in rationale
        assert "CIN" in rationale

    def test_safe_sit_mentions_protect(self):
        cat_states = {
            "K": "winning_big",
            "QS": "winning_big",
            "ERA": "winning_big",
            "WHIP": "winning_big",
        }
        rationale = generate_rationale(
            pitcherlist_raw="Start-3",
            opponent="NYY",
            recommendation="safe_sit",
            pitcherlist_tier="strong_start",
            cats=cat_states,
            ratio_exposure=0.4,
            starts_remaining=2,
        )
        assert "protect" in rationale.lower() or "safe" in rationale.lower()

    def test_sit_tier_gives_clear_rationale(self):
        """Sit-tier pitchers should get a clear 'too low to start' message,
        not misleading matchup context like 'Chasing Ks/QS upside'."""
        cat_states = {
            "K": "losing_close",
            "QS": "losing_close",
            "ERA": "winning_close",
            "WHIP": "winning_close",
        }
        rationale = generate_rationale(
            pitcherlist_raw="Sit-2",
            opponent="HOU",
            recommendation="sit",
            pitcherlist_tier="sit",
            cats=cat_states,
            ratio_exposure=0.8,
            starts_remaining=6,
        )
        assert "too low" in rationale.lower()
        assert "Chasing" not in rationale
