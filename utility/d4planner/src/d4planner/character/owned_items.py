"""Conservative, incremental owned-item observations from canonical NVDA events.

Truth contract: tooltips and control labels are NOT proof of ownership, pickup,
slot identity, movement, or complete scans. This reader never mutates events.db.
"""
from __future__ import annotations

import hashlib
import json
from contextlib import closing
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterator

from .equipment.parser import is_item_anchor, normalize, parse_item, parse_type
from . import owned_items_scans

CHEST = re.compile(r"^CHEST\s+(\d+)$", re.IGNORECASE)
POWER = re.compile(r"^[\d,]+ Item Power$")
MAX_SEGMENT = 100
PROJECTION_VERSION = 4  # v4 replays raw input + tooltip context for bag ownership
ADDITIONAL_OBSERVED_TYPES = frozenset({"Charm", "Staff", "Horadric Seal"})

def is_owned_item_anchor(name: str, kind: str, power: str) -> bool:
    if normalize(name).upper() in ("TAKE", "STORE", "EQUIP", "UNEQUIP", "EQUIPPED", "DROP", "STASH", "CHARACTER", "BLANK"):
        return False
    if is_item_anchor(name, kind, power):
        return True
    if not normalize(name) or not POWER.fullmatch(normalize(power)):
        return False
    if normalize(kind) == "Set Charm":
        return True
    parsed = parse_type(kind)
    return parsed is not None and parsed[2] in ADDITIONAL_OBSERVED_TYPES


def _connect(path: Path, *, read_only: bool = False) -> sqlite3.Connection:
    if not read_only:
        path.parent.mkdir(parents=True, exist_ok=True)
    if read_only:
        db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
        db.execute("PRAGMA query_only=ON")
    else:
        # The existing character repository owns WAL configuration. Reissuing
        # journal_mode=WAL on every concurrent reader/writer needs a schema
        # lock and can fail immediately on Windows despite busy_timeout.
        db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=15000")
    return db


def _initial() -> dict[str, Any]:
    return {"projectionVersion": PROJECTION_VERSION, "session": None, "context": "unknown", "tabHints": [], "recent": [],
            "active": None, "lastSeenAt": None, "characterInput": False,
            "bagVisible": False, "equippedPrefix": None, "speechAfterEquipped": 0}


def _reset_session(state: dict[str, Any], session: str) -> None:
    state.update({"session": session, "context": "unknown",
                  "tabHints": [], "recent": [], "active": None,
                  "characterInput": False, "bagVisible": False,
                  "equippedPrefix": None, "speechAfterEquipped": 0})


def _location(state: dict[str, Any]) -> dict[str, Any]:
    # A spoken CHEST n is often *a list of tabs*, not the active tab.
    # Do not populate location.tab without focus/selection evidence.
    return {"type": state["context"], "tab": None, "slot": None}


def _make_observation(active: dict[str, Any]) -> dict[str, Any]:
    lines = active["lines"]
    try:
        item = parse_item(lines)
        data = item.as_dict()
        if normalize(lines[1]) == 'Set Charm':
            data['item_type'] = 'Charm'
            data['rarity'] = 'Set'
    except (ValueError, IndexError, TypeError):
        data = {"name": normalize(lines[0]), "item_type": normalize(lines[1]),
                "item_power": None, "base_stats": [], "affixes": [],
                "effects_raw": [], "metadata_raw": lines[2:], "raw_lines": lines}
    normalized = {normalize(line).casefold() for line in lines[3:]}
    bag_evidence = bool(active.get("characterBag"))
    # The markers belong to the selected item, not the EQUIPPED comparison.
    action_evidence = {"equip", "mark as junk", "drop"} <= normalized
    confirmed_bag = (active["location"]["type"] == "inventory"
                     and bag_evidence and action_evidence)
    marked_equipped = (active["location"]["type"] == "equipment"
                       and active.get("equippedMarker") and bag_evidence)
    confirmed = bool(confirmed_bag or marked_equipped)
    return {
        "id": "obs:" + active["session"] + ":" + str(active["start"]),
        "name": data["name"],
        "itemType": data.get("item_type"),
        "itemPower": data.get("item_power"),
        "rarity": data.get("rarity"),
        "ancestral": bool(data.get("ancestral", False)),
        "favorite": bool(data.get("favorite", False)),
        "location": active["location"],
        "locationHints": {"spokenChestTabs": active["tabHints"]},
        "identityConfidence": "UNKNOWN",
        "baseStats": data.get("base_stats", []),
        "affixes": data.get("affixes", []),
        "effectsRaw": data.get("effects_raw", []),
        "metadataRaw": data.get("metadata_raw", []),
        "rawSpeech": lines,
        "ownershipStatus": "CONFIRMED" if confirmed else "NOT_CONFIRMED",
        "observationConfidence": "HIGH" if confirmed else "LOW",
        "ownershipEvidence": ("character-bag-actions-v1" if confirmed_bag
                              else "equipped-marker-v1" if marked_equipped else None),
        "firstSeenAt": active["timestamp"],
        "lastSeenAt": active["timestamp"],
        "pickedUpAt": None,
        "sourceSessionId": active["session"],
        "sourceEventSeqStart": active["start"],
        "sourceEventSeqEnd": active["end"],
    }


def _save_active(db: sqlite3.Connection, state: dict[str, Any]) -> None:
    active = state.get("active")
    if not active or len(active["lines"]) < 3:
        return
    obs = _make_observation(active)
    db.execute(
        """INSERT OR IGNORE INTO owned_item_observation
           (source_session_id,source_seq_start,source_seq_end,location_type,
            item_name,rarity,observed_at,observation_json)
           VALUES(?,?,?,?,?,?,?,?)""",
        (active["session"], active["start"], active["end"],
         obs["location"]["type"], obs["name"], obs["rarity"], obs["firstSeenAt"],
         json.dumps(obs, ensure_ascii=False, separators=(",", ":"))),
    )


def _consume(db: sqlite3.Connection, state: dict[str, Any], row: sqlite3.Row) -> None:
    session = str(row["session_id"])
    if state["session"] != session:
        _save_active(db, state)
        _reset_session(state, session)
    state["lastSeenAt"] = str(row["timestamp"])
    if row["type"] == "input.marker.raw":
        # Controller START is context evidence, not an item identity itself.
        # Require subsequent CHARACTER and Sort Bag speech before bag confirmation.
        try:
            marker = json.loads(row["data_json"])
        except (ValueError, TypeError):
            marker = {}
        if isinstance(marker, dict) and str(marker.get("state", "")).casefold() == "down":
            if (str(marker.get("controlId", "")).casefold() == "start"
                    or str(marker.get("key", "")).casefold() == "f3"):
                _save_active(db, state)
                state["active"] = None
                state["recent"] = []
                state["characterInput"] = True
                state["bagVisible"] = False
                state["equippedPrefix"] = None
        return
    if row["type"] != "speech.raw":
        # Structured producer events are separate from speech; they cannot be
        # inferred from marker keys or tooltip text. Flush any completed raw
        # anchor first so a scan cell can resolve its original observation ID.
        if row["type"] in (owned_items_scans.BEGIN,owned_items_scans.CELL,
                           owned_items_scans.END,owned_items_scans.ACTION,
                           owned_items_scans.MOVE,owned_items_scans.EQUIP,
                           owned_items_scans.UNEQUIP,owned_items_scans.REMOVE):
            _save_active(db,state)
            state["active"] = None
            state["recent"] = []
            owned_items_scans.consume(db,row)
        return
    try:
        data = json.loads(row["data_json"])
        line = normalize(str(data.get("text") or "")) if isinstance(data, dict) else ""
    except (ValueError, TypeError):
        # Preserve the canonical record. Reject malformed projections only.
        line = ""
    if not line:
        return

    seq = int(row["event_seq"])
    active = state["active"]
    upper = line.upper()
    if state.get("equippedPrefix") is not None and upper != "EQUIPPED":
        state["speechAfterEquipped"] += 1
    if "sort bag" in " ".join(line.casefold().split()):
        if state["context"] == "inventory" and state.get("characterInput"):
            state["bagVisible"] = True
    if upper == "EQUIPPED":
        # Hard tooltip boundary: EQUIPPED labels ONLY the next item anchor.
        _save_active(db, state)
        state["active"] = None
        state["recent"] = []
        state["equippedPrefix"] = seq
        state["speechAfterEquipped"] = 0
        return
    if upper == "STASH":
        _save_active(db, state)
        state["active"] = None
        state["context"] = "stash"
        state["characterInput"] = False
        state["bagVisible"] = False
        state["equippedPrefix"] = None
        state["tabHints"] = []
        state["recent"] = []
        return
    if upper == "CHARACTER":
        _save_active(db, state)
        state["active"] = None
        # CHARACTER may include equipment/comparison; never assert a slot.
        state["context"] = "inventory"
        state["bagVisible"] = False
        state["equippedPrefix"] = None
        state["tabHints"] = []
        state["recent"] = []
        return
    chest = CHEST.fullmatch(line)
    if chest and state["context"] == "stash":
        _save_active(db, state)
        state["active"] = None
        tab = int(chest.group(1))
        if tab not in state["tabHints"]:
            state["tabHints"].append(tab)
        state["recent"] = []
        return

    recent = state["recent"]
    # An anchor is always three *consecutive speech* lines. Keyboard marker
    # interleaving does not break the three-line speech window.
    anchor = False
    if len(recent) == 2:
        name, item_type = recent[0], recent[1]
        anchor = is_owned_item_anchor(name["text"], item_type["text"], line)
    if anchor:
        # Exactly three speech lines after EQUIPPED: name, type, power.
        marked_equipped = (state.get("equippedPrefix") is not None
                           and state["speechAfterEquipped"] == 3
                           and state["context"] == "inventory")
        state["equippedPrefix"] = None
        if active is not None:
            # The next name/type were already appended to previous tooltip.
            if len(active["lines"]) >= 2:
                active["lines"] = active["lines"][:-2]
                active["end"] = recent[0]["seq"] - 1
            _save_active(db, state)
        state["active"] = {
            "session": session, "start": recent[0]["seq"], "end": seq,
            "timestamp": recent[0]["timestamp"],
            "location": ({"type": "equipment", "tab": None, "slot": None}
                         if marked_equipped else _location(state)),
            "equippedMarker": marked_equipped,
            "characterBag": bool(state.get("characterInput") and state.get("bagVisible")),
            "tabHints": list(state["tabHints"]), "lines": [
                recent[0]["text"], recent[1]["text"], line],
        }
    elif active is not None:
        active["lines"].append(line)
        active["end"] = seq
        if len(active["lines"]) >= MAX_SEGMENT or (
            upper == "DROP" and active.get("characterBag")
            and active["location"]["type"] == "inventory"
            and {"equip", "mark as junk", "drop"}
                <= {normalize(x).casefold() for x in active["lines"][3:]}
        ):
            _save_active(db, state)
            state["active"] = None

    recent.append({"text": line, "seq": seq, "timestamp": row["timestamp"]})
    del recent[:-2]


def _canonical_text(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _candidate_facts(item: dict[str, Any]) -> dict[str, Any]:
    """Only observed properties; shorter/partially scrolled tooltips are OK."""
    facts: dict[str, Any] = {}
    for row in item.get("baseStats") or []:
        if isinstance(row, dict):
            label = _canonical_text(row.get("kind") or row.get("stat"))
            if label:
                facts["base:" + label] = _canonical_text(
                    row.get("raw") or row.get("value"))
    for row in item.get("affixes") or []:
        if isinstance(row, dict):
            label = _canonical_text(row.get("stat"))
            if label:
                facts["affix:" + label] = _canonical_text(
                    row.get("raw") or row.get("value"))
    if item.get("effectsRaw"):
        facts["effects"] = tuple(sorted(
            _canonical_text(s) for s in item["effectsRaw"]))
    return facts


def _collapse_observation_fingerprints(
    observations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Group repeated readings, never infer physical ownership from a hash.

    Use item identity fields as the bucket and compare known stat/effect facts.
    Partial tooltips merge with a compatible more-complete capture. Conflicting
    values stay separate. Equal physical items with identical stats may merge;
    this is an explicit V1 fingerprint-only tradeoff, not proof of quantity.
    """
    buckets: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for item in observations:
        location = item.get("location") or {}
        core = (
            _canonical_text(location.get("type")),
            location.get("tab"), location.get("slot"),
            _canonical_text(item.get("name")),
            _canonical_text(item.get("itemType")),
            item.get("itemPower"),
            _canonical_text(item.get("rarity")),
            bool(item.get("ancestral")),
        )
        buckets.setdefault(core, []).append(item)

    result: list[dict[str, Any]] = []
    for core, records in buckets.items():
        groups: list[dict[str, Any]] = []
        # Complete evidence first: a shortened/scrolling tooltip is a subset.
        for item in sorted(records, key=lambda v: -len(_candidate_facts(v))):
            facts = _candidate_facts(item)
            matches = [
                group for group in groups
                if all(k not in group["facts"] or group["facts"][k] == v
                       for k, v in facts.items())
                and (set(facts) <= set(group["facts"])
                     or set(group["facts"]) <= set(facts))
            ]
            if matches:
                group = max(matches, key=lambda g: sum(
                    g["facts"].get(k) == v for k, v in facts.items()))
                group["facts"].update(facts)
                group["members"].append(item)
            else:
                groups.append({"facts": dict(facts), "members": [item]})
        for group in groups:
            members = group["members"]
            representative = max(
                members, key=lambda v: (
                    v.get("ownershipStatus") == "CONFIRMED",
                    len(_candidate_facts(v)),
                ),
            )
            digest = hashlib.sha256(json.dumps(
                [core, sorted(group["facts"].items())],
                ensure_ascii=False, separators=(",", ":"),
            ).encode("utf-8")).hexdigest()
            entry = dict(representative)
            # Preserve representative observation provenance in id; hash is separate.
            entry["fingerprint"] = digest
            entry["observationCount"] = len(members)
            first_seen = [m.get("firstSeenAt") for m in members if m.get("firstSeenAt")]
            last_seen = [m.get("lastSeenAt") for m in members if m.get("lastSeenAt")]
            entry["firstSeenAt"] = min(first_seen) if first_seen else None
            entry["lastSeenAt"] = max(last_seen) if last_seen else None
            result.append(entry)
    return result


class OwnedItemsRepository:
    """A materialized, incremental projection; no event-history scan after sync."""

    def __init__(self, character_db: Path, events_db: Path):
        self.character_db = character_db
        self.events_db = events_db

    @staticmethod
    def _schema(db: sqlite3.Connection) -> None:
        db.executescript(
            """CREATE TABLE IF NOT EXISTS owned_item_observation(
                 observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                 source_session_id TEXT NOT NULL,
                 source_seq_start INTEGER NOT NULL,
                 source_seq_end INTEGER NOT NULL,
                 location_type TEXT NOT NULL,
                 item_name TEXT NOT NULL,
                 rarity TEXT,
                 observed_at TEXT NOT NULL,
                 observation_json TEXT NOT NULL,
                 UNIQUE(source_session_id,source_seq_start));
               CREATE INDEX IF NOT EXISTS ix_owned_location
                 ON owned_item_observation(location_type,observation_id);
               CREATE TABLE IF NOT EXISTS owned_item_checkpoint(
                 id INTEGER PRIMARY KEY CHECK(id=1),
                 last_event_rowid INTEGER NOT NULL,
                 state_json TEXT NOT NULL);
            """
        )
        owned_items_scans.schema(db)

    def sync(self, *, limit: int | None = None) -> int:
        """Catch up by canonical row ID. Transactional batch checkpoint.

        Newly installed builds bootstrap from canonical source once. Further
        reads fetch only rows newer than last_event_rowid. Event log is read-only.
        """
        if not self.events_db.is_file():
            return 0
        processed = 0
        with closing(_connect(self.character_db)) as dest, closing(_connect(self.events_db, read_only=True)) as src:
            self._schema(dest)
            cursor = dest.execute(
                "SELECT last_event_rowid,state_json FROM owned_item_checkpoint WHERE id=1"
            ).fetchone()
            last = int(cursor["last_event_rowid"]) if cursor else 0
            state = json.loads(cursor["state_json"]) if cursor else _initial()
            # Derived candidates are replayable; existing equipment and raw
            # canonical event records must never be changed by a migration.
            if state.get("projectionVersion") != PROJECTION_VERSION:
                with dest:
                    dest.execute("DELETE FROM owned_item_observation")
                    dest.execute("DELETE FROM owned_item_checkpoint WHERE id=1")
                last, state = 0, _initial()
            while True:
                batch_size = min(500, max(0, limit - processed)) if limit is not None else 500
                if batch_size == 0:
                    break
                rows = src.execute(
                    """SELECT id,session_id,event_seq,timestamp,type,data_json
                       FROM event_log WHERE id>? ORDER BY id LIMIT ?""",
                    (last, batch_size),
                ).fetchall()
                if not rows:
                    break
                with dest:
                    for row in rows:
                        _consume(dest, state, row)
                        last = int(row["id"])
                        processed += 1
                    dest.execute(
                        """INSERT INTO owned_item_checkpoint(id,last_event_rowid,state_json)
                           VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET
                           last_event_rowid=excluded.last_event_rowid,
                           state_json=excluded.state_json""",
                        (last, json.dumps(state, ensure_ascii=False)),
                    )
                if len(rows) < batch_size:
                    break
        return processed

    def _open_existing(self) -> sqlite3.Connection | None:
        if not self.character_db.is_file():
            return None
        return _connect(self.character_db, read_only=True)

    def _candidates(self, db: sqlite3.Connection, locations: set[str], rarity: str | None) -> list[dict[str, Any]]:
        sql = "SELECT observation_json FROM owned_item_observation"
        clauses = []
        params: list[Any] = []
        if "all" not in locations:
            clauses.append("location_type IN (" + ",".join("?" for _ in locations) + ")")
            params += sorted(locations)
        if rarity:
            clauses.append("LOWER(rarity)=LOWER(?)")
            params.append(rarity)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY observation_id"
        return _collapse_observation_fingerprints(
            [json.loads(r[0]) for r in db.execute(sql, params)]
        )

    def _equipped(self, db: sqlite3.Connection, rarity: str | None) -> list[dict[str, Any]]:
        # Reuse HIGH confidence equipment projection. Do not collapse ring
        # duplicates based on identical hashes or guess character identity.
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='equipment_current'").fetchone():
            return []
        sql = "SELECT * FROM equipment_current WHERE confidence='HIGH'"
        args: list[Any] = []
        if rarity:
            sql += " AND LOWER(json_extract(item_json,'$.rarity'))=LOWER(?)"
            args.append(rarity)
        sql += " ORDER BY slot_family,slot_index,id"
        result = []
        for r in db.execute(sql, args):
            raw = json.loads(r["item_json"])
            result.append({
                "id": "equipped:" + str(r["id"]),
                "name": r["item_name"], "itemType": r["item_type"],
                "itemPower": r["item_power"], "rarity": raw.get("rarity"),
                "ancestral": raw.get("ancestral", False),
                "location": {"type": "equipment", "tab": None, "slot": r["slot_family"]},
                "baseStats": raw.get("base_stats", []),
                "affixes": raw.get("affixes", []),
                "effectsRaw": raw.get("effects_raw", []),
                "metadataRaw": raw.get("metadata_raw", []),
                "ownershipStatus": "CONFIRMED",
                "observationConfidence": r["confidence"],
                "firstSeenAt": r["observed_at"], "lastSeenAt": r["observed_at"],
                "pickedUpAt": None,
                "sourceSessionId": r["source_session_id"],
                "sourceEventSeqStart": r["source_event_seq_start"],
                "sourceEventSeqEnd": r["source_event_seq_end"],
            })
        return result

    def listing(self, *, locations: set[str], rarity: str | None = None,
                include_unverified: bool = False) -> dict[str, Any]:
        self.sync()
        db = self._open_existing()
        try:
            items: list[dict[str, Any]] = []
            tabs: set[int] = set()
            last = None
            count = 0
            if db:
                if "all" in locations or "equipment" in locations:
                    items += self._equipped(db, rarity)
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='owned_item_observation'").fetchone():
                    # Coverage counts include candidates that the default list excludes.
                    rows = db.execute("SELECT observation_json FROM owned_item_observation")
                    for row in rows:
                        obs = json.loads(row[0])
                        if obs["location"]["type"] == "stash":
                            tabs.update(obs.get("locationHints", {}).get("spokenChestTabs", []))
                        count += 1
                    candidates = self._candidates(db, locations, rarity)
                    if include_unverified:
                        items += candidates
                    else:
                        # A verified bag action sequence can confirm the selected
                        # inventory item without a complete grid scan. Do not
                        # expose old unverified tooltip candidates by default.
                        items += [item for item in candidates
                                  if item["location"]["type"] == "inventory"
                                  and item["ownershipStatus"] == "CONFIRMED"]
                checkpoint = db.execute("SELECT state_json FROM owned_item_checkpoint WHERE id=1").fetchone()
                if checkpoint:
                    state = json.loads(checkpoint[0])
                    last = state.get("lastSeenAt")
                    tabs.update(state.get("tabHints", []))
            # Current physical character cannot be assumed from raw speech,
            # so completed scan snapshots are exposed by explicit character
            # scope, never silently mixed into default active-character items.
            scoped, _ = owned_items_scans.coverage(db) if db else ({},[])
            items.sort(key=lambda x: (x["location"]["type"], x["name"].casefold(),
                                     str(x["sourceSessionId"]), x["sourceEventSeqStart"]))
            return {
                "schemaVersion": 1,
                "character": {"id": None, "name": None, "identityConfidence": "UNKNOWN"},
                "coverage": {
                    "overall": "PARTIAL" if items or count else "NOT_SCANNED",
                    "equipment": "PARTIAL" if any(x["location"]["type"] == "equipment" for x in items) else "NOT_SCANNED",
                    "inventory": "PARTIAL" if db and self._count_location(db, "inventory") else "NOT_SCANNED",
                    "stash": {"overall": "PARTIAL" if tabs or (db and self._count_location(db, "stash")) else "NOT_SCANNED",
                              "tabs": [{"tab": n, "status": "PARTIAL", "lastScanAt": None} for n in sorted(tabs)]},
                    "lastEventAt": last,
                    "lastScanAt": None,
                    "observationCandidates": count,
                    "verifiedScopes": scoped,
                    "warning": "Only corroborated CHARACTER/Bag + item-action tooltips confirm inventory. No full scan or slot identity is inferred.",
                },
                "observedTotal": len(items),
                "items": items,
            }
        finally:
            if db:
                db.close()

    @staticmethod
    def _count_location(db: sqlite3.Connection, location: str) -> int:
        return int(db.execute(
            "SELECT COUNT(*) FROM owned_item_observation WHERE location_type=?", (location,)
        ).fetchone()[0])

    def history(self) -> list[dict[str, Any]]:
        self.sync()
        db = self._open_existing()
        if not db:
            return []
        try:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='owned_item_observation'").fetchone():
                return []
            observations=[json.loads(r[0]) for r in db.execute(
                "SELECT observation_json FROM owned_item_observation ORDER BY observation_id")]
            return observations + owned_items_scans.history(db)
        finally:
            db.close()
