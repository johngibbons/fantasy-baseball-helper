"""Measure H2H category weights from a season's weekly matchup results.

Usage:
    python3 -m backend.scripts.calibrate_category_weights \\
        --league-id 77166 --season 2026 \\
        --swid '{...}' --espn-s2 '...'

The weights in zscores.py multiply every category in the valuation model, and
the correlation matrix they were derived from is described in that file's own
comments as "approximate" — assumed rather than measured. ESPN records one
observation per team per week per category, which is exactly what is needed to
compute the real thing.

Prints paste-ready values and writes a fixture for regression testing, in the
same shape as calibrate_category_sigma.py.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from backend.analysis.category_weights import (
    DEFAULT_DAMPENING,
    calibrate_category_weights,
)
from backend.analysis.zscores import H2H_CATEGORY_WEIGHTS
from backend.data.espn_history import MatchupRecord, fetch_season_matchup_history

CAT_KEYS = ["R", "TB", "RBI", "SB", "OBP", "K", "QS", "ERA", "WHIP", "SVHD"]

# Same filter as the sigma calibration: only typical-length matchup periods, so
# period length does not masquerade as correlation.
MIN_PERIOD_DAYS = 5
MAX_PERIOD_DAYS = 9


def records_to_observations(records: list[MatchupRecord]) -> list[dict[str, float]]:
    """One dict of category totals per team-week."""
    return [
        {cat: record.cats[cat] for cat in CAT_KEYS if cat in record.cats}
        for record in records
    ]


def load_records_from_sigma_fixture(path: Path) -> list[MatchupRecord]:
    """Reuse the team-week totals already captured for the sigma calibration.

    Same league, same shape, already committed — so the weights for a completed
    past season can be measured without ESPN credentials.
    """
    payload = json.loads(path.read_text())
    return [
        MatchupRecord(
            team_id=record["team_id"],
            matchup_period_id=record["matchup_period_id"],
            period_days=record["period_days"],
            cats=record["cats"],
        )
        for record in payload["records"]
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--league-id")
    parser.add_argument("--swid")
    parser.add_argument("--espn-s2")
    parser.add_argument(
        "--from-sigma-fixture", type=Path, default=None,
        help="Calibrate from an existing sigma_calibration_<season>.json "
             "instead of fetching from ESPN (no credentials needed).",
    )
    parser.add_argument("--dampening", type=float, default=DEFAULT_DAMPENING,
                        help="0 = equal weights, 1 = raw measured (default 0.6)")
    parser.add_argument("--fixture", type=Path, default=None)
    args = parser.parse_args()

    if args.from_sigma_fixture:
        print(f"Reading team-week records from {args.from_sigma_fixture}...")
        records = load_records_from_sigma_fixture(args.from_sigma_fixture)
    else:
        missing = [flag for flag, value in
                   (("--league-id", args.league_id), ("--swid", args.swid),
                    ("--espn-s2", args.espn_s2)) if not value]
        if missing:
            raise SystemExit(
                f"Missing {', '.join(missing)}. Either supply ESPN credentials "
                f"or pass --from-sigma-fixture."
            )
        print(f"Fetching {args.season} matchup history for league {args.league_id}...")
        records = fetch_season_matchup_history(
            league_id=args.league_id, season=args.season,
            swid=args.swid, espn_s2=args.espn_s2,
        )
    print(f"  Retrieved {len(records)} team-week records.")

    filtered = [r for r in records
                if MIN_PERIOD_DAYS <= r.period_days <= MAX_PERIOD_DAYS]
    print(f"  Using {len(filtered)} typical-length team-weeks "
          f"({len(records) - len(filtered)} dropped).")

    observations = records_to_observations(filtered)
    result = calibrate_category_weights(observations, CAT_KEYS, args.dampening)

    print("\nMeasured weekly correlations (|r| with other categories):")
    for cat in CAT_KEYS:
        row = result["correlation_matrix"][cat]
        strongest = sorted(
            ((other, value) for other, value in row.items()
             if other != cat and value is not None),
            key=lambda pair: -abs(pair[1]),
        )[:3]
        pairs = ", ".join(f"{other} {value:+.2f}" for other, value in strongest)
        print(f"  {cat:<5} independence={result['independence_scores'][cat]:.3f}"
              f"   strongest: {pairs}")

    print("\nMeasured H2H_CATEGORY_WEIGHTS (paste into backend/analysis/zscores.py):")
    print("H2H_CATEGORY_WEIGHTS = {")
    for cat in CAT_KEYS:
        shipped = H2H_CATEGORY_WEIGHTS[cat]
        measured = result["weights"][cat]
        print(f'    "{cat}": {measured:.2f},'
              f'  # shipped {shipped:.2f}  ({measured - shipped:+.2f})')
    print("}")

    fixture_path = args.fixture or (
        Path(__file__).resolve().parent.parent
        / "data" / "fixtures" / f"category_weights_{args.season}.json"
    )
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    with fixture_path.open("w") as f:
        json.dump({
            **result,
            "season": args.season,
            "cat_keys": CAT_KEYS,
            "shipped_weights": H2H_CATEGORY_WEIGHTS,
            "observations": observations,
        }, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"\nFixture written: {fixture_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
