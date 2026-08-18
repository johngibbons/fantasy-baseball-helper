"""Characterization tests for the SGP valuation engine.

These pin the behaviour of backend/analysis/zscores.py so the season
retrospective can tune its constants with a net underneath. They exercise the
pure compute_* entry points, so no database is involved.
"""

from __future__ import annotations

import pytest

from backend.analysis.zscores import (
    ValuationConfig,
    _best_slot,
    _classify_pitcher,
    _eligible_slots,
    _resolve_denominators,
    compute_hitter_sgp,
    compute_pitcher_sgp,
)

# Denominators pinned so the arithmetic below is exact and independent of
# whatever seasons happen to be loaded in league_season_totals.
DENOMS = {
    "R": 20.0, "TB": 50.0, "RBI": 20.0, "SB": 10.0, "OBP": 0.004,
    "K": 80.0, "QS": 6.0, "ERA": 0.08, "WHIP": 0.012, "SVHD": 8.0,
}
FLAT_WEIGHTS = {c: 1.0 for c in DENOMS}


def config(**overrides) -> ValuationConfig:
    """A pinned, flat-weight config; overrides layer on top."""
    base = dict(
        sgp_denominators=DENOMS,
        category_weights=dict(FLAT_WEIGHTS),
        apply_playing_time_discount=False,
        apply_replacement=False,
        streaming_bonus=0.0,
    )
    base.update(overrides)
    return ValuationConfig(**base)


def hitter(mlb_id=1, name="Test Hitter", pos="OF", pa=600, r=100, tb=280,
           rbi=90, sb=20, obp=0.350, eligible=None):
    """A hitter projection row shaped like calculate_hitter_zscores' SELECT."""
    # Back out the OBP components so the pool's league_obp is self-consistent.
    ab = int(pa * 0.9)
    h = int(ab * 0.270)
    bb = pa - ab
    return {
        "mlb_id": mlb_id, "full_name": name, "primary_position": pos,
        "team": "TST", "eligible_positions": eligible,
        "proj_pa": pa, "proj_runs": r, "proj_total_bases": tb, "proj_rbi": rbi,
        "proj_stolen_bases": sb, "proj_obp": obp,
        "proj_hits": h, "proj_walks": bb, "proj_hbp": 0,
        "proj_sac_flies": 0, "proj_at_bats": ab,
    }


def pitcher(mlb_id=100, name="Test Pitcher", pos="SP", ip=180.0, k=200, qs=20,
            era=3.50, whip=1.10, sv=0, hld=0):
    """A pitcher projection row shaped like calculate_pitcher_zscores' SELECT."""
    return {
        "mlb_id": mlb_id, "full_name": name, "primary_position": pos, "team": "TST",
        "proj_ip": ip, "proj_pitcher_strikeouts": k, "proj_quality_starts": qs,
        "proj_era": era, "proj_whip": whip, "proj_saves": sv, "proj_holds": hld,
        "proj_hits_allowed": int(ip * 0.85), "proj_walks_allowed": int(ip * 0.25),
        "proj_earned_runs": int(era * ip / 9),
    }


class TestCountingStatSgp:
    def test_counting_sgp_is_raw_stat_over_denominator(self):
        [p] = compute_hitter_sgp([hitter(r=100, tb=280, rbi=90, sb=20)],
                                 config=config())
        assert p["zscore_r"] == pytest.approx(100 / 20.0, abs=1e-3)
        assert p["zscore_tb"] == pytest.approx(280 / 50.0, abs=1e-3)
        assert p["zscore_rbi"] == pytest.approx(90 / 20.0, abs=1e-3)
        assert p["zscore_sb"] == pytest.approx(20 / 10.0, abs=1e-3)

    def test_counting_sgp_is_linear_in_the_stat(self):
        rows = [hitter(mlb_id=1, r=50), hitter(mlb_id=2, r=100)]
        a, b = sorted(compute_hitter_sgp(rows, config=config()),
                      key=lambda p: p["mlb_id"])
        assert b["zscore_r"] == pytest.approx(2 * a["zscore_r"], abs=1e-3)

    def test_category_weights_scale_the_category(self):
        weights = dict(FLAT_WEIGHTS, R=0.5)
        flat = compute_hitter_sgp([hitter()], config=config())[0]
        weighted = compute_hitter_sgp(
            [hitter()], config=config(category_weights=weights))[0]
        assert weighted["zscore_r"] == pytest.approx(0.5 * flat["zscore_r"], abs=1e-3)
        assert weighted["zscore_tb"] == pytest.approx(flat["zscore_tb"], abs=1e-3)


class TestRateStatSgp:
    def test_obp_above_league_average_is_positive_and_below_is_negative(self):
        rows = [hitter(mlb_id=1, obp=0.400), hitter(mlb_id=2, obp=0.280)]
        good, bad = sorted(compute_hitter_sgp(rows, config=config()),
                           key=lambda p: p["mlb_id"])
        assert good["zscore_obp"] > 0
        assert bad["zscore_obp"] < 0

    def test_obp_impact_scales_with_playing_time(self):
        """The marginal formula weights rate stats by share of team PA."""
        rows = [hitter(mlb_id=1, obp=0.400, pa=600), hitter(mlb_id=2, obp=0.400, pa=300)]
        full, half = sorted(compute_hitter_sgp(rows, config=config()),
                            key=lambda p: p["mlb_id"])
        assert full["zscore_obp"] > half["zscore_obp"] > 0

    def test_era_and_whip_are_inverted(self):
        """Lower ERA/WHIP must produce higher SGP."""
        rows = [pitcher(mlb_id=1, era=2.50, whip=0.95),
                pitcher(mlb_id=2, era=5.00, whip=1.45)]
        ace, scrub = sorted(compute_pitcher_sgp(rows, config=config()),
                            key=lambda p: p["mlb_id"])
        assert ace["zscore_era"] > scrub["zscore_era"]
        assert ace["zscore_whip"] > scrub["zscore_whip"]


class TestPlayingTimeDiscount:
    def test_discount_applies_to_counting_stats_only(self):
        """OBP is already PA-weighted; discounting it would double-count."""
        row = hitter(pa=250, obp=0.400)
        undiscounted = compute_hitter_sgp([row], config=config())[0]
        discounted = compute_hitter_sgp(
            [row], config=config(apply_playing_time_discount=True,
                                 full_credit_pa=500))[0]
        assert discounted["zscore_r"] == pytest.approx(
            0.5 * undiscounted["zscore_r"], abs=1e-3)
        assert discounted["zscore_obp"] == pytest.approx(
            undiscounted["zscore_obp"], abs=1e-3)

    def test_no_discount_at_or_above_the_threshold(self):
        row = hitter(pa=500)
        a = compute_hitter_sgp([row], config=config())[0]
        b = compute_hitter_sgp(
            [row], config=config(apply_playing_time_discount=True,
                                 full_credit_pa=500))[0]
        assert a["total_zscore"] == pytest.approx(b["total_zscore"], abs=1e-3)

    def test_sp_and_rp_use_different_ip_thresholds(self):
        """A 50-IP reliever is full-credit; a 50-IP starter is not."""
        rows = [pitcher(mlb_id=1, pos="SP", ip=50.0, qs=5),
                pitcher(mlb_id=2, pos="RP", ip=50.0, qs=0, sv=30)]
        cfg = config(apply_playing_time_discount=True,
                     full_credit_ip_sp=140, full_credit_ip_rp=50)
        plain = {p["mlb_id"]: p for p in compute_pitcher_sgp(rows, config=config())}
        disc = {p["mlb_id"]: p for p in compute_pitcher_sgp(rows, config=cfg)}
        assert disc[1]["zscore_k"] == pytest.approx(
            plain[1]["zscore_k"] * 50 / 140, abs=1e-3)
        assert disc[2]["zscore_k"] == pytest.approx(plain[2]["zscore_k"], abs=1e-3)


class TestStreamingBonus:
    def test_bonus_only_for_starters_meeting_both_thresholds(self):
        rows = [
            pitcher(mlb_id=1, pos="SP", era=3.50, whip=1.10),   # qualifies
            pitcher(mlb_id=2, pos="SP", era=4.50, whip=1.10),   # ERA too high
            pitcher(mlb_id=3, pos="SP", era=3.50, whip=1.40),   # WHIP too high
        ]
        without = {p["mlb_id"]: p["total_zscore"]
                   for p in compute_pitcher_sgp(rows, config=config())}
        with_bonus = {p["mlb_id"]: p["total_zscore"]
                      for p in compute_pitcher_sgp(rows, config=config(streaming_bonus=0.70))}
        assert with_bonus[1] == pytest.approx(without[1] + 0.70, abs=1e-3)
        assert with_bonus[2] == pytest.approx(without[2], abs=1e-3)
        assert with_bonus[3] == pytest.approx(without[3], abs=1e-3)

    def test_relievers_never_get_the_streaming_bonus(self):
        rows = [pitcher(mlb_id=9, pos="RP", ip=65.0, qs=0, sv=35,
                        era=2.50, whip=0.95)]
        without = compute_pitcher_sgp(rows, config=config())[0]["total_zscore"]
        with_bonus = compute_pitcher_sgp(
            rows, config=config(streaming_bonus=0.70))[0]["total_zscore"]
        assert with_bonus == pytest.approx(without, abs=1e-3)


class TestReplacementLevel:
    def test_replacement_subtracts_the_slot_baseline(self):
        rows = [hitter(mlb_id=i, r=100 - i) for i in range(1, 40)]
        plain = {p["mlb_id"]: p for p in compute_hitter_sgp(rows, config=config())}
        adj = {p["mlb_id"]: p
               for p in compute_hitter_sgp(rows, config=config(apply_replacement=True))}
        for mlb_id, p in adj.items():
            assert p["total_zscore"] == pytest.approx(
                plain[mlb_id]["total_zscore"] + p["replacement_adj"], abs=1e-3)
        # Replacement is a subtraction, so the adjustment is non-positive here.
        assert all(p["replacement_adj"] <= 0 for p in adj.values())

    def test_best_slot_prefers_the_scarcest_eligible_position(self):
        levels = {"C": -1.0, "1B": 2.0, "OF": 1.0, "UTIL": 3.0}
        assert _best_slot("C/1B", "C", levels) == "C"
        assert _best_slot("1B/OF", "1B", levels) == "OF"

    def test_every_hitter_can_fill_util(self):
        assert "UTIL" in _eligible_slots("SS", "SS")
        assert "UTIL" in _eligible_slots(None, "C")


class TestPitcherClassification:
    def test_declared_positions_win(self):
        assert _classify_pitcher("SP", 0, 0) == "SP"
        assert _classify_pitcher("RP", 200, 20) == "RP"
        assert _classify_pitcher("CP", 70, 0) == "RP"

    def test_ambiguous_positions_fall_back_to_stats(self):
        assert _classify_pitcher("P", 100.0, 0) == "SP"    # IP >= 80
        assert _classify_pitcher("P", 40.0, 5) == "SP"     # has quality starts
        assert _classify_pitcher("P", 40.0, 0) == "RP"


class TestDenominatorPinning:
    def test_pinned_denominators_are_used_verbatim(self):
        cfg = config()
        assert _resolve_denominators(cfg, ["R", "TB"]) is DENOMS

    def test_missing_pinned_category_is_an_error_not_a_silent_default(self):
        cfg = ValuationConfig(sgp_denominators={"R": 20.0})
        with pytest.raises(ValueError, match="missing categories"):
            _resolve_denominators(cfg, ["R", "TB"])


class TestEmptyInput:
    def test_empty_row_lists_return_empty_results(self):
        assert compute_hitter_sgp([], config=config()) == []
        assert compute_pitcher_sgp([], config=config()) == []


class TestSlotAssignmentDeterminism:
    """The board must not depend on Python's per-process string hash seed.

    `_eligible_slots` used to return `list(set(...))`, and both the greedy
    replacement-level assignment and `_best_slot` break ties by list position.
    That made replacement levels — and therefore every hitter's total_zscore
    and the whole board ordering — differ between processes on identical data.
    It surfaced as a multi-season backtest artifact that would not reproduce:
    two consecutive runs disagreed on 23 players.
    """

    def test_eligible_slots_order_is_deterministic(self):
        slots = _eligible_slots("2B/3B/SS/OF", "2B")
        assert slots == ["2B", "3B", "SS", "OF", "UTIL"]
        # Repeated calls in-process must also agree.
        assert all(_eligible_slots("2B/3B/SS/OF", "2B") == slots for _ in range(5))

    def test_eligible_slots_preserves_listed_order_and_dedupes(self):
        # LF/CF/RF all map to OF; UTIL is appended once, last.
        assert _eligible_slots("LF/CF/RF", "LF") == ["OF", "UTIL"]
        assert _eligible_slots("DH/1B", "DH") == ["UTIL", "1B"]

    def test_best_slot_breaks_ties_without_relying_on_order(self):
        """Equal replacement levels must resolve to the same slot every time."""
        levels = {"1B": 1.0, "OF": 1.0, "UTIL": 1.0}
        chosen = {_best_slot("1B/OF", "1B", levels) for _ in range(20)}
        assert len(chosen) == 1

    def test_board_is_identical_across_hash_seeds(self):
        """End-to-end guard: same input, different PYTHONHASHSEED.

        Broader but blunter than the two order tests above, which are what
        actually pin the bug — this one only bites when a tie-break happens to
        move a replacement level, and a synthetic pool does not reliably
        produce that. It stays because it is cheap and would catch a
        reintroduction through some path other than `_eligible_slots`.
        """
        import json
        import pathlib
        import subprocess
        import sys

        script = (
            "import json;"
            "from backend.analysis.zscores import compute_hitter_sgp, ValuationConfig;"
            "elig=['1B/OF','OF/3B','SS/2B','C/1B','2B/3B/SS','OF','C','SS/OF'];"
            "rows=[{'mlb_id':i,'full_name':f'P{i}','primary_position':'1B',"
            "'eligible_positions':elig[i%len(elig)],'team':'X',"
            "'proj_pa':600,'proj_runs':120-i*0.4,'proj_total_bases':300-i,"
            "'proj_rbi':110-i*0.3,'proj_stolen_bases':30-i*0.1,'proj_obp':.360-i*0.0008,"
            "'proj_hits':170-i*0.5,'proj_walks':60,'proj_hbp':5,'proj_sac_flies':5,"
            "'proj_at_bats':550} for i in range(160)];"
            "cfg=ValuationConfig(sgp_denominators=" + json.dumps(DENOMS) + ");"
            "out=compute_hitter_sgp(rows,config=cfg);"
            "print(json.dumps([(r['mlb_id'],r['total_zscore'],r['replacement_adj'])"
            " for r in out]))"
        )

        results = []
        for seed in ("0", "1", "12345", "99999"):
            proc = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True, text=True,
                env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
                cwd=str(pathlib.Path(__file__).resolve().parents[3]),
            )
            assert proc.returncode == 0, proc.stderr
            results.append(proc.stdout.strip())

        assert len(set(results)) == 1, (
            "hitter board differs between hash seeds — slot assignment has "
            "become order-dependent again"
        )
