"""Paragon primary-attribute contributor extraction from captured ACTIVE UI nodes.

Evidence: F3 observed read-only Paragon tooltips, NOT Maxroll Golden expected,
NOT a complete class stat source, and NOT a production DSL rule.
Never treat these extracted sums as a Character Stat Actual.
"""
from __future__ import annotations
import json
import re
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import graph

STATS = ("Strength", "Intelligence", "Willpower", "Dexterity")
SOURCE_BLOB = "4d14854e0f0abfe234b2e58e270f47db1472b4ff"
SOURCE_COMMIT = "bb4c5cc6b2135583eb708f0a3f374060675b6c0b"
FINGERPRINT = "3ae138cafe3aa4b3633744d0ea5e22b1bd8d92afab77be857906d0b6010cff07"
ATTRIBUTE_LINE = re.compile(r"^\\+(\\d+(?:\\.\\d+)?) (Strength|Intelligence|Willpower|Dexterity)$")

def require(condition, reason):
    graph.reject(condition, reason)

def capture(witness):
    require(type(witness) is dict and
            set(witness) == {"schema","fixtureId","classId","patch",
                             "inputFingerprintSha256","source","meaning","nodes"},
            "INVALID_PARAGON_SOURCE_WITNESS")
    src = witness["source"]
    require(witness["schema"] == "ROGUE_DEV00_PARAGON_TOOLTIP_SOURCE_V1" and
            witness["fixtureId"] == "DEV-00" and witness["classId"] == "rogue" and
            witness["patch"] == "3.2.1.73552" and
            witness["inputFingerprintSha256"] == FINGERPRINT and
            src == {"repo":"Synclab-VN-dev/synclab-agent",
                    "commit":SOURCE_COMMIT,
                    "path":"evidence/StreamOps-106/F3-rogue-50/rogue-50-input-snapshot.json",
                    "gitBlobSha":SOURCE_BLOB} and
            witness["meaning"] == "UI_SOURCE_ONLY_NOT_FULL_PRIMARY_STAT_CONTRIBUTORS_OR_GOLDEN",
            "PARAGON_SOURCE_PROVENANCE_OR_PATCH_INVALID")
    nodes = witness["nodes"]
    require(type(nodes) is list and len(nodes) == 270,
            "PARAGON_NODE_INVENTORY_NOT_270")
    totals = {s:0.0 for s in STATS}
    source_records = []
    unclassified = []
    for i,node in enumerate(nodes):
        require(type(node) is dict and
                set(node) == {"index","boardIndex","className","tooltip"} and
                type(node["index"]) is int and node["index"] == i and
                type(node["boardIndex"]) is int and 0 <= node["boardIndex"] <= 4 and
                type(node["className"]) is str and "d4t-active" in node["className"] and
                type(node["tooltip"]) is str and len(node["tooltip"]) < 2500,
                "PARAGON_SOURCE_NODE_TAMPER_OR_NOT_ACTIVE")
        for line_number, line in enumerate(node["tooltip"].splitlines()):
            m = ATTRIBUTE_LINE.fullmatch(line.strip())
            if m:
                value = float(m.group(1))
                require(0 <= value <= 100, "UNSAFE_PARAGON_FLAT_ATTRIBUTE")
                stat = m.group(2)
                totals[stat] += value
                source_records.append({
                    "nodeIndex":i, "boardIndex":node["boardIndex"],
                    "line":line_number,"stat":stat,"flat":value,
                    "grade":"CAPTURED_ACTIVE_UI_TOOLTIP_NOT_CONTRIBUTOR_VERIFIED"})
            elif re.search(r"(Strength|Intelligence|Willpower|Dexterity)", line, re.I):
                unclassified.append({"nodeIndex":i,"line":line_number,
                                     "reason":"NON_FLAT_OR_CONDITIONAL_ATTRIBUTE_LINE"})
    require(len(source_records) > 0, "PARAGON_NO_OBSERVED_ATTRIBUTE_LINES")
    report = {
        "artifactType":"PARTIAL_PRIMARY_ATTRIBUTE_PARAGON_SOURCE_TRACE",
        "fixtureId":"DEV-00","classId":"rogue","patch":witness["patch"],
        "inputFingerprintSha256":FINGERPRINT,
        "sourceCommit":SOURCE_COMMIT,"sourceBlobSha":SOURCE_BLOB,
        "sourceProjectionSha256":graph.digest(nodes),
        "activeNodeCount":len(nodes),
        "observedFlatAttributeLineCount":len(source_records),
        "observedParagonUiFlatSums":{k:totals[k] for k in STATS},
        "contributions":source_records,
        "unclassifiedAttributeLines":unclassified,
        "sourceCoverage":"PARAGON_UI_ONLY; GLYPH/RARE/GATE_STACKING_NOT_CAUSALLY_VALIDATED",
        "missingContributorFamilies":["CLASS_BASE_AND_LEVEL","ALTARS",
            "ITEM_NID_TO_CORE_STAT","SOCKET_CHARM_AND_SKILL",
            "PARAGON_STACKING_AND_GLYPH_INTERACTIONS"],
        "characterStatActual":{stat:None for stat in STATS},
        "verifiedUniqueMetricIdsAdded":0,
        "independentGoldenCompared":False,
        "holdoutOpened":False,"publishAllowed":False,
        "status":"BLOCKED_INCOMPLETE_PRIMARY_STAT_CONTRIBUTORS"
    }
    report["reportSha256"] = graph.digest(report)
    return report

def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Read-only captured Paragon source contribution audit")
    ap.add_argument("--source",type=Path,required=True)
    ap.add_argument("--report",type=Path,required=True)
    args=ap.parse_args(argv)
    try:
        result = capture(graph.read_json(args.source))
        code=0
    except (graph.GraphError,OSError,KeyError,TypeError,ValueError) as exc:
        result={"status":"BLOCKED_INVALID_SOURCE","reason":str(exc),
                "verifiedUniqueMetricIdsAdded":0,"publishAllowed":False}
        code=2
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(result,indent=2,sort_keys=True)+"\\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k not in
                      ("contributions","unclassifiedAttributeLines")},sort_keys=True))
    return code

if __name__ == "__main__":
    sys.exit(main())
