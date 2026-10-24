"""Fetch historical ESPN H2H category league weekly results.

Used by the σ calibration script to gather every team-week's category totals
for variance estimation, and by the retrospective for each team's weekly
category results and final standings.
"""

from __future__ import annotations

import json
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field


ESPN_STAT_ID_TO_CAT: dict[str, str] = {
    "20": "R",  "8": "TB", "21": "RBI", "23": "SB", "17": "OBP",
    "48": "K",  "63": "QS", "47": "ERA", "41": "WHIP", "83": "SVHD",
}


# Matchups outside the regular season carry a bracket name here instead; only
# some teams play them, so they are left out of per-team rates.
REGULAR_SEASON_TIER = "NONE"

RESULT_POINTS: dict[str, float] = {"WIN": 1.0, "TIE": 0.5, "LOSS": 0.0}


@dataclass
class MatchupRecord:
    """One team-side observation for one matchup period."""
    team_id: int
    matchup_period_id: int
    period_days: int
    cats: dict[str, float] = field(default_factory=dict)


def parse_matchup_response(response: dict) -> list[MatchupRecord]:
    """Extract MatchupRecord per home/away side from an ESPN mMatchup response."""
    out: list[MatchupRecord] = []
    for m in response.get("schedule", []):
        period_id = m.get("matchupPeriodId")
        if period_id is None:
            continue
        for side_key in ("home", "away"):
            side = m.get(side_key)
            if not side:
                continue
            cum = side.get("cumulativeScore") or {}
            score_by_stat = cum.get("scoreByStat") or {}
            if not score_by_stat:
                continue  # future or in-progress matchup
            cats: dict[str, float] = {}
            for stat_id, cat_name in ESPN_STAT_ID_TO_CAT.items():
                score_obj = score_by_stat.get(stat_id) or {}
                cats[cat_name] = float(score_obj.get("score", 0.0))
            period_days = len(side.get("pointsByScoringPeriod") or {})
            out.append(MatchupRecord(
                team_id=side["teamId"],
                matchup_period_id=period_id,
                period_days=period_days,
                cats=cats,
            ))
    return out


def parse_category_win_rates(response: dict) -> dict[int, dict[str, float]]:
    """Each team's share of regular-season weekly matchups won, per category.

    A tie counts half, so every category averages exactly 0.5 across the
    league. A matchup is skipped unless every category has a result.
    """
    points: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    played: dict[int, int] = defaultdict(int)
    for m in response.get("schedule", []):
        if m.get("playoffTierType", REGULAR_SEASON_TIER) != REGULAR_SEASON_TIER:
            continue
        for side_key in ("home", "away"):
            side = m.get(side_key)
            if not side:
                continue
            score_by_stat = (side.get("cumulativeScore") or {}).get("scoreByStat") or {}
            results = {
                cat: (score_by_stat.get(stat_id) or {}).get("result")
                for stat_id, cat in ESPN_STAT_ID_TO_CAT.items()
            }
            if not all(result in RESULT_POINTS for result in results.values()):
                continue  # future or in-progress matchup
            played[side["teamId"]] += 1
            for cat, result in results.items():
                points[side["teamId"]][cat] += RESULT_POINTS[result]
    return {
        team_id: {cat: points[team_id][cat] / games
                  for cat in ESPN_STAT_ID_TO_CAT.values()}
        for team_id, games in played.items()
    }


def parse_standings(response: dict) -> list[dict]:
    """Regular-season category record, playoff seed and final rank per team.

    In an H2H categories league the record counts categories, not matchups:
    one week contributes ten decisions.
    """
    out = []
    for team in response.get("teams", []):
        record = (team.get("record") or {}).get("overall") or {}
        out.append({
            "team_id": team["id"],
            "wins": record.get("wins"),
            "losses": record.get("losses"),
            "ties": record.get("ties"),
            "playoff_seed": team.get("playoffSeed"),
            "final_rank": team.get("rankCalculatedFinal"),
        })
    return sorted(out, key=lambda row: (row["final_rank"] is None,
                                        row["final_rank"], row["team_id"]))


def fetch_league_views(
    league_id: str,
    season: int,
    swid: str,
    espn_s2: str,
    views: tuple[str, ...],
) -> dict:
    """One league request carrying the given ESPN views."""
    query = "&".join(f"view={view}" for view in views)
    # scoringPeriodId=7 is arbitrary — empirically ESPN returns full season data
    # regardless of which scoring period is requested, as long as data exists.
    url = (
        f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb/seasons/"
        f"{season}/segments/0/leagues/{league_id}?{query}&scoringPeriodId=7"
    )
    req = urllib.request.Request(
        url,
        headers={
            "Cookie": f"swid={swid}; espn_s2={espn_s2}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def fetch_season_matchup_history(
    league_id: str,
    season: int,
    swid: str,
    espn_s2: str,
) -> list[MatchupRecord]:
    """Fetch all completed matchups for one season's H2H league.

    A single ESPN call with `view=mMatchup&scoringPeriodId=N` returns the
    complete season schedule with `cumulativeScore.scoreByStat` populated
    for every completed matchup period (any positive scoringPeriodId works
    once the season has data).
    """
    return parse_matchup_response(fetch_league_views(
        league_id, season, swid, espn_s2, views=("mMatchup",)))
