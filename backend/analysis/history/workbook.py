"""Parse the league's draft workbook into normalized rows.

The workbook is seventeen seasons of a spreadsheet maintained by hand, so its
layout drifted. Three eras exist for the Draft sheets alone:

  2010-2014  pick # in col 0, team label in col 1, no `Owner` header. The team
             label is a franchise name ("London Wankers") in 2010-2013 and a
             real manager name in 2014.
  2016-2017  `Owner` header present, pick # still positional in col 0.
  2018-2026  an explicit `#` column, and the remaining columns shift around it
             (2025 has a spacer column; 2026 shifts one further right).

Rather than switching on the season, every parser here locates the header row
and maps *labels* to column indices, falling back to position only where a
sheet has no usable header. The detected variant is reported so the manifest
records which path each sheet took.

The other rule this module follows: **report, never repair**. A row that does
not parse produces an `Issue` naming the sheet, the row number and the raw
values. Nothing is silently dropped, because a silent drop in an older season
biases that season toward the players the spreadsheet happened to spell in a
way this code liked.

Pure functions — the caller supplies rows as tuples, which is what
`openpyxl`'s `values_only` iteration yields.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

Row = tuple

# Header labels, normalized, that identify each logical column. A sheet need
# not carry all of them.
_PICK_LABELS = {"#", "pick", "rank"}
_OWNER_LABELS = {"owner", "manager", "team"}
_PLAYER_LABELS = {"player"}
_POSITION_LABELS = {"position", "pos", "elig. pos.", "elig. pos"}
_MLB_TEAM_LABELS = {"mlb team"}
_NOTES_LABELS = {
    "notes",
    "trade notes",
    "comments, incendiary or otherwise",
}

_ROUND_RE = re.compile(r"^\s*(supplemental\s+)?round\s+(\d+)", re.IGNORECASE)
_SUPPLEMENTAL_RE = re.compile(r"^\s*supplemental\s*$", re.IGNORECASE)
_ORDINAL_RE = re.compile(r"^\s*(\d+)\s*(?:st|nd|rd|th)\s*$", re.IGNORECASE)
_TRAILING_MARK_RE = re.compile(r"^\s*(\d+)\s*[*+†]\s*$")

# "Atlanta Bombers (from Jeff Goldblum)" is the Bombers making a pick they
# acquired by trade, not a distinct franchise. Splitting this out is what keeps
# the pre-2014 owner lists from showing 28 teams in a ten-team league.
_ACQUIRED_RE = re.compile(r"^(.*?)\s*\((?:from|via)\s+(.*?)\)\s*$", re.IGNORECASE)


@dataclass
class Issue:
    """One thing that did not parse cleanly, for the manifest."""

    sheet: str
    row_number: int
    kind: str
    detail: str
    raw: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "sheet": self.sheet,
            "row_number": self.row_number,
            "kind": self.kind,
            "detail": self.detail,
            "raw": [_scalar(v) for v in self.raw],
        }


def _scalar(value):
    """JSON-safe rendering of a cell, for issue reporting."""
    if value is None or isinstance(value, (int, float, bool, str)):
        return value
    return str(value)


def _clean(value) -> str | None:
    """Trim a cell to a string, collapsing the workbook's stray whitespace.

    Non-breaking spaces appear throughout (pasted from email), and several
    names carry trailing spaces that would otherwise defeat name matching.
    """
    if value is None:
        return None
    text = str(value).replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _norm_label(value) -> str:
    text = _clean(value)
    return text.lower() if text else ""


def _as_int(value) -> int | None:
    """Read an integer from the several shapes the workbook uses.

    Rounds appear as 12, 12.0, "12", "1st", and "11*" (the asterisk marking a
    round cost adjusted because the pick had been traded away).
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and value != int(value):
            return None
        return int(value)
    text = _clean(value)
    if not text:
        return None
    for pattern in (_ORDINAL_RE, _TRAILING_MARK_RE):
        match = pattern.match(text)
        if match:
            return int(match.group(1))
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    return None


def _round_marker(value) -> tuple[int | None, bool] | None:
    """Interpret a divider row: `(round, is_supplemental)`, or None if not one.

    Three forms appear: `Round 12`, `Supplemental Round 26`, and a bare
    `Supplemental` heading whose picks carry no round at all. The bare form is
    why 2016-2025 all looked like they had an overfull final round — the
    supplemental picks were being attributed to round 25.
    """
    if not isinstance(value, str):
        return None
    match = _ROUND_RE.match(value)
    if match:
        return int(match.group(2)), bool(match.group(1))
    if _SUPPLEMENTAL_RE.match(value):
        return None, True
    return None


def split_owner(label: str | None) -> tuple[str | None, str | None]:
    """Separate a pick's owner from a `(from X)` trade annotation."""
    if label is None:
        return None, None
    match = _ACQUIRED_RE.match(label)
    if not match:
        return label, None
    owner, acquired_from = match.group(1).strip(), match.group(2).strip()
    return (owner or label), (acquired_from or None)


# ── header location ──────────────────────────────────────────────────────


@dataclass
class ColumnMap:
    pick: int | None = None
    owner: int | None = None
    player: int | None = None
    position: int | None = None
    mlb_team: int | None = None
    notes: int | None = None
    header_row: int = 0

    def as_dict(self) -> dict:
        return {
            "pick": self.pick,
            "owner": self.owner,
            "player": self.player,
            "position": self.position,
            "mlb_team": self.mlb_team,
            "notes": self.notes,
            "header_row": self.header_row,
        }


def find_header_row(rows: list[Row], required: set[str], start: int = 0,
                    limit: int = 40) -> int | None:
    """Index of the first row carrying every label in `required`.

    `required` holds normalized labels. Bounded by `limit` so a sheet whose
    header is missing entirely fails fast rather than scanning 1,000 rows.
    """
    for index in range(start, min(len(rows), start + limit)):
        labels = {_norm_label(cell) for cell in rows[index]}
        if required <= labels:
            return index
    return None


def map_draft_columns(header: Row, header_row: int) -> ColumnMap:
    """Map a Draft sheet's header labels to column indices.

    Falls back to position for the 2010-2014 sheets, which label only Player,
    Position and MLB Team — the pick number sits in col 0 alongside the round
    markers, and the team label immediately precedes Player.
    """
    columns = ColumnMap(header_row=header_row)
    for index, cell in enumerate(header):
        label = _norm_label(cell)
        if not label:
            continue
        if label in _PICK_LABELS and columns.pick is None:
            columns.pick = index
        elif label in _OWNER_LABELS and columns.owner is None:
            columns.owner = index
        elif label in _PLAYER_LABELS and columns.player is None:
            columns.player = index
        elif label in _POSITION_LABELS and columns.position is None:
            columns.position = index
        elif label in _MLB_TEAM_LABELS and columns.mlb_team is None:
            columns.mlb_team = index
        elif label in _NOTES_LABELS and columns.notes is None:
            columns.notes = index

    if columns.player is not None and columns.owner is None:
        # Pre-2016: the team label is unheaded, directly left of Player.
        candidate = columns.player - 1
        if candidate >= 0:
            columns.owner = candidate
    return columns


def draft_variant(columns: ColumnMap) -> str:
    """Name the layout era, for the manifest."""
    if columns.pick is not None:
        return "numbered"          # 2018-2026: explicit `#` column
    if columns.owner is not None and columns.owner > 0:
        return "positional"        # 2010-2017: pick number shares col 0
    return "unknown"


# ── drafts ───────────────────────────────────────────────────────────────


@dataclass
class DraftParse:
    season: int
    sheet: str
    variant: str
    columns: ColumnMap
    picks: list[dict]
    issues: list[Issue]

    @property
    def owners(self) -> list[str]:
        return sorted({p["owner"] for p in self.picks if p["owner"]})


def parse_draft_sheet(rows: list[Row], season: int, sheet: str,
                      start: int = 0) -> DraftParse:
    """Rows of a `YYYY Draft` sheet into pick records.

    `start` lets the 2015 draft be parsed out of the middle of the 2015 Keepers
    sheet, where it was pasted below the keeper table.

    The pick number is taken from the sheet where the sheet states one, because
    traded picks and forfeited keeper rounds make position an unreliable proxy.
    Where no pick column exists the position within the sheet is used and the
    record says so via `pick_number_source`.
    """
    issues: list[Issue] = []
    header_row = find_header_row(rows, {"player"}, start=start)
    if header_row is None:
        issues.append(Issue(sheet, start, "no_header",
                            "no row carrying a `Player` label"))
        return DraftParse(season, sheet, "unknown", ColumnMap(), [], issues)

    columns = map_draft_columns(rows[header_row], header_row)
    variant = draft_variant(columns)
    if columns.player is None:
        issues.append(Issue(sheet, header_row + 1, "no_player_column",
                            "header found but no Player column", list(rows[header_row])))
        return DraftParse(season, sheet, variant, columns, [], issues)

    # In the positional era the pick number shares column 0 with the round
    # markers; in the numbered era it has its own column.
    pick_column = columns.pick if columns.pick is not None else 0

    picks: list[dict] = []
    current_round: int | None = None
    supplemental = False
    sequence = 0

    for offset, row in enumerate(rows[header_row + 1:], start=header_row + 2):
        if not any(cell is not None for cell in row):
            continue

        marker = _round_marker(row[0] if row else None)
        if marker is not None:
            current_round, supplemental = marker
            continue

        player = _clean(_at(row, columns.player))
        if player is None:
            # A row with content but no player is either a stray note or a
            # second table beginning. Both belong in the manifest.
            if any(_clean(cell) for cell in row):
                issues.append(Issue(sheet, offset, "row_without_player",
                                    "non-empty row carried no player name",
                                    list(row)))
            continue

        sequence += 1
        stated_pick = _as_int(_at(row, pick_column))
        if stated_pick is None and columns.pick is not None:
            issues.append(Issue(sheet, offset, "unparsed_pick_number",
                                f"pick column held {_at(row, pick_column)!r}",
                                list(row)))

        owner, acquired_from = split_owner(_clean(_at(row, columns.owner)))
        if owner is None:
            issues.append(Issue(sheet, offset, "missing_owner",
                                f"no owner for {player!r}", list(row)))

        picks.append({
            "pick_number": stated_pick if stated_pick is not None else sequence,
            "pick_number_source": "sheet" if stated_pick is not None else "position",
            "round": current_round,
            "supplemental": supplemental,
            "owner": owner,
            "acquired_from": acquired_from,
            "player_name": player,
            "position": _clean(_at(row, columns.position)),
            "mlb_team": _clean(_at(row, columns.mlb_team)),
            "notes": _clean(_at(row, columns.notes)),
        })

    issues.extend(validate_draft(picks, sheet))
    return DraftParse(season, sheet, variant, columns, picks, issues)


def _at(row: Row, index: int | None):
    if index is None or index < 0 or index >= len(row):
        return None
    return row[index]


def validate_draft(picks: list[dict], sheet: str) -> list[Issue]:
    """Structural checks on a parsed draft.

    Catches the failure that mattered in 2026 — picks arriving out of order —
    plus the two that matter across a long history: a manager missing a whole
    round, and rounds of unequal size (which usually means a row was dropped).
    """
    issues: list[Issue] = []
    if not picks:
        return [Issue(sheet, 0, "empty_draft", "no picks parsed")]

    numbers = [p["pick_number"] for p in picks]
    duplicates = sorted({n for n in numbers if numbers.count(n) > 1})
    if duplicates:
        issues.append(Issue(sheet, 0, "duplicate_pick_numbers",
                            f"pick numbers repeated: {duplicates[:10]}"))
    if numbers != sorted(numbers):
        issues.append(Issue(sheet, 0, "picks_out_of_order",
                            "pick numbers are not ascending in sheet order"))

    expected = set(range(1, len(picks) + 1))
    missing = sorted(expected - set(numbers))
    if missing:
        issues.append(Issue(sheet, 0, "missing_pick_numbers",
                            f"{len(missing)} gaps, e.g. {missing[:10]}"))

    # Supplemental picks are outside the round structure by design, so they
    # are excluded from the round-shape checks but still counted as roster.
    main = [p for p in picks if not p.get("supplemental")]

    orphans = [p for p in main if p["round"] is None]
    if orphans:
        issues.append(Issue(sheet, 0, "picks_without_round",
                            f"{len(orphans)} picks had no preceding "
                            f"`Round N` marker"))

    sizes: dict[int, int] = {}
    for pick in main:
        if pick["round"] is not None:
            sizes[pick["round"]] = sizes.get(pick["round"], 0) + 1
    if sizes:
        modal = max(set(sizes.values()), key=list(sizes.values()).count)
        odd = {r: n for r, n in sorted(sizes.items()) if n != modal}
        if odd:
            issues.append(Issue(sheet, 0, "uneven_rounds",
                                f"most rounds hold {modal} picks; these differ: {odd}"))

    counts: dict[str, int] = {}
    for pick in picks:
        if pick["owner"]:
            counts[pick["owner"]] = counts.get(pick["owner"], 0) + 1
    if counts:
        modal_owner = max(set(counts.values()), key=list(counts.values()).count)
        short = {o: n for o, n in sorted(counts.items()) if n != modal_owner}
        if short:
            issues.append(Issue(sheet, 0, "uneven_rosters",
                                f"most managers hold {modal_owner} picks; "
                                f"these differ: {short}"))
    return issues


# ── keepers ──────────────────────────────────────────────────────────────


@dataclass
class KeeperParse:
    season: int
    sheet: str
    variant: str
    keepers: list[dict]
    issues: list[Issue]
    # 2015 and 2016 paste a second table below the doctrine listing which draft
    # slot each keeper consumed. It is not a draft — it holds only the keeper
    # picks — but it is the only record of keeper pick numbers for those years.
    pick_slots: list[dict] = field(default_factory=list)
    pick_slots_row: int | None = None


def parse_keeper_sheet(rows: list[Row], season: int, sheet: str) -> KeeperParse:
    """Rows of a `YYYY Keepers` sheet into keeper records.

    Two shapes exist. 2015-2016 repeat (Keeper, Round Forfeited); 2017 onward
    add a Seasons Kept column to each group. Group width is read from the
    header rather than assumed, since getting it wrong silently shifts every
    round cost by one column.

    `Seasons Kept` is sometimes the word "final" (2018) rather than a count;
    that is preserved raw and left unparsed rather than guessed at.
    """
    issues: list[Issue] = []
    header_row = find_header_row(rows, {"manager"})
    if header_row is None:
        issues.append(Issue(sheet, 0, "no_header", "no `Manager` header row"))
        return KeeperParse(season, sheet, "unknown", [], issues)

    header = rows[header_row]
    labels = [_norm_label(c) for c in header]
    has_seasons = "seasons kept" in labels
    width = 3 if has_seasons else 2
    variant = "manager_round_seasons" if has_seasons else "manager_round"

    # Each group starts at a labelled `Keeper N` column. Deriving the starts
    # from the labels rather than striding by `width` from the first one keeps
    # the trailing unlabelled columns (2016 has 26) from being read as groups.
    starts = [i for i, lab in enumerate(labels) if lab.startswith("keeper")]
    if not starts:
        issues.append(Issue(sheet, header_row + 1, "no_keeper_columns",
                            "header had no `Keeper N` label", list(header)))
        return KeeperParse(season, sheet, variant, [], issues)

    keepers: list[dict] = []
    end_row = len(rows)

    for offset, row in enumerate(rows[header_row + 1:], start=header_row + 2):
        manager = _clean(_at(row, 0))
        if manager is None:
            continue
        # The keeper table ends at the doctrine text. Everything below it is
        # prose or a second table whose first column holds pick numbers; either
        # way, continuing would read pick numbers as manager names.
        if _is_prose(manager) or _as_int(manager) is not None:
            end_row = offset - 1
            break

        for slot, base in enumerate(starts, start=1):
            name = _clean(_at(row, base))
            if name is None:
                continue
            raw_round = _at(row, base + 1)
            round_cost = _as_int(raw_round)
            if round_cost is None:
                issues.append(Issue(sheet, offset, "unparsed_round_cost",
                                    f"{manager} / {name}: round cell was "
                                    f"{raw_round!r}", list(row)))
            raw_seasons = _at(row, base + 2) if has_seasons else None
            seasons_kept = _as_int(raw_seasons) if has_seasons else None
            if has_seasons and seasons_kept is None and raw_seasons is not None:
                issues.append(Issue(sheet, offset, "unparsed_seasons_kept",
                                    f"{manager} / {name}: seasons cell was "
                                    f"{raw_seasons!r}", list(row)))

            keepers.append({
                "manager": manager,
                "slot": slot,
                "player_name": name,
                "round_cost": round_cost,
                "round_cost_raw": _scalar(raw_round),
                "seasons_kept": seasons_kept,
                "seasons_kept_raw": _scalar(raw_seasons),
            })

    if not keepers:
        issues.append(Issue(sheet, 0, "empty_keepers", "no keepers parsed"))

    # Look below the doctrine for the keeper pick-slot table (2015, 2016).
    pick_slots: list[dict] = []
    slots_row = find_header_row(rows, {"player"}, start=end_row, limit=60)
    if slots_row is not None:
        slots = parse_draft_sheet(rows, season, sheet, start=slots_row)
        pick_slots = slots.picks
        # Its round-shape checks are meaningless — by construction it holds
        # only the ~40 slots keepers consumed — so its issues are dropped
        # except the ones about individual rows.
        issues.extend(i for i in slots.issues
                      if i.kind in {"row_without_player", "missing_owner",
                                    "unparsed_pick_number"})

    return KeeperParse(season, sheet, variant, keepers, issues,
                       pick_slots, slots_row)


_PROSE_PREFIXES = ("keeper doctrine", "draft pick trade", "-", "*", "pick")


def _is_prose(text: str) -> bool:
    """Is this a doctrine paragraph or footnote rather than a manager name?"""
    lowered = text.lower()
    if any(lowered.startswith(prefix) for prefix in _PROSE_PREFIXES):
        return True
    # Manager names are two or three words; doctrine lines are sentences.
    return len(text.split()) > 5


# ── rankings ─────────────────────────────────────────────────────────────


_SHEET_DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})")


def ranking_snapshot_date(sheet: str) -> str | None:
    """ISO date encoded in a sheet name like `ESPN 300 2.2.25`, if present."""
    match = _SHEET_DATE_RE.search(sheet)
    if not match:
        return None
    month, day, year = (int(g) for g in match.groups())
    if year < 100:
        year += 2000
    try:
        from datetime import date

        return date(year, month, day).isoformat()
    except ValueError:
        return None


@dataclass
class RankingParse:
    sheet: str
    season: int | None
    snapshot_date: str | None
    rankings: list[dict]
    issues: list[Issue]
    season_inferred: bool = False


def parse_ranking_sheet(rows: list[Row], sheet: str, season: int | None,
                        season_inferred: bool = False) -> RankingParse:
    """An ESPN/Yahoo top-300 sheet into ranked player rows.

    These sheets vary more than the others: the rank column is sometimes
    unlabelled, sometimes called RANK, and sits left of the player in most
    years but right of it in two. The 2017 sheet splits the name across two
    `Player` columns. Where no rank column can be found at all, sheet order is
    used and the record says so.
    """
    issues: list[Issue] = []
    header_row = find_header_row(rows, {"player"})
    if header_row is None:
        issues.append(Issue(sheet, 0, "no_header", "no `Player` label"))
        return RankingParse(sheet, season, ranking_snapshot_date(sheet), [],
                            issues, season_inferred)

    header = rows[header_row]
    labels = [_norm_label(c) for c in header]
    player_columns = [i for i, lab in enumerate(labels) if lab == "player"]
    player_column = player_columns[0]
    # 2017 splits first and last name across two adjacent `Player` columns.
    surname_column = (player_columns[1]
                      if len(player_columns) > 1
                      and player_columns[1] == player_column + 1 else None)

    rank_column = next(
        (i for i, lab in enumerate(labels) if lab in _PICK_LABELS), None)
    if rank_column is None:
        # Unlabelled rank: col 0 when the player is not already there.
        rank_column = 0 if player_column != 0 else None

    team_column = next((i for i, lab in enumerate(labels)
                        if lab in {"team", "mlb team"}), None)
    position_column = next((i for i, lab in enumerate(labels)
                            if lab in _POSITION_LABELS), None)
    status_column = next((i for i, lab in enumerate(labels)
                          if lab in {"status", "drafted?"}), None)

    rankings: list[dict] = []
    unranked = 0
    for offset, row in enumerate(rows[header_row + 1:], start=header_row + 2):
        name = _clean(_at(row, player_column))
        if name is None:
            continue
        if surname_column is not None:
            surname = _clean(_at(row, surname_column))
            if surname:
                name = f"{name} {surname}"
        rank = _as_int(_at(row, rank_column)) if rank_column is not None else None
        if rank is None:
            # Several sheets append players who were drafted but fell outside
            # the published top 300. They carry no rank, and inventing one from
            # sheet position would put them ahead of genuinely ranked players.
            unranked += 1
        rankings.append({
            "rank": rank,
            "rank_source": "sheet" if rank is not None else "unranked",
            "player_name": name,
            "mlb_team": _clean(_at(row, team_column)),
            "position": _clean(_at(row, position_column)),
            "status": _clean(_at(row, status_column)),
        })

    if unranked:
        issues.append(Issue(sheet, 0, "unranked_rows",
                            f"{unranked} rows carried a player but no rank; "
                            f"kept with rank=null"))

    if not rankings:
        issues.append(Issue(sheet, 0, "empty_rankings", "no rankings parsed"))

    return RankingParse(sheet, season, ranking_snapshot_date(sheet), rankings,
                        issues, season_inferred)
