"""Layer B: draft decision quality.

Usage:
    python3 -m backend.scripts.retro_draft --season 2026

Requires the boards from retro_expost.py and the frozen draft state from
retro_snapshot.py. Emits:
  draft_decisions.json   — per-pick regret, by team and by round
  team_evaluations.json  — predicted category wins per team from actual rosters
  counterfactuals.json   — what other drafting strategies would have produced

Values: realized value is raw ex-post SGP (pace-adjusted). Board value is the
preseason SGP with the pitcher normalizer applied, because that is the number
the draft board actually ranked by.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from backend.analysis.retro.draft_replay import (
    DraftContext,
    build_draft_board,
    compare_predicted_to_actual,
    draftable_pool,
    predicted_category_wins,
    replay,
    summarize_by_round,
    summarize_by_team,
    team_category_totals,
)
from backend.analysis.zscores import PITCHER_CATEGORY_NORMALIZER
from backend.simulation.config import SimConfig
from backend.simulation.player_pool import load_players_from_rows

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
NUM_TEAMS = 10
ROSTER_SIZE = 25


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def value_map(board: dict, normalizer: float) -> dict[int, float]:
    """mlb_id -> value, applying the pitcher normalizer to the pitcher pool."""
    values = {r["mlb_id"]: float(r["total_zscore"]) for r in board["hitters"]}
    for row in board["pitchers"]:
        values[row["mlb_id"]] = float(row["total_zscore"]) * normalizer
    return values


def counterfactual_drafts(context: DraftContext,
                          strategies: dict[str, dict[int, float]]) -> dict:
    """Re-run the draft with every team following one strategy.

    Each strategy is a value map; at every pick the team on the clock takes the
    highest-valued player still available. Because all ten teams follow the same
    rule, the comparison is like-for-like: the difference between strategies is
    the ordering they impose, not who happened to pick first.
    """
    pool = draftable_pool(context)
    keeper_by_team: dict[int, list[int]] = {}
    for slot in context.board:
        if slot and slot["is_keeper"]:
            keeper_by_team.setdefault(slot["team_id"], []).append(slot["mlb_id"])

    results = {}
    for label, values in strategies.items():
        available = set(pool)
        rosters: dict[int, list[int]] = {
            team_id: list(keepers) for team_id, keepers in keeper_by_team.items()
        }
        for slot in context.board:
            # Keeper slots are already filled; they are not a choice.
            if slot is None or slot["is_keeper"]:
                continue
            if not available:
                break
            chosen = max(available, key=lambda p: values.get(p, 0.0))
            available.discard(chosen)
            rosters.setdefault(slot["team_id"], []).append(chosen)

        results[label] = {
            "team_totals": {
                str(team_id): round(
                    sum(context.realized_value.get(p, 0.0) for p in players), 2)
                for team_id, players in sorted(rosters.items())
            },
            "rosters": {str(t): p for t, p in sorted(rosters.items())},
        }
    return results


def solo_counterfactual(context: DraftContext, my_team_id: int,
                        values: dict[int, float]) -> dict:
    """Replay the real draft, changing only one team's choices.

    The league-wide counterfactual answers "what if everyone drafted this way",
    which is like-for-like but says little about your decisions: when all ten
    teams change behaviour, the pool in front of you changes too. This holds the
    other nine teams to exactly the players they really took, and re-picks only
    your slots from whatever is genuinely available at that moment.
    """
    available = draftable_pool(context)
    my_roster: list[int] = []

    for slot in context.board:
        if slot is None:
            continue
        actual_id, team_id = slot["mlb_id"], slot["team_id"]
        if slot["is_keeper"]:
            available.discard(actual_id)
            if team_id == my_team_id:
                my_roster.append(actual_id)
            continue

        if team_id == my_team_id:
            if not available:
                continue
            chosen = max(available, key=lambda p: values.get(p, 0.0))
            my_roster.append(chosen)
            available.discard(chosen)
        else:
            available.discard(actual_id)

    return {
        "team_total": round(
            sum(context.realized_value.get(p, 0.0) for p in my_roster), 2),
        "roster": my_roster,
        "names": [context.names.get(p) for p in my_roster],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--dir", type=Path, default=None)
    parser.add_argument("--actual-win-rates", type=Path, default=None,
                        help="JSON of {team_id: {cat: win_rate}} from ESPN "
                             "weekly results, for validating the team model.")
    args = parser.parse_args()

    out_dir = args.dir or (REPO_ROOT / "backend" / "data" / "fixtures"
                           / f"retro_{args.season}")
    state = json.loads((out_dir / f"draft_state_{args.season}.json").read_text())
    preseason = json.loads((out_dir / "preseason_board.json").read_text())
    paced_path = out_dir / "expost_values_paced.json"
    expost = json.loads((paced_path if paced_path.exists()
                         else out_dir / "expost_values.json").read_text())
    adp_payload = json.loads((out_dir / f"adp_draftday_{args.season}.json").read_text())

    board_rows = preseason["hitters"] + preseason["pitchers"]
    expost_rows = expost["hitters"] + expost["pitchers"]
    names = {r["mlb_id"]: r.get("full_name") for r in board_rows}

    # `state["picks"]` is a Map dumped to an array (mlb_id -> teamId), so its
    # positions are insertion order, not pick indices. Rebuild the real board.
    pick_schedule = state["pickSchedule"]
    draft_board = build_draft_board(
        state["leagueKeepers"], state["pickLog"], pick_schedule,
        state["roundStarts"], len(pick_schedule),
    )

    context = DraftContext(
        board=draft_board,
        keeper_ids=set(state["keeperMlbIds"]),
        pool_ids={r["mlb_id"] for r in board_rows},
        # Realized value is raw SGP: it is the objective, not a ranking that
        # needs the pitcher category correction applied to it.
        realized_value=value_map(expost, 1.0),
        board_value=value_map(preseason, PITCHER_CATEGORY_NORMALIZER),
        adp={int(k): v for k, v in adp_payload["adp_by_mlb_id"].items()},
        names=names,
    )

    header = {
        "as_of": expost["as_of"],
        "season": args.season,
        "season_elapsed_fraction": expost["season_elapsed_fraction"],
        "preseason_source": preseason["preseason_source"],
    }

    # ── Per-pick regret ──
    rows = replay(context)
    by_team = summarize_by_team(rows)
    by_round = summarize_by_round(rows)
    _write_json(out_dir / "draft_decisions.json", {
        **header,
        "picks": rows,
        "by_team": by_team,
        "by_round": by_round,
        "worst_board_decisions": sorted(rows, key=lambda r: r["board_regret"])[:20],
        "worst_outcomes": sorted(rows, key=lambda r: r["realized_regret"])[:20],
        "best_picks": sorted(rows, key=lambda r: -r["realized_value"])[:20],
    })

    # ── Team model validation ──
    config = SimConfig()
    expost_by_id = {r["mlb_id"]: r for r in expost_rows}
    rosters: dict[int, list[int]] = {}
    for slot in draft_board:
        if slot is not None:
            rosters.setdefault(slot["team_id"], []).append(slot["mlb_id"])

    team_totals = {}
    for team_id, member_ids in rosters.items():
        rows_for_team = [expost_by_id[i] for i in member_ids if i in expost_by_id]
        players = load_players_from_rows(rows_for_team)
        team_totals[team_id] = team_category_totals(players, config)

    predicted = predicted_category_wins(team_totals, NUM_TEAMS)
    evaluation = {
        **header,
        "note": ("Category win probabilities implied by each team's actual "
                 "roster valued on realized production."),
        "predicted": {
            str(team_id): {
                "expected_wins": round(value["expected_wins"], 3),
                "cat_win_probs": {k: round(v, 4)
                                  for k, v in value["cat_win_probs"].items()},
                "roster_size": len(rosters[team_id]),
            }
            for team_id, value in sorted(predicted.items())
        },
    }
    if args.actual_win_rates and args.actual_win_rates.exists():
        actual = {int(k): v for k, v in
                  json.loads(args.actual_win_rates.read_text()).items()}
        evaluation["comparison"] = compare_predicted_to_actual(predicted, actual)
    _write_json(out_dir / "team_evaluations.json", evaluation)

    # ── Counterfactuals ──
    my_team = state.get("myTeamId")
    counterfactuals = counterfactual_drafts(context, {
        "board_best_available": context.board_value,
        "adp_follow": {mlb_id: -adp for mlb_id, adp in context.adp.items()},
        "expost_optimal": context.realized_value,
    })
    actual_team_totals = {
        str(team_id): round(
            sum(context.realized_value.get(p, 0.0) for p in members), 2)
        for team_id, members in sorted(rosters.items())
    }
    counterfactuals["actual"] = {"team_totals": actual_team_totals}

    # Isolate your own decisions: everyone else keeps the players they really took.
    counterfactuals["solo"] = {
        "note": ("Only your team re-picks; the other nine are held to their "
                 "actual selections, so the pool you face is the real one."),
        "actual": float(actual_team_totals[str(my_team)]),
        "board_best_available": solo_counterfactual(
            context, my_team, context.board_value),
        "expost_optimal": solo_counterfactual(
            context, my_team, context.realized_value),
        "adp_follow": solo_counterfactual(
            context, my_team, {m: -a for m, a in context.adp.items()}),
    }
    _write_json(out_dir / "counterfactuals.json", {**header, **counterfactuals})

    # ── Console summary ──
    print(f"\nLayer B — draft decisions ({len(rows)} logged picks, "
          f"{header['season_elapsed_fraction']:.0%} of season)\n")

    print("Per-team (mean regret per pick, SGP):")
    print(f"  {'team':>5} {'picks':>6} {'realized':>9} {'board rgrt':>11} "
          f"{'real rgrt':>10} {'ADP delta':>10}")
    for team in sorted(by_team, key=lambda t: -t["realized_value"]):
        marker = " <- you" if team["team_id"] == my_team else ""
        print(f"  {team['team_id']:>5} {team['picks']:>6} "
              f"{team['realized_value']:>9.1f} {team['mean_board_regret']:>11.2f} "
              f"{team['mean_realized_regret']:>10.2f} "
              f"{team['mean_adp_delta']:>10.1f}{marker}")

    print("\nIf the whole league drafted this way (realized SGP):")
    for label in ("actual", "board_best_available", "adp_follow", "expost_optimal"):
        totals = counterfactuals[label]["team_totals"]
        print(f"  {label:<22} league={sum(totals.values()):8.1f}")

    print("\nIf only your team drafted this way (others held to real picks):")
    solo = counterfactuals["solo"]
    print(f"  {'actual':<22} {solo['actual']:8.1f}")
    for label in ("board_best_available", "adp_follow", "expost_optimal"):
        value = solo[label]["team_total"]
        print(f"  {label:<22} {value:8.1f}   ({value - solo['actual']:+.1f})")

    print("\nPredicted expected weekly category wins from actual rosters:")
    for team_id, value in sorted(predicted.items(),
                                 key=lambda kv: -kv[1]["expected_wins"]):
        marker = " <- you" if team_id == my_team else ""
        print(f"  team {team_id:>2}: {value['expected_wins']:.2f}{marker}")

    print(f"\nArtifacts written to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
