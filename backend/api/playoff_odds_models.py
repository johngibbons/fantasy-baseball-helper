# backend/api/playoff_odds_models.py
"""Pydantic models for the playoff odds endpoint."""

from __future__ import annotations

from pydantic import BaseModel
from typing import Optional


class RosterPlayer(BaseModel):
    """A single roster entry as sent from the TS layer."""
    name: str
    position: str  # ESPN default position abbrev (e.g. "OF", "SP")
    player_type: str  # "hitter" or "pitcher"
    lineup_slot_id: int  # 0-15 active, 16 BE, 17+ IL
    eligible_positions: str  # slash-separated, e.g. "OF/UTIL"
    injury_status: str = "ACTIVE"


class TeamPayload(BaseModel):
    team_id: int
    team_name: str
    roster: list[RosterPlayer]
    current_wins: int = 0
    current_losses: int = 0
    current_ties: int = 0


class MatchupPair(BaseModel):
    matchup_period_id: int
    home_team_id: int
    away_team_id: int


class PlayoffOddsRequest(BaseModel):
    season: int
    teams: list[TeamPayload]
    remaining_schedule: list[MatchupPair]
    # Per-period weight (period_days / sum_remaining_days). Same length and order
    # as remaining_schedule's distinct period IDs (smallest first).
    period_weights: dict[int, float]
    playoff_slots: int = 6
    n_trials: int = 5000
    seed: Optional[int] = None


class TeamOdds(BaseModel):
    team_id: int
    team_name: str
    current_wins: int
    current_losses: int
    current_ties: int
    playoff_odds: float  # 0.0–1.0
    avg_final_wins: float
    avg_final_losses: float
    avg_final_ties: float
    avg_final_rank: float


class PlayoffOddsResponse(BaseModel):
    teams: list[TeamOdds]  # sorted by playoff_odds desc
    n_trials: int
    matched_player_count: int
    unmatched_player_names: list[str]
