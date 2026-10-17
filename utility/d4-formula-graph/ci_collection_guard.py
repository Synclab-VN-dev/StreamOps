"""#108 hard CI test collection guard. PASS requires actual complete execution.

No absent, silently omitted, skipped, xfailed or duplicated unit test counts.
The test runner is independent from #108 Golden approval.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import unittest
import sys

class CollectionBlocked(ValueError):pass
def need(ok,msg):
    if not ok:raise CollectionBlocked(msg)

def inspect_log(text,selected_ids,minimum=1):
    need(type(text)==str and type(selected_ids)==list,
         "INVALID_TEST_COLLECTION_INPUT")
    need(len(selected_ids)>=minimum,"INCOMPLETE_TEST_DISCOVERY")
    need(len(selected_ids)==len(set(selected_ids)),
         "DUPLICATE_COLLECTED_TEST")
    x=re.findall(r"(?m)^Ran ([0-9]+) tests? in [0-9.]+s\s*$",text)
    need(len(x)==1,"MISSING_OR_DUPLICATED_RUNNER_SUMMARY")
    need(int(x[0])==len(selected_ids),"NOT_ALL_COLLECTED_TESTS_RAN")
    verdict=re.findall(r"(?m)^OK(?:\s*\(([^)]*)\))?\s*$",text)
    need(len(verdict)==1 and not verdict[0],
         "NONPASSING_OR_SKIPPED_TEST_VERDICT")
    need(not re.search(r"(?im)(\bskip(?:ped)?\b|\bxfail\b|expected failure|unexpected success|^FAIL\b|^ERROR\b)",text),
         "SKIP_XFAIL_OR_FAILED_TEST_BLOCKED")
    return {"status":"PASS_COMPLETE_COLLECTION_NO_SKIPPED_TESTS",
            "discovered":len(selected_ids),"executed":int(x[0]),
            "skipped":0,"expectedFailures":0,"unexpectedSuccesses":0,
            "testNamesSha256":hashlib.sha256(
                "\n".join(sorted(selected_ids)).encode("utf-8")).hexdigest(),
            "independentGoldenParity":"NOT_RUN","publishAllowed":False}

def collect(start:Path):
    loader=unittest.TestLoader()
    suites=loader.discover(str(start.resolve()),pattern="test_*.py")
    need(not loader.errors,"TEST_DISCOVERY_IMPORT_ERRORS")
    flattened=[]
    def descend(suite):
        for t in suite:
            if isinstance(t,unittest.TestSuite):descend(t)
            else:flattened.append(t)
    descend(suites)
    for test in flattened:
        method=getattr(test,test._testMethodName)
        need(not getattr(test,"__unittest_skip__",False) and
             not getattr(method,"__unittest_skip__",False),
             "DISABLED_OR_SKIPPED_TEST_DISCOVERED")
        need(not getattr(test,"__unittest_expecting_failure__",False) and
             not getattr(method,"__unittest_expecting_failure__",False),
             "EXPECTED_FAILURE_TEST_DISCOVERED")
    return [t.id() for t in flattened]

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--tests-dir",type=Path,required=True)
    p.add_argument("--unit-log",type=Path,required=True)
    p.add_argument("--report",type=Path,required=True)
    p.add_argument("--minimum",type=int,default=90)
    args=p.parse_args()
    try:
        ids=collect(args.tests_dir)
        out=inspect_log(args.unit_log.read_text(encoding="utf-8"),
                        ids,args.minimum)
        code=0
    except (CollectionBlocked,OSError,TypeError,ValueError) as e:
        out={"status":"BLOCKED","reason":str(e),
             "independentGoldenParity":"NOT_RUN","publishAllowed":False}
        code=2
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(out,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(out,sort_keys=True))
    return code
if __name__=="__main__":sys.exit(main())
