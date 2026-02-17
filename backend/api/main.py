"""FastAPI application — Fantasy Baseball valuation API."""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.api.routes import router
from backend.database import init_db

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


@app.on_event("startup")
def startup():
    init_db()


@app.get("/health")
def health():
    return {"status": "ok"}
