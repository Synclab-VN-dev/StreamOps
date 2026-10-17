"""#111 event-based offense sandbox. No Diablo IV/Maxroll DPS claims."""
import hashlib,json,math,random
class Blocked(ValueError):pass
def need(ok,msg):
    if not ok:raise Blocked(msg)
def digest(x):
    return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
KEYS={"mode","power","rate","critChance","critMultiplier","procChance",
      "procMultiplier","procIcd","cooldown","resource","cost","regen","cap",
      "uptime","horizon","seed","rank","rankBonus"}
def simulate(p):
    need(type(p)==dict and set(p)==KEYS and p["mode"]=="SYNTHETIC_ONLY",
         "UNTRUSTED_SIMULATION_INPUT")
    need(type(p["seed"])==int and 0<=p["seed"]<2**32,"BAD_SEED")
    for k in KEYS-{"mode","seed"}:
        need(type(p[k]) in (int,float) and math.isfinite(p[k]) and p[k]>=0,
             "NONFINITE_OR_NEGATIVE_"+k)
    need(0<p["horizon"]<=3600 and 0<p["rate"]<=100 and
         0<=p["critChance"]<=1 and 0<=p["procChance"]<=1 and
         0<=p["uptime"]<=1 and 1<=p["critMultiplier"]<=100 and
         p["cap"]>=p["resource"]>=0 and p["cap"]>=p["cost"] and
         0<=p["rank"]<=30,"OUT_OF_BOUNDS")
    n=math.ceil(p["horizon"]*p["rate"])
    need(n<=360000,"TOO_MANY_EVENTS")
    rng=random.Random(p["seed"])
    power=p["power"]*(1+p["rank"]*p["rankBonus"])
    stored=float(p["resource"]);last_t=0;last_cast=-math.inf;last_proc=-math.inf
    events=[];base=crit=proc=0.0
    for i in range(n):
        t=i/p["rate"]
        if t>=p["horizon"] or t>=p["horizon"]*p["uptime"]:continue
        stored=min(p["cap"],stored+(t-last_t)*p["regen"]);last_t=t
        if t-last_cast+1e-9<p["cooldown"] or stored+1e-9<p["cost"]:continue
        stored-=p["cost"];last_cast=t
        crit_d=power*(p["critMultiplier"]-1) if rng.random()<p["critChance"] else 0
        triggered=rng.random()<p["procChance"] and t-last_proc+1e-9>=p["procIcd"]
        proc_d=power*p["procMultiplier"] if triggered else 0
        if triggered:last_proc=t
        base+=power;crit+=crit_d;proc+=proc_d
        events.append({"time":round(t,9),"base":power,"critExtra":crit_d,
                       "procExtra":proc_d,"resourceAfter":round(stored,9)})
    out={"artifactType":"SYNTHETIC_OFFENSE_ONLY_NOT_GAME_DPS",
         "sourceMode":"SYNTHETIC_ONLY","seed":p["seed"],
         "inputSha256":digest(p),"eventCount":len(events),
         "events":events,"damageBreakdown":{"base":base,"critExtra":crit,"procExtra":proc},
         "syntheticDps":(base+crit+proc)/p["horizon"],
         "realDps":None,"maxrollGoldenParity":"NOT_RUN","publishAllowed":False}
    out["reportSha256"]=digest(out);return out

def require_graph(graph,offensive_metric_ids):
    need(type(graph)==dict and graph.get("artifactType") in {
        "DEVELOPMENT_SOURCE_GRAPH_NOT_PUBLIC_BE",
        "INTERNAL_GOLDEN_DRIVEN_CANDIDATE_ACTUAL_NOT_PUBLIC_BE"},
        "NOT_GRAPH_METRIC_INPUT")
    need(type(offensive_metric_ids)==list and offensive_metric_ids and
         len(set(offensive_metric_ids))==len(offensive_metric_ids),
         "INVALID_METRIC_DEPENDENCY_SET")
    rows=graph.get("sourceStatActual",graph.get("characterMetrics",[]))
    known={r["metricId"]:r for r in rows}
    unresolved=[mid for mid in offensive_metric_ids
                if mid not in known or
                known[mid].get("status")!="VERIFIED_INDEPENDENT_MAXROLL_PARITY"]
    conditional=graph.get("scenarioStates",{})
    unknown=[x for x,v in conditional.items() if v=="UNKNOWN"]
    blocked=bool(unresolved or unknown or not graph.get("publishAllowed"))
    return {"status":"BLOCKED" if blocked else "ELIGIBILITY_ONLY_NOT_DPS",
            "unverifiedRequiredMetrics":unresolved,"unknownScenarioTruths":unknown,
            "graphSha256":graph.get("graphSha256"),"realDps":None,
            "syntheticDps":None,"statRecalculation":False,
            "completeCharacterStatParity":False,"publishAllowed":False}
