"""Read-only DEVELOPMENT source→typed graph snapshot and causal *structural* diffs.

Source data is independently captured public Maxroll build input (not Golden);
the graph contains no unapproved item-to-stat semantics. Only level is a
source-derived numeric candidate. Every other displayed metric stays UNKNOWN.
This module does NOT define the public FormulaGraphResult contract.
"""
from __future__ import annotations
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import graph
import golden_candidate_eval as actual
import source_roll_index as rolls

ALLOWED_CLASSES={"DEV-00":"rogue","DEV-01":"sorcerer"}
# Independently captured full visible-row sidecars (source inventory only, NOT Golden expected).
# Use frozen Git blob identity to ensure no hidden/dropped/rewritten Maxroll UI row
# is silently treated as a complete fixture.
INVENTORY_BLOBS={"DEV-00":"326568feb5159af5e74f65fbdf4628591c014677",
                 "DEV-01":"dcabe1550451b29d1aac6bb991a37c974f84924e"}
INVENTORY_COUNTS={"DEV-00":(50,50),"DEV-01":(49,47)}

def inventory_blob(index):
    raw=(json.dumps(index,ensure_ascii=False,indent=2)+"\n").encode("utf-8")
    return hashlib.sha1(b"blob "+str(len(raw)).encode("ascii")+b"\0"+raw).hexdigest()

DYNAMIC_UNKNOWN=("targetDebuffs","procUptime","transientStacks","snapshotSceneTime")

def demand(cond,reason):graph.reject(cond,reason)

def validate(s,w,index):
    demand(type(s)==dict and set(s)=={
        "artifactType","fixtureId","partition","gamePatch","classId",
        "inputFingerprintSha256","sourceRef","variant","level","skillBar",
        "skillRanks","paragonBoards","extraClassMechanic","sockets",
        "sourceTruths"},"INVALID_DEV_MECHANICS_SOURCE")
    fid=s["fixtureId"]
    demand(fid in ALLOWED_CLASSES and s["classId"]==ALLOWED_CLASSES[fid] and
           s["gamePatch"]=="3.2.1.73552" and
           s["partition"]=="DEVELOPMENT" and
           s["artifactType"]=="DEV_SOURCE_MECHANICS_INPUT_NOT_GOLDEN" and
           s["inputFingerprintSha256"]==w["inputFingerprintSha256"] and
           s["sourceRef"]==w["captureRef"] and
           s["sourceTruths"]=="UNKNOWN_DYNAMIC_COMBAT",
           "DEV_SOURCE_PATCH_CLASS_OR_PROVENANCE_MISMATCH")
    demand(type(s["level"])==int and 1<=s["level"]<=100
           and type(s["variant"])==str and bool(s["variant"]),
           "MISSING_DEV_LEVEL_OR_VARIANT")
    demand(type(s["skillBar"])==list and
           all(type(x)==str and x for x in s["skillBar"]) and
           len(set(s["skillBar"]))==len(s["skillBar"]),
           "INVALID_CAPTURED_SKILL_BAR")
    ranks=s["skillRanks"]
    demand(type(ranks)==dict and len(ranks)>0 and
           all(type(k)==str and k.isdecimal() and
               type(v)==int and 0<=v<=20 for k,v in ranks.items()),
           "INVALID_CAPTURED_SKILL_RANKS")
    boards=s["paragonBoards"]
    demand(type(boards)==list and len(boards)>0 and
           all(type(b)==dict and set(b)=={"id","glyph","glyphLevel","spentNodeIds"}
               and type(b["id"])==str and b["id"] and
               (b["glyph"] is None or type(b["glyph"])==str) and
               type(b["glyphLevel"])==int and 0<=b["glyphLevel"]<=100
               and type(b["spentNodeIds"])==list and
               len(b["spentNodeIds"])==len(set(b["spentNodeIds"]))
               and all(type(k)==str and k.isdecimal() for k in b["spentNodeIds"])
               for b in boards),"INVALID_CAPTURED_PARAGON")
    demand(len({b["id"] for b in boards})==len(boards),"DUPLICATE_CAPTURED_PARAGON")
    demand(type(s["extraClassMechanic"])==list and
           all(x is None or type(x)==str for x in s["extraClassMechanic"]),
           "BAD_CAPTURED_CLASS_MECHANIC")
    sockets=s["sockets"]
    demand(type(sockets)==list and
           len({v["slotId"] for v in sockets})==len(sockets) and
           all(type(v)==dict and set(v)=={"slotId","values"} and
               type(v["slotId"])==str and type(v["values"])==list and
               all(x is None or type(x)==str for x in v["values"])
               for v in sockets),"BAD_CAPTURED_SOCKETS")
    demand({x["slotId"] for x in sockets}==
           {x["slotId"] for x in w["slots"]},"SOURCE_ROLL_SOCKET_SLOT_MISMATCH")
    demand(index["fixtureId"]==fid and index["gamePatch"]==s["gamePatch"]
           and index["classId"]==s["classId"] and
           index["inputFingerprintSha256"]==s["inputFingerprintSha256"],
           "SOURCE_GRAPH_INVENTORY_IDENTITY_MISMATCH")
    demand(len({(x["group"].casefold(),x["metricId"])
                for x in index["metrics"]})==len(index["metrics"]),
           "DUPLICATED_VISIBLE_ROW_POSITION")
    rows=index["metrics"]
    demand((len(rows),len({r["metricId"] for r in rows}))==
           INVENTORY_COUNTS[fid],"INCOMPLETE_VISIBLE_SOURCE_METRIC_DENOMINATOR")
    demand(inventory_blob(index)==INVENTORY_BLOBS[fid],
           "FROZEN_MAXROLL_SOURCE_INVENTORY_CHANGED")
    actual.metadata_fixture(index)

def build(s,w,index,rules):
    validate(s,w,index)
    source=rolls.index(w)
    # Never accept golden/source display as input; do not silently infer NID mapping.
    derived={"fixture":{"class":s["classId"].title(),"gameVersion":s["gamePatch"],
                          "level":s["level"]},
             "currentReadOnlyPublicProfile":{"level":s["level"],
                                              "class":actual.KNOWN_CLASS[s["classId"]]},
             "fingerprints":{"f1InputSnapshotSha256":s["inputFingerprintSha256"]},
             "inputCompleteness":"PARTIAL"}
    # Sorcerer source wrapper (its native capture shape differs from Rogue).
    if s["classId"]=="sorcerer":
        derived={"activeProfile":{"level":s["level"],"class":0},
                 "level":s["level"],"patch":s["gamePatch"],
                 "fingerprints":{"fullInputSha256":s["inputFingerprintSha256"]},
                 "completeness":"PARTIAL"}
    computed=actual.build(derived,index,rules)
    nodes={}
    def add(id_,kind,payload):
        demand(id_ not in nodes,"DUPLICATED_GRAPH_NODE")
        nodes[id_]={"nodeId":id_,"kind":kind,"value":payload}
    add("build/variant","build_variant",s["variant"])
    add("build/level","build_level",s["level"])
    for x in source["contributors"]:
        add("equipment/"+x["sourceId"],"observed_affix_roll",
            {"slotId":x["slotId"],"itemId":x["itemId"],
             "nid":x["nid"],"values":x["values"],
             "sourceGroup":x["sourceGroup"]})
    for x in s["sockets"]:
        for i,v in enumerate(x["values"]):
            add("sockets/"+x["slotId"]+"/"+str(i),"observed_socket",
                {"slotId":x["slotId"],"socketIndex":i,"gemRune":v})
    for sk,rank in sorted(s["skillRanks"].items()):
        add("skill-rank/"+sk,"observed_skill_rank",rank)
    for i,skill in enumerate(s["skillBar"]):
        add("skillbar/"+str(i),"observed_skill_bar",
            {"index":i,"skill":skill})
    for board in s["paragonBoards"]:
        add("paragon/"+board["id"],"observed_paragon",
            {"glyph":board["glyph"],"glyphLevel":board["glyphLevel"],
             "nodeIds":board["spentNodeIds"]})
    for i,v in enumerate(s["extraClassMechanic"]):
        add("classMechanic/"+str(i),"observed_class_mechanic",v)
    for x in computed["characterMetrics"]:
        id_="metric/"+x["group"].casefold()+"/"+x["metricId"]
        add(id_,"projected_metric",{"metricId":x["metricId"],"raw":x["raw"],
            "state":x["status"],"unit":"UNKNOWN_UNVERIFIED",
            "trace":x["trace"]})
    links=[{"from":"build/level",
            "to":"metric/"+r["group"].casefold()+"/"+r["metricId"],
            "kind":"SOURCE_LEVEL_TO_GRAPH_CANDIDATE"}
           for r in computed["characterMetrics"] if r["metricId"]==actual.LEVEL_ID]
    result={
      "artifactType":"DEVELOPMENT_SOURCE_GRAPH_NOT_PUBLIC_BE",
      "fixtureId":s["fixtureId"],"classId":s["classId"],
      "gamePatch":s["gamePatch"],"fixtureInputFingerprint":s["inputFingerprintSha256"],
      "sourceMechanicsSha256":graph.digest(s),"sourceRollIndexSha256":source["indexSha256"],
      "candidateRuleSetSha256":computed["candidateRuleSetSha256"],
      "visibleMetricRows":computed["sourceRowCount"],
      "uniqueMetricIds":computed["uniqueMetricCount"],
      "candidateComputedUnique":computed["computedUniqueMetricCount"],
      "sourceStatActual":computed["characterMetrics"],
      "sourceNodeCount":len(nodes),
      "nodes":[nodes[k] for k in sorted(nodes)],
      "edges":links,
      "scenarioStates":{k:"UNKNOWN" for k in DYNAMIC_UNKNOWN},
      "unmappedObservedRolls":source["rollCount"],
      "sourceUnknownMetricIds":sorted({r["metricId"] for r in computed["characterMetrics"]
                                     if not r["computed"]}),
      "fullVerifiedStatCount":0,
      "sourceGoldenExpectedLoaded":False,
      "holdoutExpectedLoaded":False,
      "simulationContext":None,"publishAllowed":False,
    }
    result["graphSha256"]=graph.digest(result)
    return result

def diff(before,after):
    demand(before["artifactType"]==after["artifactType"]==
           "DEVELOPMENT_SOURCE_GRAPH_NOT_PUBLIC_BE" and
           before["fixtureId"]==after["fixtureId"] and
           before["gamePatch"]==after["gamePatch"],
           "SOURCE_GRAPH_DIFF_CROSS_FIXTURE_OR_PATCH")
    a={x["nodeId"]:graph.digest(x) for x in before["nodes"]}
    b={x["nodeId"]:graph.digest(x) for x in after["nodes"]}
    change={"added":sorted(set(b)-set(a)),"removed":sorted(set(a)-set(b)),
            "changed":sorted(k for k in set(a)&set(b) if a[k]!=b[k])}
    out={"artifactType":"DEVELOPMENT_SOURCE_GRAPH_DIFF",
         "fixtureId":before["fixtureId"],"beforeGraphSha256":before["graphSha256"],
         "afterGraphSha256":after["graphSha256"],
         "sourceChanges":change,"statCandidatesBefore":before["candidateComputedUnique"],
         "statCandidatesAfter":after["candidateComputedUnique"],
         "verifiedGameMetricDelta":0,"independentGoldenParity":"NOT_RUN",
         "publishAllowed":False}
    out["diffSha256"]=graph.digest(out)
    return out
