"""#110 real Maxroll-source input -> candidate metric actual (SANDBOX ONLY).

Golden expected is never loaded by this module. This is an internal evaluation
experiment, not a production registry, signed Golden or public FormulaGraphResult.
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import graph
from d4_rulekit.schema_check import validate_rule

EXPECTED_KEYS={"schema","fixtureId","partition","classId","gamePatch",
               "inputFingerprintSha256","runtimeSourceSha256","metrics"}
METRIC_KEYS={"metricId","group","label"}
KNOWN_CLASS={"rogue":3,"sorcerer":0}
LEVEL_ID="maxroll.heroDetails.279"
FORBIDDEN={"golden","expected","expected-maxroll","actualFromGolden","parity",
           "sourceExpected","referenceRaw","expectedRawValue","expectedDisplayValue"}
HEX=graph.SHA64


def reject_expected(value,depth=0):
    """Reject smuggled Oracle data anywhere in Graph's input or rule manifest."""
    graph.reject(depth<=80,"SOURCE_INPUT_EXCESSIVE_NESTING")
    if isinstance(value,dict):
        for key,v in value.items():
            graph.reject((key=="expectedF1InputFingerprintSha256" and depth==1 and type(v)==str and bool(HEX.fullmatch(v))) or (key not in FORBIDDEN and not str(key).lower().startswith("expected")),
                         "GOLDEN_EXPECTED_IN_GRAPH_INPUT")
            reject_expected(v,depth+1)
    elif isinstance(value,list):
        for item in value:reject_expected(item,depth+1)


def metadata_fixture(fixture):
    graph.reject(type(fixture)==dict and set(fixture)==EXPECTED_KEYS,
                 "INVALID_CANDIDATE_FIXTURE_DESCRIPTOR")
    graph.reject(fixture["schema"]=="candidate-fixture-index-v1"
                 and fixture["partition"]=="DEVELOPMENT",
                 "HOLDOUT_EXPECTED_AND_EXECUTION_SEPARATION")
    graph.reject(fixture["classId"] in KNOWN_CLASS and
                 fixture["gamePatch"]=="3.2.1.73552"
                 and type(fixture["fixtureId"])==str
                 and fixture["fixtureId"].startswith("DEV-"),
                 "FIXTURE_PATCH_CLASS_SCOPE_MISMATCH")
    for key in ("inputFingerprintSha256","runtimeSourceSha256"):
        graph.reject(type(fixture[key])==str and HEX.fullmatch(fixture[key]),
                     "MISSING_SOURCE_FINGERPRINT")
    allrows=fixture["metrics"]
    graph.reject(type(allrows)==list and 0<len(allrows)<=250,
                 "INVALID_METRIC_INVENTORY")
    seen=set();per_id={}
    for item in allrows:
        graph.reject(type(item)==dict and set(item)==METRIC_KEYS,
                     "INVALID_METRIC_INVENTORY_ROW")
        metric,group,label=item["metricId"],item["group"],item["label"]
        graph.reject(type(metric)==str and metric.startswith("maxroll.heroDetails.")
                     and type(group)==str and group and type(label)==str and label,
                     "INVALID_METRIC_ID_OR_LABEL")
        position=(group.lower().replace(" ","_"),metric)
        graph.reject(position not in seen,"DUPLICATED_METRIC_UI_POSITION")
        seen.add(position)
        if metric in per_id:
            graph.reject(per_id[metric].casefold()==label.casefold(),
                         "INCONSISTENT_DUPLICATE_METRIC_LABEL")
        else:per_id[metric]=label
    graph.reject(LEVEL_ID in per_id,"SOURCE_LEVEL_METRIC_NOT_PRESENT")
    return len(per_id)


def normalized_source(source,fixture):
    reject_expected(source)
    graph.reject(type(source)==dict,"INVALID_MAXROLL_SOURCE_INPUT")
    graph.reject(source.get("completeness")== "PARTIAL" or
                 source.get("inputCompleteness")=="PARTIAL",
                 "FALSE_COMPLETE_SOURCE_INPUT")
    # F-INPUT-01/F3 and new F-GOLDEN-01 have different wrappers.
    if "currentReadOnlyPublicProfile" in source:
        profile=source["currentReadOnlyPublicProfile"]
        declared=source.get("fixture",{}).get("gameVersion")
        fingerprint=source.get("fingerprints",{}).get("f1InputSnapshotSha256")
        cls=source.get("fixture",{}).get("class","").lower()
    else:
        profile=source.get("activeProfile")
        declared=source.get("patch")
        fingerprint=source.get("fingerprints",{}).get("fullInputSha256")
        cls=fixture["classId"]
        graph.reject(source.get("level")==profile.get("level") if
                     type(profile)==dict else False,"SOURCE_LEVEL_WRAPPER_MISMATCH")
    graph.reject(type(profile)==dict and type(profile.get("level"))==int
                 and not isinstance(profile["level"],bool)
                 and 1<=profile["level"]<=100,"INVALID_SOURCE_LEVEL")
    graph.reject(declared==fixture["gamePatch"] and
                 fingerprint==fixture["inputFingerprintSha256"] and
                 cls==fixture["classId"],"SOURCE_FIXTURE_PATCH_OR_HASH_MISMATCH")
    if type(profile["class"])==int:
        graph.reject(profile["class"]==KNOWN_CLASS[cls],"SOURCE_CLASS_MISMATCH")
    else:
        graph.reject(False,"UNSUPPORTED_CLASS_ID_SOURCE")
    return {"level":profile["level"]}


def evaluate_value(expr,env):
    graph.reject(type(expr)==dict,"INVALID_CANDIDATE_AST")
    if expr.get("kind")=="ref":
        graph.reject(set(expr)=={"kind","scope","path"} and
                     expr["scope"]=="build" and expr["path"] in env,
                     "CANDIDATE_REFERENCE_NOT_FOUND")
        return env[expr["path"]]
    graph.reject(expr.get("kind")=="literal" and set(expr)=={"kind","value"},
                 "UNSUPPORTED_TEST_ONLY_EXPRESSION")
    val=expr["value"]
    graph.reject(type(val) in (int,float) and math.isfinite(val),
                 "INVALID_TEST_ONLY_LITERAL")
    return val


def evaluate_rule(rule,fixture,env,inventory):
    errors=validate_rule(rule)
    graph.reject(not errors,"CANDIDATE_G1_SCHEMA_FAILURE: "+json.dumps(errors)[:300])
    graph.reject(rule["verification"]["status"]=="unverified",
                 "FALSE_VERIFIED_CANDIDATE")
    graph.reject(rule["source"]["kind"] in {"global_rule","class_mechanic"},
                 "UNSUPPORTED_CANDIDATE_SOURCE_KIND")
    graph.reject((rule["game"]["gameVersion"],rule["game"]["buildNumber"])==
                 ("3.2.1","73552"),"CANDIDATE_RULE_PATCH_MISMATCH")
    graph.reject(set(rule)=={"schemaVersion","ruleId","name","game","source",
                             "mechanics","verification"},
                 "CANDIDATE_RULE_SCOPE_TOO_BROAD")
    ms=rule["mechanics"]
    graph.reject(len(ms)==1,"MULTI_MECHANIC_RULE_UNSUPPORTED")
    m=ms[0]
    graph.reject(m["phase"]=="pre_build" and m["trigger"]=={"kind":"always"}
                 and set(m)=={"id","phase","trigger","actions"},
                 "CANDIDATE_TRIGGER_OR_CONDITION_NOT_SUPPORTED")
    actions=m["actions"]
    graph.reject(len(actions)==1,"MULTI_ACTION_RULE_UNSUPPORTED")
    action=actions[0]
    graph.reject(action.get("op")=="modify_stat"
                 and action.get("math")=="set"
                 and action.get("who")=="actor"
                 and action.get("stage")=="base"
                 and set(action)=={"op","math","who","stage","stat","value"},
                 "CANDIDATE_ACTION_NOT_SUPPORTED")
    mid=action["stat"]
    graph.reject(mid in inventory,"CANDIDATE_METRIC_NOT_IN_FIXTURE")
    graph.reject(mid==LEVEL_ID,"CANDIDATE_FORMULA_NOT_SOURCE_SUPPORTED")
    graph.reject(action["value"]=={"kind":"ref","scope":"build","path":"level"},
                 "CANDIDATE_SOURCE_VALUE_MUST_BE_REF_LEVEL")
    value=evaluate_value(action["value"],env)
    graph.reject(type(value)==int and 1<=value<=100,
                 "INVALID_LEVEL_FORMULA_RESULT")
    return mid,value,{"ruleId":rule["ruleId"],"sourceField":"build.level",
                     "source":"MAXROLL_BUILD_INPUT_NOT_GOLDEN",
                     "verification":"CANDIDATE_TEST_ONLY"}


def build(source,fixture,rules):
    metadata_fixture(fixture)
    env=normalized_source(source,fixture)
    reject_expected(rules)
    graph.reject(type(rules)==list and 0<len(rules)<=32,
                 "INVALID_CANDIDATE_RULESET")
    identity={x["metricId"] for x in fixture["metrics"]}
    computed={};traces={}
    for rule in rules:
        mid,value,trace=evaluate_rule(rule,fixture,env,identity)
        graph.reject(mid not in computed,"CANDIDATE_MULTIPLE_WRITERS")
        computed[mid]=value;traces[mid]=[trace]
    rows=[]
    for item in fixture["metrics"]:
        id_=item["metricId"];found=id_ in computed
        rows.append({**item,"rowKey":item["group"].lower().replace(" ","_")+"/"+id_,
                     "status":"CANDIDATE_COMPUTED_UNVERIFIED" if found else "UNKNOWN",
                     "raw":computed.get(id_),"display":None,"computed":found,
                     "trace":traces.get(id_,[]),
                     "reason":"TEST_ONLY_NOT_INDEPENDENTLY_VERIFIED" if found else
                              "NO_EXECUTABLE_CANDIDATE_RULE"})
    out={
        "artifactType":"INTERNAL_GOLDEN_DRIVEN_CANDIDATE_ACTUAL_NOT_PUBLIC_BE",
        "partition":"DEVELOPMENT",
        "fixtureId":fixture["fixtureId"],"classId":fixture["classId"],
        "gamePatch":fixture["gamePatch"],
        "sourceInputFingerprint":fixture["inputFingerprintSha256"],
        "runtimeSourceSha256":fixture["runtimeSourceSha256"],
        "sourceInputCompleteness":"PARTIAL",
        "candidateRuleSetSha256":graph.digest(rules),
        "sourceInputSha256":graph.digest(source),
        "fixtureInventorySha256":graph.digest(fixture),
        "sourceRowCount":len(rows),"uniqueMetricCount":len(identity),
        "computedUniqueMetricCount":len(computed),
        "computedDisplayRowCount":sum(r["computed"] for r in rows),
        "verifiedMetrics":0,"approvedGoldens":0,
        "maxrollParity":"NOT_RUN",
        "characterMetrics":rows,"simulationContext":None,
        "publishAllowed":False,
        "sourceExpectedImported":False,
    }
    out["graphSha256"]=graph.digest(out)
    return out


def main(argv=None):
    ap=argparse.ArgumentParser(description="Real source input / test-only candidate actual; no Golden expected")
    ap.add_argument("--source",type=Path,required=True)
    ap.add_argument("--inventory",type=Path,required=True)
    ap.add_argument("--rules",type=Path,required=True)
    ap.add_argument("--report",type=Path,required=True)
    args=ap.parse_args(argv)
    try:
        out=build(graph.read_json(args.source),graph.read_json(args.inventory),
                  graph.read_json(args.rules));code=0
    except (graph.GraphError,ValueError,TypeError,KeyError,OSError,UnicodeError,
            ImportError,RecursionError) as error:
        out={"status":"BLOCKED","errors":[str(error)],
             "publishAllowed":False,"maxrollParity":"NOT_RUN"};code=2
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(out,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in out.items() if k!="characterMetrics"},sort_keys=True))
    return code

if __name__=="__main__":
    sys.exit(main())
