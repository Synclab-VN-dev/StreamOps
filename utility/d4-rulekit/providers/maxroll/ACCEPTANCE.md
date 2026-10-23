# Maxroll Provider acceptance

| ID | Local automated evidence | Phase A status |
|---|---|---|
| MXP-01 | clean packed local dependency, direct BrowserInfrastructure import, package/typecheck/provider surface | LOCAL_PASS |
| MXP-02 | snapshot manifest, runtime version, game patch and asset hash mismatch tests | LOCAL_PASS |
| MXP-03 | idempotent lifecycle, timeout, late resolution, crash and cleanup tests | LOCAL_PASS |
| MXP-04 | strict bounded build mapper, effect mutation and read-back | LOCAL_PASS |
| MXP-05 | 50 expected raw IDs, 34 display values, finite-number/display/unit/phase/completeness gates | LOCAL_PASS_SYNTHETIC |
| MXP-06 | three A→B→A cycles, exact restore, stale/incomplete fail-closed | LOCAL_PASS_SYNTHETIC |
| MXP-07 | CalculationProvider contract fixture, no Application API duplication | LOCAL_PASS |
| MXP-08 | real Chromium cold replay/warm reuse/zero egress plus launch, load, calculation, queue and RSS measurements | LOCAL_PASS_SYNTHETIC |
| MXP-09 | automated live capture + reusable real offline A→B→A contract | LIVE_CAPTURE_PASS / BLOCKED_PATCH_DRIFT |
| MXP-10 | all 8 Application APIs through DI, offline Chromium preview/commit/reset/cleanup | LOCAL_PASS_SYNTHETIC; REAL_CONTRACT_PASS / BLOCKED_PATCH_DRIFT |
| MXP-11 | package/docs/regressions/CI evidence job | LOCAL_PASS / CI_PENDING |

Synthetic values validate orchestration only and are never reported as Maxroll Golden or formula
correctness. The 50-ID catalog comes from the existing Issue #106 research evidence; the synthetic
fixture does not reproduce Diablo IV formulas.

Real adapter compatibility and provenance are documented in `RUNTIME-COMPATIBILITY.md`. The
version-specific runtime/read-back/extraction strategies and executable contract now exist. Issue
#132 automates the ephemeral snapshot lifecycle and validates it against the independent trust
anchor. The current live asset `/assets/export-D12aM6KT.js` does not match the historical pinned
asset, so real execution is correctly blocked pending a reviewed version profile/adapter update.

The integrated synthetic Chromium test proves the complete Application → Provider → Browser
Infrastructure → pinned snapshot control flow. It does not satisfy the real-runtime portion of
MXP-09/MXP-10; those gates remain blocked until the observed runtime drift is investigated and a
compatible profile is independently reviewed.
