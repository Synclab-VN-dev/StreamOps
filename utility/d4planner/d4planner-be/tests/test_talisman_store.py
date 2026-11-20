import sqlite3
from contextlib import closing

import pytest

from d4planner.character.talisman_store import TalismanProjection
from d4planner.runtime.events.repository import SQLiteEventRepository
from test_talisman import speech


def test_reopen_during_tooltip_and_retry_failed_transaction(tmp_path):
    source = SQLiteEventRepository(tmp_path / "events.db")
    path = tmp_path / "character.db"
    try:
        source.append_batch([speech(i, t) for i, t in enumerate(
            ["Seal", "EQUIPPED", "FIRST SEAL", "Legendary Horadric Seal", "850 Item Power"], 1)])
        TalismanProjection(path).advance(source)
        projection = TalismanProjection(path)
        source.append_batch([speech(6, "Bottom action button"), speech(7, "Move"), speech(8, "Unequip")])
        with closing(sqlite3.connect(path)) as db:
            db.execute("""CREATE TRIGGER interrupt BEFORE INSERT ON talisman_observation
                          BEGIN SELECT RAISE(ABORT,'interrupted'); END""")
            with pytest.raises(sqlite3.IntegrityError):
                projection.advance(source)
            assert db.execute("SELECT event_seq FROM talisman_checkpoint").fetchone() == (5,)
            db.execute("DROP TRIGGER interrupt")
            projection.advance(source)
            TalismanProjection(path).advance(source)
            assert db.execute("SELECT name,slot_index FROM talisman_equipped_observations").fetchall() == [
                ("FIRST SEAL", None)]
    finally:
        source.close()
