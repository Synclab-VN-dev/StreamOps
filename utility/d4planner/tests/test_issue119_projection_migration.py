"""#119 migration/replay contract and conservative context regression."""
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from d4planner.character.owned_items import OwnedItemsRepository, PROJECTION_VERSION

class ProjectionMigration(unittest.TestCase):
    def test_previous_checkpoint_rebuilds_only_derived_observations(self):
        with TemporaryDirectory() as d:
            dbfile = Path(d)/"events.db"
            target = Path(d)/"character.db"
            speech = ["STASH", "CHEST 1", "STAFF IN STASH", "Legendary Staff",
                      "900 Item Power", "Take", "CHEST 2"]
            with closing(sqlite3.connect(dbfile)) as db, db:
                db.execute("CREATE TABLE event_log(id INTEGER PRIMARY KEY,session_id TEXT,event_seq INTEGER,timestamp TEXT,type TEXT,data_json TEXT)")
                for i,txt in enumerate(speech,1):
                    db.execute("INSERT INTO event_log VALUES(?,?,?,?,?,?)", (i,"capture-A",i,"2026-10-17T10:00:00+07:00","speech.raw",json.dumps({"text":txt})))
            repo = OwnedItemsRepository(target,dbfile)
            with closing(sqlite3.connect(target)) as db, db:
                repo._schema(db)
                db.execute("INSERT INTO owned_item_checkpoint VALUES(1, ?, ?)",
                           (len(speech),json.dumps({"projectionVersion":1,"session":"capture-A","context":"stash","tabHints":[1,2],"recent":[],"active":None})))
            source_bytes = dbfile.read_bytes()
            obs = repo.listing(locations={"all"},include_unverified=True)
            self.assertEqual(obs["observedTotal"],1)
            self.assertEqual(obs["items"][0]["name"],"STAFF IN STASH")
            self.assertIsNone(obs["items"][0]["location"]["tab"])
            self.assertEqual(repo.sync(),0)
            self.assertEqual(dbfile.read_bytes(),source_bytes)
            with closing(sqlite3.connect(target)) as db:
                raw = db.execute("SELECT last_event_rowid,state_json FROM owned_item_checkpoint WHERE id=1").fetchone()
                self.assertEqual(raw[0],len(speech))
                self.assertEqual(json.loads(raw[1])["projectionVersion"],PROJECTION_VERSION)

    def test_chunk_boundary_and_resume_without_duplicate(self):
        with TemporaryDirectory() as d:
            events,target = Path(d)/"events.db",Path(d)/"character.db"
            with closing(sqlite3.connect(events)) as db,db:
                db.execute("CREATE TABLE event_log(id INTEGER PRIMARY KEY,session_id TEXT,event_seq INTEGER,timestamp TEXT,type TEXT,data_json TEXT)")
                for i,txt in enumerate(["CHARACTER","RING A","Legendary Ring","850 Item Power","CHARACTER"],1):
                    db.execute("INSERT INTO event_log VALUES(?,?,?,?,?,?)",(i,"s1",i,"2026-10-17T10:00:00+07:00","speech.raw",json.dumps({"text":txt})))
            repo=OwnedItemsRepository(target,events)
            self.assertEqual(repo.sync(limit=3),3)
            with closing(sqlite3.connect(target)) as check:
                self.assertEqual(check.execute("SELECT COUNT(*) FROM owned_item_observation").fetchone()[0],0)
            self.assertEqual(repo.sync(),2)
            self.assertEqual(len(repo.history()),1)
            self.assertEqual(repo.sync(),0)
            self.assertEqual(len(repo.history()),1)
if __name__ == "__main__":
    unittest.main()
