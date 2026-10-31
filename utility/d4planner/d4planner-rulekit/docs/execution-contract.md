# Rule Execution Contract v1 — CI-03 CANDIDATE

**Review checkpoint:** Owner approval required in #107. This is a design proposal, **not**
an executable simulator and not a claim that every Diablo IV mechanic is proven.

## 1. Responsibility boundary

`DSL Schema` enforces allowed syntax/AST, `Rule Resolver` selects rule instances, `Formula
Graph Builder` composes typed operations, and `Combat Simulator` executes timed events.
This ticket implements **G1 structural validation only**. G2 semantic/type/reference checks,
G3 independent calculation and G4 patch coverage belong to #108. No arbitrary Python,
JavaScript, or unsafe evaluation is allowed in Rule DSL.

## 2. Proposed phase ordering

1. **pre_build:** Resolve class, item slots, set counts, base parameters and static affixes.
2. **pre_skill:** Apply selected skill variants, tag/category/element transforms and base rank/shape.
3. **pre_cast:** Evaluate resource, cooldown, cast restrictions and snapshot-at-cast modifiers.
4. **on_cast:** Emit skill/projectile/trigger events with bounded recursion metadata.
5. **pre_hit:** Select targets; evaluate tag-based and conditional stat modifiers on **current** tags.
6. **on_hit:** Resolve event damage, crit/overpower/vulnerable and damage processing according to patch mechanics.
7. **post_hit:** Apply valid procs and on-hit state changes after the hit they were triggered by.
8. **on_tick / on_state_change / post_event:** Dispatch DoT/timed/summon lifecycle events and cleanup.
9. **on_equip / on_unequip:** Re-resolve equipment-derived rules and invalidate relevant graph parts.

A mechanic's `phase` is the event subscription stage; an individual action's `stage`
sets its intended calculation stage when declared. G2 must reject mismatched phase/stage
rather than silently move an action. **This compatibility matrix is not yet final.**

## 3. Deterministic order proposal

- Sort events by simulated timestamp, then phase priority, rule priority, stable ruleId/mechanicId.
- **Skill tag transforms happen before tag-filtered damage conditions.**
- Apply flat/base changes before applicable additive bucket aggregation; bucket multiplicative
  behavior is **explicitly patch-versioned**, not hardcoded global D4 truth.
- `set`/`override` conflicts need a deterministic winner and a G2 conflict diagnostic; two
  incompatible equal-priority overrides must fail rather than depend on JSON list order.
- A stat modifier is scoped to `actor`, `target`, `skill`, `summon` or `event`;
  no global leak between independent skills/targets.
- `literal.unit` is mandatory for data that enters typed arithmetic; a bare percentage must
  not be ambiguously interpreted as +20 percentage points or x1.20.
- `snapshot: cast | hit | tick | dynamic` defines when a value is captured. Re-evaluating
  another stage is a semantics error unless the action explicitly permits it.

## 4. State/event/proc proposal

- `trigger_skill`, `spawn_projectile`, `emit_event`, and `spawn_entity` create
  identifiable child events carrying origin, parent, rule chain depth and provenance.
- `chanceModel`, Lucky Hit coefficient, per-target/per-cast gating, internal cooldown,
  stack duration and reset behavior must be interpreted by the *versioned* engine.
- Recursive triggering is denied by default; explicit policies must bound `maxChainDepth`
  and prevent infinite self-trigger loops/cycles.
- State changes affect **future** events; retroactive re-evaluation of an earlier hit is forbidden.
- Expiration/tie-break at the same simulation timestamp must be consistent; exact convention
  and event inheritance flags remain **OPEN for Owner contract review**.

## 5. Gaps and non-goals

- No proven patch-accurate crit/vulnerable/overpower/armor formula, attack frames, projectile
  physics, summon AI, proc rolls, or hit probability in this ticket. No false DPS outputs.
- No G2/G3/G4 implementation: a G1 PASS means **schema valid only**, not runnable/verified rule.
- Parent #105 scope is Offensive; contract types anticipate Defense/Sustain without scoring them.
- Open design decisions: phase-action compatibility, override precedence, numeric unit algebra,
  damage bucket registry, event ordering ties, state snapshot and recursion inheritance policy.
  Changes beyond approved candidate require explicit Owner approval before freezing v1.

## 6. Contract examples

See synthetic `fixtures/valid/{skill,item-effect,charm-set,synthetic-proc}.json`.
They demonstrate syntax across skill, conditional aspect, charm set and proc-chain classes.
Not game-verified coefficients or a substitute for independent calculation goldens.

## 7. Machine-readable contract (CI-03)

**Canonical source:** [contracts/execution-v1.json](../contracts/execution-v1.json).
Unlike the prose above, this document is machine-checked against all 15 action discriminators
in `rule-v1.schema.json`, the complete phase enum, evidence registry and bounded
reference vectors. The model's tie-break order is an **engineering convention**,
not a proven Blizzard internal event order.

The current baseline is patch 3.2.3 build 73883. Blizzard's patch notes certify patch identity,
not a universal damage algorithm; numerical vectors are labeled historical or synthetic.
See [mechanics evidence](game-mechanics-3.2.3.md) and [semantic decisions](semantics-decisions.md).

Run:
```bash
python -m d4_rulekit.contract_check \
  --contract utility/d4planner/d4planner-rulekit/contracts/execution-v1.json \
  --references utility/d4planner/d4planner-rulekit/references/3.2.3/ci03-reference-vectors.json \
  --report artifacts/d4-rulekit/ci03-contract.json
```

**Important:** a CI-03 PASS proves the declarative contract consistency and explicitly sourced
example behavior only. No arbitrary 3.2.3 skill damage, snapshot, DoT, proc or DPS accuracy is
claimed. Such mechanics must remain UNVERIFIED/UNKNOWN until #108 G2/G3 and #109 rule evidence.
New semantic policy is a substantial addition to the previously approved PR #112 schema
candidate and requires a renewed Owner review before freezing or merging.
