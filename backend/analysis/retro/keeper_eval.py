"""Layer C: what is a draft pick worth, and were the keepers worth their cost?

Keeper decisions are the highest-stakes pre-draft output the app produces —
they are made once, months early, and they constrain the whole draft. Every
keeper call rests on one assumption in src/app/keepers/page.tsx:96:

    expectedValueAtRound(round) = value of the player ranked (round x 10)

That is a guess about the shape of the value curve. A completed draft measures
it directly: what the board said was available at each pick, and what those
picks actually returned. If the real curve is flatter or steeper than
rank-linear, every keeper surplus number in the app is biased in the same
direction.

Pure functions.
"""

from __future__ import annotations

from dataclasses import dataclass

NUM_TEAMS = 10
MAX_KEEPER_SEASONS = 3


def keeper_cost(draft_round: int | None, keeper_season: int,
                max_rounds: int = 25) -> int:
    """Round cost of keeping a player. Port of keeperCost in keepers/page.tsx.

    First season costs the original draft round; each additional season costs
    five rounds earlier, floored at round 1.
    """
    base = draft_round if draft_round is not None else max_rounds
    if keeper_season == 1:
        return base
    return max(1, base - 5 * (keeper_season - 1))


def expected_value_at_round_assumed(round_number: int,
                                    board: list[dict]) -> float | None:
    """The app's current assumption: the player ranked round x 10.

    `board` must be sorted best-first; rank is taken from position.
    """
    target = round_number * NUM_TEAMS
    if not board:
        return None
    index = min(max(target - 1, 0), len(board) - 1)
    return float(board[index]["total_zscore"])


def value_at_pick_curve(picks: list[dict], bucket_size: int = NUM_TEAMS) -> list[dict]:
    """What each round of the draft actually returned.

    Two series, both per round:
      board_value    — what the preseason board thought those picks were worth
      realized_value — what they turned out to be worth

    The gap between them is what a keeper decision made in February cannot see.
    """
    buckets: dict[int, list[dict]] = {}
    for pick in picks:
        round_number = pick["pick_index"] // bucket_size + 1
        buckets.setdefault(round_number, []).append(pick)

    out = []
    for round_number, group in sorted(buckets.items()):
        board = [p["board_value"] for p in group]
        realized = [p["realized_value"] for p in group]
        out.append({
            "round": round_number,
            "picks": len(group),
            "mean_board_value": round(sum(board) / len(board), 3),
            "mean_realized_value": round(sum(realized) / len(realized), 3),
            "max_realized_value": round(max(realized), 3),
            "min_realized_value": round(min(realized), 3),
        })
    return out


def compare_curve_to_assumption(curve: list[dict], board: list[dict]) -> list[dict]:
    """Assumed value at each round against what the round actually delivered."""
    rows = []
    for entry in curve:
        assumed = expected_value_at_round_assumed(entry["round"], board)
        if assumed is None:
            continue
        rows.append({
            "round": entry["round"],
            "assumed_value": round(assumed, 3),
            "actual_board_value": entry["mean_board_value"],
            "actual_realized_value": entry["mean_realized_value"],
            "assumption_error_vs_board": round(
                assumed - entry["mean_board_value"], 3),
            "assumption_error_vs_realized": round(
                assumed - entry["mean_realized_value"], 3),
        })
    return rows


@dataclass(frozen=True)
class KeeperOutcome:
    mlb_id: int
    name: str | None
    team_id: int
    round_cost: int
    board_value: float
    realized_value: float
    replacement_board: float
    replacement_realized: float

    @property
    def board_surplus(self) -> float:
        """Surplus the app would have shown at decision time."""
        return self.board_value - self.replacement_board

    @property
    def realized_surplus(self) -> float:
        """Surplus with hindsight."""
        return self.realized_value - self.replacement_realized

    def as_dict(self) -> dict:
        return {
            "mlb_id": self.mlb_id,
            "name": self.name,
            "team_id": self.team_id,
            "round_cost": self.round_cost,
            "board_value": round(self.board_value, 3),
            "realized_value": round(self.realized_value, 3),
            "board_surplus": round(self.board_surplus, 3),
            "realized_surplus": round(self.realized_surplus, 3),
            "verdict": ("correct" if self.realized_surplus > 0
                        else "should have passed"),
        }


def evaluate_keepers(
    keepers: list[dict],
    board_value: dict[int, float],
    realized_value: dict[int, float],
    curve: list[dict],
    names: dict[int, str] | None = None,
) -> list[dict]:
    """Was each keeper worth the round it cost?

    The comparison is against what that round actually returned this season,
    not against the rank-linear assumption — that is the point of measuring the
    curve.
    """
    by_round = {entry["round"]: entry for entry in curve}
    last_round = max(by_round) if by_round else 1

    outcomes = []
    for keeper in keepers:
        cost = keeper.get("roundCost") or 1
        reference = by_round.get(min(cost, last_round))
        if reference is None:
            continue
        mlb_id = keeper["mlb_id"]
        outcomes.append(KeeperOutcome(
            mlb_id=mlb_id,
            name=keeper.get("playerName") or (names or {}).get(mlb_id),
            team_id=keeper["teamId"],
            round_cost=cost,
            board_value=board_value.get(mlb_id, 0.0),
            realized_value=realized_value.get(mlb_id, 0.0),
            replacement_board=reference["mean_board_value"],
            replacement_realized=reference["mean_realized_value"],
        ).as_dict())

    outcomes.sort(key=lambda o: -o["realized_surplus"])
    return outcomes


def keeper_accuracy(outcomes: list[dict]) -> dict:
    """How often the surplus sign the app showed matched the outcome."""
    if not outcomes:
        return {"n": 0}
    agreed = sum(1 for o in outcomes
                 if (o["board_surplus"] > 0) == (o["realized_surplus"] > 0))
    positive_board = [o for o in outcomes if o["board_surplus"] > 0]
    return {
        "n": len(outcomes),
        "sign_agreement": round(agreed / len(outcomes), 3),
        "mean_board_surplus": round(
            sum(o["board_surplus"] for o in outcomes) / len(outcomes), 3),
        "mean_realized_surplus": round(
            sum(o["realized_surplus"] for o in outcomes) / len(outcomes), 3),
        "kept_and_worth_it": sum(1 for o in outcomes if o["realized_surplus"] > 0),
        "board_said_keep_and_was_right": (
            round(sum(1 for o in positive_board if o["realized_surplus"] > 0)
                  / len(positive_board), 3) if positive_board else None),
    }
