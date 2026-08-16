"""Layer B: was each pick a good decision, and was the team model right?

Two questions that must not be confused:

  Was it a bad decision?  Compare the pick against the best player the board
                          itself ranked higher and still available. This is
                          answerable at the time, and it is the only part the
                          app could have improved.
  Was it bad luck?        Compare the pick against the best player who turned
                          out best. Nobody could have known.

Reporting only the second would blame the drafter for every injury; reporting
only the first would miss systematic blind spots. Both are computed for all 211
logged picks across all ten teams — n=211 rather than the 21 picks of a single
team, which is what makes any of this measurable.

Pure functions; the fixtures and CLI live in backend/scripts/retro_draft.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.simulation.player_pool import ALL_CAT_KEYS, Player
from backend.simulation.roster import RosterState
from backend.simulation.scoring_model import compute_rank, win_prob_from_rank


def keeper_pick_index(team_id: int, round_cost: int, pick_schedule: list[int],
                      round_starts: list[int], used: set[int]) -> int:
    """The slot a keeper occupies: the team's first pick in its cost round.

    Port of keeperPickIndexFromSchedule in src/lib/league-teams.ts. Two keepers
    from the same team at the same round cost take successive slots, which is
    why `used` is threaded through.
    """
    round0 = round_cost - 1
    if round0 < 0 or round0 >= len(round_starts):
        return -1
    start = round_starts[round0]
    end = (round_starts[round0 + 1] if round0 + 1 < len(round_starts)
           else len(pick_schedule))
    for i in range(start, min(end, len(pick_schedule))):
        if pick_schedule[i] == team_id and i not in used:
            return i
    return -1


def build_draft_board(league_keepers: list[dict], pick_log: list[dict],
                      pick_schedule: list[int], round_starts: list[int],
                      total_picks: int) -> list[dict | None]:
    """Reconstruct what happened at each slot, in true pick order.

    The `picks` field of the saved draft state cannot be used for this: it is
    `[...draftPicks.entries()]` of a Map keyed by mlb_id, so its array position
    is insertion order, not pick index. The board is instead the union of
    keeper slots (placed by round cost) and pickLog entries (which carry an
    explicit pickIndex).
    """
    board: list[dict | None] = [None] * total_picks
    used: set[int] = set()
    for keeper in league_keepers:
        index = keeper_pick_index(
            keeper["teamId"], keeper.get("roundCost") or 1,
            pick_schedule, round_starts, used)
        if 0 <= index < total_picks:
            used.add(index)
            board[index] = {
                "mlb_id": keeper["mlb_id"], "team_id": keeper["teamId"],
                "is_keeper": True,
            }

    for entry in pick_log:
        index = entry["pickIndex"]
        if 0 <= index < total_picks and board[index] is None:
            board[index] = {
                "mlb_id": entry["mlbId"], "team_id": entry["teamId"],
                "is_keeper": False,
            }
    return board


@dataclass
class DraftContext:
    """Everything needed to replay the draft."""

    board: list[dict | None]              # pick index -> {mlb_id, team_id, is_keeper}
    keeper_ids: set[int]
    pool_ids: set[int]
    realized_value: dict[int, float]      # mlb_id -> ex-post SGP
    board_value: dict[int, float]         # mlb_id -> preseason SGP (as ranked)
    adp: dict[int, float] = field(default_factory=dict)
    names: dict[int, str] = field(default_factory=dict)


def draftable_pool(context: DraftContext) -> set[int]:
    """Players who could actually be drafted.

    Keepers are excluded outright rather than only from the point their round
    slot passes: they were locked before the draft opened, so treating them as
    available to anyone would invent options that never existed.
    """
    return context.pool_ids - context.keeper_ids


def replay(context: DraftContext) -> list[dict]:
    """One row per drafted pick, with regret measured both ways."""
    available = draftable_pool(context)

    rows = []
    for index, slot in enumerate(context.board):
        if slot is None:
            continue
        mlb_id = slot["mlb_id"]
        if slot["is_keeper"]:
            # Not a decision, and already excluded from the draftable pool.
            available.discard(mlb_id)
            continue

        candidates = available
        best_realized_id = max(
            candidates, key=lambda p: context.realized_value.get(p, 0.0),
            default=None)
        best_board_id = max(
            candidates, key=lambda p: context.board_value.get(p, 0.0),
            default=None)

        taken_realized = context.realized_value.get(mlb_id, 0.0)
        taken_board = context.board_value.get(mlb_id, 0.0)

        rows.append({
            "pick_index": index,
            "round": index // 10 + 1,
            "team_id": slot["team_id"],
            "mlb_id": mlb_id,
            "name": context.names.get(mlb_id),
            "board_value": round(taken_board, 3),
            "realized_value": round(taken_realized, 3),
            # Negative = the board had someone better still on the table.
            "board_regret": round(
                taken_board - context.board_value.get(best_board_id, 0.0), 3),
            "board_best_available": context.names.get(best_board_id),
            # Negative = someone still available turned out better.
            "realized_regret": round(
                taken_realized - context.realized_value.get(best_realized_id, 0.0), 3),
            "realized_best_available": context.names.get(best_realized_id),
            "adp": context.adp.get(mlb_id),
            # Positive = taken later than ADP (a value); negative = a reach.
            "adp_delta": (None if context.adp.get(mlb_id) is None
                          else round(context.adp[mlb_id] - (index + 1), 1)),
        })
        available.discard(mlb_id)

    return rows


def summarize_by_team(rows: list[dict], team_names: dict[int, str] | None = None) -> list[dict]:
    """Per-team totals. Board regret is the part a better model could fix."""
    teams: dict[int, list[dict]] = {}
    for row in rows:
        teams.setdefault(row["team_id"], []).append(row)

    out = []
    for team_id, picks in sorted(teams.items()):
        n = len(picks)
        out.append({
            "team_id": team_id,
            "manager": (team_names or {}).get(team_id),
            "picks": n,
            "realized_value": round(sum(p["realized_value"] for p in picks), 2),
            "board_value": round(sum(p["board_value"] for p in picks), 2),
            "mean_board_regret": round(
                sum(p["board_regret"] for p in picks) / n, 3),
            "mean_realized_regret": round(
                sum(p["realized_regret"] for p in picks) / n, 3),
            "mean_adp_delta": (
                round(sum(p["adp_delta"] for p in picks if p["adp_delta"] is not None)
                      / max(1, sum(1 for p in picks if p["adp_delta"] is not None)), 2)
            ),
        })
    return out


def summarize_by_round(rows: list[dict]) -> list[dict]:
    """Where in the draft value is won and lost."""
    rounds: dict[int, list[dict]] = {}
    for row in rows:
        rounds.setdefault(row["round"], []).append(row)

    return [
        {
            "round": rnd,
            "picks": len(picks),
            "mean_realized_value": round(
                sum(p["realized_value"] for p in picks) / len(picks), 3),
            "mean_board_value": round(
                sum(p["board_value"] for p in picks) / len(picks), 3),
            "mean_realized_regret": round(
                sum(p["realized_regret"] for p in picks) / len(picks), 3),
        }
        for rnd, picks in sorted(rounds.items())
    ]


# ── Team-level model validation ──


def team_category_totals(players: list[Player], config) -> dict[str, float]:
    """Category totals for a roster, weighting bench slots as the model does.

    Mirrors the accumulation in draft_engine so that predicted category wins
    are computed the same way the simulator computes them — the point is to
    test that model, so it has to be the same model.
    """
    roster = RosterState()
    totals = {cat: 0.0 for cat in ALL_CAT_KEYS}

    # Best players first, so the starting slots go to the players who would
    # actually start.
    for player in sorted(players, key=lambda p: -p.total_zscore):
        slot = roster.add_player(player)
        if slot == "BE":
            if player.player_type == "pitcher":
                weight = (config.RP_BENCH_CONTRIBUTION
                          if player.pitcher_role() == "RP"
                          else config.PITCHER_BENCH_CONTRIBUTION)
            else:
                weight = config.HITTER_BENCH_CONTRIBUTION
        elif slot is None:
            continue  # roster full — extra players contribute nothing
        else:
            weight = 1.0
        for cat in ALL_CAT_KEYS:
            totals[cat] += player.zscores.get(cat, 0.0) * weight
    return totals


def predicted_category_wins(
    team_totals: dict[int, dict[str, float]], num_teams: int,
) -> dict[int, dict]:
    """Per-team expected weekly category win rates from roster totals."""
    out = {}
    for team_id, totals in team_totals.items():
        probs = {}
        for cat in ALL_CAT_KEYS:
            others = sorted(
                (other_totals[cat] for other_id, other_totals in team_totals.items()
                 if other_id != team_id),
                reverse=True,
            )
            rank = compute_rank(totals[cat], others)
            probs[cat] = win_prob_from_rank(rank, num_teams)
        out[team_id] = {
            "cat_win_probs": probs,
            "expected_wins": sum(probs.values()),
        }
    return out


def compare_predicted_to_actual(
    predicted: dict[int, dict],
    actual_win_rates: dict[int, dict[str, float]],
) -> dict:
    """Test the objective function the coefficient tuner maximizes.

    optimize_model.py maximizes expected weekly category wins as computed by
    evaluate_draft. If that quantity does not track what teams actually won,
    every coefficient tuned against it inherits the error — which is the
    concern SCORING_MODEL.md raises about the opponent model being ADP-only.
    """
    per_team = []
    for team_id, prediction in sorted(predicted.items()):
        actual = actual_win_rates.get(team_id)
        if not actual:
            continue
        actual_total = sum(actual.values())
        per_team.append({
            "team_id": team_id,
            "predicted_wins": round(prediction["expected_wins"], 3),
            "actual_wins": round(actual_total, 3),
            "error": round(prediction["expected_wins"] - actual_total, 3),
        })

    by_category = {}
    for cat in ALL_CAT_KEYS:
        pairs = [
            (predicted[team_id]["cat_win_probs"][cat], actual_win_rates[team_id][cat])
            for team_id in predicted
            if team_id in actual_win_rates and cat in actual_win_rates[team_id]
        ]
        if not pairs:
            continue
        by_category[cat] = {
            "mean_predicted": round(sum(p for p, _ in pairs) / len(pairs), 4),
            "mean_actual": round(sum(a for _, a in pairs) / len(pairs), 4),
            "mean_error": round(
                sum(p - a for p, a in pairs) / len(pairs), 4),
        }

    return {"per_team": per_team, "by_category": by_category}
