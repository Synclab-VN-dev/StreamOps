# Maxroll Calculation Provider

Version-pinned Calculation Provider for D4 Rule Kit. It composes the generic Chromium and Web
Snapshot infrastructure from Issue #124 and exposes the provider/session port expected by Issue
#127. It does not own Application registry, revision, preview tokens, cache or delta logic.

```text
MaxrollProvider
  -> MaxrollPatchProfile (snapshot/runtime/asset pin)
  -> MaxrollSession (desired-state and recovery lifecycle)
  -> MaxrollBuildMapper (bounded input support)
  -> MaxrollRuntimeAdapter (UI apply/read-back + CDP)
  -> MaxrollMetricsExtractor (freshness and completeness)
  -> BrowserInfrastructure / WebSnapshotManager
```

## Supported scope

The initial profile contract is deliberately bounded to the previously evidenced fixture:

- game patch `3.2.1.73552`;
- Rogue, level 50, Torment I;
- Runic Skullcap in Helm;
- optional `of-dampening` effect mutation;
- 50 raw Character Stat IDs and 34 independently displayed values.

Every other class, level, item slot, skill, Paragon, rune, charm or change type is
`UNSUPPORTED_INPUT`; it is never silently ignored. `OBSERVED` provider output is not Formula or
Golden `VERIFIED` evidence.

## Runtime safety

- Snapshot ID and external manifest SHA-256 are pinned and verified before acquiring Chromium.
- The active runtime asset SHA-256, runtime version and game patch are checked fail-closed.
- Offline-strict snapshot routing is mounted before navigation; missing requests are aborted.
- Desired state is applied through the runtime UI contract and read back before metric extraction.
- Every extraction requires a new phase marker and the complete profile metric catalog.
- A timeout/cancel, browser disconnect or failed recovery invalidates and cleans the session.
- No login, Save/Publish, cookie/token access or formula implementation exists in this package.

The repository contains only a synthetic Maxroll-shaped website used to test architecture and real
Chromium lifecycle. It contains no Maxroll asset body. Real Maxroll E2E remains
`BLOCKED_AUTHORIZED_SNAPSHOT` until a permitted generic snapshot package is provisioned and pinned.

## Local tests

```bash
npm ci
npm run typecheck
npm run test:unit
npm run test:contract
BROWSER_INFRA_CHROMIUM_PATH=/path/to/pinned/chrome npm run test:e2e
```

Tests are deterministic and bounded. The E2E suite starts a local synthetic origin, captures it with
the generic Snapshot Manager, then evaluates three A→B→A cycles from offline-strict replay with zero
origin requests. It also exercises all eight D4 Rule Kit Application APIs through provider dependency
injection, including immutable preview, commit, reset and cleanup. This is architecture/lifecycle
evidence only; real Maxroll integration remains `BLOCKED_AUTHORIZED_SNAPSHOT`.

The MXP-08 E2E writes local launch/load/calculation/queue/RSS observations to ignored
`artifacts/performance.json`; these measurements are evidence, not performance thresholds.
