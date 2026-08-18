"""Phase 3: keeper outcomes across every season in the workbook.

Usage:
    .venv/bin/python -m backend.scripts.history_keepers

Requires Phases 0-2 (history_import, history_resolve, history_backfill_stats).

Emits backend/data/fixtures/league_history/keeper_outcomes.json — every keeper
decision the league has recorded, judged against what its round actually
returned, plus the aggregate answers and their confidence intervals.

The valuation path is the existing ex-post one from the 2026 retrospective:
realized stats through the same SGP engine that builds the draft board, with
the playing-time discount off (realized volume is a fact, not a risk) and
denominators pinned so every season lands on one scale.

See backend/analysis/history/keeper_backtest.py for why the comparison uses a
non-keeper value curve, and why the `prior_*` fields are a decision-time
baseline rather than the app's board.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from backend.analysis.history.keeper_backtest import (
    aggregate_accuracy,
    by_baseline_thickness,
    by_seasons_kept,
    pick_index_for_round,
    surplus_vs_round_cost,
)
from backend.analysis.history.boards import (
    ALL_CATS,
    PITCHER_POSITIONS,
    load_identities,
    stat_coverage,
    value_board,
)
from backend.analysis.retro.keeper_eval import (
    NUM_TEAMS,
    evaluate_keepers,
    keeper_cost,
    value_at_pick_curve,
)
from backend.analysis.zscores import _compute_sgp_denominators
from backend.database import get_connection

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HISTORY_DIR = REPO_ROOT / "backend" / "data" / "fixtures" / "league_history"
ROSTER_CACHE = HISTORY_DIR / "_rosters"

# Share of a season's drafted players that must have a stat row in the PRIOR
# season before that season's baseline is trusted. Well below the ~85% a real
# season reaches, and well above the 0% an un-backfilled one produces.
MIN_PRIOR_COVERAGE = 0.5


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def _load(path: Path):
    return json.loads(path.read_text()) if path.exists() else None


def roster_positions(season: int) -> dict[int, str]:
    positions: dict[int, str] = {}
    for delta in (0, -1, 1):
        cache = ROSTER_CACHE / f"players_{season + delta}.json"
        if cache.exists():
            for person in json.loads(cache.read_text()):
                positions.setdefault(person["mlb_id"],
                                     person.get("primary_position") or "")
    return positions






def analyse_season(conn, season: int, denominators: dict[str, float]) -> dict | None:
    """One season's value curve and keeper verdicts."""
    draft = _load(HISTORY_DIR / f"drafts_{season}.json")
    keepers_payload = _load(HISTORY_DIR / f"keepers_{season}.json")
    resolution = _load(HISTORY_DIR / f"resolution_{season}.json")
    if not draft or not keepers_payload or not resolution:
        return None

    ids = {r["name"]: r["mlb_id"] for r in resolution["resolutions"]
           if r["mlb_id"] is not None}
    positions = roster_positions(season)

    picks = [dict(p, mlb_id=ids.get(p["player_name"])) for p in draft["picks"]]
    resolved = [p for p in picks if p["mlb_id"] is not None]
    universe = {p["mlb_id"] for p in resolved}
    if not universe:
        return None

    hitters = {i for i in universe if positions.get(i, "") not in PITCHER_POSITIONS}
    pitchers = universe - hitters

    identities = load_identities(conn, universe)
    realized = value_board(conn, season, hitters, pitchers, identities, denominators)
    # The decision-time baseline: what these same players did the season before,
    # valued identically. This is what a manager actually had in February.
    prior = value_board(conn, season - 1, hitters, pitchers, identities, denominators)

    # A season whose predecessor was never backfilled produces a board of
    # zeros, which looks like a real baseline and is not. 2021 and 2015 have no
    # draft sheets of their own, so they are easy to miss.
    prior_coverage = stat_coverage(conn, season - 1, universe)
    if prior_coverage < MIN_PRIOR_COVERAGE:
        prior = {}

    keeper_ids = {ids.get(k["player_name"]) for k in keepers_payload["keepers"]}
    keeper_ids.discard(None)

    def is_keeper(pick: dict) -> bool:
        note = (pick.get("notes") or "").lower()
        return pick["mlb_id"] in keeper_ids or "keeper" in note

    def curve_rows(source: list[dict]) -> list[dict]:
        rows = []
        for pick in source:
            index = pick_index_for_round(pick.get("round"))
            if index is None:
                continue
            rows.append({
                "pick_index": index,
                "board_value": prior.get(pick["mlb_id"], 0.0),
                "realized_value": realized.get(pick["mlb_id"], 0.0),
            })
        return rows

    curve_all = value_at_pick_curve(curve_rows(resolved))
    non_keeper = [p for p in resolved if not is_keeper(p)]
    open_rows = curve_rows(non_keeper)
    curve_open = value_at_pick_curve(open_rows)

    # The null this analysis needs: an ordinary pick is measured against the
    # mean of its own round, and value within a round is right-skewed, so the
    # share of picks clearing that mean is below half. Without this number,
    # "keepers beat their round 72% of the time" has nothing to be 72% against.
    open_by_round = {c["round"]: c["mean_realized_value"] for c in curve_open}
    baseline_wins = sum(
        1 for row in open_rows
        if row["realized_value"] > open_by_round.get(
            row["pick_index"] // NUM_TEAMS + 1, 0.0))

    # Keeper records in the shape evaluate_keepers expects.
    managers = sorted({k["manager"] for k in keepers_payload["keepers"]})
    team_ids = {name: index + 1 for index, name in enumerate(managers)}
    keeper_rows, cost_disagreements = [], []
    for keeper in keepers_payload["keepers"]:
        mlb_id = ids.get(keeper["player_name"])
        if mlb_id is None or keeper["round_cost"] is None:
            continue
        keeper_rows.append({
            "mlb_id": mlb_id,
            "teamId": team_ids[keeper["manager"]],
            "playerName": keeper["player_name"],
            "roundCost": keeper["round_cost"],
        })
        # Cross-check the sheet's round against the league's own doctrine.
        seasons_kept = keeper.get("seasons_kept")
        if seasons_kept and seasons_kept > 1:
            prior_pick = next(
                (p for p in (_load(HISTORY_DIR / f"drafts_{season - 1}.json")
                             or {"picks": []})["picks"]
                 if ids.get(p["player_name"]) == mlb_id), None)
            if prior_pick and prior_pick.get("round"):
                expected = keeper_cost(prior_pick["round"], 2)
                if expected != keeper["round_cost"]:
                    cost_disagreements.append({
                        "player": keeper["player_name"],
                        "manager": keeper["manager"],
                        "sheet_round_cost": keeper["round_cost"],
                        "doctrine_round_cost": expected,
                        "prior_season_round": prior_pick["round"],
                    })

    outcomes = evaluate_keepers(keeper_rows, prior, realized, curve_open)
    has_prior = bool(prior)
    # How many non-keeper picks formed each keeper's comparison round.
    baseline_picks = {c["round"]: c["picks"] for c in curve_open}
    last_round = max(baseline_picks) if baseline_picks else 1

    # Rename the board_* fields: they are a prior-season baseline here, not the
    # app's board, and leaving the name would invite exactly that misreading.
    by_name = {k["player_name"]: k for k in keepers_payload["keepers"]}
    for outcome in outcomes:
        board_value = outcome.pop("board_value")
        board_surplus = outcome.pop("board_surplus")
        outcome["prior_value"] = board_value if has_prior else None
        outcome["prior_surplus"] = board_surplus if has_prior else None
        outcome["season"] = season
        outcome["baseline_picks"] = baseline_picks.get(
            min(outcome["round_cost"], last_round))
        record = by_name.get(outcome["name"], {})
        outcome["manager"] = record.get("manager")
        outcome["seasons_kept"] = record.get("seasons_kept")

    return {
        "season": season,
        "picks_resolved": len(resolved),
        "picks_total": len(picks),
        "keepers_evaluated": len(outcomes),
        "prior_season_stat_coverage": round(prior_coverage, 3),
        "non_keeper_picks": len(open_rows),
        "non_keeper_picks_beating_their_round": baseline_wins,
        "prior_baseline_usable": has_prior,
        "value_curve": curve_all,
        "value_curve_excluding_keepers": curve_open,
        "keeper_round_cost_disagreements": cost_disagreements,
        "keepers": outcomes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seasons", type=int, nargs="*", default=None)
    args = parser.parse_args()

    report = _load(HISTORY_DIR / "resolution_report.json")
    seasons = args.seasons or report["included_seasons"]

    conn = get_connection()
    # One pinned set of denominators for every season, so values are directly
    # comparable year to year. The alternative — each season on its own
    # standings — is defensible too, but mixing them silently is not, and the
    # league only has standings loaded for 2023-2025 anyway.
    denominators = {k: round(v, 6)
                    for k, v in _compute_sgp_denominators(ALL_CATS).items()}

    seasons_out, all_outcomes = [], []
    for season in seasons:
        result = analyse_season(conn, season, denominators)
        if result is None:
            continue
        seasons_out.append(result)
        all_outcomes.extend(result["keepers"])
        print(f"  {season}  {result['keepers_evaluated']:>3} keepers, "
              f"{result['picks_resolved']:>3}/{result['picks_total']} picks valued")
    conn.close()

    accuracy = aggregate_accuracy(all_outcomes)
    control_total = sum(r["non_keeper_picks"] for r in seasons_out)
    control_wins = sum(r["non_keeper_picks_beating_their_round"] for r in seasons_out)
    control = {
        "n": control_total,
        "beat_their_round": control_wins,
        "beat_rate": round(control_wins / control_total, 3) if control_total else None,
    }
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seasons": sorted(r["season"] for r in seasons_out),
        "sgp_denominators": denominators,
        "method": {
            "realized_value": "season actuals through compute_*_sgp, "
                              "playing-time discount off, streaming bonus 0",
            "prior_value": "the same players' PREVIOUS season, valued "
                           "identically — a decision-time baseline, NOT the "
                           "app's projection board, which did not exist "
                           "before 2026",
            "comparison_curve": "value at each round EXCLUDING keepers, so a "
                                "keeper is judged against what the round would "
                                "have returned had they been let go",
            "pool": "each season's own resolved draftees; absent players stay "
                    "in the pool at zero",
        },
        "aggregate": accuracy,
        "control_non_keeper_picks": control,
        "surplus_vs_round_cost": surplus_vs_round_cost(all_outcomes),
        "by_seasons_kept": by_seasons_kept(all_outcomes),
        "by_baseline_thickness": by_baseline_thickness(all_outcomes),
        "by_season": [{k: v for k, v in r.items() if k != "keepers"}
                      for r in seasons_out],
        "keepers": all_outcomes,
    }
    _write_json(HISTORY_DIR / "keeper_outcomes.json", payload)

    print(f"\n{accuracy['n']} keeper decisions across {len(seasons_out)} seasons")
    print(f"  beat their round: {accuracy['beat_their_round']}/{accuracy['n']} "
          f"= {accuracy['beat_rate']:.1%}  95% CI "
          f"{accuracy['beat_rate_ci'][0]:.1%}-{accuracy['beat_rate_ci'][1]:.1%}")
    print(f"  control — ordinary picks beating their round: "
          f"{control['beat_their_round']}/{control['n']} = {control['beat_rate']:.1%}")
    print(f"  mean realized surplus: {accuracy['mean_realized_surplus']:+.2f} SGP  "
          f"CI {accuracy['mean_realized_surplus_ci'][0]:+.2f} to "
          f"{accuracy['mean_realized_surplus_ci'][1]:+.2f}")
    if accuracy["prior_sign_agreement"] is not None:
        print(f"  prior-season baseline sign agreement: "
              f"{accuracy['prior_sign_agreement']:.1%} "
              f"(n={accuracy['prior_baseline_n']}, CI "
              f"{accuracy['prior_sign_agreement_ci'][0]:.1%}-"
              f"{accuracy['prior_sign_agreement_ci'][1]:.1%})")

    scaling = payload["surplus_vs_round_cost"]
    if "slope" in scaling:
        print(f"\n  surplus vs round cost: slope {scaling['slope']:+.3f} SGP/round "
              f"CI [{scaling['slope_ci'][0]:+.3f}, {scaling['slope_ci'][1]:+.3f}]"
              f"{'  (flat)' if scaling['flat'] else '  (NOT flat)'}")

    print("\n  robustness — beat rate by comparison-baseline size:")
    for row in payload["by_baseline_thickness"]:
        print(f"    baseline {row['baseline']:>12}: n={row['n']:>3}  "
              f"beat {row['beat_rate']:.1%}  surplus "
              f"{row['mean_realized_surplus']:+.2f}")

    print("\n  by seasons kept:")
    for row in payload["by_seasons_kept"]:
        print(f"    year {row['seasons_kept']}: n={row['n']:>3}  "
              f"mean cost R{row['mean_round_cost']:<5.1f}  "
              f"surplus {row['mean_realized_surplus']:+6.2f}  "
              f"beat rate {row['beat_rate']:.0%}")
    print(f"\nWritten to {HISTORY_DIR / 'keeper_outcomes.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
