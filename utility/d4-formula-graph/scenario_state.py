"""#110 internal, source-separated *scenario truth* for four unobserved contexts.

This is NOT an approved serialized public input/output contract or Maxroll
formula. Published Maxroll planner cannot certify live combat conditional truth.
All production-like source unknowns stay UNKNOWN. Non-unknown fields are
permitted ONLY for explicitly synthetic test vectors, never as game truth.
"""
from __future__ import annotations

import copy
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import graph

FIELDS=(
    "conditional.currentTargetDebuffs",
    "conditional.procAndUptime",
    "conditional.transientStacks",
    "conditional.snapshotSceneTime",
)
SPECS={
    FIELDS[0]:{
        "vulnerable":"bool",
        "weakened":"bool",
        "poisoned":"bool",
        "crowdControlled":"bool",
        "healthy":"bool",
    },
    FIELDS[1]:{"procActive":"bool","uptimeRatio":"ratio"},
    FIELDS[2]:{
        "ferocity":"count","resolve":"count",
        "darkShroud":"count","blackSoulstoneSouls":"count",
    },
    FIELDS[3]:{"elapsedSeconds":"seconds","snapshotSeconds":"seconds"},
}
ALLOWED_META={"mode","gamePatch","gameBuild","classId",
              "sourceFixtureFingerprint","fields"}
FIXTURE="3ae138cafe3aa4b3633744d0ea5e22b1bd8d92afab77be857906d0b6010cff07"
BASE=("3.2.1","73552","rogue")
UNKNOWN="UNKNOWN"
TRUE="TRUE"
FALSE="FALSE"


def check_type(value,typ):
    if typ=="bool":return type(value)==bool
    if typ=="count":return type(value)==int and value>=0
    if typ=="ratio":return type(value) in (float,int) and 0<=value<=1
    if typ=="seconds":return type(value) in (float,int) and value>=0
    return False


def validate(data):
    graph.reject(type(data)==dict and set(data)==ALLOWED_META,
                 "INVALID_SCENARIO_ENVELOPE")
    mode=data["mode"]
    graph.reject(mode in {"MAXROLL_STATIC_UNOBSERVED",
                          "SYNTHETIC_SCENARIO_TEST_ONLY"},
                 "UNAUTHORIZED_SCENARIO_MODE")
    graph.reject((data["gamePatch"],data["gameBuild"],data["classId"])==BASE,
                 "SCENARIO_PATCH_CLASS_MISMATCH")
    graph.reject(data["sourceFixtureFingerprint"]==FIXTURE,
                 "SCENARIO_SOURCE_FINGERPRINT_MISMATCH")
    all_fields=data["fields"]
    graph.reject(type(all_fields)==dict and set(all_fields)==set(FIELDS),
                 "MISSING_OR_UNEXPECTED_SCENARIO_FIELDS")
    for field in FIELDS:
        item=all_fields[field]
        graph.reject(type(item)==dict and
                     set(item)=={"state","value","evidenceStatus"},
                     "INVALID_SCENARIO_FIELD_SHAPE")
        if item["state"]==UNKNOWN:
            graph.reject(item["value"] is None and
                         item["evidenceStatus"]=="NOT_OBSERVED_IN_STATIC_PLANNER",
                         "UNKNOWN_FIELD_MUST_HAVE_NULL_UNOBSERVED")
            continue
        graph.reject(mode=="SYNTHETIC_SCENARIO_TEST_ONLY" and
                     item["state"]=="KNOWN_SYNTHETIC" and
                     item["evidenceStatus"]=="SYNTHETIC_TEST_ONLY",
                     "UNVERIFIED_RUNTIME_SCENARIO_PROMOTION")
        value=item["value"]
        graph.reject(type(value)==dict and set(value)==set(SPECS[field]),
                     "SCENARIO_TYPED_KEYS_MISMATCH")
        for key,typ in SPECS[field].items():
            graph.reject(check_type(value[key],typ),
                         "INVALID_SCENARIO_TYPED_VALUE")
        # prevent nan/inf passed from Python even if they match numeric predicates
        graph.reject(all(type(v)==bool or
                         (type(v) in (int,float) and graph.math.isfinite(v))
                         for v in value.values()), "SCENARIO_NONFINITE_NUMBER")
        if field==FIELDS[3]:
            graph.reject(value["snapshotSeconds"]<=value["elapsedSeconds"],
                         "SCENARIO_SNAPSHOT_AFTER_CURRENT_TIME")
    return graph.digest(data)


def truth_from_field(data,field,key,expected):
    graph.reject(field in SPECS and key in SPECS[field],
                 "UNSUPPORTED_SCENARIO_CONDITION_REFERENCE")
    typ=SPECS[field][key]
    graph.reject(check_type(expected,typ),"SCENARIO_PREDICATE_TYPE_MISMATCH")
    item=data["fields"][field]
    if item["state"]==UNKNOWN:return UNKNOWN
    return TRUE if item["value"][key]==expected else FALSE


def tri_and(states):
    graph.reject(type(states)==list and len(states)>0 and
                 all(x in (TRUE,FALSE,UNKNOWN) for x in states),
                 "INVALID_TRISTATE_INPUT")
    if FALSE in states:return FALSE
    return UNKNOWN if UNKNOWN in states else TRUE


def tri_or(states):
    graph.reject(type(states)==list and len(states)>0 and
                 all(x in (TRUE,FALSE,UNKNOWN) for x in states),
                 "INVALID_TRISTATE_INPUT")
    if TRUE in states:return TRUE
    return UNKNOWN if UNKNOWN in states else FALSE


def evaluate_condition(data,expr):
    """Only a bounded internal predicate mini-AST for conditional trace gates."""
    graph.reject(type(expr)==dict,"INVALID_SCENARIO_PREDICATE")
    op=expr.get("op")
    if op=="equals":
        graph.reject(set(expr)=={"op","field","key","expected"},
                     "INVALID_SCENARIO_PREDICATE_SHAPE")
        return truth_from_field(data,expr["field"],expr["key"],expr["expected"])
    graph.reject(op in ("and","or") and set(expr)=={"op","conditions"},
                 "UNSUPPORTED_SCENARIO_PREDICATE")
    xs=expr["conditions"]
    graph.reject(type(xs)==list and 1<=len(xs)<=16,
                 "INVALID_SCENARIO_PREDICATE_ARITY")
    items=[evaluate_condition(data,x) for x in xs]
    return tri_and(items) if op=="and" else tri_or(items)


def gate_trace(data,conditions):
    """No real active rule execution: this only reports synthetic/debug gates."""
    s=validate(data)
    graph.reject(type(conditions)==dict and
                 0<len(conditions)<=16 and
                 all(type(k)==str and k for k in conditions),
                 "INVALID_SCENARIO_GATE_MANIFEST")
    trace=[]
    for name,expr in sorted(conditions.items()):
        state=evaluate_condition(data,expr)
        trace.append({"gateId":name,"result":state,
                      "effectExecution":"BLOCKED_UNKNOWN_CONDITION" if
                      state==UNKNOWN else "SYNTHETIC_TRACE_ONLY_NOT_RULE_EXECUTION",
                      "realFormulaExecuted":False})
    result={
        "artifactType":"INTERNAL_SCENARIO_GATE_TRACE_NOT_BE_CONTRACT",
        "scenarioSha256":s,
        "sourceFixtureFingerprint":FIXTURE,
        "scenarioMode":data["mode"],
        "truthCoverage":{"unknown":sum(x["state"]==UNKNOWN for x in
                                       data["fields"].values()),
                         "knownSynthetic":sum(x["state"]=="KNOWN_SYNTHETIC" for x in
                                              data["fields"].values()),
                         "knownReal":0},
        "trace":trace,
        "maxrollFormulaValues":None,
        "approvedScenario":False,
        "publishAllowed":False,
    }
    result["traceSha256"]=graph.digest(result)
    return result


# Four specific condition flags from F-INPUT-01, for scoped unknown propagation.
REFERENCE_GATES={
    "target_vulnerable":{
        "op":"equals","field":FIELDS[0],"key":"vulnerable","expected":True},
    "proc_active":{
        "op":"equals","field":FIELDS[1],"key":"procActive","expected":True},
    "ferocity_stack_1":{
        "op":"equals","field":FIELDS[2],"key":"ferocity","expected":1},
    "snapshot_at_10s":{
        "op":"equals","field":FIELDS[3],"key":"snapshotSeconds","expected":10},
}
