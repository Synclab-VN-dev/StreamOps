"""Strength-only development formula (not an approved game/registry rule).

Source build input -> class-level candidate + non-duplicated Paragon source.
No Expected/Golden is read or imported here. Everything absent is explicit.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import graph
import golden_candidate_eval as source_guard
import primary_paragon_source
import strength_contributors as strength

STRENGTH_ID="maxroll.heroDetails.108"
MISSING=(
    "ACCOUNT_ALTAR_STRENGTH_UNCAPTURED",
    "EQUIPMENT_STRENGTH_NID_UNMAPPED",
    "OTHER_STRENGTH_EFFECT_UNMODELLED",
    "CLASS_LEVEL_SCALING_PATCH_UNVERIFIED",
    "GLYPH_PARAGON_INTERACTIONS_CAUSALLY_UNVERIFIED",
)

def evaluate(source,paragon_witness,rules):
    # No expected/golden imports; research rule data must be explicitly supplied.
    source_guard.reject_expected(source)
    source_guard.reject_expected(rules)
    strength.validate_rules(rules)
    graph.reject(
        source.get("inputCompleteness")=="PARTIAL" and
        source.get("fixture",{}).get("class")=="Rogue" and
        source.get("fixture",{}).get("gameVersion")==rules["patch"],
        "MIXED_STRENGTH_SOURCE_PATCH_OR_CLASS")
    profile=source["currentReadOnlyPublicProfile"]
    graph.reject(type(profile.get("level")) is int and
                 source["fixture"]["level"]==profile["level"],
                 "STRENGTH_FIXTURE_LEVEL_MISMATCH")
    witness=primary_paragon_source.capture(paragon_witness)
    graph.reject(witness["inputFingerprintSha256"]==
                 source["fingerprints"]["f1InputSnapshotSha256"],
                 "STRENGTH_PARAGON_SOURCE_FINGERPRINT_MISMATCH")
    audit_view={"sourceActiveNodes":tuple(paragon_witness["nodes"])}
    audited=strength.paragon_strength(audit_view,rules)
    base=strength.RogueStrengthBaseLevel(rules).produce(source,audit_view,None)[0]
    para=strength.EffectiveParagonStrength(rules).produce(source,audit_view,None)[0]
    raw_ui=witness["observedParagonUiFlatSums"]["Strength"]
    reconstructed=(audited["nonSocketNodeFlatSubtotal"]+
                   audited["creditedGateConnections"]*rules["gateBonusStrength"]+
                   audited["displayedGateEndpointSubtotalExcludedAsDuplicate"]+
                   audited["observedGlyphSocketStrengthSummariesExcluded"])
    graph.reject(raw_ui==reconstructed,"RAW_TOOLTIP_SUM_INCONSISTENT")
    # The observed subtotal is a candidate, never final Character Stats.
    subtotal=base.value+para.value
    candidate=int(subtotal//1)
    report={
        "schema":"scoped-strength-working-model-v1",
        "metricId":STRENGTH_ID,"classId":"rogue","fixtureId":"DEV-00",
        "patch":rules["patch"],
        "inputFingerprintSha256":witness["inputFingerprintSha256"],
        "rulesSha256":graph.digest(rules),
        "capturedParagonWitnessSha256":witness["sourceProjectionSha256"],
        "f3SourceCommit":witness["sourceCommit"],
        "components":[
            {"family":base.family,"sourceId":base.source_id,
             "value":base.value,"provenance":base.provenance},
            {"family":para.family,"sourceId":para.source_id,
             "value":para.value,"provenance":para.provenance}
        ],
        "decomposition":{**audited,"classBaseLevelSubtotal":base.value,
                          "observedNaiveTooltipTotal":raw_ui},
        "candidateRaw":candidate,"candidateDisplay":str(candidate),
        "candidateIsCompleteActual":False,
        "missingContributorFamilies":list(MISSING),
        "candidateStatus":"PARTIAL_SOURCE_DERIVED_RESEARCH_UNVERIFIED",
        "goldenExpectedImported":False,
        "goldenVerified":False,"publishAllowed":False,
    }
    report["reportSha256"]=graph.digest(report)
    return report

def main(argv=None):
    p=argparse.ArgumentParser()
    for name in ("source","paragon","rules","report"):
        p.add_argument("--"+name,type=Path,required=True)
    args=p.parse_args(argv)
    try:
        out=evaluate(graph.read_json(args.source),graph.read_json(args.paragon),
                     graph.read_json(args.rules))
        rc=0
    except (KeyError,TypeError,ValueError,OSError,graph.GraphError) as e:
        out={"status":"BLOCKED_INVALID_STRENGTH_SOURCE","reason":str(e),
             "goldenVerified":False,"publishAllowed":False}
        rc=2
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(out,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in out.items() if k not in
                      ("components","decomposition")},sort_keys=True))
    return rc

if __name__=="__main__":sys.exit(main())
