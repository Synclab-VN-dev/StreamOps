"""Replay exported event_log JSONL in an isolated directory and emit observation JSON.

Set PYTHONPATH to d4planner-be/src. Pass exports in capture order. An optional
character DB must be a tester-provided copy; the tool opens it read-only.
"""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile

from d4planner.character.repository import EquipmentRepository
from d4planner.character.talisman_store import TalismanProjection
from d4planner.runtime.events.model import EventEnvelope
from d4planner.runtime.events.repository import SQLiteEventRepository


def replay(exports, original, root):
    character = root / "character.db"
    if original:
        uri = original.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as source, closing(sqlite3.connect(character)) as db:
            source.backup(db)
    equipment = EquipmentRepository(character)
    original_view = (equipment.projection_revision(), equipment.list_equipment())
    projection = TalismanProjection(character)
    with closing(SQLiteEventRepository(root / "events.db")) as journal:
        for export in exports:
            with export.open(encoding="utf-8") as lines:
                batch = []
                for line in lines:
                    row = json.loads(line)
                    batch.append(EventEnvelope(row["event_seq"], row["type"], row["timestamp"],
                                               row["session_id"], json.loads(row["data_json"])))
                    if len(batch) == 256:
                        journal.append_batch(batch, ignore_duplicates=True)
                        projection.advance(journal)
                        batch.clear()
                journal.append_batch(batch, ignore_duplicates=True)
                while projection.caught_up != journal.last_row_id():
                    projection.advance(journal)
    if original_view != (equipment.projection_revision(), equipment.list_equipment()):
        raise RuntimeError("Equipment changed during Talisman replay")
    with closing(sqlite3.connect(character)) as db:
        db.row_factory = sqlite3.Row
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Character DB integrity check failed")
        return [dict(row) for row in db.execute(
            "SELECT * FROM talisman_observation ORDER BY session_id,start_seq"
        )]


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("exports", type=Path, nargs="+")
    cli.add_argument("--character-copy", type=Path)
    args = cli.parse_args()
    with tempfile.TemporaryDirectory() as directory:
        print(json.dumps(replay(args.exports, args.character_copy, Path(directory)), indent=2))
