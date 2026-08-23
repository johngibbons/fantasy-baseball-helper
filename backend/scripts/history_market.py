"""Phase 5: the market baseline across seasons.

Usage:
    .venv/bin/python -m backend.scripts.history_market

Requires Phases 0-2, 4 and the ranking resolution. Emits market_analysis.json.

The ESPN top-300 sheets are the league's preseason market view, and better than
a generic ADP feed in one respect: they are the list this league actually
drafted from. Five seasons carry both a ranking sheet and a draft -- 2017,
2020, 2023, 2024, 2025 -- which is enough to ask whether the 2026 ADP findings
replicate.

Three questions, and the first one has to be re-framed:

**"Board versus market" is not reproducible before 2026.** That comparison
needed a projection board, and none exists (the constraint that shapes this
whole backtest). What *is* answerable, and is arguably the more useful number,
is **market versus realized**: how well did the preseason consensus predict
what players were actually worth? That is the bar any board has to clear, and
it needs no projections at all.

**Residual spread by ADP band** replicates directly: does the sixfold growth in
spread from the top of the board to the middle rounds hold across seasons, and
does `sigma = 6.55 + 0.158 x adp` still fit best?

**Per-manager reach/wait** replicates directly, over five drafts instead of
one. This is the finding the simulator's opponent model wants, and unlike the
per-manager keeper result it was large and clean in 2026.

One adaptation worth stating. `compute_residuals` defaults to discarding any
ADP at or above 259, because ESPN's *ADP export* pads undrafted players with a
synthetic 260.0 tail. A top-300 *ranking* sheet has no such tail -- every rank
in it is genuine -- so applying that default would silently discard ranks
259-300, the deepest and most interesting part of the board. The threshold is
raised to just past each sheet's own maximum rank instead.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

from backend.analysis.history.boards import (
    ALL_CATS,
    full_pool,
    load_identities,
    season_board,
    value_map,
)
from backend.analysis.retro.adp_model import (
    compare_sigma_models,
    compute_residuals,
    fit_linear_sigma,
    manager_bias,
    sigma_by_bucket,
    sigma_summary,
)
from backend.analysis.retro.valuation import spearman
from backend.analysis.zscores import _compute_sgp_denominators
from backend.database import get_connection

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HISTORY_DIR = REPO_ROOT / "backend" / "data" / "fixtures" / "league_history"

# Prefer the sheet that most resembles a draft-day consensus board.
PREFERRED_SHEETS = ("espn",)


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def _load(path: Path):
    return json.loads(path.read_text()) if path.exists() else None


def pick_ranking_sheet(payload: dict) -> dict | None:
    """The ESPN sheet for a season, falling back to whatever exists."""
    sources = payload.get("sources") or []
    for source in sources:
        if any(tag in source["sheet"].lower() for tag in PREFERRED_SHEETS):
            return source
    return sources[0] if sources else None


def analyse_season(conn, season: int, denominators: dict[str, float],
                   manager_ids: dict[str, int]) -> dict | None:
    draft = _load(HISTORY_DIR / f"drafts_{season}.json")
    resolution = _load(HISTORY_DIR / f"resolution_{season}.json")
    rankings = _load(HISTORY_DIR / f"rankings_resolution_{season}.json")
    keepers_payload = _load(HISTORY_DIR / f"keepers_{season}.json")
    if not (draft and resolution and rankings):
        return None

    sheet = pick_ranking_sheet(rankings)
    if sheet is None:
        return None

    # rank as a stand-in for ADP. Every rank in a top-300 sheet is genuine, so
    # the filler threshold is set past the sheet's own maximum.
    market = {row["mlb_id"]: float(row["rank"]) for row in sheet["rankings"]
              if row["mlb_id"] is not None and row["rank"] is not None}
    if not market:
        return None
    max_rank = max(market.values())

    ids = {r["name"]: r["mlb_id"] for r in resolution["resolutions"]
           if r["mlb_id"] is not None}
    names = {r["mlb_id"]: r["matched_name"] for r in resolution["resolutions"]
             if r["mlb_id"] is not None}

    keeper_ids = set()
    if keepers_payload:
        keeper_ids = {ids.get(k["player_name"]) for k in keepers_payload["keepers"]}
        keeper_ids.discard(None)

    def is_keeper(pick: dict, mlb_id: int) -> bool:
        return mlb_id in keeper_ids or "keeper" in (pick.get("notes") or "").lower()

    # Keepers are excluded from the residual set. A keeper's pick number is set
    # by the round he was kept at, not by what the market thought of him:
    # Gunnar Henderson was the 5th-ranked player in 2025 and appears at pick
    # 146 because that is the round Tim Riker forfeited. Left in, those
    # +141-pick residuals are read as reaches and blow up the spread in exactly
    # the band -- the top of the board -- the analysis is trying to measure.
    #
    # They still inform `keeper_ranks`, because a kept player is off the board
    # and everyone below him does move up.
    picks = []
    for pick in draft["picks"]:
        mlb_id = ids.get(pick["player_name"])
        if mlb_id is None or not pick.get("owner") or is_keeper(pick, mlb_id):
            continue
        picks.append({
            "pick_index": pick["pick_number"] - 1,
            "team_id": manager_ids[pick["owner"]],
            "mlb_id": mlb_id,
            "name": names.get(mlb_id),
        })

    keeper_ranks = [market[i] for i in keeper_ids if i in market]

    residuals = compute_residuals(picks, market, keeper_ranks,
                                  max_valid_adp=max_rank + 1)
    if len(residuals) < 30:
        return None

    buckets = sigma_by_bucket(residuals)
    team_manager = {v: k for k, v in manager_ids.items()}

    # ── market versus realized ──
    pool_h, pool_p = full_pool(conn, season, set(market))
    identities = load_identities(conn, pool_h | pool_p)
    realized = value_map(*season_board(conn, season, pool_h, pool_p,
                                       identities, denominators))
    shared = [i for i in market if i in realized]
    # Rank is better when smaller, value when larger, so negate to align them.
    market_vs_realized = spearman([-market[i] for i in shared],
                                  [realized[i] for i in shared])

    return {
        "season": season,
        "sheet": sheet["sheet"],
        "snapshot_date": sheet["snapshot_date"],
        "ranked_players": len(market),
        "non_keeper_picks_with_a_rank": len(residuals),
        "keepers_with_a_rank": len(keeper_ranks),
        "summary": sigma_summary(residuals),
        "by_adp_bucket": buckets,
        "sigma_model_comparison": compare_sigma_models(buckets),
        "linear_sigma_fit": fit_linear_sigma(buckets),
        "manager_bias": manager_bias(residuals, team_manager),
        "market_vs_realized": {
            "n": len(shared),
            "spearman": None if market_vs_realized is None
            else round(market_vs_realized, 4),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seasons", type=int, nargs="*", default=None)
    args = parser.parse_args()

    report = _load(HISTORY_DIR / "resolution_report.json")
    seasons = args.seasons or report["included_seasons"]

    # One id per manager across every season, so the per-manager aggregate is
    # about a person rather than a seat.
    everyone = set()
    for season in seasons:
        draft = _load(HISTORY_DIR / f"drafts_{season}.json")
        if draft:
            everyone |= {p["owner"] for p in draft["picks"] if p.get("owner")}
    manager_ids = {name: index + 1 for index, name in enumerate(sorted(everyone))}

    conn = get_connection()
    denominators = {k: round(v, 6)
                    for k, v in _compute_sgp_denominators(ALL_CATS).items()}

    per_season = []
    for season in seasons:
        result = analyse_season(conn, season, denominators, manager_ids)
        if result is None:
            continue
        per_season.append(result)
        print(f"  {season}  {result['sheet']:22} "
              f"{result['non_keeper_picks_with_a_rank']:>3} picks with a rank, "
              f"market vs realized rho="
              f"{result['market_vs_realized']['spearman']:+.3f}")
    conn.close()

    if not per_season:
        raise SystemExit("no season had both a draft and a ranking sheet")

    # ── pooled sigma by band ──
    pooled_buckets: dict[str, list[dict]] = {}
    for result in per_season:
        for bucket in result["by_adp_bucket"]:
            pooled_buckets.setdefault(bucket["adp_bucket"], []).append(bucket)
    sigma_by_band = [{
        "adp_bucket": band,
        "seasons": len(rows),
        "n": sum(r["n"] for r in rows),
        "mean_adp": round(statistics.mean(r["mean_adp"] for r in rows), 1),
        "mean_sigma": round(statistics.mean(r["sigma"] for r in rows), 2),
        "min_sigma": round(min(r["sigma"] for r in rows), 2),
        "max_sigma": round(max(r["sigma"] for r in rows), 2),
    } for band, rows in pooled_buckets.items()]
    sigma_by_band.sort(key=lambda r: r["mean_adp"])

    pooled_fit = fit_linear_sigma(
        [{"mean_adp": r["mean_adp"], "sigma": r["mean_sigma"], "n": r["n"]}
         for r in sigma_by_band])

    # ── pooled manager tendency ──
    by_manager: dict[str, list[dict]] = {}
    for result in per_season:
        for row in result["manager_bias"]:
            if row.get("manager"):
                by_manager.setdefault(row["manager"], []).append(
                    dict(row, season=result["season"]))
    managers = [{
        "manager": name,
        "seasons": len(rows),
        "picks": sum(r["picks"] for r in rows),
        "mean_residual": round(
            sum(r["mean_residual"] * r["picks"] for r in rows)
            / sum(r["picks"] for r in rows), 2),
        "season_spread": round(
            max(r["mean_residual"] for r in rows)
            - min(r["mean_residual"] for r in rows), 2),
        "by_season": [{"season": r["season"], "picks": r["picks"],
                       "mean_residual": round(r["mean_residual"], 2)}
                      for r in sorted(rows, key=lambda x: x["season"])],
    } for name, rows in by_manager.items() if sum(r["picks"] for r in rows) >= 40]
    managers.sort(key=lambda m: m["mean_residual"])

    # Does manager identity explain more than the season does? If a manager
    # swings as much year to year as managers differ from each other, a
    # single-season tendency is not a usable input to an opponent model.
    between_manager = (max(m["mean_residual"] for m in managers)
                       - min(m["mean_residual"] for m in managers)) if managers else 0.0
    within_manager = (statistics.mean(m["season_spread"] for m in managers)
                      if managers else 0.0)
    stability = {
        "between_manager_spread": round(between_manager, 2),
        "mean_within_manager_season_spread": round(within_manager, 2),
        "ratio_within_over_between": round(within_manager / between_manager, 2)
        if between_manager else None,
        "separable": between_manager > within_manager,
    }

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "manager_tendency_stability": stability,
        "seasons": [r["season"] for r in per_season],
        "method": {
            "market": "ESPN preseason rank as a stand-in for draft-day ADP; "
                      "every rank in a top-300 sheet is genuine, so the "
                      "synthetic-tail filter used on ADP exports is disabled",
            "board_vs_market": "NOT computed — no projection board exists "
                               "before 2026. `market_vs_realized` answers the "
                               "answerable question instead.",
        },
        "market_vs_realized": [
            {"season": r["season"], **r["market_vs_realized"]} for r in per_season],
        "sigma_by_band_pooled": sigma_by_band,
        "pooled_linear_sigma_fit": pooled_fit,
        "manager_tendency_pooled": managers,
        "by_season": per_season,
    }
    _write_json(HISTORY_DIR / "market_analysis.json", payload)

    print(f"\nResidual spread by band, pooled over {len(per_season)} seasons")
    print(f"  {'band':>10} {'seasons':>8} {'n':>5} {'mean adp':>9} "
          f"{'sigma':>7} {'min':>7} {'max':>7}")
    for row in sigma_by_band:
        print(f"  {row['adp_bucket']:>10} {row['seasons']:>8} {row['n']:>5} "
              f"{row['mean_adp']:>9.1f} {row['mean_sigma']:>7.2f} "
              f"{row['min_sigma']:>7.2f} {row['max_sigma']:>7.2f}")
    if pooled_fit:
        print(f"\n  pooled fit: sigma = {pooled_fit['intercept']:.2f} "
              f"+ {pooled_fit['slope']:.4f} * adp")
        print(f"  2026 finding: sigma = 6.55 + 0.1580 * adp")

    print(f"\nBest-fitting sigma model per season:")
    for result in per_season:
        models = result["sigma_model_comparison"]
        print(f"  {result['season']}  {models['best']:<12} "
              + "  ".join(f"{k}={v:.2f}" for k, v in models["mean_abs_error"].items()))

    print(f"\nManager reach/wait, pooled (negative = drafts earlier than the "
          f"market expects):")
    for row in managers:
        print(f"  {row['manager']:<16} n={row['picks']:>4} "
              f"seasons={row['seasons']}  mean={row['mean_residual']:+7.2f}  "
              f"season spread={row['season_spread']:6.2f}")
    print(f"\n  between-manager spread:        {stability['between_manager_spread']:6.2f} picks")
    print(f"  mean within-manager spread:    "
          f"{stability['mean_within_manager_season_spread']:6.2f} picks")
    print(f"  -> manager identity is "
          f"{'separable from' if stability['separable'] else 'NOT separable from'}"
          f" season-to-season noise")

    print(f"\nWritten to {HISTORY_DIR / 'market_analysis.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
