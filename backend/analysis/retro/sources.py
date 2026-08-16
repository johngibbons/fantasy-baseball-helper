"""Layer D: which projection source should the 2027 board be built from?

Sources are scored in SGP space rather than stat space. Being accurate about
home runs matters only insofar as it moves standings points in this league's
ten categories, and a source can be excellent at batting average while adding
nothing here.

Two things must be controlled or the comparison is meaningless:

Coverage. The sources project wildly different numbers of players — Steamer
covers thousands, THE BAT X barely a thousand. A source that only projects
established regulars looks accurate because it never has to guess about the
hard cases. Every source is therefore scored over the same intersection of
players, with coverage reported separately.

Replacement level. It is computed over whichever pool is passed in, so each
source must be valued over that same common pool or their scales differ.

The decomposition that matters for 2027 is rate versus playing time. If every
source is equally poor at forecasting volume, then swapping sources buys
nothing and the effort belongs in injury and role modelling instead.

Pure functions.
"""

from __future__ import annotations

import math


def common_player_ids(rows_by_source: dict[str, list[dict]]) -> set[int]:
    """Players every source projects — the only fair comparison set."""
    id_sets = [{row["mlb_id"] for row in rows} for rows in rows_by_source.values()]
    if not id_sets:
        return set()
    common = id_sets[0]
    for other in id_sets[1:]:
        common &= other
    return common


def coverage_report(rows_by_source: dict[str, list[dict]],
                    common: set[int]) -> list[dict]:
    """How many players each source projects, and its share of the common set."""
    return [
        {
            "source": source,
            "projected_players": len(rows),
            "in_common_set": len({r["mlb_id"] for r in rows} & common),
        }
        for source, rows in sorted(rows_by_source.items())
    ]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _correlation(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    mx, my = _mean(xs), _mean(ys)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def volume_accuracy(projection_rows: list[dict], actual_rows: list[dict],
                    volume_key: str) -> dict:
    """How well a source forecasts playing time — PA for hitters, IP for pitchers."""
    actual = {row["mlb_id"]: float(row.get(volume_key) or 0.0)
              for row in actual_rows}
    pairs = [
        (float(row.get(volume_key) or 0.0), actual[row["mlb_id"]])
        for row in projection_rows if row["mlb_id"] in actual
    ]
    if not pairs:
        return {"n": 0}
    projected = [p for p, _ in pairs]
    realized = [a for _, a in pairs]
    errors = [a - p for p, a in pairs]
    return {
        "n": len(pairs),
        "correlation": _correlation(projected, realized),
        "mean_projected": round(_mean(projected), 1),
        "mean_actual": round(_mean(realized), 1),
        "mean_error": round(_mean(errors), 1),
        "mean_abs_error": round(_mean([abs(e) for e in errors]), 1),
    }


def rate_accuracy(projection_rows: list[dict], actual_rows: list[dict],
                  rate_key: str, volume_key: str,
                  min_volume: float) -> dict:
    """How well a source forecasts per-unit quality, ignoring playing time.

    Restricted to players who actually accumulated enough volume for the
    realized rate to mean anything.
    """
    actual = {
        row["mlb_id"]: row for row in actual_rows
        if float(row.get(volume_key) or 0.0) >= min_volume
    }
    pairs = [
        (float(row.get(rate_key) or 0.0),
         float(actual[row["mlb_id"]].get(rate_key) or 0.0))
        for row in projection_rows if row["mlb_id"] in actual
    ]
    pairs = [(p, a) for p, a in pairs if p > 0 and a > 0]
    if len(pairs) < 2:
        return {"n": len(pairs)}
    projected = [p for p, _ in pairs]
    realized = [a for _, a in pairs]
    return {
        "n": len(pairs),
        "correlation": _correlation(projected, realized),
        "mean_projected": round(_mean(projected), 4),
        "mean_actual": round(_mean(realized), 4),
        "mean_error": round(_mean([a - p for p, a in pairs]), 4),
        "mean_abs_error": round(_mean([abs(a - p) for p, a in pairs]), 4),
    }


def blend_values(value_maps: dict[str, dict[int, float]],
                 weights: dict[str, float] | None = None) -> dict[int, float]:
    """Weighted mean of several sources' valuations, over players all of them cover.

    Blending in SGP space rather than stat space keeps this comparable to the
    single-source boards; it is also what the app effectively did before commit
    8947e0c moved rankings to ATC only.
    """
    if not value_maps:
        return {}
    shared = set.intersection(*(set(values) for values in value_maps.values()))
    weights = weights or {source: 1.0 for source in value_maps}
    total_weight = sum(weights.get(source, 0.0) for source in value_maps)
    if total_weight == 0:
        return {}
    return {
        mlb_id: sum(values[mlb_id] * weights.get(source, 0.0)
                    for source, values in value_maps.items()) / total_weight
        for mlb_id in shared
    }
