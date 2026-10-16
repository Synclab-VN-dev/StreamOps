"""#109 deterministic append-only SYNTHETIC patch ledger; no live registry mutation."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import registry

EVENT_TYPES=("BASELINE","PATCH_CANDIDATE","ROLLBACK")
TAG="SYNTHETIC_ONLY_NEVER_PUBLISH"


def payload(kind, state, parent, seq):
    registry.require(kind in EVENT_TYPES and isinstance(state,dict),"BAD_LEDGER_EVENT")
    registry.require(isinstance(state.get("patch"),str) and
                     isinstance(state.get("rules"),dict),"BAD_LEDGER_STATE")
    registry.require(parent is None or
                     (isinstance(parent,str) and len(parent)==64),"BAD_PARENT_HASH")
    body={"sequence":seq,"kind":kind,"patch":state["patch"],
          "rules":deepcopy(state["rules"]),"parentEventHash":parent,
          "sourceType":TAG,"active":False}
    body["eventHash"]=registry.sha256(body)
    return body


def build(fixture):
    base=registry.simulate_synthetic_patch_cycle(fixture)
    old,new=fixture["old"],fixture["new"]
    events=[]
    for index,(kind,state) in enumerate(zip(EVENT_TYPES,(old,new,old))):
        events.append(payload(kind,state,events[-1]["eventHash"] if events else None,index))
    result={"status":"PASS_SYNTHETIC_LEDGER_ONLY","ledgerVersion":"1.0.0",
            "synthetic":True,"events":events,"oldRulesHash":registry.sha256(old["rules"]),
            "newRulesHash":registry.sha256(new["rules"]),
            "rollbackRulesHash":registry.sha256(events[-1]["rules"]),
            "diff":base["diff"],"activePublish":False,
            "maxrollParity":"NOT_TESTED"}
    result["manifestHash"]=registry.sha256(result)
    verify(result)
    return result


def verify(ledger):
    registry.require(isinstance(ledger,dict) and ledger.get("synthetic") is True
                     and ledger.get("ledgerVersion")=="1.0.0"
                     and ledger.get("status")=="PASS_SYNTHETIC_LEDGER_ONLY"
                     and ledger.get("activePublish") is False
                     and ledger.get("maxrollParity")=="NOT_TESTED","UNSAFE_LEDGER")
    events=ledger.get("events")
    registry.require(isinstance(events,list) and len(events)==3,"INCOMPLETE_EVENT_HISTORY")
    parent=None
    for i,event in enumerate(events):
        registry.require(isinstance(event,dict) and event.get("sequence")==i and
                         event.get("kind")==EVENT_TYPES[i] and
                         event.get("sourceType")==TAG and
                         event.get("active") is False and
                         event.get("parentEventHash")==parent,"BROKEN_LEDGER_CHAIN")
        digest=event.get("eventHash")
        registry.require(isinstance(digest,str) and digest==
                         registry.sha256({k:v for k,v in event.items() if k!="eventHash"}),
                         "MODIFIED_LEDGER_EVENT")
        parent=digest
        registry.require(isinstance(event.get("patch"),str) and
                         isinstance(event.get("rules"),dict),"BROKEN_LEDGER_STATE")
        rules=event["rules"]
        registry.require(all(isinstance(k,str) and isinstance(v,(int,float))
                             and not isinstance(v,bool) for k,v in rules.items()),
                         "UNSAFE_SYNTHETIC_RULES")
    old,new,rollback=events
    registry.require(old["patch"]!=new["patch"] and old["patch"]==rollback["patch"],
                     "PATCH_ORDER_INVALID")
    registry.require(old["rules"]==rollback["rules"] and
                     registry.sha256(old["rules"])==ledger.get("oldRulesHash")==
                     ledger.get("rollbackRulesHash") and
                     registry.sha256(new["rules"])==ledger.get("newRulesHash"),
                     "ROLLBACK_MISMATCH")
    a,b=old["rules"],new["rules"]
    expected={"added":sorted(set(b)-set(a)),
              "removed":sorted(set(a)-set(b)),
              "buffed":sorted(k for k in a.keys() & b.keys() if b[k]>a[k]),
              "nerfed":sorted(k for k in a.keys() & b.keys() if b[k]<a[k]),
              "unchanged":sorted(k for k in a.keys() & b.keys() if b[k]==a[k])}
    registry.require(ledger.get("diff")==expected,"PATCH_DIFF_MISMATCH")
    registry.require(ledger.get("manifestHash")==
                     registry.sha256({k:v for k,v in ledger.items() if k!="manifestHash"}),
                     "LEDGER_MANIFEST_MISMATCH")
    return {"status":"PASS_SYNTHETIC_LEDGER_REPLAY_ONLY","count":3,
            "rolledBackExactly":True,"lastEvent":parent,
            "activePublish":False,"maxrollParity":"NOT_TESTED"}


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--fixture",type=Path,default=HERE/"fixtures"/"synthetic-patch-cycle.json")
    p.add_argument("--report",type=Path,required=True)
    args=p.parse_args(argv)
    try:
        report=build(registry.load(args.fixture))
        code=0
    except (registry.RegistryError,TypeError,KeyError,ValueError,OSError) as e:
        report={"status":"BLOCKED","errors":[str(e)],
                "activePublish":False,"maxrollParity":"NOT_TESTED"}
        code=2
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k!="events"},sort_keys=True))
    return code

if __name__=="__main__":
    sys.exit(main())
