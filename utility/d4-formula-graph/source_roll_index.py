"""Create lossless source-roll index from captured DEVELOPMENT items, no stat guesses.

Each contributor has a stable (slot,field,array index,nid) source identity.
An affix nid can recur across slots, so never use nid alone as a unique writer.
"""
from __future__ import annotations
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import graph

GROUPS=("explicits","tempered","aspects")
EXPECTED={"DEV-00":("rogue","3ae138cafe3aa4b3633744d0ea5e22b1bd8d92afab77be857906d0b6010cff07"),
          "DEV-01":("sorcerer","2d1af402d8b45a83bdb8d19c87c0bd39ddc7e17b076abf7c49535c60c51de746")}

def check(x,code): graph.reject(x,code)

def index(w):
    check(type(w)==dict and set(w)=={"schema","source","fixtureId","partition",
          "classId","patch","inputFingerprintSha256","captureRef","scope",
          "slots","conditionalContext"}, "INVALID_WITNESS_ROOT")
    fid=w["fixtureId"]
    check(fid in EXPECTED and
          (w["classId"],w["inputFingerprintSha256"])==EXPECTED[fid] and
          w["patch"]=="3.2.1.73552" and w["partition"]=="DEVELOPMENT" and
          w["schema"]=="SOURCE_ROLL_WITNESS_V1" and
          w["source"]=="MAXROLL_PUBLIC_PLANNER_CAPTURE_NOT_GOLDEN" and
          w["scope"]=="ALL_RESOLVED_EQUIPMENT_SLOTS_ONLY" and
          w["captureRef"].startswith("Synclab-VN-dev/synclab-agent@") and
          w["conditionalContext"]=="UNKNOWN_NOT_DEFAULTED",
          "WITNESS_FIXTURE_OR_SOURCE_UNTRUSTED")
    slots=w["slots"]
    check(type(slots)==list and 1<=len(slots)<=40,
          "SOURCE_SLOTS_MISSING")
    seen=set();records=[];groups=Counter();by_nid=Counter()
    for slot in slots:
        check(type(slot)==dict and set(slot)=={"slotId","itemId","itemIndex","fields"},
              "INVALID_ITEM_SOURCE_SHAPE")
        sid=slot["slotId"]
        check(type(sid)==str and sid and sid not in seen and
              type(slot["itemId"])==str and slot["itemId"] and
              type(slot["itemIndex"])==int and
              type(slot["fields"])==dict and set(slot["fields"])==set(GROUPS),
              "BAD_ITEM_SLOT_OR_DUPLICATE")
        seen.add(sid)
        for group in GROUPS:
            v=slot["fields"][group]
            check(type(v)==list and len(v)<=32,"BAD_SOURCE_ROLL_GROUP")
            for offset,roll in enumerate(v):
                check(type(roll)==dict and set(roll)=={"nid","values"} and
                      type(roll["nid"])==int and roll["nid"]>0 and
                      type(roll["values"])==list and len(roll["values"])<=8
                      and all(type(n) in (float,int) and math.isfinite(n)
                              for n in roll["values"]),
                      "BAD_OBSERVED_SOURCE_ROLL")
                nid=roll["nid"];by_nid[nid]+=1;groups[group]+=1
                records.append({"sourceId":f"{sid}/{group}/{offset}/{nid}",
                                "slotId":sid,"itemId":slot["itemId"],
                                "itemIndex":slot["itemIndex"],
                                "sourceGroup":group,"rollIndex":offset,
                                "nid":nid,"values":list(roll["values"]),
                                "sourceGrade":"MAXROLL_CAPTURED_NID_ROLL_ONLY",
                                "metricMappingStatus":"UNKNOWN",
                                "metricIds":[]})
    ids=[r["sourceId"] for r in records]
    check(len(ids)==len(set(ids)),"DUPLICATE_SOURCE_ID")
    out={
        "artifactType":"CAPTURED_SOURCE_ROLLS_NO_VERIFIED_STAT_MAPPINGS",
        "fixtureId":fid,"classId":w["classId"],"patch":w["patch"],
        "sourceFingerprint":w["inputFingerprintSha256"],
        "sourceWitnessSha256":graph.digest(w),
        "slotCount":len(slots),"rollCount":len(records),
        "groupCounts":dict(sorted(groups.items())),
        "uniqueNidCount":len(by_nid),
        "repeatedNids":{str(n):c for n,c in sorted(by_nid.items()) if c>1},
        "contributors":records,
        "mappedStatCount":0,"computedRealStatsFromAffixes":0,
        "conditionalState":"UNKNOWN_NOT_DEFAULTED",
        "sourceCompleteness":"EQUIPMENT_WITNESS_ONLY_NOT_CHARACTER_INPUT_COMPLETE",
        "parity":"NOT_RUN","publishAllowed":False,"simulationContext":None,
    }
    out["indexSha256"]=graph.digest(out)
    return out

def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--source",type=Path,required=True)
    p.add_argument("--report",type=Path,required=True)
    a=p.parse_args(argv)
    try:
        output=index(graph.read_json(a.source));status=0
    except (OSError,ValueError,TypeError,KeyError,graph.GraphError) as error:
        output={"status":"BLOCKED","reason":str(error),"publishAllowed":False};status=2
    a.report.parent.mkdir(parents=True,exist_ok=True)
    a.report.write_text(json.dumps(output,indent=2,sort_keys=True)+"\n")
    print(json.dumps({k:v for k,v in output.items() if k!="contributors"},
                     sort_keys=True))
    return status
if __name__=="__main__":sys.exit(main())
