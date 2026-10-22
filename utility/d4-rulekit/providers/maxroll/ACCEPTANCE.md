# Maxroll Provider acceptance

| ID | Local automated evidence | Phase A status |
|---|---|---|
| MXP-01 | package/typecheck/provider surface/no duplicated Application APIs | LOCAL_PASS |
| MXP-02 | snapshot manifest, runtime version, game patch and asset hash mismatch tests | LOCAL_PASS |
| MXP-03 | idempotent lifecycle, timeout, late resolution, crash and cleanup tests | LOCAL_PASS |
| MXP-04 | strict bounded build mapper, effect mutation and read-back | LOCAL_PASS |
| MXP-05 | 50 expected raw IDs, 34 display values, phase/completeness negative tests | LOCAL_PASS_SYNTHETIC |
| MXP-06 | three A→B→A cycles, exact restore, stale/incomplete fail-closed | LOCAL_PASS_SYNTHETIC |
| MXP-07 | CalculationProvider contract fixture, no Application API duplication | LOCAL_PASS |
| MXP-08 | real Chromium cold replay/warm reuse/zero egress plus launch, load, calculation, queue and RSS measurements | LOCAL_PASS_SYNTHETIC |
| MXP-09 | authorized pinned Maxroll snapshot E2E | BLOCKED_AUTHORIZED_SNAPSHOT |
| MXP-10 | all 8 Application APIs through DI, offline Chromium preview/commit/reset/cleanup | LOCAL_PASS_SYNTHETIC / BLOCKED_AUTHORIZED_SNAPSHOT |
| MXP-11 | package/docs/regressions/CI evidence job | LOCAL_PASS / CI_PENDING |

Synthetic values validate orchestration only and are never reported as Maxroll Golden or formula
correctness. The 50-ID catalog comes from the existing Issue #106 research evidence; the synthetic
fixture does not reproduce Diablo IV formulas.

The integrated synthetic Chromium test proves the complete Application → Provider → Browser
Infrastructure → pinned snapshot control flow. It does not satisfy the real-runtime portion of
MXP-09/MXP-10; those gates remain blocked until an authorized Maxroll snapshot is provisioned.
