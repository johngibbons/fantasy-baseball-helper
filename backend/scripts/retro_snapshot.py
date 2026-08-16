"""Freeze the irreplaceable inputs for the season retrospective.

Usage:
    python3 -m backend.scripts.retro_snapshot --season 2026

Captures, into backend/data/fixtures/retro_<season>/:
  1. draft_state_<season>.json  — the completed draft from production. This
     lives in ONE overwritable Postgres row (draft_state.state_json); if the
     board is ever re-seeded it is gone. Highest-value artifact here.
  2. adp_draftday_<season>.json — draft-day ESPN ADP resolved to mlb_ids, with
     explicit unmatched/ambiguous lists. rankings.espn_adp has since drifted to
     live in-season ADP, so the CSV export is the only draft-day record.
  3. rankings_prod_<date>.json  — current production board. NOT preseason (that
     was overwritten by rest-of-season refreshes), but it will be stale in a
     month, so snapshot it while it exists.
  4. manifest.json             — git sha, timestamps, row counts, source URLs.

Read-only against production; writes only into the fixture directory.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from backend.analysis.retro.adp_import import (
    PlayerRow,
    coverage_summary,
    parse_adp_csv,
    resolve_adp_entries,
)
from backend.database import get_connection

DEFAULT_APP_URL = "https://fantasy-baseball-helper-production.up.railway.app"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Sanity floors for the 2026 draft — a 10-team, 25-round draft with keepers.
# If production ever returns a re-seeded (pre-draft) state these catch it
# instead of silently overwriting a good fixture with an empty board.
MIN_PICKS = 200
MIN_PICKLOG = 100


def _http_get_json(url: str, timeout: int = 60) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "retro-snapshot/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _git_sha() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT, capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def fetch_draft_state(app_url: str, season: int) -> dict:
    """Pull the completed draft from production and assert it is complete."""
    url = f"{app_url}/api/v2/draft/state?season={season}"
    payload = _http_get_json(url)
    state = payload.get("state", payload)

    picks = state.get("picks") or []
    pick_log = state.get("pickLog") or []
    if len(picks) < MIN_PICKS or len(pick_log) < MIN_PICKLOG:
        raise SystemExit(
            f"Refusing to snapshot: draft state looks incomplete "
            f"({len(picks)} picks, {len(pick_log)} pickLog entries). "
            f"Expected >= {MIN_PICKS} / {MIN_PICKLOG}. Source: {url}"
        )
    return state


def load_player_rows(season: int) -> list[PlayerRow]:
    """Players joined to their rankings, for ADP name disambiguation."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT p.mlb_id, p.full_name, p.player_type, p.is_active,
                      r.overall_rank
               FROM players p
               LEFT JOIN rankings r ON p.mlb_id = r.mlb_id AND r.season = ?""",
            (season,),
        ).fetchall()
    finally:
        conn.close()

    return [
        PlayerRow(
            mlb_id=r["mlb_id"],
            full_name=r["full_name"],
            player_type=r["player_type"],
            overall_rank=r["overall_rank"],
            is_active=bool(r["is_active"]),
        )
        for r in rows
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--app-url", default=DEFAULT_APP_URL)
    parser.add_argument(
        "--adp-csv",
        type=Path,
        default=REPO_ROOT / "espn_adp_500.csv",
        help="Draft-day ESPN ADP export (default: espn_adp_500.csv at repo root)",
    )
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--skip-remote",
        action="store_true",
        help="Skip production fetches; resolve ADP only.",
    )
    parser.add_argument(
        "--create-label",
        default=None,
        help="Take a named snapshot of the current board instead of capturing "
             "fixtures. Run this on draft day, e.g. --create-label preseason-2027.",
    )
    args = parser.parse_args()

    if args.create_label:
        from backend.analysis.snapshots import create_snapshot, is_auto

        if is_auto(args.create_label):
            raise SystemExit("Labels starting with 'auto-' are reserved for "
                             "automatic pre-refresh snapshots, which get pruned.")
        result = create_snapshot(args.create_label, args.season, kind="manual",
                                 note="draft-day snapshot")
        if result.get("created"):
            print(f"Snapshot {args.create_label}: {result['row_counts']}")
        else:
            print(f"Snapshot {args.create_label} already exists — left untouched.")
        return 0

    out_dir = args.out or (
        REPO_ROOT / "backend" / "data" / "fixtures" / f"retro_{args.season}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    # Local date, to agree with the SEASON_START/SEASON_END convention the rest
    # of the harness uses for season-elapsed fraction.
    as_of = datetime.now().strftime("%Y-%m-%d")

    manifest: dict = {
        "as_of": as_of,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "season": args.season,
        "git_sha": _git_sha(),
        "app_url": args.app_url,
        "artifacts": {},
    }

    # ── 1. The completed draft ──
    draft_pick_count = 250  # fallback when --skip-remote
    if not args.skip_remote:
        print(f"Fetching draft state for {args.season}...")
        state = fetch_draft_state(args.app_url, args.season)
        draft_pick_count = len(state.get("picks") or [])
        path = out_dir / f"draft_state_{args.season}.json"
        _write_json(path, state)
        counts = {
            "picks": len(state.get("picks") or []),
            "pickLog": len(state.get("pickLog") or []),
            "keeperMlbIds": len(state.get("keeperMlbIds") or []),
            "pickTrades": len(state.get("pickTrades") or []),
            "draftOrder": len(state.get("draftOrder") or []),
            "myTeamId": state.get("myTeamId"),
        }
        manifest["artifacts"][path.name] = counts
        print(f"  {counts['picks']} picks, {counts['pickLog']} logged picks, "
              f"{counts['keeperMlbIds']} keepers -> {path.name}")

    # ── 2. Draft-day ADP ──
    print(f"Resolving draft-day ADP from {args.adp_csv.name}...")
    entries = parse_adp_csv(args.adp_csv.read_text())
    players = load_player_rows(args.season)
    resolution = resolve_adp_entries(entries, players)
    coverage = coverage_summary(entries, resolution, adp_cutoff=float(draft_pick_count))

    adp_path = out_dir / f"adp_draftday_{args.season}.json"
    _write_json(adp_path, {
        "source_csv": args.adp_csv.name,
        "entry_count": len(entries),
        "matched_count": len(resolution.matched),
        "coverage": coverage,
        "adp_by_mlb_id": {str(k): v for k, v in resolution.matched.items()},
        "details": resolution.details,
        "unmatched": resolution.unmatched,
        "ambiguous": resolution.ambiguous,
    })
    manifest["artifacts"][adp_path.name] = {
        "entries": len(entries),
        "matched": len(resolution.matched),
        "unmatched": len(resolution.unmatched),
        "ambiguous": len(resolution.ambiguous),
        "coverage": coverage,
    }
    print(f"  {len(entries)} rows -> {len(resolution.matched)} matched, "
          f"{len(resolution.unmatched)} unmatched, "
          f"{len(resolution.ambiguous)} ambiguous -> {adp_path.name}")
    print(f"  Within the drafted range (ADP < {draft_pick_count}): "
          f"{coverage['entries_in_range']} rows, "
          f"{coverage['unmatched_in_range']} unmatched")

    # ── 3. Current production board (not preseason, but perishable) ──
    if not args.skip_remote:
        print("Fetching current production rankings...")
        try:
            rankings = _http_get_json(f"{args.app_url}/api/v2/rankings?limit=2000")
            path = out_dir / f"rankings_prod_{as_of}.json"
            _write_json(path, rankings)
            n = len(rankings.get("rankings") or [])
            manifest["artifacts"][path.name] = {"rows": n}
            print(f"  {n} ranking rows -> {path.name}")
        except Exception as exc:  # non-fatal: this one is a nice-to-have
            print(f"  WARNING: rankings snapshot failed ({exc}); continuing.")
            manifest["artifacts"]["rankings_prod"] = {"error": str(exc)}

    _write_json(out_dir / "manifest.json", manifest)
    print(f"\nManifest written: {out_dir / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
