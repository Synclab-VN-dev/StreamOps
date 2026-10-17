"""Verified grid-scan evidence consumer for Owned Items #119.

This module does not claim that NVDA emits structured slot evidence. Only a
future explicitly attesting grid observer may emit these canonical event types;
speech and keyboard button labels can NEVER trigger a confirmed placement.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

SOURCE = "verified-grid-v1"
BEGIN = "items.scan.begin"
CELL = "items.scan.cell"
END = "items.scan.end"
MOVE = "items.move.verified"
ACTION = "items.action.verified"


def schema(db: sqlite3.Connection) -> None:
    db.executescript("""
        CREATE TABLE IF NOT EXISTS owned_grid_scans(
          scan_id TEXT PRIMARY KEY,
          session_id TEXT NOT NULL, character_id TEXT NOT NULL,
          container TEXT NOT NULL, tab INTEGER,
          expected_slots INTEGER NOT NULL,
          begin_seq INTEGER NOT NULL, end_seq INTEGER,
          completed_at TEXT, status TEXT NOT NULL,
          evidence_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS owned_grid_cells(
          scan_id TEXT NOT NULL, slot_index INTEGER NOT NULL,
          observation_id TEXT, tracking_token TEXT, item_json TEXT,
          PRIMARY KEY(scan_id,slot_index));
        CREATE TABLE IF NOT EXISTS owned_grid_current(
          character_id TEXT NOT NULL, container TEXT NOT NULL,
          tab_key INTEGER NOT NULL, slot_index INTEGER NOT NULL,
          scan_id TEXT NOT NULL, item_json TEXT NOT NULL,
          PRIMARY KEY(character_id,container,tab_key,slot_index));
        CREATE TABLE IF NOT EXISTS owned_grid_history(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          session_id TEXT NOT NULL, event_seq INTEGER NOT NULL,
          kind TEXT NOT NULL, data_json TEXT NOT NULL,
          UNIQUE(session_id,event_seq,kind));
        CREATE INDEX IF NOT EXISTS ix_owned_grid_current_scope
          ON owned_grid_current(character_id,container,tab_key);
    """)


def _valid_begin(payload: dict[str, Any]) -> bool:
    """Reject claims missing direct verified selected-tab/slot census proof."""
    proof = payload.get("proof")
    container = payload.get("container")
    tab = payload.get("tab")
    return (
        payload.get("source") == SOURCE
        and isinstance(payload.get("scanId"), str) and 1 <= len(payload["scanId"]) <= 128
        and isinstance(payload.get("characterId"), str) and bool(payload["characterId"].strip())
        and len(payload["characterId"]) <= 128
        and container in ("inventory", "stash")
        and ((container == "inventory" and tab is None)
             or (container == "stash" and type(tab) is int and 1 <= tab <= 50))
        and type(payload.get("expectedSlots")) is int
        and 1 <= payload["expectedSlots"] <= 512
        and isinstance(proof, dict)
        and proof.get("selectedContainerVerified") is True
        and proof.get("allSlotsAddressable") is True
        and proof.get("emptySlotsVisible") is True
        and proof.get("captureGapFree") is True
        and proof.get("observer") == "grid-observer-v1"
    )


def _record(db: sqlite3.Connection, row: sqlite3.Row, kind: str, data: dict[str, Any]) -> None:
    db.execute("""INSERT OR IGNORE INTO owned_grid_history(
        session_id,event_seq,kind,data_json) VALUES(?,?,?,?)""",
        (row["session_id"], row["event_seq"], kind,
         json.dumps(data, ensure_ascii=False, sort_keys=True)))


def consume(db: sqlite3.Connection, row: sqlite3.Row) -> None:
    """Ingest only explicit attested events; reject malformed and stray events.

    Called in the SAME batch transaction as the owned-item checkpoint.
    """
    event = row["type"]
    if event not in (BEGIN, CELL, END, MOVE):
        return
    try:
        p = json.loads(row["data_json"])
    except (ValueError, TypeError):
        return
    if not isinstance(p, dict) or p.get("source") != SOURCE:
        return

    session, seq = str(row["session_id"]), int(row["event_seq"])
    scan_id = p.get("scanId")
    if event == BEGIN:
        if not _valid_begin(p):
            return
        if db.execute("SELECT 1 FROM owned_grid_scans WHERE scan_id=?", (scan_id,)).fetchone():
            return
        db.execute("""INSERT INTO owned_grid_scans(
          scan_id,session_id,character_id,container,tab,expected_slots,
          begin_seq,status,evidence_json) VALUES(?,?,?,?,?,?,?,'OPEN',?)""",
          (scan_id,session,p["characterId"],p["container"],p.get("tab"),
           p["expectedSlots"],seq,json.dumps(p,ensure_ascii=False)))
        return

    if event == MOVE:
        _consume_move(db,row,p)
        return
    if not isinstance(scan_id,str):
        return
    scan = db.execute("SELECT * FROM owned_grid_scans WHERE scan_id=?", (scan_id,)).fetchone()
    if not scan or scan["session_id"] != session or scan["status"] != "OPEN" or seq <= scan["begin_seq"]:
        return

    if event == CELL:
        slot = p.get("slot")
        if type(slot) is not int or not 0 <= slot < scan["expected_slots"]:
            return
        # An empty slot is explicit evidence; absence of speech is not empty.
        empty = p.get("empty")
        if type(empty) is not bool:
            return
        observation_id, token, item_json = None, None, None
        if not empty:
            observation_id = p.get("observationId")
            if not isinstance(observation_id,str):
                return
            evidence = db.execute("""SELECT observation_json
                FROM owned_item_observation
                WHERE source_session_id=? AND
                      ('obs:' || source_session_id || ':' || source_seq_start)=?""",
                (session,observation_id)).fetchone()
            if not evidence:
                return
            candidate = json.loads(evidence[0])
            if candidate.get("ownershipStatus") != "NOT_CONFIRMED":
                return
            token = p.get("trackingToken")
            if token is not None and (not isinstance(token,str) or not token.strip()):
                return
            item = dict(candidate)
            item["location"] = {"type": scan["container"], "tab": scan["tab"],
                                "slot": slot}
            item["ownershipStatus"] = "CONFIRMED"
            item["observationConfidence"] = "HIGH"
            item["identityConfidence"] = "CHARACTER_SCOPED"
            item["characterId"] = scan["character_id"]
            item["trackingToken"] = token
            item["scanId"] = scan_id
            item_json = json.dumps(item,ensure_ascii=False)
        # Duplicate slot reporting is invalid even if the payload is identical.
        try:
            db.execute("""INSERT INTO owned_grid_cells(
                scan_id,slot_index,observation_id,tracking_token,item_json)
                VALUES(?,?,?,?,?)""",(scan_id,slot,observation_id,token,item_json))
        except sqlite3.IntegrityError:
            db.execute("UPDATE owned_grid_scans SET status='INVALID' WHERE scan_id=?",(scan_id,))
        return

    if event == END:
        cells = db.execute("SELECT * FROM owned_grid_cells WHERE scan_id=? ORDER BY slot_index",
                           (scan_id,)).fetchall()
        if len(cells) != scan["expected_slots"] or any(
            int(c["slot_index"]) != i for i,c in enumerate(cells)
        ):
            db.execute("UPDATE owned_grid_scans SET status='INCOMPLETE' WHERE scan_id=?",(scan_id,))
            return
        tokens = [c["tracking_token"] for c in cells if c["tracking_token"]]
        if len(tokens) != len(set(tokens)):
            db.execute("UPDATE owned_grid_scans SET status='INVALID' WHERE scan_id=?",(scan_id,))
            return
        if p.get("expectedSlots") != scan["expected_slots"] or p.get("captureGapFree") is not True:
            db.execute("UPDATE owned_grid_scans SET status='INVALID' WHERE scan_id=?",(scan_id,))
            return
        key = scan["tab"] if scan["container"]=="stash" else 0
        # No data from one character is silently reused as another's current.
        db.execute("""DELETE FROM owned_grid_current
           WHERE character_id=? AND container=? AND tab_key=?""",
           (scan["character_id"],scan["container"],key))
        for cell in cells:
            if cell["item_json"] is not None:
                db.execute("""INSERT INTO owned_grid_current(
                  character_id,container,tab_key,slot_index,scan_id,item_json)
                  VALUES(?,?,?,?,?,?)""",
                  (scan["character_id"],scan["container"],key,cell["slot_index"],
                   scan_id,cell["item_json"]))
        db.execute("""UPDATE owned_grid_scans SET status='COMPLETE',end_seq=?,
                 completed_at=? WHERE scan_id=?""",(seq,row["timestamp"],scan_id))
        _record(db,row,"SCAN",{"scanId":scan_id,"container":scan["container"],
                              "tab":scan["tab"],"characterId":scan["character_id"],
                              "observedSlots":len(cells),"expectedSlots":scan["expected_slots"]})


def _consume_move(db: sqlite3.Connection, row: sqlite3.Row, p: dict[str, Any]) -> None:
    """Move only with four complete before/after scans and an action event.

    Never correlate two physically distinct items by matching name, power, or
    affixes. A stable observer tracking token is a necessary precondition.
    """
    ids = [p.get(k) for k in ("sourceBefore","destinationBefore",
                               "sourceAfter","destinationAfter")]
    if any(not isinstance(x,str) for x in ids) or len(set(ids)) != 4:
        return
    scans = [db.execute("SELECT * FROM owned_grid_scans WHERE scan_id=? AND status='COMPLETE'",
                        (x,)).fetchone() for x in ids]
    if any(x is None for x in scans):
        return
    sb,dbefore,sa,da = scans
    if any(s["character_id"] != sb["character_id"] for s in scans):
        return
    if any(s["session_id"] != row["session_id"] for s in scans):
        return
    if (sb["container"],sb["tab"]) != (sa["container"],sa["tab"]):
        return
    if (dbefore["container"],dbefore["tab"]) != (da["container"],da["tab"]):
        return
    if (sb["container"],sb["tab"]) == (dbefore["container"],dbefore["tab"]):
        return
    if not (sb["end_seq"] < sa["begin_seq"] and dbefore["end_seq"] < da["begin_seq"]
            and max(sa["end_seq"],da["end_seq"]) < row["event_seq"]):
        return
    source_slot, dest_slot = p.get("sourceSlot"),p.get("destinationSlot")
    if type(source_slot) is not int or type(dest_slot) is not int:
        return
    def cell(scan: sqlite3.Row, slot: int) -> sqlite3.Row | None:
        return db.execute("SELECT * FROM owned_grid_cells WHERE scan_id=? AND slot_index=?",
                          (scan["scan_id"],slot)).fetchone()
    before_from=cell(sb,source_slot)
    before_to=cell(dbefore,dest_slot)
    after_from=cell(sa,source_slot)
    after_to=cell(da,dest_slot)
    if any(x is None for x in [before_from,before_to,after_from,after_to]):
        return
    token=p.get("trackingToken")
    if not isinstance(token,str) or not token.strip():
        return
    if (before_from["tracking_token"]!=token or after_to["tracking_token"]!=token
        or before_to["item_json"] is not None or after_from["item_json"] is not None):
        return
    action_seq=p.get("actionSeq")
    if type(action_seq) is not int:
        return
    # ACTION is separately recorded in canonical event log and tied to a
    # durable source/destination intent, NOT a standalone keyboard key.
    action=db.execute("""SELECT data_json FROM event_log
        WHERE session_id=? AND event_seq=? AND type=?""",
        (row["session_id"],action_seq,ACTION)).fetchone()
    if not action:
        return
    try:
        evidence=json.loads(action["data_json"])
    except (ValueError,TypeError):
        return
    if (not isinstance(evidence,dict) or evidence.get("source")!=SOURCE
        or evidence.get("operation")!="move" or evidence.get("trackingToken")!=token
        or evidence.get("confirmed") is not True
        or evidence.get("characterId")!=sb["character_id"]
        or not max(sb["end_seq"],dbefore["end_seq"]) < action_seq < min(sa["begin_seq"],da["begin_seq"])):
        return
    _record(db,row,"MOVE",{"trackingToken":token,"characterId":sb["character_id"],
         "sourceBefore":sb["scan_id"],"destinationBefore":dbefore["scan_id"],
         "sourceAfter":sa["scan_id"],"destinationAfter":da["scan_id"],
         "sourceSlot":source_slot,"destinationSlot":dest_slot,
         "actionSeq":action_seq,"at":row["timestamp"]})


def current(db: sqlite3.Connection, locations: set[str], rarity: str | None) -> list[dict[str, Any]]:
    if not db.execute("""SELECT 1 FROM sqlite_master WHERE name='owned_grid_current'""").fetchone():
        return []
    sql="SELECT item_json FROM owned_grid_current"
    clauses=[]
    args: list[Any]=[]
    if "all" not in locations:
        clauses.append("container IN ("+",".join("?" for _ in locations)+")")
        args.extend(sorted(locations))
    if clauses:
        sql+=" WHERE "+" AND ".join(clauses)
    result=[]
    for row in db.execute(sql,args):
        item=json.loads(row[0])
        if rarity is None or str(item.get("rarity") or "").casefold()==rarity.casefold():
            result.append(item)
    return result


def coverage(db: sqlite3.Connection) -> tuple[dict[str, Any],list[dict[str, Any]]]:
    """Return only certified complete scans, grouped by character scope.

    A caller with UNKNOWN current character identity must not reinterpret a
    complete historical scan as the current active character inventory.
    """
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='owned_grid_scans'").fetchone():
        return {},[]
    records=[dict(row) for row in db.execute("""SELECT * FROM owned_grid_scans
        WHERE status='COMPLETE' ORDER BY completed_at DESC,scan_id""")]
    result: dict[str, Any]={}
    for scan in records:
        char=scan["character_id"]
        result.setdefault(char,[]).append({
            "scanId":scan["scan_id"],"type":scan["container"],"tab":scan["tab"],
            "status":"SCANNED","lastScanAt":scan["completed_at"],
            "expectedSlots":scan["expected_slots"]})
    return result,records


def history(db: sqlite3.Connection) -> list[dict[str, Any]]:
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='owned_grid_history'").fetchone():
        return []
    return [{"kind":r["kind"],"sessionId":r["session_id"],
             "sourceEventSeq":r["event_seq"],**json.loads(r["data_json"])}
            for r in db.execute("SELECT * FROM owned_grid_history ORDER BY id")]
