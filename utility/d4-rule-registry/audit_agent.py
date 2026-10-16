"""#109 offline evidence-to-DSL audit. Read-only; never generates ungrounded formula or publishes rules."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import registry  # noqa: E402

FIRE_REVIEW = "https://github.com/Synclab-VN-dev/StreamOps/issues/106#issuecomment-6212668905"
FIRE_COMMIT = "918aa4b0e1845d34909a8b847a324b445e3805a7"
FIRE_METRIC = "maxroll.heroDetails.446"
FIRE_RULE = "candidate.rogue.fire_resistance_dr_display_f7_2"
FIRE_FILE = HERE / "research" / "fire-dr-f7-2.json"


def load_fire_verifier():
    spec = importlib.util.spec_from_file_location("d4_109_fire_audit", HERE / "research" / "check_fire_dr.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def assert_fire_dsl_is_source_bounded(dsl, research, source_file=FIRE_FILE):
    """Exact structural source contract, *not* runnable graph validation."""
    registry.require(isinstance(dsl, dict), "FIRE_RULE_DSL_REQUIRED")
    registry.require(dsl.get("schemaVersion") == "1.0.0"
                     and dsl.get("ruleId") == FIRE_RULE
                     and dsl.get("verification", {}).get("status") == "unverified",
                     "FIRE_RULE_STATE_OR_SCHEMA_MISMATCH")
    game = dsl.get("game", {})
    registry.require((game.get("gameVersion"), game.get("buildNumber")) ==
                     ("3.2.1", "73552"), "FIRE_RULE_PATCH_MISMATCH")
    app = dsl.get("applicability", {})
    registry.require(app.get("classes") == ["rogue"]
                     and app.get("minCharacterLevel") == 50
                     and app.get("maxCharacterLevel") == 70,
                     "FIRE_RULE_SUPPORT_SCOPE_MISMATCH")
    mechanics = dsl.get("mechanics")
    registry.require(isinstance(mechanics, list) and len(mechanics) == 1,
                     "FIRE_RULE_MECHANIC_MISMATCH")
    item = mechanics[0]
    registry.require(item.get("phase") == "pre_build"
                     and item.get("trigger") == {"kind": "always"}
                     and item.get("affects") == ["defense"]
                     and len(item.get("actions", [])) == 1,
                     "FIRE_RULE_ACTION_SCOPE_MISMATCH")
    action = item["actions"][0]
    registry.require((action.get("op"), action.get("stat"), action.get("who"),
                      action.get("math"), action.get("stage"), action.get("snapshot")) ==
                     ("modify_stat", "resistance.fire.dr_candidate", "actor", "set", "base", "dynamic"),
                     "FIRE_RULE_WRONG_ACTION")
    R = {"kind": "ref", "scope": "actor", "path": "resistance.fire.total"}
    L = {"kind": "ref", "scope": "actor", "path": "level"}
    def call(fn, *args):
        return {"kind": "call", "fn": fn, "args": list(args)}
    expected = call("divide",
                    call("multiply", {"kind": "literal", "value": 0.9, "unit": "ratio"}, R),
                    call("add", R, call("multiply", {"kind": "literal", "value": 15, "unit": "none"}, L)))
    registry.require(action.get("value") == expected, "FIRE_SOURCE_AST_MISMATCH")
    registry.require(research.get("sourceCommit") == FIRE_COMMIT
                     and research.get("sourceReview") == FIRE_REVIEW
                     and research.get("status") == "BOUNDED_VERIFIED_DISPLAY_ONLY"
                     and research.get("sourceInputsKnownFully") is False,
                     "FIRE_RESEARCH_NOT_BOUNDED")
    limitations = dsl.get("verification", {}).get("knownLimitations", [])
    registry.require(isinstance(limitations, list) and len(limitations) >= 3
                     and "actor.resistance.fire.total" in " ".join(limitations),
                     "MISSING_UNKNOWN_BINDING_WARNING")
    return {
        "status": "G1_SHAPE_VALID_AST_SOURCE_BOUNDED",
        "expression": "0.9 * R / (R + 15 * Level)",
        "formulaMetric": FIRE_METRIC,
        "schema": "1.0.0",
        "inputBinding": "UNRESOLVED_R_AGGREGATION",
        "rawHelper": "NOT_VERIFIED",
        "explicitCap": "NOT_VERIFIED",
        "readOnlyCandidate": True,
        "activeRuleAllowed": False,
    }


def audit(catalog, catalog_hash, policy, candidates, research):
    snap = registry.snapshot(catalog, catalog_hash, policy, candidates)
    # Source observations must pre-exist independently of this PR and the #110 graph.
    source = load_fire_verifier().compare(research)
    registry.require(len(candidates) == 1, "FIRE_BOUNDED_ONLY_SOURCE_CANDIDATE")
    c = candidates[0]
    registry.require(c["metricId"] == FIRE_METRIC and c["id"] == FIRE_RULE
                     and c["sourceCommit"] == FIRE_COMMIT and c["sourceEvidence"] == FIRE_REVIEW
                     and c["researchGrade"] == "BOUNDED_VERIFIED"
                     and c["verificationGates"] == {g: "NOT_RUN" for g in registry.GATES}
                     and c["goldenStatus"] == "NOT_APPROVED"
                     and c["state"] == "CANDIDATE_UNVERIFIED",
                     "FIRE_PROMOTION_OR_SOURCE_MISMATCH")
    expression = assert_fire_dsl_is_source_bounded(c["dsl"], research)
    gaps = []
    for m in sorted(catalog["metrics"], key=lambda x: x["metricId"]):
        f4 = m.get("f4ObservedDependencies", {})
        target = m["metricId"] == FIRE_METRIC
        gaps.append({
            "metricId": m["metricId"],
            "group": m["group"],
            "sourceResearchGrade": m["formulaVerificationStatus"],
            "f4SourceStatus": f4.get("f4VerificationStatus", "UNKNOWN"),
            "f4SourceDependencyNodes": f4.get("directDependencies", []),
            "sourceInputCompleteness": "PARTIAL",
            "ruleCandidate": FIRE_RULE if target else None,
            "dslSyntaxGate": "G1_SCHEMA_VALID_ONLY" if target else "NOT_RUN",
            "semanticBindingGate": "G2_UNRESOLVED_SOURCE_INPUTS" if target else "G2_NOT_RUN",
            "numericReferenceGate": "G3_BOUNDED_DISPLAY_SOURCE_ONLY" if target else "G3_NOT_RUN",
            "coverageGate": "G4_METRIC_ID_CATALOGUED_RULE_NOT_APPROVED",
            "openGaps": m["openGaps"],
            "fullFormulaVerified": False,
            "maxrollParity": "BLOCKED_NO_GOLDEN_OR_GRAPH",
        })
    result = {
        "status": "PASS_SOURCE_CANDIDATE_AUDIT_ONLY",
        "sourceCommit": FIRE_COMMIT,
        "sourceReview": FIRE_REVIEW,
        "registrySnapshotSha256": snap["snapshotSha256"],
        "catalogSha256": catalog_hash,
        "patch": "3.2.1.73552",
        "g1CandidateDsl": 1,
        "g2VerifiedBindings": 0,
        "g3CompleteFormulas": 0,
        "g4VisibleMetricIds": 50,
        "activeRules": 0,
        "approvedGoldens": 0,
        "sourceDisplayReplay": {"checked": source["sourceMatch"], "status": source["status"]},
        "fireDsl": expression,
        "requiresDesignDecision": False,
        "requiresBrowserEvidence": "SOURCE_R_AGGREGATION_NOT_ISOLATED",
        "candidatePromotion": "NOT_ALLOWED",
        "maxrollParity": "BLOCKED_NOT_RUN",
        "reviewQueue": gaps,
    }
    result["auditSha256"] = registry.sha256(result)
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description="Read-only source-evidence agent handoff for #109")
    p.add_argument("--candidates", type=Path, default=HERE/"candidates.json")
    p.add_argument("--source", type=Path, default=FIRE_FILE)
    p.add_argument("--report", type=Path, required=True)
    args=p.parse_args(argv)
    try:
        catalog, fingerprint=registry.read_pinned_catalog()
        report=audit(catalog, fingerprint, registry.load(registry.POLICY),
                     registry.load(args.candidates), registry.load(args.source))
        code=0
    except (registry.RegistryError, ValueError, OSError, UnicodeError, KeyError, TypeError,
            AssertionError, ImportError) as exc:
        report={"status":"BLOCKED","errors":[str(exc)],"candidatePromotion":"NOT_ALLOWED",
                "maxrollParity":"NOT_TESTED","activeRules":0}
        code=2
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2)+"\n",
                           encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k!="reviewQueue"},
                     ensure_ascii=False, sort_keys=True, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
