# #110 — Dynamic Formula Graph internal smoke, not product readiness

This preliminary implementation **does not** calculate game stats. It is an
offline, fully deterministic source catalog reconciliation and typed graph
skeleton to establish fail-closed output requirements before independently
verified formulas exist.

## Scope / precedence

- Source: exact immutable #106 Rogue 50-metric Maxroll UI inventory,
  Owner-pinned game build 3.2.1.73552, source input PARTIAL.
- Output: ALL 50 groups and ID rows, each raw/display = `null`,
  unit/rounding = `null`, `status=UNKNOWN`; observed F4 runtime dependencies
  are labelled **source-only**, not silently promoted to executable edges.
- Two *synthetic-only* input overlays prove deterministic graph hashes and
  variation when equipment, skills or charms change, without inventing actual
  computed game stats.
- Generic structural DAG topological sort refuses missing refs or cycles.
- Explicitly **not** the approved serialized `FormulaGraphResult` transport
  or a verified #110 executable rule compiler/evaluator. `simulationContext`
  is null, so #111 cannot mistake the result for ready combat inputs.
- #108 Golden comparator must remain BLOCKED; no formula source-derived
  Maxroll expected value may be copied into `actual`.

## Smoke

```bash
python utility/d4-formula-graph/graph.py --overlay utility/d4-formula-graph/fixtures/synthetic-alpha.json --report artifacts/110-alpha.json
python utility/d4-formula-graph/graph.py --overlay utility/d4-formula-graph/fixtures/synthetic-beta.json --report artifacts/110-beta.json
python -m unittest discover -s utility/d4-formula-graph/tests -v
```

Next implementation needs #109 verified **active** rules, typed contributors/
units/conditions, #107 action interpretation, real complete build input and
independently sourced changed-input Maxroll vectors. Never turn UNKNOWN into
zero, and do not tick #110's full Formula Graph acceptance from this smoke.

## CI-01 synthetic DSL v1 execution/composition (bounded)

A focused `synthetic_compiler.py` stage composes exactly three **G1 schema
valid** #107 source families: active skill projectile count, conditional
legendary aspect and charm-set count threshold. It uses typed Expression AST
allowlist with no arbitrary code execution, explicit input refs, deterministic
stage sorting and strict fail-closed rejection for unsupported mechanics.
Independently frozen synthetic fixture expects projectile count 2 and damage
bonus 30 fake units. It is NOT a real game formula, Maxroll Goldens or
production graph semantic coverage for all 15 DSL action operators.

    python utility/d4-formula-graph/synthetic_compiler.py --fixture utility/d4-formula-graph/fixtures/synthetic-three-families.json --report artifacts/110-three-families.json

The rest of #110 (tags, event edges, cap/ICD, resolver, actual Maxroll 50 stat
computation, simulationContext) remains pending.

## Three-family synthetic composition integrated with source Graph

`demo_graph.py` packages a 50-ID **unknown** source Graph together with a
separate three-family synthetic DSL execution subgraph under a new internal
`syntheticOutputOnly` field. Mutating a synthetic DSL value or condition
deterministically changes the composed graph SHA while preserving 0/50 actual
Maxroll computed metrics and null `simulationContext`. This is evidence that
the **synthetic CI-01 composition** mechanism is pluggable without changing
engine code; it does not establish production full-DSL engine semantics or any
real Maxroll parity.

    python utility/d4-formula-graph/demo_graph.py --overlay utility/d4-formula-graph/fixtures/synthetic-alpha.json --synthetic utility/d4-formula-graph/fixtures/synthetic-three-families.json --report artifacts/110-composed.json

No public transport contract has been introduced or approved.
