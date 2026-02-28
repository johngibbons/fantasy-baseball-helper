"""FastAPI application — Fantasy Baseball valuation API."""

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.api.routes import router
from backend.database import init_db, get_connection
from backend.data.projections import generate_projections_from_stats, import_adp_from_csv, import_adp_from_api, fetch_all_fangraphs_projections, import_espn_adp
from backend.data.statcast_adjustments import apply_statcast_adjustments
from backend.analysis.zscores import calculate_all_zscores
from backend.data.sync import import_csv_projections
from backend.data.seed_draft_order import seed_draft_state

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Fantasy Baseball Valuations API",
    description="Z-score based player valuations for H2H Categories fantasy baseball",
    version="1.0.0",
)

_origins = ["http://localhost:3000", "http://localhost:3001"]
if os.environ.get("FRONTEND_URL"):
    _origins.append(os.environ["FRONTEND_URL"])

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")

_SEASON = int(os.environ.get("SEASON", "2026"))


@app.on_event("startup")
def startup():
    init_db()

    # Recalculate rankings on every deploy so model changes take effect
    # immediately.  Only runs if the DB has player/stats data to work with.
    conn = get_connection()
    player_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM players WHERE is_active = 1"
    ).fetchone()["cnt"]
    conn.close()

    if player_count == 0:
        logger.info("No players in DB — skipping startup recalculation")
        return

    logger.info(f"Startup recalculation for season {_SEASON} ({player_count} active players)")

    # Try FanGraphs API first, fall back to CSVs
    fg_total = 0
    fg_adp_map = {}
    try:
        fg_results = fetch_all_fangraphs_projections(_SEASON)
        fg_adp_map = fg_results.pop("_adp_map", {})
        fg_total = sum(fg_results.values())
        if fg_total > 0:
            logger.info(f"Imported {fg_total} projections from FanGraphs API")
    except Exception as e:
        logger.warning(f"FanGraphs API fetch failed (non-fatal): {e}")

    # Always import CSVs as supplementary data — they include prospects
    # (e.g. Steamer, ZiPS, THE BAT X) that ATC may not cover.
    try:
        import_csv_projections(_SEASON)
    except Exception as e:
        logger.warning(f"CSV projection import failed (non-fatal): {e}")

    try:
        generate_projections_from_stats(_SEASON)
    except Exception as e:
        logger.warning(f"Trend projection generation failed (non-fatal): {e}")

    try:
        apply_statcast_adjustments(_SEASON)
    except Exception as e:
        logger.warning(f"Statcast adjustments failed (non-fatal): {e}")

    try:
        calculate_all_zscores(_SEASON)
    except Exception as e:
        logger.error(f"Z-score calculation failed: {e}")

    if fg_adp_map:
        try:
            adp_count = import_adp_from_api(fg_adp_map, _SEASON)
            logger.info(f"Imported ADP for {adp_count} players from FanGraphs API")
        except Exception as e:
            logger.warning(f"API ADP import failed (non-fatal): {e}")
    else:
        try:
            import_adp_from_csv(season=_SEASON)
        except Exception as e:
            logger.warning(f"CSV ADP import failed (non-fatal): {e}")

    # ESPN ADP overwrites FanGraphs ADP (ESPN is authoritative for our league)
    try:
        espn_adp_count = import_espn_adp(_SEASON)
        logger.info(f"Imported ESPN ADP for {espn_adp_count} players")
    except Exception as e:
        logger.warning(f"ESPN ADP import failed (non-fatal): {e}")

    logger.info("Startup recalculation complete")

    # Seed draft order and keepers (skips if draft already in progress)
    try:
        seed_draft_state()
    except Exception as e:
        logger.warning(f"Draft state seeding failed (non-fatal): {e}")


@app.get("/health")
def health():
    return {"status": "ok"}
