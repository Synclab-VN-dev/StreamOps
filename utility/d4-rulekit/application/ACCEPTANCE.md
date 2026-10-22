# Phase A acceptance map

```text
D4Planner / future transport
            |
            v
 D4RuleKitApplication (8 operations)
   |-- ProviderRegistry
   |-- session/build state + serial executor
   |-- calculation orchestration + recovery
   |-- result normalization + delta
   `-- version-safe cache + diagnostics
            |
            v
 CalculationProvider / ProviderSession ports
```

The Application package has no dependency on Browser Infrastructure. A future browser-backed
provider may compose it, while a stateless provider can implement the same port without browser
code. Provider state and business calculations never enter Application Core.

| Acceptance | Automated evidence | Phase A expectation |
|---|---|---|
| APP-01 | registry unit tests, exact API contract, provider-B substitution | LOCAL_PASS |
| APP-02 | atomic quota reservations, late-cleanup quarantine, proactive TTL cleanup, bounded close, isolation | LOCAL_PASS |
| APP-03 | immutable preview, token/revision commit, reset, rollback quarantine | LOCAL_PASS |
| APP-04 | serial/parallel tests, late-runtime cleanup, timeout/cancel and stateful recovery | LOCAL_PASS |
| APP-05 | normalized raw/display/unit/status/provenance and percentage-point delta | LOCAL_PASS |
| APP-06 | cache identity/invalidation/isolation, diagnostics, declarations and docs | LOCAL_PASS |
| APP-07 | all 8 APIs with MaxrollProvider + pinned synthetic offline runtime | LOCAL_PASS_SYNTHETIC / BLOCKED_AUTHORIZED_SNAPSHOT |

Synthetic metrics use the `synthetic.*` namespace and are contract fixtures only. They neither
implement nor claim any Diablo IV formula, Golden verification, or real-provider integration.

## Public operation coverage

All eight operations have positive, negative and edge coverage in `tests/unit/public-api.test.js`.
Recovery/concurrency cases are in `tests/unit/recovery.test.js`; full consumer workflows are in
`tests/e2e/application.test.js`; surface and provider-port compatibility are in `tests/contract/`.

Review regressions `APP-R1` through `APP-R5` cover concurrent capacity reservation, late provider
resolution, complete metric coverage, stateful evaluation recovery and active TTL cleanup.
`APP-R6` proves a timed-out creation retains capacity until late cleanup succeeds; rejected or hung
cleanup remains fail-closed and cannot overcommit `maxSessions`.
`APP-R7` routes preview's baseline evaluation through the same checkpoint/recovery path as public
evaluation: a provider mutation followed by failure is restored, while failed restore,
timeout or cancellation quarantines the session and invalidates cached reuse.

No manual UAT is required for Phase A. Long-running stress and soak tests are not part of this
phase. The synthetic integration establishes contract compatibility but does not promote the real
Maxroll portion of APP-07, which remains explicitly blocked on an authorized snapshot.
