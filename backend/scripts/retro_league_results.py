"""Fetch a finished season's league results for the retrospective.

Usage:
    python3 -m backend.scripts.retro_league_results --season 2026 \\
        --league-id 77166 --swid '{...}' --espn-s2 '...'

Run once, after the fantasy playoffs. Emits, into the retro directory:
  actual_win_rates.json  — {team_id: {category: share of weekly matchups won}},
                           which retro_draft.py compares its team model against
  final_standings.json   — category record, playoff seed and final rank

Teams are identified by ESPN team id only, as in draft_state; names are left
out because the repository is public.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from backend.data.espn_history import (
    fetch_league_views,
    parse_category_win_rates,
    parse_standings,
)
from backend.simulation.player_pool import CAT_LABELS

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# The team model keys categories the way the simulation does (zscore_r ...).
SIM_KEY_BY_ESPN_CAT = {label: key for key, label in CAT_LABELS.items()}


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def to_sim_keys(win_rates: dict[int, dict[str, float]]) -> dict[str, dict[str, float]]:
    return {
        str(team_id): {SIM_KEY_BY_ESPN_CAT[cat]: round(rate, 6)
                       for cat, rate in rates.items()}
        for team_id, rates in sorted(win_rates.items())
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--league-id", required=True)
    parser.add_argument("--swid", required=True)
    parser.add_argument("--espn-s2", required=True)
    parser.add_argument("--dir", type=Path, default=None)
    args = parser.parse_args()

    out_dir = args.dir or (REPO_ROOT / "backend" / "data" / "fixtures"
                           / f"retro_{args.season}")
    print(f"Fetching {args.season} results for league {args.league_id}...")
    response = fetch_league_views(
        args.league_id, args.season, args.swid, args.espn_s2,
        views=("mMatchup", "mMatchupScore", "mTeam", "mStandings"),
    )

    win_rates = parse_category_win_rates(response)
    standings = parse_standings(response)
    if not win_rates or any(row["final_rank"] is None for row in standings):
        raise SystemExit("The league has no final ranks yet; run this after "
                         "the fantasy playoffs are complete.")

    state_path = out_dir / f"draft_state_{args.season}.json"
    my_team = (json.loads(state_path.read_text()).get("myTeamId")
               if state_path.exists() else None)

    _write_json(out_dir / "actual_win_rates.json", to_sim_keys(win_rates))
    _write_json(out_dir / "final_standings.json", {
        "season": args.season,
        "league_id": args.league_id,
        "my_team_id": my_team,
        "note": ("Wins, losses and ties count categories: each regular-season "
                 "week decides ten. playoff_seed is the regular-season finish; "
                 "final_rank includes the playoffs."),
        "teams": standings,
    })

    print(f"\n  {'rank':>4} {'seed':>4} {'team':>4} {'W-L-T':>10} {'wins/wk':>8}")
    for row in standings:
        weekly = sum(win_rates.get(row["team_id"], {}).values())
        marker = "  <- you" if row["team_id"] == my_team else ""
        print(f"  {row['final_rank']:>4} {row['playoff_seed']:>4} "
              f"{row['team_id']:>4} "
              f"{row['wins']:>3}-{row['losses']}-{row['ties']:<3} "
              f"{weekly:>8.2f}{marker}")
    print(f"\nWritten to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
