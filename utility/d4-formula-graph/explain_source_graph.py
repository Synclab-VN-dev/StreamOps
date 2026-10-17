"""Explain complete source Graph + independent frozen-UI G4 audit for review.

This is a human-readable source/UNKNOWN report. Does NOT assert any unverified
affix/effect formula or independent Golden numeric parity.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import graph

def explain(actual,audit):
    graph.reject(type(actual)==dict and type(audit)==dict,
                 "INVALID_GRAPH_EXPLANATION_INPUT")
    graph.reject(actual.get("artifactType")=="DEVELOPMENT_SOURCE_GRAPH_NOT_PUBLIC_BE"
                 and audit.get("artifactType")==
                 "DEVELOPMENT_G4_VISIBLE_METRIC_COVERAGE_NOT_GOLDEN_PARITY"
                 and actual.get("fixtureId")==audit.get("fixtureId")
                 and actual.get("graphSha256")==audit.get("sourceGraphSha256"),
                 "G4_EXPLANATION_WRONG_SOURCE_GRAPH")
    graph.reject(actual.get("graphSha256")==graph.digest(
            {k:v for k,v in actual.items() if k!="graphSha256"}) and
            audit.get("auditSha256")==graph.digest(
            {k:v for k,v in audit.items() if k!="auditSha256"}),
            "G4_EXPLANATION_TAMPERED_EVIDENCE")
    graph.reject(actual.get("sourceGoldenExpectedLoaded") is False and
                 audit.get("goldenReferenceLoaded") is False and
                 actual.get("publishAllowed") is False and
                 audit.get("ownerApprovedGolden") is False and
                 audit.get("fullCapturedFixtureParity")=="BLOCKED_NOT_VERIFIED",
                 "G4_EXPLANATION_FALSE_APPROVAL")
    rows=audit["rows"]
    graph.reject(len(rows)==audit["visibleMetricRows"] and
                 sum(x["visible"] for x in audit["groupCoverage"].values())==len(rows),
                 "MISSING_VISIBLE_METRIC_EXPLANATION")
    result=[
        "# Maxroll Development Graph — Evidence-Only Explanation",
        "",
        f"- Fixture: **{actual['fixtureId']}** / class **{actual['classId']}**",
        f"- Patch: **{actual['gamePatch']}**",
        f"- Graph SHA-256: \`{actual['graphSha256']}\`",
        f"- Source input fingerprint: \`{actual['fixtureInputFingerprint']}\`",
        f"- Captured source nodes: **{actual['sourceNodeCount']}**; "
        f"observed affix/aspect roll records: **{actual['unmappedObservedRolls']}**",
        f"- Visible UI metric rows: **{audit['visibleMetricRows']}**; "
        f"distinct metric IDs: **{audit['distinctMetricIds']}**",
        f"- Formula verified: **0**; Golden parity: **BLOCKED**; "
        "HOLDOUT expected: **NOT OPENED**",
        "",
        "## Per-group source coverage (not Golden parity)",
        "",
        "| Group | Visible rows | Candidate unverified | Unknown | Missing | Stale | Unsupported/NA |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name,group in sorted(audit["groupCoverage"].items()):
        result.append(
          f"| {name} | {group['visible']} | {group['CANDIDATE_UNVERIFIED']} | "
          f"{group['UNKNOWN']} | {group['MISSING_GRAPH_ROW']} | "
          f"{group['STALE_SOURCE']} | "
          f"{group['UNSUPPORTED']+group['UNAVAILABLE']+group['NOT_APPLICABLE']} |"
        )
    result.extend(["","## Every captured visible metric", "",
                   "| Source group | Metric ID | Maxroll label | Evidence status | Explanation |",
                   "|---|---|---|---|---|"])
    for x in rows:
        reason=x["sourceReason"] or "UNPROVEN_RUNTIME_CONTRIBUTOR"
        result.append(f"| {x['group']} | \`{x['metricId']}\` | {x['label']} "
                      f"| {x['state']} | {reason} |")
    result.extend(["",
        "## Source graph provenance and limitations", "",
        "- Source nodes are observed equipment rolls, socket/runes, ranked skills, "
        "Paragon/glyph, selected variant and class mechanics, not verified stat rules.",
        "- Mutating a captured source roll changes the graph and its trace, "
        "**not** a verified computed Character Stat unless a proven contributor exists.",
        "- Four live combat scenarios remain UNKNOWN: target debuffs, proc uptime, "
        "transient stacks, snapshot scene/time. No UNKNOWN is defaulted to zero.",
        "- Formula Graph Level is a source-input candidate, not complete gameplay math.",
        "- No independent Golden Expected was supplied to this report. "
        "Do not treat a source-metric inventory match as Maxroll numeric parity.",
        "- Production publish and verified DPS remain blocked.",
        ""])
    return "\n".join(result)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source-graph",type=Path,required=True)
    p.add_argument("--coverage",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    try:
        report=explain(graph.read_json(a.source_graph),graph.read_json(a.coverage))
        status=0
    except (graph.GraphError,TypeError,KeyError,ValueError,OSError) as e:
        report="# BLOCKED graph explanation\n\nEvidence mismatch: "+str(e)+"\n"
        status=2
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(report,encoding="utf-8")
    print({"status":"PASS_EXPLANATION_NOT_PARITY" if status==0 else "BLOCKED",
           "lines":len(report.splitlines())})
    return status
if __name__=="__main__":sys.exit(main())
