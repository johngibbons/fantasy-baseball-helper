"""Build ex-post SGP values and the reconstructed preseason board.

Usage:
    # first run of the season needs actuals pulled from MLB Stats API
    python3 -m backend.scripts.retro_expost --season 2026 --refresh-actuals

    # subsequent runs reuse what is already in batting_stats / pitching_stats
    python3 -m backend.scripts.retro_expost --season 2026

Produces, in backend/data/fixtures/retro_<season>/:
  preseason_board.json  — what the valuation model said before the season
  expost_values.json    — what players were actually worth, same scale
  attrition.json        — projected vs. realized playing time

Both boards are valued over the identical player pool with identical SGP
denominators; the ex-post run additionally turns off the playing-time discount,
which prices risk that no longer exists once the season has happened. See
backend/analysis/retro/expost.py for why each of those matters.

The preseason ATC board the draft actually used was overwritten in place by
rest-of-season refreshes and is unrecoverable, so the baseline is reconstructed
from the git-tracked February FanGraphs CSVs (THE BAT X by default).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

from backend.analysis.retro.expost import (
    EXPOST_SOURCE,
    PlayerIdentity,
    align_pool,
    attrition_report,
    batting_actuals_to_row,
    pace_adjust_hitters,
    pace_adjust_pitchers,
    pitching_actuals_to_row,
    season_elapsed_fraction,
)
from backend.analysis.zscores import (
    ValuationConfig,
    _compute_sgp_denominators,
    compute_hitter_sgp,
    compute_pitcher_sgp,
)
from backend.database import get_connection

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ALL_CATS = ["R", "TB", "RBI", "SB", "OBP", "K", "QS", "ERA", "WHIP", "SVHD"]

HITTER_COLS = """p.mlb_id, p.full_name, p.primary_position, p.team, p.eligible_positions,
    pr.proj_pa, pr.proj_runs, pr.proj_total_bases, pr.proj_rbi, pr.proj_stolen_bases,
    pr.proj_obp, pr.proj_hits, pr.proj_walks, pr.proj_hbp, pr.proj_sac_flies,
    pr.proj_at_bats"""
PITCHER_COLS = """p.mlb_id, p.full_name, p.primary_position, p.team,
    pr.proj_ip, pr.proj_pitcher_strikeouts, pr.proj_quality_starts, pr.proj_era,
    pr.proj_whip, pr.proj_saves, pr.proj_holds, pr.proj_hits_allowed,
    pr.proj_walks_allowed, pr.proj_earned_runs"""


def _git_sha() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
                             capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def load_projection_rows(conn, season: int, source: str, player_type: str) -> list[dict]:
    cols = HITTER_COLS if player_type == "hitter" else PITCHER_COLS
    rows = conn.execute(
        f"""SELECT {cols}
            FROM projections pr JOIN players p ON pr.mlb_id = p.mlb_id
            WHERE pr.season = ? AND pr.source = ? AND pr.player_type = ?""",
        (season, source, player_type),
    ).fetchall()
    return [dict(r) for r in rows]


def load_identities(conn, mlb_ids: set[int]) -> dict[int, PlayerIdentity]:
    if not mlb_ids:
        return {}
    marks = ",".join("?" * len(mlb_ids))
    rows = conn.execute(
        f"""SELECT mlb_id, full_name, primary_position, team, eligible_positions
            FROM players WHERE mlb_id IN ({marks})""",
        tuple(mlb_ids),
    ).fetchall()
    return {
        r["mlb_id"]: PlayerIdentity(
            mlb_id=r["mlb_id"], full_name=r["full_name"],
            primary_position=r["primary_position"], team=r["team"],
            eligible_positions=r["eligible_positions"],
        )
        for r in rows
    }


def load_actuals(conn, season: int, table: str) -> dict[int, dict]:
    rows = conn.execute(f"SELECT * FROM {table} WHERE season = ?", (season,)).fetchall()
    return {r["mlb_id"]: dict(r) for r in rows}


def build_boards(conn, season: int, source: str, as_of: date, streaming_bonus: float):
    """Value the same player pool twice: on February projections, and on what
    actually happened."""
    preseason_hitters = load_projection_rows(conn, season, source, "hitter")
    preseason_pitchers = load_projection_rows(conn, season, source, "pitcher")
    if not preseason_hitters or not preseason_pitchers:
        raise SystemExit(
            f"No {source} projections for {season}. Run "
            f"`import_csv_projections({season})` from backend.data.sync first."
        )

    hitter_universe = {r["mlb_id"] for r in preseason_hitters}
    pitcher_universe = {r["mlb_id"] for r in preseason_pitchers}
    identities = load_identities(conn, hitter_universe | pitcher_universe)

    batting = load_actuals(conn, season, "batting_stats")
    pitching = load_actuals(conn, season, "pitching_stats")

    expost_hitter_rows = [
        batting_actuals_to_row(identities[mlb_id], batting.get(mlb_id))
        for mlb_id in sorted(hitter_universe) if mlb_id in identities
    ]
    expost_pitcher_rows = [
        pitching_actuals_to_row(identities[mlb_id], pitching.get(mlb_id))
        for mlb_id in sorted(pitcher_universe) if mlb_id in identities
    ]
    expost_hitter_rows = align_pool(expost_hitter_rows, hitter_universe,
                                    identities, batting_actuals_to_row)
    expost_pitcher_rows = align_pool(expost_pitcher_rows, pitcher_universe,
                                     identities, pitching_actuals_to_row)

    # Pin denominators so both boards share a scale, and keep them out of the
    # ex-post pool's influence entirely.
    denoms = {k: round(v, 6) for k, v in _compute_sgp_denominators(ALL_CATS).items()}

    preseason_cfg = ValuationConfig(sgp_denominators=denoms)
    expost_cfg = ValuationConfig(
        sgp_denominators=denoms,
        apply_playing_time_discount=False,   # realized volume is a fact, not a risk
        streaming_bonus=streaming_bonus,
    )

    # A second ex-post board with counting stats projected to a full-season
    # pace, so that *levels* can be compared against full-season projections.
    # See pace_adjust for why the raw board understates counting categories.
    elapsed = season_elapsed_fraction(as_of)
    paced_hitter_rows = pace_adjust_hitters(expost_hitter_rows, elapsed)
    paced_pitcher_rows = pace_adjust_pitchers(expost_pitcher_rows, elapsed)

    boards = {
        "preseason": {
            "hitters": compute_hitter_sgp(preseason_hitters, config=preseason_cfg),
            "pitchers": compute_pitcher_sgp(preseason_pitchers, config=preseason_cfg),
        },
        "expost": {
            "hitters": compute_hitter_sgp(expost_hitter_rows, config=expost_cfg),
            "pitchers": compute_pitcher_sgp(expost_pitcher_rows, config=expost_cfg),
        },
        "expost_paced": {
            "hitters": compute_hitter_sgp(paced_hitter_rows, config=expost_cfg),
            "pitchers": compute_pitcher_sgp(paced_pitcher_rows, config=expost_cfg),
        },
    }
    raw_rows = {
        "preseason_hitters": preseason_hitters, "preseason_pitchers": preseason_pitchers,
        "expost_hitters": expost_hitter_rows, "expost_pitchers": expost_pitcher_rows,
    }
    return boards, raw_rows, denoms


def slim(results: list[dict]) -> list[dict]:
    """Trim a valued board to the fields the analysis layers read.

    The raw stat columns are kept alongside the SGP ones so Layer D can split
    a source's error into playing time versus per-unit rate without going back
    to the database.
    """
    keep = ("mlb_id", "full_name", "primary_position", "eligible_positions",
            "player_type", "total_zscore", "replacement_adj",
            "zscore_r", "zscore_tb", "zscore_rbi", "zscore_sb", "zscore_obp",
            "zscore_k", "zscore_qs", "zscore_era", "zscore_whip", "zscore_svhd",
            "proj_pa", "proj_r", "proj_tb", "proj_rbi", "proj_sb", "proj_obp",
            "proj_ip", "proj_k", "proj_qs", "proj_era", "proj_whip", "proj_svhd")
    return [{k: r[k] for k in keep if k in r} for r in results]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--source", default="thebatx",
                        help="Preseason projection source (default: thebatx)")
    parser.add_argument("--as-of", default=None,
                        help="Date the actuals reflect (default: today)")
    parser.add_argument("--refresh-actuals", action="store_true",
                        help="Re-pull season actuals from MLB Stats API first")
    parser.add_argument("--streaming-bonus", type=float, default=0.0,
                        help="Streaming bonus for the ex-post board. Default 0 — "
                             "the primary truth metric is pure realized production.")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    as_of = (datetime.strptime(args.as_of, "%Y-%m-%d").date()
             if args.as_of else date.today())
    out_dir = args.out or (REPO_ROOT / "backend" / "data" / "fixtures"
                           / f"retro_{args.season}")

    conn = get_connection()

    if args.refresh_actuals:
        from backend.analysis.performance import refresh_actuals_for_players

        targets = [
            (r["mlb_id"], r["player_type"])
            for r in conn.execute(
                """SELECT DISTINCT pr.mlb_id, pr.player_type FROM projections pr
                   WHERE pr.season = ? AND pr.source = ?""",
                (args.season, args.source),
            ).fetchall()
        ]
        print(f"Refreshing {args.season} actuals for {len(targets)} players...")
        # QS is one of the ten scored categories but is not exposed by the
        # season-stats endpoint, so it has to be derived from game logs.
        state = asyncio.run(refresh_actuals_for_players(
            targets, args.season, include_quality_starts=True))
        print(f"  {state['done']} fetched, "
              f"{state.get('no_stats', 0)} with no {args.season} stats, "
              f"{state['errors']} failed (status={state['status']})")
        if state["errors"]:
            # A failed fetch is indistinguishable from "never played" once the
            # rows are zero-filled, which would understate real production.
            failed = state.get("failed_ids", [])
            raise SystemExit(
                f"{state['errors']} player fetches failed "
                f"(e.g. {failed[:5]}). Re-run --refresh-actuals; the boards "
                f"would otherwise value these players at zero."
            )
        conn.close()
        conn = get_connection()

    boards, raw_rows, denoms = build_boards(
        conn, args.season, args.source, as_of, args.streaming_bonus)
    conn.close()

    elapsed = season_elapsed_fraction(as_of)
    header = {
        "as_of": as_of.isoformat(),
        "season": args.season,
        "season_elapsed_fraction": round(elapsed, 4),
        "git_sha": _git_sha(),
        "sgp_denominators": denoms,
        "preseason_source": args.source,
        "expost_source": EXPOST_SOURCE,
    }

    pre_h, pre_p = boards["preseason"]["hitters"], boards["preseason"]["pitchers"]
    exp_h, exp_p = boards["expost"]["hitters"], boards["expost"]["pitchers"]
    paced_h, paced_p = (boards["expost_paced"]["hitters"],
                        boards["expost_paced"]["pitchers"])

    _write_json(out_dir / "preseason_board.json", {
        **header,
        "config": {"apply_playing_time_discount": True, "streaming_bonus": 0.70},
        "hitters": slim(pre_h), "pitchers": slim(pre_p),
    })
    _write_json(out_dir / "expost_values.json", {
        **header,
        "config": {"apply_playing_time_discount": False,
                   "streaming_bonus": args.streaming_bonus},
        "hitters": slim(exp_h), "pitchers": slim(exp_p),
    })
    _write_json(out_dir / "expost_values_paced.json", {
        **header,
        "config": {"apply_playing_time_discount": False,
                   "streaming_bonus": args.streaming_bonus,
                   "pace_adjusted": True},
        "hitters": slim(paced_h), "pitchers": slim(paced_p),
    })
    _write_json(out_dir / "attrition.json", {
        **header,
        "hitters": attrition_report(raw_rows["preseason_hitters"],
                                    raw_rows["expost_hitters"], "proj_pa"),
        "pitchers": attrition_report(raw_rows["preseason_pitchers"],
                                     raw_rows["expost_pitchers"], "proj_ip"),
    })

    played_h = sum(1 for r in raw_rows["expost_hitters"] if r["proj_pa"] > 0)
    played_p = sum(1 for r in raw_rows["expost_pitchers"] if r["proj_ip"] > 0)
    print(f"\nSeason elapsed: {elapsed:.1%} (as of {as_of})")
    print(f"Pool: {len(pre_h)} hitters, {len(pre_p)} pitchers "
          f"({played_h} / {played_p} with {args.season} playing time)")
    print("\nTop 5 ex-post hitters:")
    for r in exp_h[:5]:
        print(f"  {r['total_zscore']:7.2f}  {r['full_name']}")
    print("Top 5 ex-post pitchers:")
    for r in exp_p[:5]:
        print(f"  {r['total_zscore']:7.2f}  {r['full_name']}")
    print(f"\nArtifacts written to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
