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

## #108 real Maxroll parity negative integration

The #110 CI invokes the actual pinned #108 validator on #110's synthetic
composed artifact **without inventing approved Golden/formulas**. The gate
**must exit 2 and report BLOCKED**. This makes the absence of real Formula Graph
and input-complete independent Maxroll reference a hard prerequisite, despite
all structural/synthetic graph tests being green. No unchanged reference is
overwritten and no fake expected value is produced.

## F-INPUT-01 — Four missing combat-scenario truth groups (source-safe)

The [#110 independently reviewed Dev F evidence](https://github.com/Synclab-VN-dev/StreamOps/issues/110#issuecomment-6227720834)
shows **13/13 sockets and all 50 source display/raw rows**, but source-input
reproducibility is still `PARTIAL` due to four unobserved *runtime* conditions:
target debuffs, proc/uptime, transient stacks, scene/snapshot time. The 23→5
closure happened previously in F3; only 5→4 (Preparation specialty UI label)
is new for F-INPUT-01. Do not falsely call static context complete.

`scenario_state.py` is a bounded **internal schema only**, not a serialized
public #110 API change. It pins exact patch/class/F1 fingerprint and requires
all four input families. Unobserved source mode means
`state=UNKNOWN, value=null, evidenceStatus=NOT_OBSERVED_IN_STATIC_PLANNER`
for each family; no implicit false/0. Only `SYNTHETIC_SCENARIO_TEST_ONLY`
allows KNOWN values and enforces typed structures (boolean target/proc,
integer stacks, finite ratio/times, snapshot no later than current time).
No real runtime-known values are accepted or promoted. An AST-like *test-only*
predicate evaluator uses three-valued TRUE/FALSE/UNKNOWN logic with explicit
safe short-circuit rules. It is NOT the approved #107 DSL evaluator.

`scenario_graph.py` adds four labelled internal state nodes and a condition
trace, with unknowns explicitly blocking conditional effects. The real
Maxroll 50 Character Stat outputs stay `raw/display=null`, and all formula,
Golden, simulationContext and parity claims stay BLOCKED; even four complete
**synthetic test values** cannot promote real numeric calculation.

```bash
python utility/d4-formula-graph/scenario_graph.py \
  --overlay utility/d4-formula-graph/fixtures/synthetic-alpha.json \
  --scenario utility/d4-formula-graph/fixtures/maxroll-unobserved-scenario.json \
  --report artifacts/110-scenario-unknown.json
```

The four family names are public sanitized status metadata. No private
source metrics, screenshots, dynamic truth guesses or Maxroll Golden values
were committed to this PR. Full simulator dynamic-state semantics and actual
rule execution require independent verification and an approved transport.

## CI-02 mutation matrix — entirely synthetic, real class rules still pending

`synthetic_mutations.py` runs six separately asserted changed-build input
vectors against the *same* G1 DSL three-family compositor, without engine code
changes: remove item, add unrelated item, switch variant, change rune count,
change charm-set count, and change skill rank. It supports a tiny bounded
internal `build` AST allowlist for `equals`, `contains` and `and` to
exercise generic source selection. All rule docs remain explicitly synthetic;
no change to the approved #107 DSL schema and no product Maxroll formula is
executed. The separate synthetic expected table intentionally detects test
fixture drift, not gameplay balance drift.

```bash
python utility/d4-formula-graph/synthetic_mutations.py \
  --overlay utility/d4-formula-graph/fixtures/synthetic-alpha.json \
  --fixture utility/d4-formula-graph/fixtures/synthetic-three-families.json \
  --report artifacts/110-build-mutations.json
```

Full CI-02 across *real* item/skill/variant/rune rule families still requires
an approved actual rule registry/semantic model. A six-vector synthetic PASS
cannot be represented as 50/50 source-verified formula coverage.

## #109 → #110 registry selection consumer (internal, read-only)

`registry_selection_bridge.py` parses an externally generated #109
`select_rules.py` artifact and checks all 50 source IDs/groups, exact
catalog fingerprint, patch/class, all hashed selection fields, null
`executableRule`/`value`, no approved Goldens or public publish path.
The single Fire candidate remains `UNVERIFIED`, the other 49 remain
`UNKNOWN` (or all 50 UNKNOWN if the candidate is missing).
**No numeric stat can be activated from this staging source.**

The regression synthesizes the #109 selection interface because #109 Draft
PR #118 is **not merged** into #110; it does NOT falsely claim a live
cross-PR executable integration. Once Owner authorizes branch integration,
the exact real #109 selection artifact can be supplied to the same CLI.
This does not change #107 DSL or public Graph transport.

## First real-source INPUT-derived metric candidate — F-GOLDEN-01 development set

`golden_candidate_eval.py` is an **isolated test-only candidate** evaluator.
It consumes Maxroll-source input data and a **separately sanitized visible
metric inventory**, never the source's expected Character Stat outputs or any
holdout expected values. It permits only #107-G1-schema-valid unverified
`global_rule`/`class_mechanic` to set the **Level** stat via an actual
`build.level` reference; it refuses fabricated literal values, stale patch,
wrong class/fixture, extra/unexpected source rule mechanics, false VERIFIED,
mixed expected values, unsupported formulas and missing inventory rows.

This is the first **real captured-input-to-actual evaluation**, not a fake
Maxroll formula nor a full Character Stat calculation. The source Level field
is observed in two independently captured Development builds, and is NOT
taken from the golden expected files. Other stat outputs remain null/UNKNOWN.
A successful Level actual is still `CANDIDATE_COMPUTED_UNVERIFIED` until
independent parity and Owner Golden policy allow further claims.

Critical cross-class UI distinction from F-GOLDEN-01:
- Rogue DEV-00 = **50 visible rows / 50 unique metric IDs**.
- Sorcerer DEV-01 = **49 visible rows / 47 unique metric IDs**. The metric
  IDs for Toughness and Armor each appear in two different UI sections with
  equal observed values. Coverage should preserve all 49 UI row placements
  while computing a single actual value per unique ID; do not report 49 unique
  stat computations or silently discard duplicate display positions.
- Necromancer HOLDOUT-01 metric inventory reports 48 UI rows / 46 unique
  IDs, but no expected HOLDOUT values were accessed or used by this module.

```bash
python utility/d4-formula-graph/golden_candidate_eval.py \
  --source utility/d4-formula-graph/fixtures/dev01-source-sanitized.json \
  --inventory utility/d4-formula-graph/fixtures/dev01-visible-inventory.json \
  --rules utility/d4-formula-graph/fixtures/candidate-source-level.json \
  --report artifacts/110-dev01-actual.json
```

CI fixtures contain only the small *source-input* Level field and
independently captured public metric ID/group/label inventory, no source raw
Character Stats values, no hidden/private HOLDOUT expected values. For full
external offline evaluation, provide the intact authorized private source
`development/DEV-00/input.json` or `DEV-01/input.json` to `--source`;
the two captured source wrappers are independently checked. The current
partial scenario conditions do not prevent an unconditional Level value,
but any condition-dependent formulas must preserve UNKNOWN, not default 0.
No game-stat formula fidelity, full #108 parity, simulator or publishing
is implied by these 1/50 and 1/47 narrowly computed source-input branches.
