"""Unified persistent physical item projection for Issue #119.

Only the Engine writes here. CLI readers open character.db read-only and never
consult events.db or trigger a resolver. DEV projection v3 starts clean; historical observed candidates are audit-only.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

from .current_reducer import CurrentItemIntent, CurrentItemReducer


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _has_table(db: sqlite3.Connection, name: str) -> bool:
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def schema(db: sqlite3.Connection) -> None:
    db.executescript("""
    CREATE TABLE IF NOT EXISTS item_current(
        item_key TEXT PRIMARY KEY,
        character_scope TEXT,
        name TEXT NOT NULL,
        item_type TEXT,
        item_power INTEGER,
        rarity TEXT,
        location TEXT NOT NULL CHECK(location IN ('equipment','inventory','stash','unknown')),
        slot TEXT,
        tab INTEGER,
        fingerprint TEXT,
        ownership_status TEXT NOT NULL,
        presence_status TEXT NOT NULL,
        item_json TEXT NOT NULL,
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        last_confirmed_at TEXT,
        source_session_id TEXT NOT NULL,
        source_event_seq_start INTEGER NOT NULL,
        source_event_seq_end INTEGER NOT NULL,
        revision INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS ix_item_current_location
      ON item_current(location, name);
    CREATE TABLE IF NOT EXISTS item_projection_state(
        id INTEGER PRIMARY KEY CHECK(id=1),
        last_engine_session_id TEXT,
        last_event_rowid INTEGER NOT NULL DEFAULT 0,
        revision INTEGER NOT NULL DEFAULT 0,
        projection_version INTEGER NOT NULL DEFAULT 1,
        coverage_json TEXT NOT NULL DEFAULT '{}',
        committed_at TEXT
    );
    """)

    # DEV v3 starts clean. Historical projection tables are intentionally NOT
    # imported into the new physical-item authority (owner-approved DEV reset).
    # Never silently mix an existing v2 database into the new resolver.
    metadata = db.execute(
        "SELECT projection_version FROM item_projection_state WHERE id=1"
    ).fetchone()
    if metadata is None:
        db.execute(
            "INSERT INTO item_projection_state(id,last_event_rowid,revision,"
            "projection_version) VALUES(1,0,0,3)"
        )
    elif int(metadata[0]) != 3:
        raise RuntimeError(
            "Incompatible D4Planner DEV character.db projection; use an "
            "isolated clean PR120 HomeDir. No automatic data deletion."
        )


def _revision(db: sqlite3.Connection, when: str, session: str) -> int:
    db.execute(
        """UPDATE item_projection_state
           SET revision=revision+1, committed_at=?, last_engine_session_id=?
           WHERE id=1""", (when, session)
    )
    return int(db.execute(
        "SELECT revision FROM item_projection_state WHERE id=1"
    ).fetchone()[0])


def equipment_payload(*, name: str, item_type: str, item_power: int,
                      raw: dict[str, Any], slot: str, observed_at: str,
                      session_id: str, seq_start: int, seq_end: int) -> dict[str, Any]:
    return {
        "name": name, "itemType": item_type, "itemPower": item_power,
        "rarity": raw.get("rarity"), "ancestral": bool(raw.get("ancestral")),
        "favorite": bool(raw.get("favorite")),
        "location": {"type": "equipment", "slot": slot, "tab": None},
        "baseStats": raw.get("base_stats", []),
        "affixes": raw.get("affixes", []),
        "effectsRaw": raw.get("effects_raw", []),
        "metadataRaw": raw.get("metadata_raw", []),
        "ownershipStatus": "CONFIRMED", "observationConfidence": "HIGH",
        "presenceStatus": "LAST_CONFIRMED",
        "firstSeenAt": observed_at, "lastSeenAt": observed_at,
        "lastConfirmedAt": observed_at, "pickedUpAt": None,
        "sourceSessionId": session_id,
        "sourceEventSeqStart": seq_start, "sourceEventSeqEnd": seq_end,
    }


def upsert(db: sqlite3.Connection, item_key: str, payload: dict[str, Any],
           *, fingerprint: str, scope: str | None = None) -> bool:
    """Persist a physically confirmed item; reject comparison-only candidates."""
    location = payload.get("location") or {}
    where = location.get("type", "unknown")
    if where not in {"equipment", "inventory", "stash", "unknown"}:
        where = "unknown"
    # Materialized current tracks physically confirmed items only.
    # Comparison and name-only EQUIPPED hints remain in observation history.
    if payload.get("ownershipStatus") != "CONFIRMED":
        return False
    previous = db.execute(
        "SELECT item_json FROM item_current WHERE item_key=?", (item_key,)
    ).fetchone()
    # Comparison excludes observation timestamps: repeated tooltip is a no-op.
    def facts(item: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in item.items()
                if k not in ("id", "firstSeenAt", "lastSeenAt", "lastConfirmedAt",
                             "sourceSessionId", "sourceEventSeqStart",
                             "sourceEventSeqEnd", "revision")}
    if previous and facts(json.loads(previous[0])) == facts(payload):
        return False
    when = str(payload.get("lastSeenAt") or "")
    session = str(payload.get("sourceSessionId") or "")
    revision = _revision(db, when, session)
    saved = dict(payload)
    saved["id"] = item_key
    saved["revision"] = revision
    if previous:
        original = json.loads(previous[0])
        saved["firstSeenAt"] = original.get("firstSeenAt", when)
    db.execute(
        """INSERT INTO item_current(
           item_key,character_scope,name,item_type,item_power,rarity,location,slot,tab,
           fingerprint,ownership_status,presence_status,item_json,
           first_seen_at,last_seen_at,last_confirmed_at,source_session_id,
           source_event_seq_start,source_event_seq_end,revision)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(item_key) DO UPDATE SET
           name=excluded.name,item_type=excluded.item_type,
           item_power=excluded.item_power,rarity=excluded.rarity,
           location=excluded.location,slot=excluded.slot,tab=excluded.tab,
           fingerprint=excluded.fingerprint,ownership_status=excluded.ownership_status,
           presence_status=excluded.presence_status,item_json=excluded.item_json,
           last_seen_at=excluded.last_seen_at,last_confirmed_at=excluded.last_confirmed_at,
           source_session_id=excluded.source_session_id,
           source_event_seq_start=excluded.source_event_seq_start,
           source_event_seq_end=excluded.source_event_seq_end,revision=excluded.revision""",
        (item_key, scope, saved["name"], saved.get("itemType"),
         saved.get("itemPower"), saved.get("rarity"), where,
         location.get("slot"), location.get("tab"), fingerprint,
         saved["ownershipStatus"], saved.get("presenceStatus", "LAST_CONFIRMED"),
         _json(saved), saved["firstSeenAt"], when,
         saved.get("lastConfirmedAt", when), session,
         int(saved.get("sourceEventSeqStart", 0)),
         int(saved.get("sourceEventSeqEnd", 0)), revision)
    )
    return True


class _SqliteItemPort:
    """SQLite adapter; domain reducer imports neither SQLite nor NVDA."""

    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def upsert(self, intent: CurrentItemIntent) -> bool:
        return upsert(self.db, intent.key, dict(intent.payload),
                      fingerprint=intent.fingerprint, scope=intent.scope)

    def invalidate_slot(self, slot: str, except_key: str,
                        intent: CurrentItemIntent) -> None:
        mark_location_unknown(
            self.db, "location='equipment' AND slot=? AND item_key<>?",
            (slot, except_key),
            when=str(intent.payload.get("lastSeenAt") or ""),
            session=str(intent.payload.get("sourceSessionId") or ""))

    def limit_ring_positions(self, intent: CurrentItemIntent) -> None:
        rows = self.db.execute(
            """SELECT item_key FROM item_current
               WHERE location='equipment' AND slot='ring'
               ORDER BY last_seen_at DESC,revision DESC"""
        ).fetchall()
        for row in rows[2:]:
            mark_location_unknown(
                self.db, "item_key=?", (row[0],),
                when=str(intent.payload.get("lastSeenAt") or ""),
                session=str(intent.payload.get("sourceSessionId") or ""))


def record_equipment(db: sqlite3.Connection, observation: Any) -> None:
    item = observation.item
    payload = equipment_payload(
        name=item.name, item_type=item.item_type, item_power=item.item_power,
        raw=item.as_dict(), slot=observation.slot_family,
        observed_at=observation.observed_at, session_id=observation.session_id,
        seq_start=observation.seq_start, seq_end=observation.seq_end)
    CurrentItemReducer(_SqliteItemPort(db)).apply(CurrentItemIntent(
        source="equipped-slot", key="eq:" + observation.fingerprint,
        payload=payload, fingerprint=observation.fingerprint))


def mark_location_unknown(db, where, params, when, session):
    rows = db.execute("SELECT item_key,item_json,fingerprint FROM item_current WHERE "
                      + where, params).fetchall()
    for row in rows:
        item = json.loads(row["item_json"])
        item["location"] = {"type":"unknown","tab":None,"slot":None}
        item["presenceStatus"] = "LOCATION_UNVERIFIED"
        item["lastSeenAt"] = when
        item["sourceSessionId"] = session
        upsert(db,row["item_key"],item,fingerprint=row["fingerprint"] or "")


def remove_where(db: sqlite3.Connection, condition: str, args: tuple[Any, ...],
                 *, when: str, session: str) -> None:
    count = db.execute(
        "DELETE FROM item_current WHERE " + condition, args
    ).rowcount
    if count:
        _revision(db, when, session)


def record_observation(db: sqlite3.Connection, observation: dict[str, Any]) -> None:
    # Owner's NVDA bag context + selected item actions can attest presence.
    # Equipped comparison markers are handled by the equipment projector;
    # copying comparison tooltips here would invent physical equipment slots.
    if (observation.get("ownershipStatus") != "CONFIRMED"
            or (observation.get("location") or {}).get("type") != "inventory"):
        return
    canonical = {
        "name": observation.get("name"),
        "itemType": observation.get("itemType"),
        "itemPower": observation.get("itemPower"),
        "rarity": observation.get("rarity"),
        "ancestral": observation.get("ancestral"),
        "affixes": observation.get("affixes"),
        "baseStats": observation.get("baseStats"),
        "effectsRaw": observation.get("effectsRaw"),
    }
    digest = hashlib.sha256(_json(canonical).encode("utf-8")).hexdigest()
    payload = dict(observation)
    payload["presenceStatus"] = "LAST_CONFIRMED"
    payload["lastConfirmedAt"] = payload.get("lastSeenAt")
    CurrentItemReducer(_SqliteItemPort(db)).apply(CurrentItemIntent(
        source="bag-selected", key="bag:" + digest,
        payload=payload, fingerprint=digest))


def update_cursor(db: sqlite3.Connection, *, session: str,
                  event_rowid: int, observed_at: str) -> None:
    db.execute(
        """UPDATE item_projection_state SET
           last_engine_session_id=?,last_event_rowid=MAX(last_event_rowid,?),
           committed_at=COALESCE(committed_at,?)
           WHERE id=1""", (session, event_rowid, observed_at)
    )


def apply_verified_scan(db: sqlite3.Connection, scan: sqlite3.Row,
                        cells: list[sqlite3.Row], event: sqlite3.Row) -> None:
    """Project a completed, attested grid scan into item_current."""
    owner = scan["character_id"]
    container = scan["container"]
    tab = scan["tab"] if container == "stash" else None
    incoming = set()
    for cell in cells:
        if cell["item_json"] is None:
            continue
        item = json.loads(cell["item_json"])
        token = cell["tracking_token"]
        key = ("grid:" + owner + ":token:" + token if token else
               "grid:" + owner + ":slot:" + container + ":" +
               str(tab) + ":" + str(cell["slot_index"]))
        incoming.add(key)
        item["location"] = {"type": container, "slot": cell["slot_index"],
                            "tab": tab}
        item["ownershipStatus"] = "CONFIRMED"
        item["observationConfidence"] = "HIGH"
        item["presenceStatus"] = "LAST_CONFIRMED"
        item["lastConfirmedAt"] = event["timestamp"]
        item["lastSeenAt"] = event["timestamp"]
        item["sourceSessionId"] = event["session_id"]
        item["sourceEventSeqEnd"] = event["event_seq"]
        digest = hashlib.sha256(_json([owner, token, item.get("name"),
                                       item.get("itemPower"), item.get("affixes")])
                                .encode("utf-8")).hexdigest()
        CurrentItemReducer(_SqliteItemPort(db)).apply(CurrentItemIntent(
            source="verified-grid", key=key, payload=item,
            fingerprint=digest, scope=owner))
    rows = db.execute(
        "SELECT item_key,item_json FROM item_current WHERE character_scope=? "
        "AND location=? AND COALESCE(tab,-1)=COALESCE(?,-1)",
        (owner, container, tab)).fetchall()
    for row in rows:
        if row["item_key"] in incoming:
            continue
        item = json.loads(row["item_json"])
        item["location"] = {"type": "unknown", "slot": None, "tab": None}
        item["presenceStatus"] = "LOCATION_UNVERIFIED"
        item["lastSeenAt"] = event["timestamp"]
        item["sourceSessionId"] = event["session_id"]
        item["sourceEventSeqEnd"] = event["event_seq"]
        upsert(db, row["item_key"], item,
               fingerprint=item.get("fingerprint") or "", scope=owner)


def snapshot(path: Path, *, locations: set[str] | None = None,
             rarity: str | None = None, confirmed_only: bool = False) -> dict[str, Any]:
    """Read committed projection only; no CREATE, REPLAY, MIGRATION or writes."""
    result: dict[str, Any] = {
        "schemaVersion": 2, "revision": 0,
        "character": {"id": None, "name": None, "identityConfidence": "UNKNOWN"},
        "coverage": {"overall": "NOT_SCANNED", "equipment": "NOT_SCANNED",
                     "inventory": "NOT_SCANNED",
                     "stash": {"overall": "NOT_SCANNED", "tabs": []},
                     "observationCandidates": 0},
        "items": [], "observedTotal": 0, "lastCommittedAt": None,
        "warning": "Last-known observations; an unobserved inventory or stash is not a complete scan.",
    }
    if not path.is_file():
        return result
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro",
                                 uri=True, timeout=5)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")  # pin one read snapshot for metadata + item rows
        if not _has_table(db, "item_current"):
            return result
        state = db.execute("SELECT revision,committed_at FROM item_projection_state WHERE id=1").fetchone()
        if state:
            result["revision"] = state["revision"]
            result["lastCommittedAt"] = state["committed_at"]
        query = "SELECT item_json FROM item_current"
        args: list[Any] = []
        conditions: list[str] = []
        if locations and "all" not in locations:
            conditions.append("location IN (" + ",".join("?" for _ in locations) + ")")
            args += sorted(locations)
        if rarity:
            conditions.append("LOWER(rarity)=LOWER(?)")
            args.append(rarity)
        if confirmed_only:
            conditions.append("ownership_status='CONFIRMED'")
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY location,name,item_key"
        result["items"] = [json.loads(row[0]) for row in db.execute(query, args)]
        result["observedTotal"] = len(result["items"])
        for place in ("equipment", "inventory", "stash"):
            val = ("PARTIAL" if any(
                x.get("location", {}).get("type") == place for x in result["items"]
            ) else "NOT_SCANNED")
            if place == "stash":
                result["coverage"]["stash"]["overall"] = val
            else:
                result["coverage"][place] = val
        if result["items"]:
            result["coverage"]["overall"] = "PARTIAL"
    return result
