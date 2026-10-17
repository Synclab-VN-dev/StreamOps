"""#119 certified grid snapshot/move evidence — synthetic contract tests.

No test claims that the current Real-A NVDA producer emits structured grid
events. They exercise a future evidence interface fail-closed.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from d4planner.character.owned_items import OwnedItemsRepository
from d4planner.character import owned_items_scans as gates


class GridEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root=Path(self.dir.name)
        (self.root/"state").mkdir()
        self.src=self.root/"state"/"events.db"
        self.dst=self.root/"state"/"character.db"
        with closing(sqlite3.connect(self.src)) as db,db:
            db.execute("""CREATE TABLE event_log(
              id INTEGER PRIMARY KEY,session_id TEXT,event_seq INTEGER,
              timestamp TEXT,type TEXT,data_json TEXT,
              UNIQUE(session_id,event_seq))""")
        self.seq=0
        self.session="synthetic-grid-session"

    def event(self,kind,payload):
        self.seq += 1
        with closing(sqlite3.connect(self.src)) as db,db:
            db.execute("""INSERT INTO event_log(session_id,event_seq,timestamp,type,data_json)
                        VALUES(?,?,?,?,?)""",
                       (self.session,self.seq,"2026-10-17T16:00:00+07:00",
                        kind,json.dumps(payload,ensure_ascii=False)))
        return self.seq

    def item(self,name="TWIN RING"):
        first=self.seq+1
        for text in (name,"Legendary Ring","900 Item Power","CHARACTER"):
            self.event("speech.raw",{"text":text})
        return f"obs:{self.session}:{first}"

    def scan(self,scan_id,container,slots, *,tab=None,character="sorc-1",
             proof=None,expected=None,gap_free=True):
        evidence={"selectedContainerVerified":True,"allSlotsAddressable":True,
                  "emptySlotsVisible":True,"captureGapFree":True,
                  "observer":"grid-observer-v1"} if proof is None else proof
        self.event(gates.BEGIN,{"source":gates.SOURCE,"scanId":scan_id,
            "container":container,"tab":tab,"characterId":character,
            "expectedSlots":expected or len(slots),"proof":evidence})
        for i,cell in enumerate(slots):
            event={"source":gates.SOURCE,"scanId":scan_id,
                   "slot":i,"empty":cell is None}
            if cell is not None:
                observation,token=cell
                event.update({"observationId":observation,"trackingToken":token})
            self.event(gates.CELL,event)
        self.event(gates.END,{"source":gates.SOURCE,"scanId":scan_id,
            "expectedSlots":expected or len(slots),"captureGapFree":gap_free})

    def repo(self):
        return OwnedItemsRepository(self.dst,self.src)

    def db(self):
        db=sqlite3.connect(self.dst)
        db.row_factory=sqlite3.Row
        return closing(db)

    def test_complete_explicit_scan_has_positioned_items_and_character_scope(self):
        obs=self.item()
        self.scan("grid-one","inventory",[(obs,"physical-A"),None],expected=2)
        repo=self.repo()
        default=repo.listing(locations={"all"})
        self.assertEqual(default["items"],[])  # Active identity is UNKNOWN.
        self.assertEqual(default["coverage"]["overall"],"PARTIAL")
        self.assertEqual(len(default["coverage"]["verifiedScopes"]["sorc-1"]),1)
        self.assertEqual(default["coverage"]["verifiedScopes"]["sorc-1"][0]["expectedSlots"],2)
        with self.db() as db:
            rows=gates.current(db,{"all"},None)
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]["name"],"TWIN RING")
            self.assertEqual(rows[0]["location"],{"type":"inventory","tab":None,"slot":0})
            self.assertEqual(rows[0]["ownershipStatus"],"CONFIRMED")
            self.assertEqual(rows[0]["characterId"],"sorc-1")
        self.assertEqual(len([h for h in repo.history() if h.get("kind")=="SCAN"]),1)
        self.assertEqual(repo.sync(),0)

    def test_multiple_tabs_duplicate_name_keep_independent_physical_slots(self):
        first=self.item("SAME RING")
        second=self.item("SAME RING")
        self.scan("tab-one","stash",[(first,"token-1")],tab=1)
        self.scan("tab-two","stash",[(second,"token-2")],tab=2)
        result=self.repo().listing(locations={"stash"})
        self.assertEqual(result["items"],[])  # No current-character proof.
        self.assertEqual(len(result["coverage"]["verifiedScopes"]["sorc-1"]),2)
        with self.db() as db:
            rows=gates.current(db,{"stash"},None)
            self.assertEqual(len(rows),2)
            self.assertEqual({x["location"]["tab"] for x in rows},{1,2})
            self.assertEqual({x["trackingToken"] for x in rows},{"token-1","token-2"})

    def test_missing_cell_wrong_tab_proof_and_unsupported_speech_fail_closed(self):
        obs=self.item()
        self.scan("missing-cell","inventory",[(obs,"token")],expected=2)
        self.scan("unverified-tab","stash",[(obs,"token")],tab=1,
                  proof={"observer":"grid-observer-v1",
                         "selectedContainerVerified":False,
                         "allSlotsAddressable":True,"emptySlotsVisible":True,
                         "captureGapFree":True})
        self.scan("missing-observation","inventory",[("obs:fake:1","token")])
        self.event("input.marker.raw",{"controlId":"A","state":"up",
                                       "suppressed":True})
        repo=self.repo()
        result=repo.listing(locations={"all"})
        self.assertEqual(result["coverage"]["verifiedScopes"],{})
        with self.db() as db:
            self.assertEqual(gates.current(db,{"all"},None),[])
            self.assertEqual(db.execute("SELECT status FROM owned_grid_scans WHERE scan_id='missing-cell'").fetchone()[0],
                             "INCOMPLETE")
            self.assertFalse(db.execute("SELECT 1 FROM owned_grid_scans WHERE scan_id='unverified-tab'").fetchone())
        self.assertEqual(repo.sync(),0)

    def test_move_requires_four_complete_scans_and_separate_verified_action(self):
        obs=self.item()
        self.scan("source-before","inventory",[(obs,"physical-A")])
        self.scan("dest-before","stash",[None],tab=2)
        self.event(gates.ACTION,{"source":gates.SOURCE,"observer":"grid-observer-v1",
           "operation":"move","confirmed":True,"trackingToken":"physical-A",
           "characterId":"sorc-1"})
        action_seq=self.seq
        self.scan("source-after","inventory",[None])
        self.scan("dest-after","stash",[(obs,"physical-A")],tab=2)
        move={"source":gates.SOURCE,"sourceBefore":"source-before",
              "destinationBefore":"dest-before",
              "sourceAfter":"source-after","destinationAfter":"dest-after",
              "sourceSlot":0,"destinationSlot":0,
              "trackingToken":"physical-A","actionSeq":action_seq}
        self.event(gates.MOVE,move)
        history=self.repo().history()
        events=[h for h in history if h.get("kind")=="MOVE"]
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]["actionSeq"],action_seq)
        with self.db() as db:
            self.assertEqual(len(gates.current(db,{"inventory"},None)),0)
            self.assertEqual(len(gates.current(db,{"stash"},None)),1)
        self.assertEqual(self.repo().sync(),0)
        self.assertEqual(len([x for x in self.repo().history() if x.get("kind")=="MOVE"]),1)

    def test_equip_and_unequip_require_explicit_action_provenance(self):
        obs=self.item("EQUIPMENT RING")
        self.scan("bag-before","inventory",[(obs,"ring-one")])
        self.scan("gear-before","equipment",[None])
        self.event(gates.ACTION,{"source":gates.SOURCE,"observer":"grid-observer-v1",
           "operation":"equip","confirmed":True,"trackingToken":"ring-one",
           "characterId":"sorc-1"})
        action=self.seq
        self.scan("bag-after","inventory",[None])
        self.scan("gear-after","equipment",[(obs,"ring-one")])
        self.event(gates.EQUIP,{"source":gates.SOURCE,
            "sourceBefore":"bag-before","destinationBefore":"gear-before",
            "sourceAfter":"bag-after","destinationAfter":"gear-after",
            "sourceSlot":0,"destinationSlot":0,
            "trackingToken":"ring-one","actionSeq":action})
        history=self.repo().history()
        self.assertEqual(len([h for h in history if h.get("kind")=="EQUIP"]),1)
        with self.db() as db:
            gear=gates.current(db,{"equipment"},None)
            self.assertEqual(len(gear),1)
            self.assertEqual(gear[0]["characterId"],"sorc-1")
        # Identical speech, button label, or an invented action seq must not
        # create an UNEQUIP transition without four certified scans.
        self.event("speech.raw",{"text":"UNEQUIPPED"})
        self.event(gates.UNEQUIP,{"source":gates.SOURCE,
            "sourceBefore":"gear-after","destinationBefore":"bag-after",
            "sourceAfter":"bag-before","destinationAfter":"gear-before",
            "sourceSlot":0,"destinationSlot":0,"trackingToken":"ring-one",
            "actionSeq":action})
        self.assertEqual(len([h for h in self.repo().history() if h.get("kind")=="UNEQUIP"]),0)

    def test_removal_requires_two_full_scans_action_and_explicit_reason(self):
        obs=self.item("UNIQUE RING")
        self.scan("before-remove","inventory",[(obs,"physical-id")])
        # No action: disappearing from a partial scan is not a removal.
        self.scan("incomplete-remove","inventory",[None],expected=2)
        self.event(gates.REMOVE,{"source":gates.SOURCE,"sourceBefore":"before-remove",
            "sourceAfter":"incomplete-remove","sourceSlot":0,
            "trackingToken":"physical-id","actionSeq":123})
        self.assertEqual(len([x for x in self.repo().history() if x.get("kind")=="REMOVAL"]),0)
        self.event(gates.ACTION,{"source":gates.SOURCE,"observer":"grid-observer-v1",
            "operation":"remove","confirmed":True,"reason":"salvage",
            "trackingToken":"physical-id","characterId":"sorc-1"})
        action=self.seq
        self.scan("after-remove","inventory",[None])
        self.event(gates.REMOVE,{"source":gates.SOURCE,"sourceBefore":"before-remove",
            "sourceAfter":"after-remove","sourceSlot":0,
            "trackingToken":"physical-id","actionSeq":action})
        result=self.repo().history()
        removal=[h for h in result if h.get("kind")=="REMOVAL"]
        self.assertEqual(len(removal),1)
        self.assertEqual(removal[0]["reason"],"salvage")
        self.assertEqual(self.repo().sync(),0)
        self.assertEqual(len([h for h in self.repo().history() if h.get("kind")=="REMOVAL"]),1)

    def test_mixed_cli_sqlite_e2e_two_stash_tabs_duplicate_and_move(self):
        # One canonical source session: duplicate rings, inventory,
        # equipment (legacy confirmed), two certified stash tabs, explicit move.
        from contextlib import redirect_stdout
        from io import StringIO
        import os
        from d4planner.cli import main
        first=self.item("DUPLICATE RING")
        second=self.item("DUPLICATE RING")
        self.scan("inventory-before","inventory",[(first,"track-A")])
        self.scan("stash1","stash",[(second,"track-B")],tab=1)
        self.scan("stash2-before","stash",[None],tab=2)
        self.event(gates.ACTION,{"source":gates.SOURCE,"observer":"grid-observer-v1",
            "operation":"move","confirmed":True,"trackingToken":"track-A",
            "characterId":"sorc-1"})
        action=self.seq
        self.scan("inventory-after","inventory",[None])
        self.scan("stash2-after","stash",[(first,"track-A")],tab=2)
        self.event(gates.MOVE,{"source":gates.SOURCE,
            "sourceBefore":"inventory-before","destinationBefore":"stash2-before",
            "sourceAfter":"inventory-after","destinationAfter":"stash2-after",
            "sourceSlot":0,"destinationSlot":0,"trackingToken":"track-A",
            "actionSeq":action})
        # Preserve equipment compatibility while querying same SQLite database.
        self.repo().sync()
        with self.db() as db, db:
            db.execute("""CREATE TABLE equipment_current(
                id INTEGER PRIMARY KEY,slot_family TEXT,slot_index INTEGER,
                item_name TEXT,item_type TEXT,item_power INTEGER,item_json TEXT,
                observed_at TEXT,source_session_id TEXT,source_event_seq_start INTEGER,
                source_event_seq_end INTEGER,confidence TEXT)""")
            db.execute("""INSERT INTO equipment_current VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (1,"helm",0,"CONFIRMED HELM","Helm",900,
                        json.dumps({"rarity":"Legendary"}),
                        "2026-10-17T16:00:00+07:00",self.session,1,4,"HIGH"))
        old=os.environ.get("D4PLANNER_HOME")
        os.environ["D4PLANNER_HOME"]=str(self.root)
        try:
            def invoke(*args):
                output=StringIO()
                with redirect_stdout(output):
                    rc=main(["items",*args])
                self.assertEqual(rc,0)
                return json.loads(output.getvalue())
            listed=invoke("--json")
            self.assertEqual([x["name"] for x in listed["items"]],["CONFIRMED HELM"])
            self.assertEqual(listed["coverage"]["overall"],"PARTIAL")
            scoped=listed["coverage"]["verifiedScopes"]["sorc-1"]
            self.assertEqual({(x["type"],x["tab"]) for x in scoped},
                             {("inventory",None),("stash",1),("stash",2)})
            # Raw speech candidates are explicit opt-in, even for certified
            # character-scoped observations.
            candidates=invoke("--json","--include-unverified")
            self.assertEqual(len([x for x in candidates["items"]
                                  if x["ownershipStatus"]=="NOT_CONFIRMED"]),2)
            with self.db() as db:
                physical=gates.current(db,{"all"},None)
                self.assertEqual(len(physical),2)
                self.assertEqual({x["location"]["tab"] for x in physical},{1,2})
                self.assertEqual({x["trackingToken"] for x in physical},{"track-A","track-B"})
            history=invoke("history","--json")["observations"]
            self.assertEqual(len([x for x in history if x.get("kind")=="MOVE"]),1)
            output=self.root/"verified-owned-history.jsonl"
            out=StringIO()
            with redirect_stdout(out):
                rc=main(["items","export","--format","jsonl","--output",str(output)])
            self.assertEqual(rc,0)
            written=[json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(written,history)
            self.assertEqual(len([x for x in written if x.get("kind")=="MOVE"]),1)
        finally:
            if old is None: os.environ.pop("D4PLANNER_HOME",None)
            else: os.environ["D4PLANNER_HOME"]=old

    def test_no_move_from_identical_names_or_missing_action_or_cross_character(self):
        obs=self.item()
        self.scan("s-before","inventory",[(obs,"a")])
        self.scan("d-before","stash",[None],tab=1)
        self.scan("s-after","inventory",[None])
        self.scan("d-after","stash",[(obs,"a")],tab=1)
        p={"source":gates.SOURCE,"sourceBefore":"s-before","destinationBefore":"d-before",
           "sourceAfter":"s-after","destinationAfter":"d-after",
           "sourceSlot":0,"destinationSlot":0,"trackingToken":"a","actionSeq":777}
        self.event(gates.MOVE,p)
        self.assertFalse([x for x in self.repo().history() if x.get("kind")=="MOVE"])
        self.scan("other-character","stash",[(obs,"a")],tab=1,character="other-character")
        self.repo().sync()  # Materialize appended source before inspecting its DB
        with self.db() as db:
            self.assertEqual(len(gates.current(db,{"stash"},None)),2)
            self.assertFalse(db.execute("SELECT 1 FROM owned_grid_history WHERE kind='MOVE'").fetchone())
        self.assertEqual(self.repo().sync(),0)


if __name__=="__main__":
    unittest.main()
