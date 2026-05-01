"""Fetch historical ESPN H2H category league weekly results.

Used by the σ calibration script to gather every team-week's category totals
for variance estimation.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass, field


ESPN_STAT_ID_TO_CAT: dict[str, str] = {
    "20": "R",  "8": "TB", "21": "RBI", "23": "SB", "17": "OBP",
    "48": "K",  "63": "QS", "47": "ERA", "41": "WHIP", "83": "SVHD",
}


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
    # scoringPeriodId=7 is arbitrary — empirically ESPN returns full season data
    # regardless of which scoring period is requested, as long as data exists.
    url = (
        f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb/seasons/"
        f"{season}/segments/0/leagues/{league_id}?view=mMatchup&scoringPeriodId=7"
    )
    req = urllib.request.Request(
        url,
        headers={
            "Cookie": f"swid={swid}; espn_s2={espn_s2}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
    return parse_matchup_response(data)
