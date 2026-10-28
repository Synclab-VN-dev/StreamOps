# Managed Rule Kit worker (S3)

Contract source: S1 #138, revision `d4planner-r1-contract/2026-10-25.5`.
Implementation ticket: #140.

## Ownership and boundaries

The D4Planner backend owns exactly one long-lived Node worker. The Python
`RuleKitProcessWrapper` owns process lifecycle, while `RuleKitClient` owns the
private JSON-lines IPC correlation. The Node composition root reuses the
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
