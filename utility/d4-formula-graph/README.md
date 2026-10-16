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
