"""Daily breakout-finder sync orchestrator.

Run this at 03:00 ET daily, before the 04:00 ET ESPN waiver run, to refresh:
  1. rolling_batting_stats / rolling_pitching_stats (7/14/30 day windows)
  2. statcast_batting / statcast_pitching (current season)
  3. statcast_baselines (deltas + composites)

Each step is idempotent. Failures in one step don't block the others.

Usage:
    python -m backend.scripts.daily_breakout_sync --season 2026
"""

from __future__ import annotations

import argparse
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--skip-rolling", action="store_true")
    parser.add_argument("--skip-statcast", action="store_true")
    parser.add_argument("--skip-baselines", action="store_true")
    args = parser.parse_args()

    failures = 0

    if not args.skip_rolling:
        try:
            from backend.data.rolling_stats import sync_rolling_stats
            logger.info("Step 1/3: rolling stats")
            sync_rolling_stats(season=args.season)
        except Exception as e:
            logger.error(f"Rolling stats sync failed: {e}", exc_info=True)
            failures += 1

    if not args.skip_statcast:
        try:
            from backend.data.statcast import sync_statcast_data
            logger.info("Step 2/3: current-season Statcast")
            sync_statcast_data(season=args.season)
        except Exception as e:
            logger.error(f"Statcast sync failed: {e}", exc_info=True)
            failures += 1

    if not args.skip_baselines:
        try:
            from backend.analysis.skill_baselines import compute_skill_baselines
            logger.info("Step 3/3: skill baselines")
            compute_skill_baselines(season=args.season)
        except Exception as e:
            logger.error(f"Skill baselines compute failed: {e}", exc_info=True)
            failures += 1

    if failures:
        logger.error(f"{failures} step(s) failed")
        return 1
    logger.info("Daily breakout sync complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
