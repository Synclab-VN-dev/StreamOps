"""#110 synthetic-only #107 G1 DSL compositor; never executes real Maxroll rules."""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import graph
from d4_rulekit.schema_check import validate_rule

FAMILIES={"active_skill","legendary_aspect","charm_set_bonus"}
STAGES=("pre_build","pre_skill","pre_transform","pre_cast")

def number(v):
    graph.reject(type(v) in (int,float) and math.isfinite(v),"BAD_NUMERIC_INPUT")
    return v

def evaluate(ast,env):
    graph.reject(isinstance(ast,dict),"INVALID_AST")
    kind=ast.get("kind")
    if kind=="literal":
        v=ast.get("value")
        graph.reject(type(v) in (int,float,bool),"UNSUPPORTED_LITERAL")
        return v
    if kind=="ref":
        graph.reject(ast.get("scope")=="build" and ast.get("path") in env,
                     "UNKNOWN_INPUT_REFERENCE")
        return env[ast["path"]]
    graph.reject(kind=="call","UNSUPPORTED_AST_KIND")
    fn,args=ast.get("fn"),ast.get("args",[])
    graph.reject(fn in {"greater_equal","add","multiply"} and len(args)==2,
                 "UNSUPPORTED_FUNCTION_OR_ARITY")
    a,b=evaluate(args[0],env),evaluate(args[1],env)
    if fn=="greater_equal":return number(a)>=number(b)
    if fn=="add":return number(a)+number(b)
    return number(a)*number(b)

def compose(doc):
    graph.reject(isinstance(doc,dict) and
                 set(doc)=={"synthetic","gamePatch","gameBuild","classId",
                            "input","stats","skills","rules"},"BAD_SYNTHETIC_ENVELOPE")
    graph.reject(doc["synthetic"] is True,"REAL_RULE_EXECUTION_PROHIBITED")
    graph.reject((doc["gamePatch"],doc["gameBuild"],doc["classId"])==
                 ("3.2.1","73552","rogue"),"WRONG_SYNTHETIC_PATCH")
    env=doc["input"]
    graph.reject(isinstance(env,dict) and
                 set(env)=={"aspectEquipped","charmCount","skillRank"} and
                 type(env["aspectEquipped"])==bool and
                 type(env["charmCount"])==int and env["charmCount"]>=0 and
                 type(env["skillRank"])==int and env["skillRank"]>=0,
                 "INVALID_SYNTHETIC_INPUT")
    stats=doc["stats"];skills=doc["skills"]
    graph.reject(isinstance(stats,dict) and set(stats)=={"synthetic.damageBonus"}
                 and isinstance(skills,dict)
                 and set(skills)=={"synthetic.projectile"} and
                 set(skills["synthetic.projectile"])=={"projectile_count"},
                 "INVALID_SYNTHETIC_OUTPUT_SEED")
    stats={k:number(v) for k,v in stats.items()}
    skills={k:{p:number(v) for p,v in props.items()} for k,props in skills.items()}
    rules=doc["rules"]
    graph.reject(isinstance(rules,list) and len(rules)==3,"WRONG_FAMILY_COUNT")
    entries=[]; seen=set(); families=set()
    for rule in rules:
        errors=validate_rule(rule)
        graph.reject(not errors,"G1_SCHEMA_FAILURE "+json.dumps(errors)[:450])
        rid=rule["ruleId"]
        graph.reject(rid not in seen,"DUPLICATE_RULE")
        seen.add(rid)
        graph.reject((rule["game"].get("gameVersion"),
                      rule["game"].get("buildNumber"))==("3.2.1","73552"),
                     "RULE_PATCH_MISMATCH")
        graph.reject(rule["verification"]["status"]=="unverified",
                     "FALSE_FORMULA_VERIFICATION")
        family=rule["source"]["kind"]
        graph.reject(family in FAMILIES,"UNKNOWN_SYNTHETIC_RULE_FAMILY")
        families.add(family)
        graph.reject(len(rule["mechanics"])==1,"MULTIPLE_MECHANICS_UNSUPPORTED")
        m=rule["mechanics"][0]
        graph.reject(m.get("phase") in STAGES and
                     m.get("trigger")=={"kind":"always"}
                     and len(m.get("actions",[]))==1,"UNSUPPORTED_EVENT_OR_PHASE")
        entries.append((STAGES.index(m["phase"]),rid,family,m))
    graph.reject(families==FAMILIES,"MISSING_SYNTHETIC_FAMILY")
    trace=[]
    for _,rid,family,m in sorted(entries,key=lambda x:(x[0],x[1])):
        if "when" in m:
            condition=evaluate(m["when"],env)
            graph.reject(type(condition)==bool,"NON_BOOLEAN_WHEN")
            if not condition:
                trace.append({"ruleId":rid,"status":"SKIPPED_CONDITION"})
                continue
        action=m["actions"][0]; op=action.get("op"); math_op=action.get("math")
        graph.reject(op in {"modify_skill","modify_stat"},"UNSUPPORTED_ACTION")
        graph.reject(math_op in {"set","add","multiply"},"UNSUPPORTED_STACKING")
        value=number(evaluate(action["value"],env))
        if op=="modify_skill":
            selector=action["skill"]
            graph.reject(selector.get("kind")=="id"
                         and selector.get("id") in skills,"UNRESOLVED_SKILL")
            props=skills[selector["id"]]
            key=action.get("property")
            graph.reject(key in props,"UNRESOLVED_SKILL_PROPERTY")
            old=props[key]
            props[key]={"set":value,"add":old+value,"multiply":old*value}[math_op]
        else:
            key=action.get("stat")
            graph.reject(key in stats,"UNRESOLVED_STAT")
            old=stats[key]
            stats[key]={"set":value,"add":old+value,"multiply":old*value}[math_op]
        trace.append({"ruleId":rid,"sourceFamily":family,"status":"SYNTHETIC_APPLIED"})
    result={"status":"PASS_SYNTHETIC_G1_THREE_FAMILY_COMPOSITION_ONLY",
            "fixtureType":"SYNTHETIC_NOT_GAME_TRUTH","patch":"3.2.1.73552",
            "sourceFamilies":sorted(families),
            "inputSha256":graph.digest(env),"rulesetSha256":graph.digest(rules),
            "stats":stats,"skills":skills,"trace":trace,
            "activeMaxrollFormulaCount":0,"independentGoldenCount":0,
            "maxrollParity":"BLOCKED_NOT_RUN","publishAllowed":False}
    result["manifestSha256"]=graph.digest(result)
    return result

def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--fixture",type=Path,required=True)
    p.add_argument("--report",type=Path,required=True)
    a=p.parse_args(argv)
    try:
        out=compose(graph.read_json(a.fixture));code=0
    except (graph.GraphError,ValueError,KeyError,TypeError,OSError,
            UnicodeError,ImportError) as e:
        out={"status":"BLOCKED","errors":[str(e)],
             "publishAllowed":False,"maxrollParity":"BLOCKED_NOT_RUN"};code=2
    a.report.parent.mkdir(parents=True,exist_ok=True)
    a.report.write_text(json.dumps(out,indent=2,sort_keys=True)+"\n")
    print(json.dumps({k:v for k,v in out.items() if k!="trace"},sort_keys=True))
    return code
if __name__=="__main__":
    sys.exit(main())
