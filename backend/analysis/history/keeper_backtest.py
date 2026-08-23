"""Phase 3: keeper outcomes across every season, not just 2026.

The 2026 retrospective validated the keeper model on 40 decisions. This module
runs the same evaluation over every season the workbook covers, which takes the
sample to roughly 320. It needs no projections at all — a keeper decision is
judged against what that round actually returned — so there is no lookahead
risk here of the kind that makes Phase 6 dangerous.

Three things need saying about method, because each changes what the numbers
mean.

**There is no preseason board before 2026.** The app did not exist, and no
archived projections do either. So the "did the model say keep?" question
cannot be asked of those seasons. What can be asked is whether a *decision-time
baseline* predicted the outcome, and the honest baseline is the player's
production the previous season — the thing every manager in the league actually
had in front of them in February. Every field named `prior_*` in the output is
that baseline. It is not the app's board, and it must never be reported as
though it were.

**A keeper's alternative is not another keeper.** The value-at-pick curve is
what a round returned, and keepers sit inside those rounds. Judging a keeper
against a round average that includes keepers compares them partly to
themselves. So the curve is computed twice, and the keeper comparison uses the
non-keeper curve: what a manager would have got by letting the player go and
drafting that round normally.

**Value is pool-relative.** Each season's board is computed over that season's
250 drafted players with pinned, shared denominators, so replacement level is
constructed identically every year and the seasons are comparable.

Pure functions.
"""

from __future__ import annotations

import numpy as np

from backend.analysis.retro.keeper_eval import NUM_TEAMS, keeper_cost


def pick_index_for_round(round_number: int | None,
                         teams: int = NUM_TEAMS) -> int | None:
    """A synthetic pick index that buckets back into the sheet's own round.

    `value_at_pick_curve` derives the round as `pick_index // teams + 1`, so
    feeding it `(round - 1) * teams` reproduces the round the spreadsheet
    recorded. That matters because rounds are not reliably ten picks wide once
    traded picks and supplemental rounds are in play — deriving the round from
    a running pick count would smear picks across round boundaries.
    """
    if round_number is None or round_number < 1:
        return None
    return (round_number - 1) * teams


def bootstrap_mean_ci(values: list[float], iterations: int = 2000,
                      alpha: float = 0.05, seed: int = 42
                      ) -> tuple[float | None, float | None]:
    """Percentile bootstrap CI for a mean."""
    if len(values) < 5:
        return (None, None)
    rng = np.random.default_rng(seed)
    array = np.asarray(values, dtype=float)
    means = array[rng.integers(0, len(array), (iterations, len(array)))].mean(axis=1)
    return (float(np.percentile(means, 100 * alpha / 2)),
            float(np.percentile(means, 100 * (1 - alpha / 2))))


def bootstrap_proportion_ci(successes: int, total: int, iterations: int = 2000,
                            alpha: float = 0.05, seed: int = 42
                            ) -> tuple[float | None, float | None]:
    """Percentile bootstrap CI for a hit rate.

    Reported alongside every rate in this analysis, because the whole point of
    the exercise is that 70% on n=40 was not distinguishable from a coin flip.
    """
    if total < 5:
        return (None, None)
    rng = np.random.default_rng(seed)
    draws = rng.binomial(total, successes / total, iterations) / total
    return (float(np.percentile(draws, 100 * alpha / 2)),
            float(np.percentile(draws, 100 * (1 - alpha / 2))))


def surplus_vs_round_cost(outcomes: list[dict]) -> dict:
    """Does keeper surplus scale with the round it cost?

    The app's model assumes a keeper kept at round R is worth roughly what
    round R returns, so realized surplus should be flat in R — a manager should
    not systematically do better keeping cheap late-round players than
    expensive early ones. A non-zero slope says the round-cost model is
    mispriced, and its sign says which way.
    """
    rows = [(o["round_cost"], o["realized_surplus"]) for o in outcomes
            if o.get("round_cost") is not None]
    if len(rows) < 10:
        return {"n": len(rows)}
    costs = np.asarray([r[0] for r in rows], dtype=float)
    surplus = np.asarray([r[1] for r in rows], dtype=float)
    slope, intercept = np.polyfit(costs, surplus, 1)
    predicted = slope * costs + intercept
    ss_res = float(((surplus - predicted) ** 2).sum())
    ss_tot = float(((surplus - surplus.mean()) ** 2).sum())

    # Bootstrap the slope so a near-zero result can be called flat honestly.
    rng = np.random.default_rng(42)
    slopes = []
    for _ in range(2000):
        idx = rng.integers(0, len(costs), len(costs))
        if np.std(costs[idx]) == 0:
            continue
        slopes.append(np.polyfit(costs[idx], surplus[idx], 1)[0])
    lo, hi = ((float(np.percentile(slopes, 2.5)), float(np.percentile(slopes, 97.5)))
              if slopes else (None, None))

    return {
        "n": len(rows),
        "slope": round(float(slope), 4),
        "intercept": round(float(intercept), 3),
        "r_squared": None if ss_tot == 0 else round(1 - ss_res / ss_tot, 4),
        "slope_ci": [None if lo is None else round(lo, 4),
                     None if hi is None else round(hi, 4)],
        "flat": lo is not None and lo <= 0 <= hi,
    }


def by_seasons_kept(outcomes: list[dict]) -> list[dict]:
    """Do multi-season keepers stay worth it in years two and three?

    Under the league's doctrine a keeper's cost climbs five rounds a year, so a
    player kept three times is paying a materially higher price for what is
    usually an ageing season. This is the group where the model is most likely
    to be wrong, and `KEEPER_HISTORY` shows players kept five seasons.
    """
    buckets: dict[int, list[dict]] = {}
    for outcome in outcomes:
        season = outcome.get("seasons_kept")
        if season is None:
            continue
        buckets.setdefault(season, []).append(outcome)

    rows = []
    for season, group in sorted(buckets.items()):
        surplus = [o["realized_surplus"] for o in group]
        wins = sum(1 for value in surplus if value > 0)
        lo, hi = bootstrap_mean_ci(surplus)
        rows.append({
            "seasons_kept": season,
            "n": len(group),
            "mean_round_cost": round(
                sum(o["round_cost"] for o in group) / len(group), 2),
            "mean_realized_surplus": round(sum(surplus) / len(surplus), 3),
            "surplus_ci": [None if lo is None else round(lo, 3),
                           None if hi is None else round(hi, 3)],
            "beat_their_round": wins,
            "beat_rate": round(wins / len(group), 3),
        })
    return rows


def by_baseline_thickness(outcomes: list[dict], threshold: int = 5) -> list[dict]:
    """Split the beat rate by how many picks formed the comparison baseline.

    Managers park keepers in the cheapest rounds, so round 25 often holds only
    two or three non-keeper picks — a thin and noisy thing to be measured
    against. If the beat rate held up only where the baseline is thin, the
    headline would be an artifact of that noise rather than a finding.
    """
    groups = {"thin": [], "thick": []}
    for outcome in outcomes:
        picks = outcome.get("baseline_picks")
        if picks is None:
            continue
        groups["thin" if picks < threshold else "thick"].append(outcome)

    rows = []
    for label, group in groups.items():
        if not group:
            continue
        wins = sum(1 for o in group if o["realized_surplus"] > 0)
        lo, hi = bootstrap_proportion_ci(wins, len(group))
        rows.append({
            "baseline": f"<{threshold} picks" if label == "thin"
                        else f">={threshold} picks",
            "n": len(group),
            "beat_rate": round(wins / len(group), 3),
            "beat_rate_ci": [None if lo is None else round(lo, 3),
                             None if hi is None else round(hi, 3)],
            "mean_realized_surplus": round(
                sum(o["realized_surplus"] for o in group) / len(group), 3),
        })
    return rows


def aggregate_accuracy(outcomes: list[dict]) -> dict:
    """Headline numbers over every keeper decision in scope.

    `beat_their_round` answers the question that needs no projections at all:
    did keeping this player return more than that round actually returned?
    `prior_sign_agreement` answers the weaker one the data can support — did a
    decision-time baseline point the right way?
    """
    if not outcomes:
        return {"n": 0}

    surplus = [o["realized_surplus"] for o in outcomes]
    wins = sum(1 for value in surplus if value > 0)
    win_lo, win_hi = bootstrap_proportion_ci(wins, len(outcomes))
    mean_lo, mean_hi = bootstrap_mean_ci(surplus)

    with_prior = [o for o in outcomes if o.get("prior_surplus") is not None]
    agreed = sum(1 for o in with_prior
                 if (o["prior_surplus"] > 0) == (o["realized_surplus"] > 0))
    agree_lo, agree_hi = bootstrap_proportion_ci(agreed, len(with_prior))

    return {
        "n": len(outcomes),
        "beat_their_round": wins,
        "beat_rate": round(wins / len(outcomes), 3),
        "beat_rate_ci": [None if win_lo is None else round(win_lo, 3),
                         None if win_hi is None else round(win_hi, 3)],
        "mean_realized_surplus": round(sum(surplus) / len(surplus), 3),
        "mean_realized_surplus_ci": [
            None if mean_lo is None else round(mean_lo, 3),
            None if mean_hi is None else round(mean_hi, 3)],
        "prior_baseline_n": len(with_prior),
        "prior_sign_agreement": (round(agreed / len(with_prior), 3)
                                 if with_prior else None),
        "prior_sign_agreement_ci": [
            None if agree_lo is None else round(agree_lo, 3),
            None if agree_hi is None else round(agree_hi, 3)],
    }
