"""
Seed the 2026 draft state and keepers state into the database.

Computes the full draft order (trades, 25-cap, supplemental picks),
resolves keeper MLB IDs, and writes both:
  - draft_state JSON (draft board pre-populated on first load)
  - keepers_state JSON (keepers page pre-populated on first load)

Draft state is idempotent: skips seeding if a draft has already
started (non-keeper picks exist in the saved state).

Keepers state always overwrites existing data.

Called from backend startup (main.py) and can also be run standalone:
    python -m backend.data.seed_draft_order
"""

import json
import logging
import re
import unicodedata
from collections import defaultdict

from backend.database import get_connection, init_db

logger = logging.getLogger(__name__)

SEASON = 2026

# ── ESPN team IDs (from TEAM_MANAGER in draft-history.ts) ──
TEAM_ID_TO_MANAGER = {
    1: "Jess Barron",
    2: "Chris Herbst",
    3: "Tim Riker",
    4: "Harris Cook",
    5: "Jason McComb",
    6: "Matt Wayne",
    7: "David Rotatori",
    8: "John Gibbons",
    9: "Eric Mercado",
    10: "Bryan Lewis",
}
MANAGER_TO_TEAM_ID = {v: k for k, v in TEAM_ID_TO_MANAGER.items()}

# ── Draft order: reverse of 2025 final standings ──
# 10th place picks 1st, 1st place picks 10th
DRAFT_ORDER = [2, 5, 9, 8, 3, 10, 4, 6, 1, 7]

NUM_ROUNDS = 25
ROSTER_SIZE = 25
NUM_TEAMS = 10

# ── Pick trades: (from_manager, to_manager, round) ──
PICK_TRADES = [
    ("Eric Mercado",   "Chris Herbst",  4),
    ("David Rotatori", "Chris Herbst",  6),
    ("Harris Cook",    "Chris Herbst",  5),
    ("Matt Wayne",     "Chris Herbst",  8),
    ("Bryan Lewis",    "Chris Herbst",  11),
    ("Matt Wayne",     "Chris Herbst",  16),
    ("Harris Cook",    "Chris Herbst",  10),
    ("Jason McComb",   "Chris Herbst",  14),
    ("Chris Herbst",   "Jason McComb",  15),
    ("Chris Herbst",   "Jason McComb",  16),
    ("David Rotatori", "Eric Mercado",  9),
    ("David Rotatori", "Eric Mercado",  16),
    ("Chris Herbst",   "Tim Riker",     18),
    ("Chris Herbst",   "Tim Riker",     19),
    ("Tim Riker",      "Chris Herbst",  23),
    ("Tim Riker",      "Chris Herbst",  24),
]

# ── Keepers: (manager, declared_round, player_name, year_label) ──
KEEPERS = [
    # (manager, round, player_name, keeper_year, mlb_id)
    ("Chris Herbst",   20, "Jackson Merrill",      "2nd yr", 701538),
    ("Chris Herbst",   23, "Eury Perez",           "1st yr", 691587),
    ("Chris Herbst",   24, "Drake Baldwin",         "1st yr", 686948),
    ("Chris Herbst",   25, "Roman Anthony",         "1st yr", 701350),
    ("Jason McComb",    9, "Brice Turang",          "1st yr", 668930),
    ("Jason McComb",   23, "Alex Vesia",            "1st yr", 681911),
    ("Jason McComb",   24, "Tony Santillan",        "1st yr", 663574),
    ("Jason McComb",   25, "Abner Uribe",           "1st yr", 682842),
    ("Jess Barron",     1, "Shohei Ohtani",        "2nd yr", 660271),
    ("Jess Barron",     9, "Ketel Marte",          "3rd yr", 606466),
    ("Jess Barron",    24, "Cade Smith",            "1st yr", 671922),
    ("Jess Barron",    25, "Geraldo Perdomo",       "1st yr", 672695),
    ("Harris Cook",    14, "Tarik Skubal",          "3rd yr", 669373),
    ("Harris Cook",    12, "Bryan Woo",             "2nd yr", 693433),
    ("Harris Cook",    13, "Pete Crow-Armstrong",   "1st yr", 691718),
    ("Harris Cook",    25, "Chase Burns",           "1st yr", 695505),
    ("Eric Mercado",    1, "Aaron Judge",           "2nd yr", 592450),
    ("Eric Mercado",   19, "Mackenzie Gore",        "1st yr", 669022),
    ("Eric Mercado",   20, "Kyle Stowers",          "1st yr", 669065),
    ("Eric Mercado",   24, "Spencer Jones",         "1st yr", 682987),
    ("Tim Riker",       1, "Jose Ramirez",          "1st yr", 608070),
    ("Tim Riker",       4, "Yoshinobu Yamamoto",    "1st yr", 808967),
    ("Tim Riker",      10, "Cal Raleigh",           "1st yr", 663728),
    ("Tim Riker",      25, "Jacob Misiorowski",     "1st yr", 694819),
    ("Matt Wayne",     17, "Cristopher Sanchez",    "2nd yr", 650911),
    ("Matt Wayne",     18, "Garrett Crochet",       "2nd yr", 676979),
    ("Matt Wayne",     20, "James Wood",            "2nd yr", 695578),
    ("John Gibbons",    1, "Juan Soto",             "1st yr", 665742),
    ("John Gibbons",    7, "Jackson Chourio",       "2nd yr", 694192),
    ("John Gibbons",   20, "Lawrence Butler",       "2nd yr", 671732),
    ("John Gibbons",   25, "Nick Kurtz",            "1st yr", 701762),
    ("David Rotatori", 12, "Hunter Brown",          "2nd yr", 686613),
    ("David Rotatori", 20, "Mason Miller",          "2nd yr", 695243),
    ("David Rotatori", 24, "Trevor Rogers",         "1st yr", 669432),
    ("David Rotatori", 25, "Kyle Bradish",          "1st yr", 680694),
]


# ── Draft order computation (mirrors compute_2026_draft_order.py) ──

def _get_round_order(round_num):
    """Snake order: odd rounds forward (1→10), even rounds reverse (10→1)."""
    if round_num % 2 == 1:
        return list(range(1, NUM_TEAMS + 1))
    return list(range(NUM_TEAMS, 0, -1))


def _managers():
    """Draft-position → manager mapping (matches compute script)."""
    return {
        1: "Chris Herbst",
        2: "Jason McComb",
        3: "Eric Mercado",
        4: "John Gibbons",
        5: "Tim Riker",
        6: "Bryan Lewis",
        7: "Harris Cook",
        8: "Matt Wayne",
        9: "Jess Barron",
        10: "David Rotatori",
    }


def _compute_all_pick_slots():
    managers = _managers()
    lost_picks = {}
    for from_mgr, to_mgr, rnd in PICK_TRADES:
        lost_picks[(from_mgr, rnd)] = to_mgr

    manager_slots = defaultdict(list)
    for rnd in range(1, NUM_ROUNDS + 1):
        for pos in _get_round_order(rnd):
            mgr = managers[pos]
            if (mgr, rnd) in lost_picks:
                receiver = lost_picks[(mgr, rnd)]
                manager_slots[receiver].append(
                    (rnd, pos, f"(traded from {mgr})")
                )
            else:
                manager_slots[mgr].append((rnd, pos, ""))
    return manager_slots


def _assign_keepers_with_cap(manager_slots):
    managers = _managers()
    mgr_keepers = defaultdict(list)
    for mgr, rnd, player, yr, *_ in KEEPERS:
        mgr_keepers[mgr].append((rnd, player, yr))
    for mgr in mgr_keepers:
        mgr_keepers[mgr].sort(key=lambda x: x[0])

    final_slots = {}
    supplemental_needs = {}
    keeper_adjustments = []

    for mgr in managers.values():
        slots = manager_slots[mgr]
        keepers = mgr_keepers.get(mgr, [])
        total = len(slots)

        # Step 1: first ROSTER_SIZE slots survive
        surviving = set(range(min(total, ROSTER_SIZE)))

        # Step 2: assign keepers
        keeper_map = {}
        unplaced = []

        for kp_rnd, player, yr in keepers:
            found_idx = None
            for i, (rnd, pos, note) in enumerate(slots):
                if rnd == kp_rnd and i in surviving and i not in keeper_map:
                    found_idx = i
                    break
            if found_idx is None:
                for i, (rnd, pos, note) in enumerate(slots):
                    if (rnd == kp_rnd and i not in surviving
                            and i not in keeper_map and note):
                        found_idx = i
                        break

            if found_idx is not None:
                if found_idx not in surviving:
                    surviving.add(found_idx)
                    for j in range(total - 1, -1, -1):
                        if j in surviving and j not in keeper_map and j != found_idx:
                            surviving.discard(j)
                            break
                keeper_map[found_idx] = (player, yr, kp_rnd)
            else:
                unplaced.append((kp_rnd, player, yr))

        # Step 3: unplaced keepers slide to latest surviving draft slot
        unplaced.sort(key=lambda x: x[0], reverse=True)
        for kp_rnd, player, yr in unplaced:
            for j in range(total - 1, -1, -1):
                if j in surviving and j not in keeper_map:
                    keeper_map[j] = (player, yr, kp_rnd)
                    actual_rnd = slots[j][0]
                    keeper_adjustments.append((mgr, player, kp_rnd, actual_rnd))
                    break

        result = []
        for i, (rnd, pos, note) in enumerate(slots):
            if i in keeper_map:
                player, yr, orig_rnd = keeper_map[i]
                adj_note = f"KEEPER: {player} ({yr})"
                if orig_rnd != rnd:
                    adj_note += f" [moved from Rd {orig_rnd}]"
                result.append((rnd, pos, "keeper", adj_note))
            elif i in surviving:
                result.append((rnd, pos, "draft", note))

        final_slots[mgr] = result
        supplemental_needs[mgr] = max(0, ROSTER_SIZE - len(result))

    return final_slots, supplemental_needs, keeper_adjustments


def _build_draft_order(final_slots, supplemental_needs):
    managers = _managers()
    round_events = defaultdict(list)

    for mgr, slots in final_slots.items():
        for rnd, pos, stype, notes in slots:
            round_events[rnd].append((pos, mgr, stype, notes))

    for rnd in round_events:
        base_order = _get_round_order(rnd)
        pos_order = {p: i for i, p in enumerate(base_order)}
        round_events[rnd].sort(key=lambda x: pos_order.get(x[0], 99))

    results = []
    overall_pick = 0

    for rnd in range(1, NUM_ROUNDS + 1):
        for pos, mgr, stype, notes in round_events.get(rnd, []):
            if stype == "keeper":
                results.append({
                    "overall_pick": "KEEPER", "round": rnd,
                    "manager": mgr, "notes": notes,
                })
            else:
                overall_pick += 1
                results.append({
                    "overall_pick": overall_pick, "round": rnd,
                    "manager": mgr, "notes": notes,
                })

    # Supplemental rounds
    supp_remaining = dict(supplemental_needs)
    supp_round = NUM_ROUNDS + 1
    while sum(supp_remaining.values()) > 0:
        for pos in _get_round_order(supp_round):
            mgr = managers[pos]
            if supp_remaining.get(mgr, 0) > 0:
                overall_pick += 1
                supp_remaining[mgr] -= 1
                results.append({
                    "overall_pick": overall_pick, "round": supp_round,
                    "manager": mgr, "notes": "(supplemental)",
                })
        supp_round += 1

    return results


# ── Pick trade index computation ──

def _base_snake_pick_index(team_id, round_1based):
    """Find a team's pick index in the base snake schedule."""
    round_0 = round_1based - 1
    if round_0 % 2 == 0:
        pos = DRAFT_ORDER.index(team_id)
    else:
        pos = NUM_TEAMS - 1 - DRAFT_ORDER.index(team_id)
    return round_0 * NUM_TEAMS + pos


def _compute_pick_trades():
    """Convert PICK_TRADES to frontend PickTrade format."""
    trades = []
    for from_mgr, to_mgr, rnd in PICK_TRADES:
        from_id = MANAGER_TO_TEAM_ID[from_mgr]
        to_id = MANAGER_TO_TEAM_ID[to_mgr]
        idx = _base_snake_pick_index(from_id, rnd)
        trades.append({
            "pickIndex": idx,
            "fromTeamId": from_id,
            "toTeamId": to_id,
        })
    return trades


# ── Keeper MLB ID resolution ──

def _strip_accents(s):
    """Remove diacritics for name matching (e.g. Pérez → Perez)."""
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def _resolve_keeper_ids(conn):
    """Look up MLB IDs for all keeper players.

    Uses the mlb_id from KEEPERS directly when available, falling back to
    name-based lookup for backwards compatibility.
    """
    resolved = {}
    for entry in KEEPERS:
        mgr, _, player, _ = entry[0], entry[1], entry[2], entry[3]
        mlb_id = entry[4] if len(entry) > 4 else None
        key = (mgr, player)
        if key in resolved:
            continue

        row = None

        # Prefer explicit mlb_id (no ambiguity)
        if mlb_id:
            row = conn.execute(
                "SELECT mlb_id, primary_position FROM players WHERE mlb_id = ?",
                (mlb_id,),
            ).fetchone()
            if not row:
                # Auto-create the player record so keepers always resolve
                from backend.data.projections import _auto_create_player
                _auto_create_player(conn, mlb_id, player, "", "hitter")
                conn.commit()
                row = conn.execute(
                    "SELECT mlb_id, primary_position FROM players WHERE mlb_id = ?",
                    (mlb_id,),
                ).fetchone()

        # Fall back to name match
        if not row:
            row = conn.execute(
                "SELECT mlb_id, primary_position FROM players "
                "WHERE full_name = ? AND is_active = 1",
                (player,),
            ).fetchone()

        if not row:
            # Try accent-insensitive match
            target = _strip_accents(player).lower()
            candidates = conn.execute(
                "SELECT mlb_id, full_name, primary_position FROM players "
                "WHERE is_active = 1"
            ).fetchall()
            for c in candidates:
                if _strip_accents(c["full_name"]).lower() == target:
                    row = c
                    logger.info(f"Accent-matched: {player} → {c['full_name']}")
                    break

        if row:
            resolved[key] = (row["mlb_id"], row["primary_position"])
        else:
            logger.error(f"Could not resolve keeper: {player} ({mgr})")
    return resolved


# ── Keepers page state ──

def _keeper_year_from_label(yr_label):
    """Parse '1st yr' / '2nd yr' / '3rd yr' → integer."""
    m = re.match(r"(\d+)", yr_label)
    return int(m.group(1)) if m else 1


def _build_keepers_state(conn, results, keeper_db):
    """Build the keepers-page state dict from computed draft results."""
    my_team_id = 8  # John Gibbons

    # Build keeper_season lookup from KEEPERS config
    keeper_year = {}
    for mgr, _, player, yr_label, *_ in KEEPERS:
        keeper_year[(mgr, player)] = _keeper_year_from_label(yr_label)

    # Load ranking data for ResolvedKeeper objects
    ranking_data = {}
    rows = conn.execute(
        """SELECT p.mlb_id, p.full_name, p.primary_position, p.team,
                  p.player_type, p.eligible_positions,
                  r.overall_rank, r.total_zscore,
                  r.zscore_r, r.zscore_tb, r.zscore_rbi, r.zscore_sb, r.zscore_obp,
                  r.zscore_k, r.zscore_qs, r.zscore_era, r.zscore_whip, r.zscore_svhd
           FROM players p
           LEFT JOIN rankings r ON p.mlb_id = r.mlb_id AND r.season = ?
           WHERE p.is_active = 1""",
        (SEASON,),
    ).fetchall()
    for row in rows:
        ranking_data[row["mlb_id"]] = dict(row)

    other = defaultdict(list)           # team_id str → [{name, roundCost}]
    selected = defaultdict(list)        # team_id str → [mlb_id]
    other_resolved = defaultdict(list)  # team_id str → [ResolvedKeeper]

    for r in results:
        if r["overall_pick"] != "KEEPER":
            continue

        m = re.match(r"KEEPER: (.+?) \(", r["notes"])
        if not m:
            continue
        player = m.group(1)
        mgr = r["manager"]
        team_id = MANAGER_TO_TEAM_ID[mgr]
        round_cost = r["round"]

        if team_id == my_team_id:
            continue  # My team keepers go in roster/resolved, not other

        info = keeper_db.get((mgr, player))
        if not info:
            logger.error(
                "Skipping unresolved keeper in keepers state: %s (%s)",
                player, mgr,
            )
            continue

        mlb_id, position = info
        tid = str(team_id)

        other[tid].append({"name": player, "roundCost": round_cost})
        selected[tid].append(mlb_id)

        rd = ranking_data.get(mlb_id, {})
        yr = keeper_year.get((mgr, player), 1)
        other_resolved[tid].append({
            "name": player,
            "mlb_id": mlb_id,
            "matched_name": rd.get("full_name", player),
            "match_confidence": 1.0,
            "draft_round": round_cost,
            "keeper_season": yr,
            "overall_rank": rd.get("overall_rank"),
            "total_zscore": rd.get("total_zscore"),
            "primary_position": rd.get("primary_position", position or ""),
            "team": rd.get("team", ""),
            "player_type": rd.get("player_type", "hitter"),
            "eligible_positions": rd.get("eligible_positions"),
            "zscore_r": rd.get("zscore_r"),
            "zscore_tb": rd.get("zscore_tb"),
            "zscore_rbi": rd.get("zscore_rbi"),
            "zscore_sb": rd.get("zscore_sb"),
            "zscore_obp": rd.get("zscore_obp"),
            "zscore_k": rd.get("zscore_k"),
            "zscore_qs": rd.get("zscore_qs"),
            "zscore_era": rd.get("zscore_era"),
            "zscore_whip": rd.get("zscore_whip"),
            "zscore_svhd": rd.get("zscore_svhd"),
        })

    return {
        "myTeamId": my_team_id,
        "roster": {},
        "resolved": {},
        "selected": dict(selected),
        "other": dict(other),
        "otherResolved": dict(other_resolved),
    }


def _seed_keepers_state(conn, results, keeper_db):
    """Build and persist keepers-page state (always overwrites)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS keepers_state (
            season INTEGER PRIMARY KEY,
            state_json TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

    state = _build_keepers_state(conn, results, keeper_db)
    state_json = json.dumps(state)
    conn.execute(
        """INSERT INTO keepers_state (season, state_json) VALUES (?, ?)
           ON CONFLICT (season) DO UPDATE
           SET state_json = ?, updated_at = CURRENT_TIMESTAMP""",
        (SEASON, state_json, state_json),
    )
    conn.commit()

    keeper_count = sum(len(v) for v in state["other"].values())
    logger.info("Seeded keepers state: %d keepers across %d teams",
                keeper_count, len(state["other"]))
    return state


# ── Main seed function ──

def _build_fresh_keeper_data(conn, results):
    """Resolve keeper IDs and build keeper picks, keeperMlbIds, leagueKeepers."""
    keeper_db = _resolve_keeper_ids(conn)

    picks = []
    keeper_mlb_ids = []
    league_keepers = []
    keeper_pick_indices = set()

    for i, r in enumerate(results):
        if r["overall_pick"] != "KEEPER":
            continue

        notes = r["notes"]
        m = re.match(r"KEEPER: (.+?) \(", notes)
        if not m:
            continue
        player = m.group(1)
        mgr = r["manager"]
        team_id = MANAGER_TO_TEAM_ID[mgr]

        info = keeper_db.get((mgr, player))
        if not info:
            logger.error(f"Skipping unresolved keeper: {player} ({mgr})")
            continue

        mlb_id, position = info
        picks.append([mlb_id, team_id])
        keeper_mlb_ids.append(mlb_id)
        keeper_pick_indices.add(i)
        league_keepers.append({
            "teamId": team_id,
            "mlb_id": mlb_id,
            "playerName": player,
            "roundCost": r["round"],
            "primaryPosition": position or "",
        })

    return keeper_db, picks, keeper_mlb_ids, league_keepers, keeper_pick_indices


def seed_draft_state(force=False):
    """
    Compute and store the 2026 draft state.

    Keeper data (keeperMlbIds, leagueKeepers, keeper picks) is always
    refreshed from the authoritative KEEPERS config — even when the draft
    is in progress — so that code-level fixes to keeper resolution take
    effect on every deploy.

    Non-keeper draft progress (pickLog, currentPickIndex, non-keeper picks)
    is preserved when the draft is underway and force=False.

    Returns the state dict, or None if seeding was skipped.
    """
    conn = get_connection()

    # Compute full draft order (always needed for keeper data)
    manager_slots = _compute_all_pick_slots()
    final_slots, supp_needs, keeper_adj = _assign_keepers_with_cap(manager_slots)
    results = _build_draft_order(final_slots, supp_needs)

    # Build pick schedule (team ID per pick index)
    schedule = [MANAGER_TO_TEAM_ID[r["manager"]] for r in results]

    # Build pick trades
    pick_trades = _compute_pick_trades()

    # Resolve keeper data from the database
    keeper_db, keeper_picks, keeper_mlb_ids, league_keepers, keeper_pick_indices = \
        _build_fresh_keeper_data(conn, results)

    # Check for existing state — merge draft progress if underway
    existing_progress = None
    if not force:
        row = conn.execute(
            "SELECT state_json FROM draft_state WHERE season = ?", (SEASON,)
        ).fetchone()
        if row:
            existing = json.loads(row["state_json"])
            old_keeper_ids = set(existing.get("keeperMlbIds", []))
            old_picks = existing.get("picks", [])
            non_keeper_picks = [p for p in old_picks if p[0] not in old_keeper_ids]
            if non_keeper_picks:
                existing_progress = existing
                logger.info(
                    "Draft in progress (%d non-keeper picks) — "
                    "refreshing keeper data while preserving progress",
                    len(non_keeper_picks),
                )

    if existing_progress:
        # Merge: replace keeper data but keep draft progress
        old_keeper_ids = set(existing_progress.get("keeperMlbIds", []))
        preserved_picks = [p for p in existing_progress["picks"]
                           if p[0] not in old_keeper_ids]
        all_picks = keeper_picks + preserved_picks

        draft_state = {
            "picks": all_picks,
            "myTeamId": existing_progress.get("myTeamId", 8),
            "draftOrder": DRAFT_ORDER,
            "currentPickIndex": existing_progress.get("currentPickIndex", 0),
            "keeperMlbIds": keeper_mlb_ids,
            "pickSchedule": schedule,
            "pickTrades": pick_trades,
            "pickLog": existing_progress.get("pickLog", []),
            "leagueKeepers": league_keepers,
        }
    else:
        # Fresh seed
        current_pick_index = 0
        while current_pick_index in keeper_pick_indices:
            current_pick_index += 1

        draft_state = {
            "picks": keeper_picks,
            "myTeamId": 8,  # John Gibbons
            "draftOrder": DRAFT_ORDER,
            "currentPickIndex": current_pick_index,
            "keeperMlbIds": keeper_mlb_ids,
            "pickSchedule": schedule,
            "pickTrades": pick_trades,
            "pickLog": [],
            "leagueKeepers": league_keepers,
        }

    state_json = json.dumps(draft_state)
    conn.execute(
        """INSERT INTO draft_state (season, state_json) VALUES (?, ?)
           ON CONFLICT (season) DO UPDATE
           SET state_json = ?, updated_at = CURRENT_TIMESTAMP""",
        (SEASON, state_json, state_json),
    )
    conn.commit()

    logger.info(
        "Seeded 2026 draft state: %d-pick schedule, %d keepers, %d trades",
        len(schedule), len(keeper_picks), len(pick_trades),
    )

    # Seed keepers-page state (always overwrite)
    _seed_keepers_state(conn, results, keeper_db)

    conn.close()
    return draft_state


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    init_db()
    state = seed_draft_state(force=True)
    if state:
        print(
            f"Done. Schedule: {len(state['pickSchedule'])} picks, "
            f"Keepers: {len(state['picks'])}, "
            f"Trades: {len(state['pickTrades'])}"
        )
    else:
        print("Skipped (draft already in progress)")
