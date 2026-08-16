"""Run the whole season retrospective in order.

Usage:
    # after the regular season ends
    python3 -m backend.scripts.retro_all --season 2026 --refresh-actuals

    # re-run the analysis on actuals already in the database
    python3 -m backend.scripts.retro_all --season 2026

Every stage writes into backend/data/fixtures/retro_<season>/ and every
artifact carries the same header (as_of, season_elapsed_fraction, git sha), so
an August run and a September run differ only in their numbers — never in
their shape.

Stage 0 (freezing the draft state and draft-day ADP) is deliberately not part
of this: it captures production state that should be committed once and then
left alone. Run backend.scripts.retro_snapshot for that.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

STAGES = [
    ("expost", "backend.scripts.retro_expost",
     "ex-post values + reconstructed preseason board"),
    ("valuation", "backend.scripts.retro_valuation",
     "Layer A — valuation accuracy, attribution, ablations"),
    ("draft", "backend.scripts.retro_draft",
     "Layer B — per-pick regret and counterfactuals"),
    ("keepers", "backend.scripts.retro_keepers_adp",
     "Layer C — ADP calibration, value-at-pick, keepers"),
    ("sources", "backend.scripts.retro_sources",
     "Layer D — projection source accuracy"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--refresh-actuals", action="store_true",
                        help="Re-pull season actuals from MLB Stats API first")
    parser.add_argument("--source", default="thebatx",
                        help="Preseason projection source (default: thebatx)")
    parser.add_argument("--only", nargs="*", default=None,
                        help=f"Run only these stages: {[s[0] for s in STAGES]}")
    args = parser.parse_args()

    stages = [s for s in STAGES if not args.only or s[0] in args.only]
    if not stages:
        raise SystemExit(f"No stages matched {args.only}")

    for index, (name, module, description) in enumerate(stages, start=1):
        command = [sys.executable, "-m", module, "--season", str(args.season)]
        if name == "expost":
            if args.refresh_actuals:
                command.append("--refresh-actuals")
            if args.as_of:
                command += ["--as-of", args.as_of]
        # Layer D scores every source against the same objective, so it has no
        # single preseason source to be told about.
        if name in ("expost", "valuation"):
            command += ["--source", args.source]

        print(f"\n{'=' * 72}\n[{index}/{len(stages)}] {name} — {description}\n"
              f"{'=' * 72}")
        result = subprocess.run(command, cwd=REPO_ROOT)
        if result.returncode != 0:
            print(f"\nStage '{name}' failed ({result.returncode}); stopping. "
                  f"Later stages read its artifacts, so their output would be "
                  f"stale rather than wrong-and-obvious.")
            return result.returncode

    out_dir = REPO_ROOT / "backend" / "data" / "fixtures" / f"retro_{args.season}"
    print(f"\n{'=' * 72}\nAll stages complete. Artifacts in {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
