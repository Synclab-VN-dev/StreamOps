"""#109 fail-closed staging/review policy: no real snapshot publish capability.

CI-02 guard enforces pinned source/gates and immutability of a SYNTHETIC lock.
No real owner-approved snapshots, full Golden or Graph outputs exist yet.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import registry

FIRE_METRIC = "maxroll.heroDetails.446"
FIRE_SOURCE_COMMIT = "918aa4b0e1845d34909a8b847a324b445e3805a7"
FIRE_SOURCE_URL = "https://maxroll.gg/d4/planner/1g1any0x#3"
FIRE_REVIEW = "https://github.com/Synclab-VN-dev/StreamOps/issues/106#issuecomment-6212668905"
SYNTHETIC_LOCK = HERE / "fixtures" / "synthetic-approved-lock.json"
SYNTHETIC_LOCK_PIN = "0dfef4e6776ad885892e0105cd0d3c182f038ca21842674aa6bef77ecadec4eb"
EXPECTED_LOCKED_RULES = {"fake.direct": 1, "fake.nerf": 5,
                         "fake.remove": 4, "fake.stable": 7}


def trusted_source_check(catalog, candidates):
    """Only the single independently reviewed Maxroll candidate can be staged."""
    metric_by_id = {m["metricId"]: m for m in catalog["metrics"]}
    for item in candidates:
        mid = item["metricId"]
        registry.require(mid == FIRE_METRIC, "UNPINNED_MAXROLL_SOURCE")
        registry.require(item.get("sourceKind") == "MAXROLL_SOURCE_OBSERVATION"
                         and item.get("sourceCommit") == FIRE_SOURCE_COMMIT
                         and item.get("sourceUrl") == FIRE_SOURCE_URL
                         and item.get("sourceEvidence") == FIRE_REVIEW,
                         "PROVENANCE_NOT_MATCHING_REVIEWED_SOURCE")
        registry.require(item.get("researchGrade") ==
                         metric_by_id[mid]["formulaVerificationStatus"],
                         "RESEARCH_GRADE_FALSE_PROMOTION")
        registry.require(item.get("goldenStatus") == "NOT_APPROVED"
                         and item.get("verificationGates") ==
                         {x:"NOT_RUN" for x in registry.GATES}
                         and item.get("state") == "CANDIDATE_UNVERIFIED"
                         and item.get("ownerReview") is None,
                         "G1_G4_OR_OWNER_FAKE_PROMOTION")
        dsl = item.get("dsl")
        registry.require(isinstance(dsl, dict)
                         and dsl.get("verification",{}).get("status") == "unverified"
                         and bool(dsl.get("verification",{}).get("knownLimitations")),
                         "G3_UNAVAILABLE_NOT_UNVERIFIED")
    return len(candidates)


def validate_synthetic_lock(lock):
    """Independent constant is required: a tampered file cannot bless its own hash."""
    registry.require(isinstance(lock,dict)
                     and set(lock) == {"fixtureKind","approvalKind","registryVersion",
                                      "patch","classId","sourceCommit","lockedRules",
                                      "ruleVerification","realGoldenCount","publishedToProduction"},
                     "SIMULATED_LOCK_SCHEMA_MISMATCH")
    registry.require(lock.get("fixtureKind")=="SYNTHETIC_ONLY"
                     and lock.get("approvalKind")=="SIMULATED_APPROVAL_NOT_REAL"
                     and lock.get("registryVersion")=="1.0.0"
                     and lock.get("patch")=="synthetic-old"
                     and lock.get("classId")=="rogue"
                     and lock.get("sourceCommit")=="synthetic.fixture.reference"
                     and lock.get("ruleVerification")=="SYNTHETIC_TEST_ONLY"
                     and lock.get("realGoldenCount")==0
                     and lock.get("publishedToProduction") is False
                     and lock.get("lockedRules")==EXPECTED_LOCKED_RULES,
                     "SIMULATED_LOCK_CONTENT_MISMATCH")
    registry.require(registry.sha256(lock)==SYNTHETIC_LOCK_PIN,
                     "SIMULATED_LOCK_HASH_MISMATCH")
    return SYNTHETIC_LOCK_PIN


def check_immutable_key(lock, requested_key, proposed_rules, *, operation):
    """A simulated already-locked key is never rewritten, even with owner-like claims."""
    validate_synthetic_lock(lock)
    registry.require(operation in {"REPLACE_APPROVED", "PUBLISH",
                                   "AUTO_PUBLISH", "UPSERT_APPROVED"},
                     "INVALID_MUTATION_OPERATION")
    registry.require(requested_key ==
                     (lock["patch"],lock["classId"],lock["registryVersion"]),
                     "LOCK_KEY_MISMATCH")
    # The lock is immutable even for identical payloads: no staging code writes.
    raise registry.RegistryError("APPROVED_SNAPSHOT_IMMUTABLE_NO_WRITE_PATH")


def read_only_review(catalog, catalog_hash, policy, candidates, lock):
    registry.require(isinstance(candidates,list),"INVALID_CANDIDATES")
    snap = registry.snapshot(catalog,catalog_hash,policy,candidates)
    count = trusted_source_check(catalog,candidates)
    pinned = validate_synthetic_lock(lock)
    registry.require(snap["coverage"]["activeRules"]==0
                     and snap["coverage"]["fullyVerifiedFormulas"]==0
                     and snap["coverage"]["approvedGolden"]==0
                     and snap["publishStatus"]=="NOT_APPROVED",
                     "REAL_PUBLISH_FORBIDDEN")
    return {
        "status":"PASS_CI02_READ_ONLY_POLICY_GUARDS_ONLY",
        "oracle":"MAXROLL_ONLY",
        "patch":"3.2.1.73552",
        "registrySnapshotSha256":snap["snapshotSha256"],
        "catalogSha256":catalog_hash,
        "candidateCount":count,
        "sourcePinnedCount":count,
        "sourceGrade":"BOUNDED_VERIFIED_DISPLAY_ONLY" if count else "NONE",
        "g1Schema":"STAGED_ONLY",
        "g2Semantics":"NOT_VERIFIED",
        "g3IndependentGolden":"NOT_AVAILABLE",
        "g4FullCharacterStats":"NOT_VERIFIED",
        "approvedSyntheticFixtureHash":pinned,
        "syntheticImmutableOverwriteGate":"ENFORCED",
        "realApprovedSnapshotExists":False,
        "realPublishTested":False,
        "writeAttempted":False,
        "publishAllowed":False,
        "activeRules":0,
        "fullyVerifiedFormulas":0,
        "maxrollParity":"BLOCKED_NOT_RUN",
        "openGaps":[
            "No independently approved complete Maxroll Golden",
            "No real previously owner-approved registry snapshot to overwrite",
            "No publish capability or permission in this #109 staging module",
            "Unverified input binding and 49 missing candidate formulas"
        ],
    }


def main(argv=None):
    p=argparse.ArgumentParser(description="Fail-closed #109 registry promotion policy review")
    p.add_argument("--candidates",type=Path,default=HERE/"candidates.json")
    p.add_argument("--lock",type=Path,default=SYNTHETIC_LOCK)
    p.add_argument("--report",type=Path,required=True)
    args=p.parse_args(argv)
    try:
        cat,sha = registry.read_pinned_catalog()
        result = read_only_review(cat,sha,registry.load(registry.POLICY),
                                  registry.load(args.candidates),registry.load(args.lock))
        code=0
    except (registry.RegistryError,ValueError,KeyError,TypeError,OSError,
            UnicodeError,ImportError,IndexError) as exc:
        result = {"status":"BLOCKED","errors":[str(exc)],"publishAllowed":False,
                  "writeAttempted":False,"maxrollParity":"NOT_TESTED"}
        code=2
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(result,sort_keys=True))
    return code


if __name__=="__main__":
    sys.exit(main())
