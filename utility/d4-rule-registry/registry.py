"""#109 Maxroll-only, evidence-first rule registry. Not a formula evaluator or a Golden registry."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

BASE = Path(__file__).resolve().parents[1]
CATALOG = BASE / "d4-maxroll-reference" / "f8-character-metric-catalog.json"
POLICY = Path(__file__).with_name("policy.json")
PATCH, BUILD, CLASS = "3.2.1", "73552", "rogue"
SOURCE_BLOB = "ebf17a0e64e249448609145b89753fec3709ae7d"
SOURCE_COMMIT = "8fdf59a988b0425e789248a5f1898ef67b27314d"
GATES = ("G1", "G2", "G3", "G4")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
VALID_GRADES = {"PARTIAL", "BOUNDED_VERIFIED", "VERIFIED"}


class RegistryError(ValueError):
    """A fail-closed registry or evidence error."""


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256(obj):
    return hashlib.sha256(canonical(obj)).hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def require(condition, reason):
    if not condition:
        raise RegistryError(reason)


def read_pinned_catalog(path=CATALOG):
    data = Path(path).read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()
    require(blob == SOURCE_BLOB, "SOURCE_CATALOG_BLOB_MISMATCH")
    catalog = json.loads(data)
    require(catalog.get("catalogVersion") == "1.1.0"
            and catalog.get("scope") == "SOURCE_EVIDENCE_INVENTORY_ONLY"
            and catalog.get("oracle") == "MAXROLL_ONLY", "CATALOG_SCOPE_MISMATCH")
    baseline = catalog.get("baseline", {})
    require((baseline.get("gamePatch"), baseline.get("gameBuild"),
             baseline.get("classId"), baseline.get("ownerPinned")) ==
            (PATCH, BUILD, CLASS, True), "SOURCE_PATCH_OR_CLASS_MISMATCH")
    fixture = catalog.get("fixture", {})
    require(fixture.get("inputCompleteness") == "PARTIAL"
            and bool(HEX64.fullmatch(fixture.get("inputSnapshotSha256", ""))),
            "FALSE_COMPLETE_INPUT")
    provenance = catalog.get("provenance", {})
    require(provenance.get("sourceCommit") == SOURCE_COMMIT, "SOURCE_PROVENANCE_MISMATCH")
    coverage = catalog.get("coverage", {})
    require(coverage.get("denominator") == 50
            and coverage.get("fullFormulaVerified") == 0
            and coverage.get("approvedGoldenCount") == 0
            and coverage.get("fullMaxrollParity") == "NOT_RUN", "FALSE_VERIFICATION")
    metrics = catalog.get("metrics")
    require(isinstance(metrics, list) and len(metrics) == 50, "INCOMPLETE_METRIC_INVENTORY")
    ids = [m.get("metricId") for m in metrics]
    require(len(set(ids)) == 50
            and all(isinstance(x, str) and x.startswith("maxroll.heroDetails.") for x in ids),
            "INVALID_OR_DUPLICATE_METRIC_ID")
    groups, grades = Counter(), Counter()
    for m in metrics:
        require(m.get("group") in coverage.get("sourceGroupCounts", {}),
                "UNKNOWN_METRIC_GROUP")
        require(isinstance(m.get("label"), str) and bool(m["label"]), "MISSING_LABEL")
        require(m.get("formulaVerificationStatus") in VALID_GRADES, "INVALID_RESEARCH_GRADE")
        # #106 F7.2 reports one bounded Fire-DR display-curve hypothesis.
        # It is source-only, never an executable rule or approved Golden.
        hypothesis = m.get("formulaCandidate")
        if m["metricId"] == "maxroll.heroDetails.446":
            require(isinstance(hypothesis, dict)
                    and hypothesis.get("testedPatch") == "3.2.1.73552"
                    and hypothesis.get("testedClass") == "rogue"
                    and hypothesis.get("observedDisplayMatches") == 67
                    and hypothesis.get("verifiedExactHelper") is False
                    and hypothesis.get("provenExplicitCap") is False,
                    "UNAPPROVED_FIRE_HYPOTHESIS_PROMOTION")
        else:
            require(hypothesis is None, "UNAPPROVED_METRIC_FORMULA")
        require(m.get("goldenStatus") == "NOT_APPROVED"
                and m.get("maxrollGraphParity") == "NOT_RUN",
                "FALSE_GOLDEN_OR_RULE")
        require(bool(m.get("openGaps")), "HIDDEN_METRIC_GAP")
        groups[m["group"]] += 1
        grades[m["formulaVerificationStatus"]] += 1
    require(dict(groups) == coverage["sourceGroupCounts"], "GROUP_DENOMINATOR_MISMATCH")
    require(grades == {"BOUNDED_VERIFIED": 27, "PARTIAL": 23}, "SOURCE_GRADE_MISMATCH")
    return catalog, hashlib.sha256(data).hexdigest()


def check_policy(policy):
    require(policy.get("registryVersion") == "1.0.0"
            and policy.get("oracle") == "MAXROLL_ONLY"
            and policy.get("sourceCatalogGitBlob") == SOURCE_BLOB, "REGISTRY_POLICY_MISMATCH")
    require((policy.get("gamePatch"), policy.get("gameBuild"), policy.get("classId")) ==
            (PATCH, BUILD, CLASS), "REGISTRY_PATCH_MISMATCH")
    require(policy.get("activeRulePolicy") == "VERIFIED_G1_G2_G3_G4_OWNER_REVIEW_ONLY"
            and policy.get("numericUnknownFallback") == "FORBIDDEN"
            and policy.get("autoPublish") is False
            and policy.get("approvedGoldenCount") == 0, "UNSAFE_PUBLISH_POLICY")


def check_candidate(record, metric_ids):
    require(isinstance(record, dict), "CANDIDATE_NOT_OBJECT")
    allowed = {"id", "metricId", "gamePatch", "gameBuild", "classId", "state",
               "sourceKind", "sourceUrl", "sourceCommit", "sourceEvidence",
               "researchGrade", "dependencies", "dsl", "goldenStatus",
               "verificationGates", "ownerReview"}
    require(set(record) <= allowed, "UNRECOGNIZED_CANDIDATE_FIELD")
    require(isinstance(record.get("id"), str) and record["id"].startswith("candidate."),
            "INVALID_CANDIDATE_ID")
    require(record.get("metricId") in metric_ids, "UNKNOWN_CANDIDATE_METRIC")
    require((record.get("gamePatch"), record.get("gameBuild"), record.get("classId")) ==
            (PATCH, BUILD, CLASS), "CANDIDATE_PATCH_MISMATCH")
    require(record.get("state") == "CANDIDATE_UNVERIFIED", "UNAPPROVED_ACTIVE_RULE")
    require(record.get("sourceKind") == "MAXROLL_SOURCE_OBSERVATION"
            and isinstance(record.get("sourceUrl"), str)
            and record["sourceUrl"].startswith("https://maxroll.gg/d4/planner/")
            and isinstance(record.get("sourceEvidence"), str)
            and record["sourceEvidence"].startswith("https://github.com/")
            and isinstance(record.get("sourceCommit"), str)
            and HEX40.fullmatch(record["sourceCommit"]),
            "MISSING_INDEPENDENT_SOURCE_PROVENANCE")
    require(record.get("researchGrade") in {"PARTIAL", "BOUNDED_VERIFIED"}
            and record.get("goldenStatus") == "NOT_APPROVED"
            and record.get("ownerReview") is None
            and record.get("verificationGates") == {g: "NOT_RUN" for g in GATES},
            "FALSE_CANDIDATE_PROMOTION")
    deps = record.get("dependencies", [])
    require(isinstance(deps, list) and len(deps) == len(set(deps))
            and all(dep in metric_ids for dep in deps)
            and record["metricId"] not in deps, "INVALID_DEPENDENCIES")
    dsl = record.get("dsl")
    if dsl is not None:
        require(isinstance(dsl, dict), "INVALID_RULE_DSL")
        from d4_rulekit.schema_check import load_schema, validate_rule
        known = {item["properties"]["op"]["const"]
                 for item in load_schema()["$defs"]["action"]["oneOf"]}
        for mechanic in dsl.get("mechanics", []):
            for action in mechanic.get("actions", []):
                if isinstance(action, dict) and action.get("op") not in known:
                    raise RegistryError("SCHEMA_EXTENSION_REQUIRED: " + str(action.get("op")))
        errors = validate_rule(dsl)
        require(not errors, "G1_SCHEMA_FAIL: " + json.dumps(errors, sort_keys=True)[:500])
        require(dsl.get("schemaVersion") == "1.0.0"
                and dsl.get("ruleId") == record["id"]
                and dsl.get("game", {}).get("gameVersion") == PATCH
                and dsl.get("game", {}).get("buildNumber") == BUILD,
                "DSL_PATCH_OR_ID_MISMATCH")
        require(dsl.get("verification", {}).get("status") != "verified",
                "CANDIDATE_CLAIMS_VERIFIED")
    return record


def cycle_check(candidates):
    deps_by_id = {r["metricId"]: r["dependencies"] for r in candidates}
    visited, visiting = set(), set()

    def walk(mid):
        require(mid not in visiting, "G2_CANDIDATE_DEPENDENCY_CYCLE")
        if mid in visited:
            return
        visiting.add(mid)
        for dependency in deps_by_id.get(mid, ()):
            walk(dependency)
        visiting.remove(mid)
        visited.add(mid)

    for mid in deps_by_id:
        walk(mid)


def snapshot(catalog, catalog_hash, policy, candidates):
    check_policy(policy)
    require(catalog.get("coverage", {}).get("denominator") == 50, "CATALOG_NOT_PINNED")
    metric_ids = {m["metricId"] for m in catalog["metrics"]}
    by_metric, ids = {}, set()
    for record in candidates:
        check_candidate(record, metric_ids)
        require(record["id"] not in ids and record["metricId"] not in by_metric,
                "DUPLICATE_CANDIDATE")
        ids.add(record["id"])
        by_metric[record["metricId"]] = record
    cycle_check(candidates)
    records = []
    for m in sorted(catalog["metrics"], key=lambda item: item["metricId"]):
        candidate = by_metric.get(m["metricId"])
        records.append({
            "metricId": m["metricId"],
            "group": m["group"],
            "label": m["label"],
            "sourceFormulaResearchStatus": m["formulaVerificationStatus"],
            "sourceDependencies": m.get("f4ObservedDependencies", {}).get("directDependencies", []),
            "sourceDependenciesStatus": "OBSERVED_ONLY_NOT_RULE_RESOLVER_INPUT",
            "sourceEvidence": catalog["provenance"]["sourceCommit"],
            "ruleStatus": "CANDIDATE_UNVERIFIED" if candidate else "UNKNOWN",
            "candidateId": candidate["id"] if candidate else None,
            "activeRule": None,
            "calculatedValue": None,
            "maxrollParity": "BLOCKED_NO_APPROVED_GOLDEN_OR_GRAPH",
        })
    result = {
        "registryVersion": "1.0.0",
        "oracle": "MAXROLL_ONLY",
        "patch": PATCH,
        "build": BUILD,
        "classId": CLASS,
        "fixtureFingerprint": catalog["fixture"]["inputSnapshotSha256"],
        "catalogGitBlobSha1": SOURCE_BLOB,
        "catalogSha256": catalog_hash,
        "inputCompleteness": "PARTIAL",
        "metrics": records,
        "candidates": sorted(candidates, key=lambda item: item["id"]),
        "coverage": {
            "denominator": 50,
            "identified": 50,
            "fullyVerifiedFormulas": 0,
            "approvedGolden": 0,
            "activeRules": 0,
            "sourceBounded": 27,
            "sourcePartial": 23,
            "unknownRuleCount": 50-len(candidates),
            "candidateUnverified": len(candidates),
            "fullParity": "BLOCKED",
        },
        "publishStatus": "NOT_APPROVED",
        "status": "PASS_REGISTRY_STRUCTURE_ONLY",
    }
    result["snapshotSha256"] = sha256(result)
    return result


def simulate_synthetic_patch_cycle(fixture):
    """Synthetic deterministic old->new->rollback, never a production ruleset."""
    require(fixture.get("synthetic") is True, "REAL_PATCH_MUTATION_FORBIDDEN")
    old, new = fixture.get("old"), fixture.get("new")
    require(isinstance(old, dict) and isinstance(new, dict), "BAD_SYNTHETIC_PATCH")
    require(old.get("patch") != new.get("patch"), "PATCH_NOT_CHANGED")
    for state in (old, new):
        require(isinstance(state.get("rules"), dict)
                and all(isinstance(k, str) and isinstance(v, (int, float))
                        and not isinstance(v, bool) for k, v in state["rules"].items()),
                "BAD_SYNTHETIC_RULES")
    a, b = old["rules"], new["rules"]
    return {
        "status": "PASS_SYNTHETIC_ONLY",
        "oldHash": sha256(old),
        "newHash": sha256(new),
        "rollbackHash": sha256(old),
        "restoredExactly": sha256(old) == sha256(json.loads(canonical(old))),
        "diff": {
            "added": sorted(set(b)-set(a)),
            "removed": sorted(set(a)-set(b)),
            "buffed": sorted(k for k in a.keys() & b.keys() if b[k] > a[k]),
            "nerfed": sorted(k for k in a.keys() & b.keys() if b[k] < a[k]),
            "unchanged": sorted(k for k in a.keys() & b.keys() if b[k] == a[k]),
        },
        "activePublish": False,
        "maxrollParity": "NOT_TESTED",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Maxroll source-bounded registry, not formula parity")
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    parser.add_argument("--policy", type=Path, default=POLICY)
    parser.add_argument("--candidates", type=Path, default=Path(__file__).with_name("candidates.json"))
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--synthetic-patch-cycle", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.synthetic_patch_cycle:
            report = simulate_synthetic_patch_cycle(load(args.synthetic_patch_cycle))
        else:
            catalog, fingerprint = read_pinned_catalog(args.catalog)
            candidates = load(args.candidates)
            require(isinstance(candidates, list), "CANDIDATES_MUST_BE_LIST")
            report = snapshot(catalog, fingerprint, load(args.policy), candidates)
        code = 0
    except (RegistryError, OSError, UnicodeError, json.JSONDecodeError, ImportError, TypeError, KeyError) as exc:
        report, code = {"status": "BLOCKED", "errors": [str(exc)],
                        "maxrollParity": "NOT_TESTED", "activePublish": False}, 2
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in {"metrics", "candidates"}},
                     indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
