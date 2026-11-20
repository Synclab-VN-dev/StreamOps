"""Session-scoped, read-only Talisman display evidence for the public HUD."""
from contextlib import closing
import json
import re
import sqlite3


def empty_view(session=None):
    return {"sourceState": "READY", "sessionId": session, "liveSession": bool(session),
            "comparisonObserved": False, "items": []}


def read_talisman(path, active_session):
    view = empty_view(active_session)
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=.1)) as db:
        db.execute("BEGIN")
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='talisman_observation'").fetchone():
            return view
        session = active_session
        if session is None:
            last = db.execute("SELECT session_id FROM talisman_observation ORDER BY rowid DESC LIMIT 1").fetchone()
            if not last:
                return view
            session = last[0]
        view["sessionId"] = session
        view["comparisonObserved"] = bool(db.execute(
            "SELECT 1 FROM talisman_observation WHERE session_id=? AND comparison_name IS NOT NULL LIMIT 1",
            (session,)).fetchone())
        rows = db.execute("""
            SELECT start_seq,kind,name,item_power,item_type,attributes_json,observed_at
            FROM talisman_observation WHERE session_id=? AND role='equipped' ORDER BY start_seq
        """, (session,))
        observed = {}
        for seq, kind, name, power, item_type, raw, timestamp in rows:
            attributes = json.loads(raw)
            if not isinstance(attributes, list) or not all(isinstance(line, str) for line in attributes):
                raise ValueError("Invalid Talisman attributes")
            key = ("seal",) if kind == "seal" else (kind, name, power, item_type, tuple(sorted(attributes)))
            # Keep the original row ID across repeated visits to the same charm.
            item_id = observed[key]["id"] if kind == "charm" and key in observed else f"{session}/{seq}"
            observed[key] = {"id": item_id, "kind": kind, "name": name, "itemPower": power,
                "observedAt": timestamp,
                "affixes": [line for line in attributes if re.match(r"^(?:[+]?[\d,.]+%?\s|Lucky Hit:)", line)],
                "effect": None, "setBonuses": []}
        view["items"] = list(observed.values())
    return view
