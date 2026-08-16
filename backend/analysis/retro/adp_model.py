"""Layer C: how well does ADP predict when a player actually goes?

The draft board and the simulator disagree about this and always have. The
board uses a variable sigma that grows with ADP (pick-predictor.ts:55:
`6 + adp/250 * 6`), while backend/simulation/config.py ships a flat
ADP_SIGMA = 18.0 with USE_VARIABLE_SIGMA = False. SCORING_IMPROVEMENTS.md §6
rejected variable sigma on simulation evidence, but neither setting has ever
been checked against a real draft. A completed 250-pick draft settles it.

The keeper adjustment matters more than the sigma. Forty players are off the
board before it opens, so everyone else is drafted earlier than their redraft
ADP suggests — in 2026, by 26 to 70 picks depending on the team. Any residual
computed against raw ADP measures that shift, not the model's error.

Pure functions.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass


def count_kept_below(adp: float, sorted_keeper_adps: list[float]) -> int:
    """How many keepers have an ADP at or above this player on the board.

    Port of count_kept_below_adp / the keeper adjustment in pick-predictor.ts.
    Each such keeper is a player who will not be drafted, so the player in
    question moves up one slot in expectation.
    """
    return bisect.bisect_right(sorted_keeper_adps, adp)


def effective_adp(adp: float, sorted_keeper_adps: list[float]) -> float:
    """Redraft ADP shifted for the keepers removed from the pool."""
    return adp - count_kept_below(adp, sorted_keeper_adps)


@dataclass(frozen=True)
class Residual:
    mlb_id: int
    name: str | None
    team_id: int
    pick_number: int          # 1-indexed
    adp: float
    effective_adp: float
    raw_residual: float       # pick - adp
    residual: float           # pick - effective_adp


# ESPN pads its export with a synthetic tail for players it does not expect to
# be drafted — 260.0 for over a thousand players, then 259.9, 259.8 and so on.
# Those are placeholders, not draft positions, and including them would put
# pure noise into the calibration.
FILLER_ADP_THRESHOLD = 259.0


def compute_residuals(picks: list[dict], adp: dict[int, float],
                      keeper_adps: list[float],
                      max_valid_adp: float = FILLER_ADP_THRESHOLD) -> list[Residual]:
    """One residual per drafted pick that has a genuine draft-day ADP.

    `picks` are the replay rows: {pick_index, team_id, mlb_id, name}.
    """
    sorted_keepers = sorted(a for a in keeper_adps if a < max_valid_adp)
    out = []
    for pick in picks:
        value = adp.get(pick["mlb_id"])
        if value is None or value >= max_valid_adp:
            continue
        pick_number = pick["pick_index"] + 1
        adjusted = effective_adp(value, sorted_keepers)
        out.append(Residual(
            mlb_id=pick["mlb_id"],
            name=pick.get("name"),
            team_id=pick["team_id"],
            pick_number=pick_number,
            adp=value,
            effective_adp=adjusted,
            raw_residual=pick_number - value,
            residual=pick_number - adjusted,
        ))
    return out


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _stddev(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = _mean(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1))


def sigma_summary(residuals: list[Residual]) -> dict:
    """Overall bias and spread, on both raw and keeper-adjusted residuals."""
    raw = [r.raw_residual for r in residuals]
    adjusted = [r.residual for r in residuals]
    return {
        "n": len(residuals),
        "raw": {"mean": round(_mean(raw), 2), "sigma": round(_stddev(raw), 2)},
        "keeper_adjusted": {"mean": round(_mean(adjusted), 2),
                            "sigma": round(_stddev(adjusted), 2)},
    }


def sigma_by_bucket(residuals: list[Residual],
                    edges: tuple[float, ...] = (50, 100, 150, 200)) -> list[dict]:
    """Residual spread by ADP band — the test of a constant sigma.

    A flat sigma predicts the same spread in every band; a variable sigma
    predicts it growing with ADP.
    """
    buckets: dict[str, list[Residual]] = {}
    for residual in residuals:
        label = f"{int(edges[-1])}+"
        low = 0.0
        for edge in edges:
            if residual.adp < edge:
                label = f"{int(low)}-{int(edge)}"
                break
            low = edge
        buckets.setdefault(label, []).append(residual)

    def sort_key(label: str) -> float:
        return float(label.split("-")[0].rstrip("+"))

    return [
        {
            "adp_bucket": label,
            "n": len(group),
            "mean_adp": round(_mean([r.adp for r in group]), 1),
            "mean_residual": round(_mean([r.residual for r in group]), 2),
            "sigma": round(_stddev([r.residual for r in group]), 2),
        }
        for label, group in sorted(buckets.items(), key=lambda kv: sort_key(kv[0]))
    ]


def compare_sigma_models(buckets: list[dict]) -> dict:
    """Score every sigma model the codebase has ever used against reality.

    flat_18      — ADP_SIGMA in backend/simulation/config.py, the shipped default.
    variable_ts  — `6 + adp/250 * 6` in src/lib/pick-predictor.ts, what the live
                   draft board actually uses.
    variable_py  — `10 + 0.1 * adp` in scoring_model.variable_adp_sigma, which
                   SCORING_IMPROVEMENTS.md section 6 rejected on simulation
                   evidence and left switched off.

    Lower mean absolute error wins. This is the evidence that settles a
    disagreement the two implementations have carried for months.
    """
    flat_sigma = 18.0
    errors: dict[str, list[float]] = {
        "flat_18": [], "variable_ts": [], "variable_py": []}
    rows = []
    for bucket in buckets:
        measured = bucket["sigma"]
        adp = bucket["mean_adp"]
        variable_ts = 6 + (max(1.0, adp) / 250) * 6
        variable_py = 10.0 + 0.1 * adp
        errors["flat_18"].append(abs(measured - flat_sigma))
        errors["variable_ts"].append(abs(measured - variable_ts))
        errors["variable_py"].append(abs(measured - variable_py))
        rows.append({
            "adp_bucket": bucket["adp_bucket"],
            "measured_sigma": measured,
            "flat_18": flat_sigma,
            "variable_ts": round(variable_ts, 2),
            "variable_py": round(variable_py, 2),
        })
    return {
        "per_bucket": rows,
        "mean_abs_error": {
            model: round(_mean(values), 3) for model, values in errors.items()
        },
        "best": min(errors, key=lambda m: _mean(errors[m])),
    }


def fit_linear_sigma(buckets: list[dict]) -> dict | None:
    """Least-squares fit of sigma = intercept + slope x ADP across buckets."""
    points = [(b["mean_adp"], b["sigma"]) for b in buckets if b["n"] >= 5]
    if len(points) < 2:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    mean_x, mean_y = _mean(xs), _mean(ys)
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom == 0:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in points) / denom
    return {
        "intercept": round(mean_y - slope * mean_x, 3),
        "slope": round(slope, 5),
        "note": "sigma = intercept + slope * adp, fitted on bucket sigmas",
    }


def manager_bias(residuals: list[Residual],
                 team_manager: dict[int, str] | None = None) -> list[dict]:
    """Per-manager reach/wait tendency.

    A negative mean residual means the manager consistently drafts players
    before the field expects — a reacher. This is the measurable version of the
    hand-curated MANAGER_PROFILES in src/lib/draft-history.ts, and it is what
    the simulator's opponent model (draft_engine._opponent_pick) should be
    calibrated against.
    """
    by_team: dict[int, list[Residual]] = {}
    for residual in residuals:
        by_team.setdefault(residual.team_id, []).append(residual)

    return [
        {
            "team_id": team_id,
            "manager": (team_manager or {}).get(team_id),
            "picks": len(group),
            "mean_residual": round(_mean([r.residual for r in group]), 2),
            "sigma": round(_stddev([r.residual for r in group]), 2),
            "biggest_reach": min(
                ({"name": r.name, "residual": round(r.residual, 1)} for r in group),
                key=lambda d: d["residual"], default=None),
        }
        for team_id, group in sorted(by_team.items())
    ]
