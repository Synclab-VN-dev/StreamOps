"""Unified persistent item-current projection for Issue #119.

Only the Engine writes here. CLI readers open character.db read-only and never
consult events.db or trigger a resolver. Historical equipment_current is a
one-time migration INPUT, never an ongoing current-state writer.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any


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

    # One-time, non-destructive migration: keep the legacy table for rollback
    # and audit, but never write to it again after this schema is installed.
    metadata = db.execute(
        "SELECT projection_version FROM item_projection_state WHERE id=1"
    ).fetchone()
    if metadata and int(metadata[0]) >= 2:
        return
    if metadata is None:
        db.execute(
            "INSERT INTO item_projection_state(id,last_event_rowid,revision) VALUES(1,0,0)"
        )
    if metadata is None and _has_table(db, "equipment_current"):
        rows = db.execute(
            "SELECT * FROM equipment_current WHERE confidence='HIGH' ORDER BY id"
        ).fetchall()
        for row in rows:
            legacy = dict(row)
            data = json.loads(legacy["item_json"])
            payload = equipment_payload(
                name=legacy["item_name"],
                item_type=legacy["item_type"],
                item_power=legacy["item_power"],
                raw=data,
                slot=legacy["slot_family"],
                observed_at=legacy["observed_at"],
                session_id=legacy["source_session_id"],
                seq_start=legacy["source_event_seq_start"],
                seq_end=legacy["source_event_seq_end"],
            )
            # Older SQLite fixtures and installs may predate the fingerprint
            # column; include physical legacy row/slot so twin rings survive.
            legacy_fingerprint = legacy.get("item_fingerprint") or hashlib.sha256(
                _json([legacy.get("id"), legacy.get("slot_family"),
                       legacy.get("slot_index"), legacy.get("item_name")])
                .encode("utf-8")).hexdigest()
            upsert(db, "eq:" + legacy_fingerprint, payload,
                   fingerprint=legacy_fingerprint)
    if _has_table(db, "owned_grid_current"):
        # Legacy attested grid snapshots are migrated once, not replayed as
        # fresh events. Keep original physical token/scope when available.
        for row in db.execute("SELECT * FROM owned_grid_current").fetchall():
            old = dict(row)
            payload = json.loads(old["item_json"])
            if payload.get("ownershipStatus") != "CONFIRMED":
                continue
            token = payload.get("trackingToken")
            key = ("grid:" + old["character_id"] + ":token:" + token
                   if token else "grid:" + old["character_id"] +
                   ":slot:" + old["container"] + ":" +
                   str(old["tab_key"]) + ":" + str(old["slot_index"]))
            digest = hashlib.sha256(_json([old["character_id"], token,
                                          payload.get("name"), payload.get("affixes")])
                                    .encode("utf-8")).hexdigest()
            upsert(db, key, payload, fingerprint=digest,
                   scope=old["character_id"])
    db.execute("UPDATE item_projection_state SET projection_version=2 WHERE id=1")



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
    """Persist a confirmed observation; repeated identical speech is no-op."""
    location = payload.get("location") or {}
    where = location.get("type", "unknown")
    if where not in {"equipment", "inventory", "stash", "unknown"}:
        where = "unknown"
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


def record_equipment(db: sqlite3.Connection, observation: Any) -> None:
    item = observation.item
    payload = equipment_payload(
        name=item.name, item_type=item.item_type, item_power=item.item_power,
        raw=item.as_dict(), slot=observation.slot_family,
        observed_at=observation.observed_at, session_id=observation.session_id,
        seq_start=observation.seq_start, seq_end=observation.seq_end)
    key = "eq:" + observation.fingerprint
    # A unique non-ring slot replaces an old item. An unequipped item should
    # remain in inventory only if a separately verified transition proves it.
    if observation.slot_family != "ring":
        mark_location_unknown(db, "location='equipment' AND slot=? AND item_key<>?",
                     (observation.slot_family, key),
                     when=observation.observed_at, session=observation.session_id)
    upsert(db, key, payload, fingerprint=observation.fingerprint)
    if observation.slot_family == "ring":
        rows = db.execute(
            """SELECT item_key FROM item_current
               WHERE location='equipment' AND slot='ring'
               ORDER BY last_seen_at DESC,revision DESC"""
        ).fetchall()
        for row in rows[2:]:
            mark_location_unknown(db, "item_key=?", (row[0],),
                         when=observation.observed_at, session=observation.session_id)


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


def record_equipped_hint(db: sqlite3.Connection, observation: dict[str, Any]) -> None:
    """Preserve EQUIPPED comparison speech as an unverified, read-only current hint.

    Without independently verified slot/action evidence, the item is NOT
    confirmed physically equipped. Repeated NVDA reads do not imply copies.
    """
    if ((observation.get("location") or {}).get("type") != "equipment" or
            observation.get("ownershipEvidence") not in
            {"equipped-marker-v1", "equipped-marker-name-only-v1"}):
        return
    name = str(observation.get("name") or "").strip()
    if not name:
        return
    if db.execute(
        """SELECT 1 FROM item_current WHERE location='equipment'
           AND ownership_status='CONFIRMED' AND name=? LIMIT 1""", (name,)
    ).fetchone():
        return  # stronger observation already present; no duplicate hint
    digest = hashlib.sha256(name.casefold().encode("utf-8")).hexdigest()
    key = "eq-hint:" + digest
    payload = dict(observation)
    existing = db.execute(
        "SELECT item_json FROM item_current WHERE item_key=?", (key,)
    ).fetchone()
    if existing:
        old = json.loads(existing[0])
        # An incomplete re-read cannot wipe stronger typed tooltip evidence.
        if old.get("itemPower") is not None and payload.get("itemPower") is None:
            for field in ("itemType", "itemPower", "rarity", "ancestral",
                          "baseStats", "affixes", "effectsRaw", "metadataRaw",
                          "rawSpeech", "ownershipEvidence"):
                payload[field] = old.get(field)
    payload["location"] = {"type": "equipment", "slot": None, "tab": None}
    payload["ownershipStatus"] = "NOT_CONFIRMED"
    payload["observationConfidence"] = "LOW"
    payload["presenceStatus"] = "OBSERVED_ONLY"
    payload["lastConfirmedAt"] = None
    upsert(db, key, payload, fingerprint=digest)


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
    upsert(db, "bag:" + digest, payload, fingerprint=digest)


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
        upsert(db, key, item, fingerprint=digest, scope=owner)
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
