# Issue #134 Local Acceptance

Status: `IMPLEMENTATION_COMPLETE / LOCAL_ACCEPTANCE_PASS / CI_NOT_CHECKED`

This report covers the pinned `3.2.1.73552` engine and snapshot
`maxroll-20261023T034150Z`. Returned metrics remain `OBSERVED`; exact reference
parity is not independent formula verification.

## Workstreams

| Workstream | Status | Local evidence |
|---|---|---|
| B1 Canonical schema/codec | PASS | Published schema validation for 8/8 fixtures; 128 seeded authored round-trips; unknown nested/version fields fail closed |
| B2 Entity resolver | PASS | 16/16 catalog families; stable IDs and authoritative class/slot/tree relations; other legality delegated to native loader plus exact read-back |
| B3 Whole-build loader | PASS | 8/8 real fixtures and 8/8 scratch-authored builds load through one data-driven implementation |
| B4 Semantic read-back | PASS | Profile/items/sections from calculation frame; season and shared options from scoped runtime UI; no desired-state echo |
| B5 Character Stats | PASS | Coherent runtime epoch; class-applicable raw counts 44-53; every observed display row; G1-G4 and zero egress |
| B6 Application integration | PASS | 8/8 public APIs; exact baseline/preview/commit/reset vectors; all six change kinds covered |
| B7 Universal acceptance | PASS | 8/8 classes, authored builds, deterministic property matrix, real mutations, negative and legacy regression |

## Final checklist

| ID | Status | Evidence |
|---|---|---|
| C01 | PASS | Encrypted r01/r02 fixture trust, file/input/output linkage and tamper/swap/egress/cleanup negatives |
| C02 | PASS | Runtime-definition/UI completion enumerates applicable IDs; low configured count and late valid metrics cannot truncate capture |
| C03 | PASS | JSON Schema, TypeScript and codec agree; all real fixtures and scratch inputs validate/round-trip |
| C04 | PASS | Exact applied profile/item/season/options read-back; ignored, altered, missing and ambiguous controls fail closed |
| C05 | PASS | Canonical -> Application -> engine -> independent expected raw parity for 8/8 classes |
| C06 | PASS | Eight APIs and six published change kinds have state/vector/delta assertions |
| C07 | PASS | Per-class real A->B->A plus non-empty equipment/skill/Paragon/effect/options branches |
| C08 | PASS | No known pinned valid-input mapping gap; non-authoritative legality is verified by native apply/read-back |
| C09 | PASS | Epoch/version/session/cache/recovery/zero-egress/owned-resource cleanup gates |
| C10 | PASS | Provider, Application, Browser Infrastructure and Python Rule Kit regressions |
| C11 | PASS | One-shot encrypted-Release runner, targeted resume and guaranteed plaintext cleanup |
| C12 | PASS | Current docs/coverage describe full B1-B7 rather than the earlier B0 slice |

## Real class matrix

| Class | Raw | Display | Reference | Read-back | Egress | Cleanup |
|---|---:|---:|---|---|---:|---|
| Rogue | 50 | 50 | EXACT | EXACT | 0 | PASS |
| Sorcerer | 50 | 50 | EXACT | EXACT | 0 | PASS |
| Druid | 47 | 47 | EXACT | EXACT | 0 | PASS |
| Barbarian | 47 | 47 | EXACT | EXACT | 0 | PASS |
| Necromancer | 49 | 49 | EXACT | EXACT | 0 | PASS |
| Spiritborn | 53 | 53 | EXACT plus 3 late applicable IDs beyond published 50 | EXACT | 0 | PASS |
| Paladin | 46 | 46 | EXACT | EXACT | 0 | PASS |
| Warlock | 44 | 44 | EXACT | EXACT | 0 | PASS |

## Reproduction

```bash
npm --prefix utility/d4-rulekit/providers/maxroll run acceptance:issue134 -- \
  --identity /private/fixture.agekey \
  --age-bin /path/to/age \
  --chromium /path/to/chromium \
  --resume all
```

Each child suite has a bounded timeout. `--resume` accepts a comma-separated subset of
`static,synthetic,multiclass,mutations,application,regression`. The runner downloads only the
pinned encrypted releases, verifies every trust anchor, writes sanitized evidence, and removes
decrypted temporary data on success, failure or cancellation.

GitHub Actions was neither triggered nor inspected: `CI_NOT_CHECKED`.
