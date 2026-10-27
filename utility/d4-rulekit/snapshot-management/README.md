# Rule Kit Snapshot Management v1

Owner approved API/operating semantics and Ed25519 trust design on 27/10/2026.
Production trust activation remains **BLOCKED: Owner verification key/key ID not
provided**. `src/production-trust-anchors.json` contains no keys. No private key,
test verification key, snapshot payload or real private profile is shipped.

## Ownership and contracts

Rule Kit owns registry/trust/resolver/profile/strategy/import/selection/rollback.
BE transports requests and restarts its owned worker only when Rule Kit requests
it. FE consumes normalized BE status. Canonical build schema and the eight
Application methods are unchanged.

Management uses a separate private IPC namespace `d4-rulekit-snapshots/v1` with
correlation, worker identity/generation, bounded queue, operation deadlines and
typed errors. Calls are JSON Schema validated (`schemas/call.schema.json`), registry
and package manifests have separate real JSON Schema validation.

| Method | Params | Result |
|---|---|---|
| listInstalled | `{}` | Installed IDs, integrity and compatibility status |
| checkCompatibility | `entryId` | Exact verified binding/evidence class or error |
| getCapabilities | `{}` | Calculation/management availability and typed capabilities |
| importPackage | `kind=SNAPSHOT, packagePath` or `kind=REGISTRY, envelope` | Verified immutable import; never implicit activation |
| activate / switchSnapshot | `entryId` | Pending selection + `restartRequired` |
| getActive | `{}` | Active binding, worker generation, selection revision or UNAVAILABLE |
| rollback | `{}` | Explicit verified previous selection + `restartRequired` |
| compareSnapshots | baseline/candidate snapshot refs + scope/coverage | Offline content version/diff; no compatibility/activation |

Directory packages contain `snapshot-package.json`, `profile.json`, and
`snapshot/<id>/{manifest.json,manifest.sha256,blobs/...}`. Outer manifest inventories
every file with size/SHA; inner captured manifest and its approved pin are never
rewritten. Public IPC cannot override internal store/profile paths. Filesystem
paths are only available to this owned private/local provisioning boundary, not
arbitrary WebSocket messages.

## Compatibility and strategies

Registry entries bind Rule Kit/provider/codec/schema versions, strategy/profile,
snapshot manifest, game patch/engine/catalog hashes, exact capabilities and
approval evidence. A signature does not create a codec or prove compatibility.
The resolver only uses strategy implementations registered in Rule Kit code.

The existing D12 canonical guards remain unchanged. `maxroll-ui-cdp-D12-v1`
supports the established narrow UI fixture contract; `maxroll-native-D12-v1`
uses the existing canonical codec/universal factory with its original strict
D12 snapshot guard. A newer snapshot needs independently verified bindings and
an implemented compatible strategy; same patch/checksum alone is insufficient.

| Binding | Evidence | Production status |
|---|---|---|
| Synthetic A/B, shared synthetic strategy | Node manager + real Node IPC switch/restart/rollback tests | TEST_ONLY; rejected in PRODUCTION scope |
| Existing pinned D12 provider/codec | Existing guards retained; new registry path requires Owner-signed exact binding/evidence | BLOCKED pending production anchor/registry |
| Second real snapshot | Not supplied/authorized with compatibility evidence | NOT_RUN |

## Lifecycle and failure semantics

Multiple snapshots may be installed. One worker generation uses one active
binding. Switch closes sessions, invalidates old calls and persists the next
selection, then requests bounded worker reconfiguration. A fresh process/client
invalidates old session refs, leases and cache. Explicit rebind does not spend the
separate crash-recovery restart budget. No automatic snapshot/profile fallback.

No selection: Application/BE/HUD/Equipment may run, calculation UNAVAILABLE.
Configured-invalid/revoked: never calculation READY; management reports the
reason and retains data so explicit repair is possible. Rule Kit upgrade preflight
rejects incompatible/untrusted active bindings. Legacy bundled-snapshot installs
require explicit trusted migration; public application upgrade cannot silently
remove/disable their old snapshot. Installer keeps old app/data on failure.

Store is outside installation. Imports stage/verify before immutable publish,
reject undeclared files/symlinks/path traversal and never activate implicitly.
Selection changes preserve unrelated DB/Targets/Settings. Unknown/corrupt bindings
fail closed. Process ownership locks reject active managers; a stale lock can only
be reclaimed after its recorded PID is dead, without killing another process.

## Trust/revocation

Ed25519 signs canonical JSON of the registry payload (object keys sorted, arrays
ordered, UTF-8). Public anchors and minimum revision are pinned in Rule Kit, never
loaded from user-provided APPROVED JSON or arbitrary environment keys. Test anchors
are injected only into isolated test composition, excluded from production build.

Registry signatures, expiration, monotonic revision, same-revision collisions and
cumulative revocations are checked independently from resource integrity and
compatibility. Persisted registry/high-water mismatch is UNAVAILABLE/fail-closed;
a verified later registry can explicitly repair an interrupted update. Offline
revocation becomes effective only after importing a verified revision.

Anti-rollback uses pinned minimum revision plus retained authenticated registry
and high-water state. It is not a claim of hardware rollback protection against
an attacker restoring/replacing the entire user installation/state/clock. Secret
signing keys are never stored in source, application or artifacts.

Distribution permission is separate, currently PRIVATE_ONLY. No approval to
publish Maxroll snapshot plaintext or encrypted content has been granted.

## Local checks

```bash
npm ci --ignore-scripts --prefix utility/d4-rulekit/snapshot-management
node --test utility/d4-rulekit/snapshot-management/tests/*.test.js
PYTHONPATH=utility/d4planner/src python -m pytest -q utility/d4planner/tests/test_snapshot_worker.py utility/d4planner/tests/test_rulekit_worker.py
```

These tests do not certify real multiple-snapshot provider compatibility. Native
Windows/real provider tests are separately reported, never inferred from synthetic
fixtures. No Actions dispatch/query is performed.

Content-version contract và SVER-01…05: [CONTENT-VERSION.md](CONTENT-VERSION.md).
