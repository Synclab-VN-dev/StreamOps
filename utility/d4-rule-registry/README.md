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
  their proposed DSL passes G1. candidates.json contains ONE evidence-linked bounded Fire Resistance display hypothesis from F7.2, WITHOUT executable DSL. It remains CANDIDATE_UNVERIFIED; the other 49 active rules remain UNKNOWN.

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
