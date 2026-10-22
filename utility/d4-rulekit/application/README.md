# D4 Rule Kit Application

Provider-agnostic session orchestration for calculated build metrics. The package owns build
revisions, preview/commit/reset semantics, result normalization, cache identity, diagnostics,
timeouts and cleanup. Providers own all game-specific change application and calculation.

The public application surface has exactly eight operations:

1. `listProviders()`
2. `createSession()`
3. `evaluate()`
4. `previewChanges()`
5. `commitChanges()`
6. `resetSession()`
7. `getSession()`
8. `closeSession()`

```js
const { CONTRACT_VERSION, D4RuleKitApplication } = require('@streamops/d4-rulekit-application');

const app = new D4RuleKitApplication({ providers: [provider] });
const session = await app.createSession({
  contractVersion: CONTRACT_VERSION,
  providerId: provider.id,
  providerVersion: provider.version,
  snapshotId: null,
  snapshotManifestSha256: null,
  buildSchemaVersion: 'consumer-build/v1',
  build,
});
const current = await app.evaluate(session.sessionId);
```

## Safety semantics

- A session pins provider version, snapshot identity/digest, build schema, fingerprint and revision.
- Preview never publishes candidate state. Stateful providers must implement checkpoint/restore.
- Commit requires both optimistic `expectedRevision` and a matching preview token.
- Rollback failure quarantines the session. Timed-out/cancelled stateful mutation is fail-closed.
- `UNKNOWN` and `UNSUPPORTED` metrics preserve `null`; normalization never invents zero.
- Provider `OBSERVED` output is never promoted to `VERIFIED`.
- Cache identity includes provider, snapshot digest, build, contract/schema and capability policy versions.
- Application core imports no browser or provider-specific implementation.

The synthetic providers in tests exercise contracts only; they are not Diablo IV formulas and are
not evidence for APP-07. Real provider integration remains blocked on Issue #128.

## Local gates

```bash
npm ci
npm test
```

Each test command is bounded to two minutes and writes local reports under ignored `artifacts/`.
