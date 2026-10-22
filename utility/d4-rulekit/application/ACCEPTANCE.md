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
| APP-02 | lifecycle, quota, TTL, bounded close, multi-session isolation | LOCAL_PASS |
| APP-03 | immutable preview, token/revision commit, reset, rollback quarantine | LOCAL_PASS |
| APP-04 | serial/parallel deterministic tests, timeout/cancel, atomic failure | LOCAL_PASS |
| APP-05 | normalized raw/display/unit/status/provenance and percentage-point delta | LOCAL_PASS |
| APP-06 | cache identity/invalidation/isolation, diagnostics, declarations and docs | LOCAL_PASS |
| APP-07 | Real Maxroll Provider integration from Issue #128 | BLOCKED_DEPENDENCY |

Synthetic metrics use the `synthetic.*` namespace and are contract fixtures only. They neither
implement nor claim any Diablo IV formula, Golden verification, or real-provider integration.

## Public operation coverage

All eight operations have positive, negative and edge coverage in `tests/unit/public-api.test.js`.
Recovery/concurrency cases are in `tests/unit/recovery.test.js`; full consumer workflows are in
`tests/e2e/application.test.js`; surface and provider-port compatibility are in `tests/contract/`.

No manual UAT is required for Phase A. Long-running stress, soak and real-provider tests are not
part of this phase; APP-07 remains explicitly blocked rather than represented by synthetic tests.
