"""Calibrate CATEGORY_SIGMA values from a completed H2H season.

Usage:
    python3 -m backend.scripts.calibrate_category_sigma \\
        --league-id 77166 --season 2025 \\
        --swid '{...}' --espn-s2 '...'

Prints calibrated σ values and writes a fixture JSON to
backend/data/fixtures/sigma_calibration_<season>.json for regression testing.

To pool σ_between across seasons already calibrated, with weekly noise
removed (what matchup.py ships):
    python3 -m backend.scripts.calibrate_category_sigma --pool-seasons 2025 2026
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

from backend.analysis.sigma_calibration import (
    CountStatObservation,
    compute_category_sigma,
    compute_between_team_sigma,
    pool_variance,
    split_half_between_variance,
    true_between_team_variance,
)
from backend.data.espn_history import (
    ESPN_STAT_ID_TO_CAT,
    MatchupRecord,
    fetch_season_matchup_history,
)

# Mirrors the cat list in matchup.py's CATEGORY_SIGMA
CAT_KEYS = ["R", "TB", "RBI", "SB", "OBP", "K", "QS", "ERA", "WHIP", "SVHD"]
CAT_KINDS: dict[str, str] = {
    "R": "count", "TB": "count", "RBI": "count", "SB": "count", "OBP": "rate",
    "K": "count", "QS": "count", "ERA": "rate", "WHIP": "rate", "SVHD": "count",
}

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "data" / "fixtures"

# v1 filter: include only typical-length matchup periods (5–9 days inclusive)
MIN_PERIOD_DAYS = 5
MAX_PERIOD_DAYS = 9


def filter_records(records: list[MatchupRecord]) -> list[MatchupRecord]:
    """Drop matchup periods outside typical 7-day length to avoid period-length confound."""
    return [r for r in records if MIN_PERIOD_DAYS <= r.period_days <= MAX_PERIOD_DAYS]


def compute_team_rates_per_day(
    records: list[MatchupRecord],
) -> dict[int, dict[str, float]]:
    """For each team, compute season-rate per day per cat.

    Count stats: total_observed / total_filtered_days.
    Rate stats: unweighted mean across periods (no PA/IP weights available
    from ESPN's matchup response). Acceptable for v1 calibration.
    """
    by_team: dict[int, list[MatchupRecord]] = defaultdict(list)
    for r in records:
        by_team[r.team_id].append(r)

    rates: dict[int, dict[str, float]] = {}
    for team_id, team_records in by_team.items():
        total_days = sum(r.period_days for r in team_records)
        cat_rates: dict[str, float] = {}
        for cat in CAT_KEYS:
            kind = CAT_KINDS[cat]
            if kind == "count":
                total = sum(r.cats.get(cat, 0.0) for r in team_records)
                cat_rates[cat] = (total / total_days) if total_days > 0 else 0.0
            else:  # rate
                values = [r.cats.get(cat, 0.0) for r in team_records]
                cat_rates[cat] = (sum(values) / len(values)) if values else 0.0
        rates[team_id] = cat_rates
    return rates


def records_to_observations(records: list[MatchupRecord]) -> list[CountStatObservation]:
    """Flatten MatchupRecords into per-cat observations for the calibrator."""
    out: list[CountStatObservation] = []
    for r in records:
        for cat in CAT_KEYS:
            if cat not in r.cats:
                continue
            out.append(CountStatObservation(
                team_id=r.team_id,
                period_id=r.matchup_period_id,
                period_days=r.period_days,
                cat=cat,
                observed=r.cats[cat],
            ))
    return out


def write_fixture(
    fixture_path: Path,
    records: list[MatchupRecord],
    computed_sigma: dict[str, float],
    computed_between_sigma: dict[str, float],
) -> None:
    """Persist raw records + computed σ values for regression testing."""
    payload = {
        "computed_sigma": computed_sigma,
        "computed_between_sigma": computed_between_sigma,
        "records": [
            {
                "team_id": r.team_id,
                "matchup_period_id": r.matchup_period_id,
                "period_days": r.period_days,
                "cats": r.cats,
            }
            for r in records
        ],
    }
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    with fixture_path.open("w") as f:
        json.dump(payload, f, indent=2, sort_keys=True)


def load_fixture(season: int) -> dict:
    with (FIXTURES_DIR / f"sigma_calibration_{season}.json").open() as f:
        return json.load(f)


def _periods_per_team(fixture: dict) -> dict[int, int]:
    counts: dict[int, int] = defaultdict(int)
    for r in fixture["records"]:
        counts[r["team_id"]] += 1
    return counts


def pooled_between_variance(seasons: list[int]) -> dict[str, float]:
    """Variance of teams' true typical-period means, pooled over *seasons*.

    Each season's observed σ_between has its weekly noise removed, then the
    seasons are pooled. May be negative; see pooled_between_sigma.
    """
    estimates = []
    for season in seasons:
        fixture = load_fixture(season)
        periods = list(_periods_per_team(fixture).values())
        estimates.append((true_between_team_variance(
            fixture["computed_between_sigma"], fixture["computed_sigma"], periods,
        ), len(periods)))
    return pool_variance(estimates)


def pooled_between_sigma(seasons: list[int]) -> dict[str, float]:
    """σ_between for matchup.py: pooled_between_variance, truncated at zero.

    Zero means the observed spread is no wider than weekly noise alone would
    produce, and the playoff-odds shrinkage then uses the projection alone.
    """
    return {cat: math.sqrt(max(0.0, v))
            for cat, v in pooled_between_variance(seasons).items()}


def pooled_split_half_variance(seasons: list[int]) -> dict[str, float]:
    """The odd/even-period cross-check, pooled the same way."""
    estimates = []
    for season in seasons:
        fixture = load_fixture(season)
        by_cat = {}
        for cat in CAT_KEYS:
            periods_by_team: dict[int, list[tuple[int, int, float]]] = defaultdict(list)
            for r in fixture["records"]:
                periods_by_team[r["team_id"]].append(
                    (r["matchup_period_id"], r["period_days"], r["cats"][cat]))
            by_cat[cat] = split_half_between_variance(periods_by_team, CAT_KINDS[cat])
        estimates.append((by_cat, len(_periods_per_team(fixture))))
    return pool_variance(estimates)


def _signed_sqrt(v: float) -> float:
    return math.copysign(math.sqrt(abs(v)), v)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league-id")
    parser.add_argument("--season", type=int)
    parser.add_argument("--swid")
    parser.add_argument("--espn-s2")
    parser.add_argument(
        "--fixture",
        type=Path,
        default=None,
        help="Output fixture path (default: backend/data/fixtures/sigma_calibration_<season>.json)",
    )
    parser.add_argument(
        "--pool-seasons", type=int, nargs="+", default=None,
        help="Skip ESPN; pool noise-corrected σ_between across these seasons' fixtures",
    )
    args = parser.parse_args()

    if args.pool_seasons:
        observed = pool_variance([
            ({cat: s ** 2 for cat, s in load_fixture(season)["computed_between_sigma"].items()},
             len(_periods_per_team(load_fixture(season))))
            for season in args.pool_seasons
        ])
        corrected = pooled_between_variance(args.pool_seasons)
        split_half = pooled_split_half_variance(args.pool_seasons)
        print("σ_between by category: observed spread of season averages, with weekly")
        print("noise removed, and the odd/even-period cross-check (negative = below noise).")
        print(f"  {'cat':5} {'observed':>10} {'corrected':>10} {'odd/even':>10}")
        for cat in CAT_KEYS:
            print(f"  {cat:5} {math.sqrt(observed[cat]):10.4g} "
                  f"{_signed_sqrt(corrected[cat]):10.4g} {_signed_sqrt(split_half[cat]):10.4g}")
        print()

        pooled = pooled_between_sigma(args.pool_seasons)
        seasons = " and ".join(str(s) for s in args.pool_seasons)
        print(f"CATEGORY_BETWEEN_SIGMA pooled over {seasons}, noise removed "
              "(paste into backend/analysis/matchup.py):")
        print("CATEGORY_BETWEEN_SIGMA: dict[str, float] = {")
        for cat in CAT_KEYS:
            print(f'    "{cat}": {pooled[cat]:.6g},')
        print("}")
        return 0

    missing = [flag for flag, value in (("--league-id", args.league_id),
                                        ("--season", args.season),
                                        ("--swid", args.swid),
                                        ("--espn-s2", args.espn_s2)) if value is None]
    if missing:
        parser.error(f"required unless --pool-seasons is given: {', '.join(missing)}")

    print(f"Fetching {args.season} matchup history for league {args.league_id}...")
    records = fetch_season_matchup_history(
        league_id=args.league_id,
        season=args.season,
        swid=args.swid,
        espn_s2=args.espn_s2,
    )
    print(f"  Retrieved {len(records)} team-week records.")

    filtered = filter_records(records)
    dropped = len(records) - len(filtered)
    print(f"  Filtered to {len(filtered)} typical-length team-weeks ({dropped} dropped).")

    period_lengths = sorted(set(r.period_days for r in filtered))
    print(f"  Period lengths in calibration set: {period_lengths}")

    rates = compute_team_rates_per_day(filtered)
    observations = records_to_observations(filtered)
    sigma = compute_category_sigma(
        observations=observations,
        team_rates_per_day=rates,
        cat_keys=CAT_KEYS,
        cat_kinds=CAT_KINDS,
    )

    print()
    print("Calibrated CATEGORY_SIGMA (paste into backend/analysis/matchup.py):")
    print("CATEGORY_SIGMA: dict[str, float] = {")
    for cat in CAT_KEYS:
        print(f'    "{cat}": {sigma[cat]:.4f},')
    print("}")

    between_sigma = compute_between_team_sigma(
        team_rates_per_day=rates,
        cat_keys=CAT_KEYS,
        cat_kinds=CAT_KINDS,
    )

    print()
    print("Calibrated CATEGORY_BETWEEN_SIGMA (paste into backend/analysis/matchup.py):")
    print("CATEGORY_BETWEEN_SIGMA: dict[str, float] = {")
    for cat in CAT_KEYS:
        print(f'    "{cat}": {between_sigma[cat]:.4f},')
    print("}")

    fixture_path = args.fixture or FIXTURES_DIR / f"sigma_calibration_{args.season}.json"
    write_fixture(fixture_path, filtered, sigma, between_sigma)
    print(f"\nFixture written: {fixture_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
