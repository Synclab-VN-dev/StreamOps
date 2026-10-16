# #109 — Maxroll Rule Registry / AI candidate staging

This is a **version-pinned, offline, read-only candidate staging registry**. It is not an
AI inference engine, a Dynamic Formula Graph, a Maxroll Golden store, or a DPS simulator.
It does not crawl Maxroll, modify any equipment/profile, publish anything, or change the
#107 DSL Schema v1. It never executes a candidate expression.

## Source contract

- Source catalog: ../d4-maxroll-reference/f8-character-metric-catalog.json from #106
  (pinned Git blob ebf17a0e64e249448609145b89753fec3709ae7d).
- Baseline: Owner-pinned Maxroll 3.2.1.73552, **one Rogue fixture**,
  input-completeness PARTIAL.
- 50 stable IDs: 27 BOUNDED_VERIFIED / 23 PARTIAL as *source research only*.
  None is full VERIFIED; Golden approved 0; real Graph-vs-Maxroll parity NOT_RUN.
- Registry initial state: 50 UNKNOWN active rules, 0 numeric outputs. Candidate
  entries may carry research evidence but remain CANDIDATE_UNVERIFIED even when
  their proposed DSL passes G1. candidates.json contains ONE evidence-linked bounded Fire Resistance display hypothesis from F7.2, with a schema-valid *staged DSL expression* that is NOT executable/active: its input binding R is UNKNOWN and complete resistance aggregation, caps, conditions and Golden parity are not proved. It remains CANDIDATE_UNVERIFIED; the other 49 active rules remain UNKNOWN.

## Run locally (Python 3.12)

    python -m pip install -e 'utility/d4-rulekit[dev]'
    python utility/d4-rule-registry/registry.py --report artifacts/109-snapshot.json
    python utility/d4-rule-registry/registry.py --synthetic-patch-cycle utility/d4-rule-registry/fixtures/synthetic-patch-cycle.json --report artifacts/109-patch.json
    python -m unittest discover -s utility/d4-rule-registry/tests -p 'test_*.py' -v

Exit: 0 = structural PASS / simulated patch PASS, 2 = BLOCKED with an explanatory
JSON report. Structural PASS is **never** a numeric/game-correctness or G3/G4 PASS.

## Candidate staging policy

Optional candidates.json records must supply the exact patch/build/class/metric ID,
immutable-looking source SHA, independently linkable Maxroll evidence, G1-G4 NOT_RUN
and no active rule or Golden. Candidate DSL, when provided, is checked against
the **existing #107 JSON Schema**; schema acceptance is G1 only. G2 candidate
metric dependency cycles/unknown references are rejected. Unsupported operators
cause G1_SCHEMA_FAIL, not automatic schema extension.

Promotion is intentionally **unavailable** in this stage. To add promotion, #109
must first receive independent formula evidence, all approved G1–G4 gates,
a policy decision on publishing signed/approved rules, rollback plan, and explicit
Owner approval. There is no published snapshot mutation or active math.

The synthetic patch cycle proves a deterministic diff for add/remove/buff/nerf and
reproducible old→new→rollback *only using fake fixture names*. It is NOT evidence
about a real Diablo IV patch; never promote its values.

## Handoff

- #109: continue provenance-graded candidate enrichment from immutable Maxroll
  captures; never fill the missing 23 formulas by guessing.
- #110: only independently validated active rules may drive Formula Graph values;
  unknown rule contributions become UNKNOWN, not zero.
- #108: independent complete Golden vs Graph actual, separate fail-closed gate.
- #111: offense-only simulator consumes Graph outputs.
- Any agent proposes candidate data via PR only; no auto-publish or unreviewed
  source update. Owner reviews the consolidated Epic #117, not individual PRs
  unless a genuine contract/design checkpoint is needed.

## F7.2 independently reviewed source-only display replay

The **single** staged Fire Resistance candidate links independent F7.2 source
evidence (5 controlled R points at Rogue level 50). Offline Decimal arithmetic
checks the bounded display relation **90*R/(R+15*Level)** within predeclared
0.05 percentage points. This is a source research replay, **not** a verified
complete stat formula: resistance aggregation, unrounded helper, explicit cap,
other classes/branches, fully reproducible character inputs and #108 Golden
parity remain unverified. The staged DSL uses existing #107 `modify_stat` + expression AST operators only and is never executed by #109. G1 syntax PASS is not G2 input binding, G3 numeric evidence or G4 coverage PASS. Neither candidate nor the source fixture is active.

    python utility/d4-rule-registry/research/check_fire_dr.py --report artifacts/109-fire-dr.json

CI fails closed for a changed source value, patch, level, tolerance or attempted
raw-helper/cap/Golden promotion. The source vector is independent of a future
Graph implementation but **is not itself an approved complete Golden fixture**.

## Deterministic on-demand agent handoff

`audit_agent.py` provides an offline, **non-generative evidence-to-candidate audit**:
it reads the immutable #106 catalog, pinned reviewed F7.2 source vectors, and
the candidate #107 DSL v1 expression. It constructs a **50-row review queue**
without guessing the other 49 formulas. The one staged Fire AST must contain
the exact source-bounded multipliers (`0.9`, `15`), references to
`actor.resistance.fire.total` and `actor.level`, and the required source
limitations. Numeric coefficient/binding tampering or fake Golden/Verified
promotion fails closed.

    python utility/d4-rule-registry/audit_agent.py --report artifacts/109-agent-audit.json

Report state: G1 candidate DSL shape valid; G2 actor binding UNRESOLVED, G3
only observed rounded display evidence, G4 50/50 ID coverage but just ONE
DSL candidate, 0 active rules. This is not an LLM inference workflow or full
agent-generated patch discovery. New candidate formula proposals must arrive
with independent source evidence; agent must never fabricate expected values
or promote its own formula prediction to Golden.

## Append-only patch ledger / rollback

`versioned_history.py` records a **synthetic-only** immutable 3-event hash
chain: baseline, changed patch, and rollback to precisely the original rule
data. Every event pins the previous event hash; the manifest pins full history.
An independent `verify` pass rejects altered event contents, reordered events,
broken parents, inaccurate added/removed/buffed/nerfed classifications, and
any attempt to mark a record active. CI runs positive and negative tests and
uploads the replay report.

    python utility/d4-rule-registry/versioned_history.py --report artifacts/109-ledger.json

This exercise proves deterministic versioning mechanics, NOT a real patch
migration or signed/approved production registry. No production publish exists.

## CI-01 source-graded patch discovery and candidate diff

`patch_proposal.py` reads an **immutable, synthetic-only** patch delta fixture
and a separately maintained evidence manifest, both pinned with real Git blob
SHA-1 and raw-file SHA-256. Produces 4 explicitly sourced candidates covering
buff, nerf, removal, and new mechanic; reports changed/sourced denominators.
It rejects missing/duplicate/stale/mismatched source pointers and cross-patch
source mutation. This is deterministic offline candidate generation, not
generative-AI reverse engineering. No executable game rule or active patch
change; #107 DSL v1 remains unchanged. Production Maxroll patch evidence,
G2/G3/G4 and Owner review would still be mandatory for publish.

    python utility/d4-rule-registry/patch_proposal.py --report artifacts/109-proposals.json

A PASS here proves **CI-01 with synthetic patch input only**, not that any new
real game mechanics have been independently discovered or verified.

## CI-02 read-only provenance and immutability guard

`review_policy.py` performs independent **source binding review** beyond a
syntactically plausible 40-character commit: the sole staged Fire candidate
must match the exact #106 independently reviewed source URL, issue evidence,
commit, patch/class, evidence research grade, the existing DSL v1 G1 gate,
and all four unrun G1–G4 promotion statuses. Extra unregistered rule sources,
forced G1/G2/G3/G4 `PASS`, claimed Golden or Owner signoff, stale versions,
and any policy attempt to auto-publish are rejected before output.

`fixtures/synthetic-approved-lock.json` represents an **approved-like
SIMULATION ONLY**. Its immutable content hash is independently pinned inside
`review_policy.py`. Testing any attempted rewrite (including identical
payloads, misleading approval metadata, new hash, wrong key) is rejected.
It is explicitly **not an actual owner-approved Maxroll ruleset**; no
production-publish operation or real owner-approved snapshot exists. The
review function never writes to an approved store.

    python utility/d4-rule-registry/review_policy.py --report artifacts/109-policy.json

`PASS_CI02_READ_ONLY_POLICY_GUARDS_ONLY` means automated CI-02 safety checks
are in place for **staged data and an immutable synthetic approval fixture**,
not that a real owner-approved snapshot was tested. Publication remains blocked
until an approved real Golden, independently verified G1–G4, recorded Owner
approval and a separately approved publish workflow exist. Keep CI-02's full
live-publish acceptance pending.
