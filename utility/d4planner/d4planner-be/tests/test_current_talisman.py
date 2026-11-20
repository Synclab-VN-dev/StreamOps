import json
import sqlite3
from contextlib import closing

from d4planner.character.current_talisman import read_talisman
from d4planner.character.talisman_store import TalismanProjection


def test_display_evidence_is_scoped_to_session_and_verified_role(tmp_path):
    path = tmp_path / "character.db"
    assert read_talisman(path, "new")["items"] == []
    TalismanProjection(path)
    with closing(sqlite3.connect(path)) as db, db:
        for session, seq, kind, role, name, roll, comparison in [
            ("a",1,"charm","equipped","Same",1,None), ("a",2,"charm","equipped","Same",1,None),
            ("a",3,"charm","equipped","Same",2,None), ("a",4,"seal","equipped","Old",1,None),
            ("a",5,"seal","equipped","New",1,None), ("b",1,"charm","bag","Candidate",3,"Same")]:
            db.execute("INSERT INTO talisman_observation VALUES(?,?,?,?,?,?,NULL,?,?,?,?,?)",
                       (session,seq,seq,str(seq),role,kind,name,"type",850,json.dumps([f"+{roll} Stat"]),comparison))
    items = read_talisman(path,"a")["items"]
    assert [(x["id"],x["name"],x["observedAt"]) for x in items] == [
        ("a/1","Same","2"), ("a/3","Same","3"), ("a/5","New","5")]
    assert read_talisman(path,"b")["items"] == []
    assert read_talisman(path,None) == {"sourceState":"READY","sessionId":"b","liveSession":False,
                                        "comparisonObserved":True,"items":[]}
    assert not read_talisman(path,"new")["comparisonObserved"]
