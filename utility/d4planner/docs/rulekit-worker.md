# Managed Rule Kit worker (S3)

Contract source: S1 #138, revision `d4planner-r1-contract/2026-10-25.5`.
Implementation ticket: #140.

## Ownership and boundaries

The D4Planner backend owns exactly one long-lived Node worker. The Python
`RuleKitProcessWrapper` owns process lifecycle, while `RuleKitClient` owns the
private JSON-lines IPC correlation. The internal Rule Kit bootstrap (under `utility/d4-rulekit/application/src/runtime/`) reuses the
existing `D4RuleKitApplication`, `MaxrollProvider`, `WebSnapshotManager`, and a
single shared `BrowserInfrastructure` instance.

The wrapper never searches for a process by executable name. Graceful stop,
termination and final kill address only the child PID/process group returned by
its injected process driver. stdin EOF, owner shutdown, SIGTERM and SIGINT all
close sessions and the shared browser. A valid READY message proves that the
composition was created and exposes the exact approved API/version; spawning a
process alone is not readiness.

```text
STOPPED -> STARTING -> READY -> STOPPING -> STOPPED
                 \-> FAILED <- unexpected child exit

READY -- bounded restart --> STOPPED -> STARTING (new instance + generation)
```

Worker restart invalidates every old session reference and preview token. The
caller must create a new session from a complete, committed canonical input;
mutations are never replayed blindly. Rule Kit health is independent from
Equipment assessment status.

## Private IPC

Protocol `d4-rulekit-ipc/v1` is newline-delimited JSON over inherited pipes.
Each request has a UUID correlation ID. Responses are `result` or typed
`error`; operation timeout sends a cancellation control message. Shutdown and
cancel are lifecycle controls, not Application APIs.

The Application surface remains exactly:

1. `listProviders`
2. `createSession`
3. `evaluate`
4. `previewChanges`
5. `commitChanges`
6. `resetSession`
7. `getSession`
8. `closeSession`

The worker queue, concurrent operations, sessions, browser contexts and browser
queue are independently bounded. Operation timeout does not shorten the
session TTL or browser lease. Application revision, preview-token and cache
checks remain fail-closed.

## Production configuration

The managed launcher supplies the worker identity/generation. Deployment must
also supply:

| Variable | Meaning |
|---|---|
| `D4_RULEKIT_PROFILE_JSON` | Approved pinned Maxroll profile JSON |
| `D4_RULEKIT_SNAPSHOT_ROOT` | Provisioned, verified offline snapshot store |
| `D4_RULEKIT_CHROMIUM_EXECUTABLE` | Packaged Chromium executable, when not resolved by infrastructure |
| `D4_RULEKIT_MAX_SESSIONS` | Application session bound (default 8) |
| `D4_RULEKIT_SESSION_TTL_MS` | Session lifetime (default 30 minutes) |
| `D4_RULEKIT_OPERATION_TIMEOUT_MS` | Per-operation timeout (default 15 seconds) |
| `D4_RULEKIT_MAX_CONTEXTS` | Shared browser context bound (default 2) |
| `D4_RULEKIT_BROWSER_MAX_QUEUE` | Browser lease queue bound (default 16) |
| `D4_RULEKIT_MAX_CONCURRENT` | IPC operation concurrency bound (default 4) |
| `D4_RULEKIT_MAX_QUEUE` | IPC waiting queue bound (default 32) |
| `D4_RULEKIT_WORKER_CLEANUP_TIMEOUT_MS` | Parent-death/shutdown cleanup bound (default 10 seconds) |

Production fails startup when profile/snapshot configuration is absent. It
does not capture, download, sync or substitute a test fixture. The profile,
canonical schema, approved snapshot pins and eight APIs are unchanged.

`D4_RULEKIT_COMPOSITION_MODULE` is an injection seam used by automated tests.
The checked-in composition fixture is explicitly `TEST_ONLY` and synthetic; it
is never imported by `production-composition.js` and is not evidence of real
Maxroll or Windows/Chromium acceptance.

## Release 1 behavior and performance evidence

Equipment conformity scoring belongs to #141 and does not call Rule Kit for
each affix. Partial capture is not padded with Target Skills/Paragon data. A
Rule Kit session is created only from a complete canonical build; incomplete
input returns a typed error.

Targeted Linux contract tests measure lifecycle/API correctness and bounded
recovery. Real cold start, warm session/cache, browser capacity, offline
zero-egress, Windows cleanup, and P50/P95 latency require the approved packaged
snapshot/Chromium runtime and remain runtime acceptance gates. No unmeasured
latency promise is made here.

Local verification:

```bash
python -m pytest -q utility/d4planner/tests/test_rulekit_worker.py
python -m pytest -q utility/d4planner/tests/contracts/test_release1_contract.py
python -m compileall -q utility/d4planner
(cd utility/d4-rulekit/application && npm test)
```

## S3-F01 / SNAP-05 final failure-path review

Cleanup now bounds the graceful request+wait together, terminate+wait, and final
kill wait. A failed kill/timeout retains the owned child in FAILED and invalidates
the client. Start/reconfigure cannot overwrite a retained handle. Explicit stop
retry can release it only after confirmed exit. Startup after spawn and runtime
post-READY failures use the same ownership rule. These tests prove Linux owned
Node processes and deterministic failure injection, not Windows job containment.

Snapshot operations use the Rule Kit durable-intent semantics documented in
`snapshot-management/README.md`. BE checks the acknowledged entry/revision and
worker generation, not compatibility policy. Callback failures are operation
failures; the same request can resume after cleanup. Unconfirmed binding never
returns a successful switch. No application DB is restored or edited.

```sh
PYTHONPATH=utility/d4planner/src python -m pytest -q utility/d4planner/tests/test_rulekit_worker.py utility/d4planner/tests/test_snapshot_worker.py utility/d4planner/tests/test_rulekit_cleanup_failure.py
npm test --prefix utility/d4-rulekit/snapshot-management
python -m compileall -q utility/d4planner
```

Production managed-snapshot mode may start without a selected snapshot and
reports calculation UNAVAILABLE; the legacy profile/snapshot-required mode
above remains distinct. No production trust activation is implied.

### CI prerequisites and startup diagnostics

Windows runtime tests launch real Node workers; installing Python `[dev]` alone
is insufficient. `tests.yml` pins Node 22.23.4 and runs locked `npm ci` for
snapshot-management, browser-infra, providers/maxroll and application, then
requires the management/test-composition modules before pytest. Each native
command exit code is checked explicitly in PowerShell. No Chromium download or
private snapshot is required for these synthetic IPC tests.

The process wrapper drains stderr immediately after spawn in fixed-size chunks.
This prevents a full pipe or oversized diagnostic line from blocking READY or
fatal exit. Content is discarded, never forwarded over IPC or retained in logs.
Startup failure cancels its drain task after bounded owned-child cleanup. Tests
exercise a real Node process with large stderr before successful READY and
before fatal exit; these are Linux subprocess checks, not Windows-native proof.

## Package boundary and internal bootstrap

The Python package ships this layout (including in wheels):

```text
src/d4planner/rulekit/
  __init__.py
  client.py
  process.py
  protocol.py
  runtime.py
  worker.js
```

`worker.js` is an IPC adapter. It imports no Rule Kit implementation and receives
only the eight Application calls, the approved Snapshot Management dispatcher,
startup health and owned-runtime cleanup. The worker tracks restart-required
receipts locally; it never reads manager fields. Rule Kit retains the internal
quiescing guard even when a management failure has no success receipt.

`RuleKitRuntimeService` starts one process with:

```text
<absolute node> <absolute Rule Kit bootstrap.js> <absolute packaged worker.js>
```

The private executable bootstrap is
`utility/d4-rulekit/application/src/runtime/bootstrap.js`. Its sibling composition
modules own profile loading, Maxroll provider construction, snapshot registry /
resolver / strategy selection, and shared browser infrastructure. These modules
are not exported from the Application package entrypoint or TypeScript contract.
The Application core remains provider agnostic. No ninth Application method or
new public integration API is introduced; bootstrap is internal process wiring.

The adapter defaults to `Path(__file__).with_name("worker.js")`, independent of
working directory. `D4PLANNER_RULEKIT_WORKER` remains an absolute-file override.
With `D4_RULEKIT_INSTALLATION_ROOT`, the bootstrap resolves beneath that root at
`utility/d4-rulekit/application/src/runtime/bootstrap.js`; source editable installs
resolve the sibling Rule Kit tree. An explicit absolute
`D4PLANNER_RULEKIT_BOOTSTRAP` can select an externally provisioned runtime. Missing
bootstrap fails before spawning. The wheel ships the adapter, not Node, Chromium
or Rule Kit dependencies; those remain installation assets.

`D4PLANNER_RULEKIT_EXECUTABLE` and `D4_RULEKIT_CHROMIUM_EXECUTABLE` still select the
portable installation binaries. Production legacy profile/snapshot paths must be
absolute. The working directory remains explicit and is not a module search root.
The test-only `D4_RULEKIT_COMPOSITION_MODULE` seam is not forwarded by production
Python runtime and is not read by the production bootstrap. Direct adapter
execution without an explicit absolute test composition fails closed.

Snapshot Management remains the separately approved `d4-rulekit-snapshots/v1`:
`listInstalled`, `checkCompatibility`, `getCapabilities`, `importPackage`,
`activate`, `getActive`, `switchSnapshot`, `rollback`, `compareSnapshots`.
The adapter allowlist is checked against its existing call schema; implementation
exports do not grant additional APIs. Application signatures and IPC envelopes
remain unchanged. Test fixtures may construct synthetic Rule Kit instances; that
is test-only dependency injection, not a production BE dependency.

The generated Rule Kit execution index includes the internal bootstrap and both
composition modules. Changing these bytes changes execution identity. Keep the
existing Owner public trust anchors and compatibility rules; do not reuse a signed
registry bound to the old execution hash or mint a production approval in tests.

Additional local gates (explicit private test Chromium):

```sh
F2_TEST_CHROMIUM=<absolute-test-chromium> python -m pytest -q tests/test_rulekit_boundary.py
BROWSER_INFRA_CHROMIUM_PATH=<absolute-test-chromium> node --test ../d4-rulekit/application/tests/runtime-bootstrap.test.js
```

These gates cover installed wheel module resolution, no-snapshot managed startup,
and actual production bootstrap with all eight APIs against synthetic offline
content. They are Linux Node/Chromium evidence, not approved Maxroll snapshot or
Windows-native acceptance.

## Downstream PR #150 integration handoff

Reviewed downstream tree: `9554248d3124dffe1507b4d448d99666bbdaee59`.
Synchronize the true stack before applying these changes on the owning PR; do not
edit another developer's checkout. Release integration is NOT_RUN until this work
and native packaging verification are complete.

| File under `utility/d4planner/` | Required change after stack synchronization |
|---|---|
| `tools/build_release1_stage.py` | Remove the old standalone worker-directory copy. The existing backend source copy now supplies `backend/site-packages/d4planner/rulekit/worker.js`; require that file and Rule Kit bootstrap in stage validation. |
| `release1/public-content-policy.json` | Add the three `utility/d4-rulekit/application/src/runtime/*.js` files explicitly to `sourceAllowlist`. Include the refreshed execution index; verify all index files are shipped with exact hashes. Do not include test composition modules. |
| `release1/package-plan.json` | Replace the old worker directory component path with `backend/site-packages/d4planner/rulekit`; account for the internal Rule Kit bootstrap assets. |
| `release1/native-launcher/src/main.rs` | Update required-file checks and worker environment path to the packaged adapter; use installation root or another existing directory for working dir. Include bootstrap preflight; preserve portable Node/Chromium paths. |
| `release1/start-d4planner.ps1` | Set the packaged adapter path (or omit override to use Python package default); replace old working directory; preserve installation-root configuration. |
| `tools/production_e2e.py` | Update worker and working-directory launch paths and verify bootstrap-backed READY; do not treat a spawn as readiness. |
| `tests/test_production_backend.py`, `tests/test_snapshot_backend.py` | Update source worker fixture paths after their owning stack commits are synchronized. Preserve synthetic classification and assertions. |
| `tests/test_public_package.py`, `tests/test_release1_delivery.py`, `tests/test_windows_install.py`, `tests/test_production_e2e_delivery.py` | Verify new allowlist/stage/launcher paths, absence of old directory, relocated installed startup and fail-closed missing bootstrap. |

Rebuild/validate the package only in its owning workspace. Re-evaluate exact
execution-binding approval independently of unchanged formula/compatibility
policy. Installer/native Windows E2E and downstream release integration cannot be
reported PASS from this source/wheel test alone. No merge, release or deployment
is part of this refactor.
