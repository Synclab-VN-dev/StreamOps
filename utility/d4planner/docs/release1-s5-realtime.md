# D4Planner Release 1 — S5 realtime transport

Source contract: `d4planner-r1-contract/1.0.0-candidate.5` at
`459cd0e1fb41f8421cf93f5009272bfab20b5a2c`.

This workstream implements the loopback WebSocket transport and the FE HUD
data source. Domain operations remain injected ports: Target discovery and
activation are owned by S4, while process ownership and credential handoff are
owned by S2. The server never reads a Target file for the FE and the FE has no
DB, file, REST-polling, or scoring fallback.

## Production boundary

- `D4PlannerWebSocketServer` binds loopback only, accepts one configured
  origin, enforces a 256 KiB message limit and bounded inbound queues, and
  disables timer pings as a data-fetch mechanism. A positive pre-auth deadline,
  connection cap, and send deadline bound unauthenticated and blocked peers.
- `D4PlannerProtocolSession` authenticates a private credential before any
  operation. It validates protocol version, generation, correlation, Target
  IDs, hashes, list revision, and snapshot request context. Errors expose
  stable codes and sanitized messages.
- `HudHub.publish_after_commit` is the only push entry point. Snapshot and
  subscription creation share one lock, so no committed revision can be lost
  at the boundary. Each slow subscriber has a one-message queue; first overflow
  coalesces to `resync.required` and persistent overflow closes the connection
  instead of accumulating unbounded HUD state or tasks.
- `HudWebSocketDataSource` preserves its revision high-water mark across a
  reconnect to the same runtime instance/generation. It rejects stale,
  duplicate, wrong-generation, wrong-correlation, wrong-subscription, and
  non-contiguous data. A known-context mismatch triggers bounded protocol
  discovery without applying the mismatched snapshot. Snapshot operation
  timeout consumes the old correlation, retries with `TIMEOUT_RETRY` and an
  incremented attempt, and stops at configured `maxDiscoveryAttempts`.
- Target activation acknowledgement never renames an existing assessment.
  The new Target binding appears only in a subsequently committed HUD payload.

Credentials are supplied by the managed BE launch/handshake described by S2;
they are not persisted by this module. The server receives a domain adapter
from S4 and does not contain repository, assessment, or persistence logic.

## Latency and capacity

The path is commit → bounded WS push → FE reducer/render as soon as work is
available. There is no intentional delay and no polling interval. Tests record
TEST_ONLY loopback commit-to-receive P50/P95 samples for regression evidence;
they do not invent a production millisecond SLA. Runtime telemetry must retain
capture, assess, commit, push, receive, and render timestamps so S7 can measure
end-to-end P50/P95 on the Windows runtime.

## Acceptance status

| Gate | Local evidence | Status |
|---|---|---|
| S5-01 | Real socket Target list, authoritative snapshot, atomic subscription, committed push; outgoing messages validate against S1 JSON Schema | PASS |
| S5-02 | Valid-only selection plus hash/list revision, malicious ID, activation error, duplicate request, and no premature relabel tests | PASS |
| S5-03 | FE tests cover same-generation reconnect, stale/equal/new revisions, gap resync, context rediscovery, and backend restart | PASS |
| S5-04 | Origin, credential, version/generation, malformed JSON, frame size, pre-auth timeout/connection cap, sanitized wire/log errors, loopback bind, and private credential constraints | PASS |
| S5-05 | One-entry coalescing queues, persistent-slow-client close, finite reconnect/snapshot recovery, old-commit rejection, no-polling data source, and TEST_ONLY P50/P95 measurement | PASS |
| S5-06 | Requires actual S2 credential handoff, S4 repository/assessment adapter, and S6 renderer on an approved integration branch/runtime | PENDING_DEPENDENCY |

The `SyntheticDomain` and S1 JSON fixtures used by tests are explicitly
TEST_ONLY. They are not compiled or wired as a production fallback.

## Local verification

```text
python -m pytest -q utility/d4planner/tests/test_realtime_transport.py \
  utility/d4planner/tests/contracts/test_release1_contract.py
python -m compileall -q utility/d4planner
python -m pip check
npm test                         # from utility/d4planner-overlay-poc
npm run build                    # from utility/d4planner-overlay-poc
git diff --check
```

CI is intentionally not queried by this workstream.

## Target operation failure boundaries (S5 review fixes)

Startup verifies repository directory enumeration, durable state and authenticated
listener readiness. Invalid Target *content* is not a repository service failure:
`targetRepository=READY` means the service can safely validate/reject requests,
not that every user file is valid. Private managed health reports `targetListing`
(`READY` or the existing Target error code), while `targetJsonCount` is the number
of candidate JSON files, not a fabricated valid-target count. Directory I/O/file
count limit failures still abort startup and close owned services. Explicit list
requests never return partial lists; invalid content produces correlated,
sanitized `TARGET_INVALID`, retryable=false (repair files then request again).

The production composition root coordinates S4's selected-target JSON and HUD
SQLite using a private, flushed/atomically replaced `target-transition.json`
intent before activation. It records previous selection/binding and the requested
ID/hash/selection revision. A matching authoritative HUD commit is the commit
point. Before that point, failure restores selection and binding; afterwards,
publish failure must retain the committed selection/HUD for resync. Recovery is
idempotent and runs before startup, activation and Equipment ingestion. Failed
recovery retains the journal and refuses dependent operations; it never silently
continues with a partially switched Target. This provides process-interruption
recovery across the two stores, not a claim that two filesystem/SQLite writes
constitute one OS transaction or that loss of durable storage can be repaired.
S4 still owns validation, persistence primitives and scoring; no SQL enters WS
transport or FE. A post-commit transport error can require authoritative resync;
it is not permission to roll back a committed Target. Existing connection-level
command dedup remains unchanged, with no exactly-once promise across reconnects.

FE pending Target selection is capped at 32 outstanding commands; exceeding the
cap rejects locally before sending (`TARGET_REQUEST_LIMIT`). Correlated success
and error both consume the pending selection. Listing errors consume only their
own pending request; unknown/duplicate correlated errors are ignored. Connection
close/disconnect clears connection-owned requests; existing socket/generation
guards reject late messages. No renderer changes or polling were added.

## D5 migration (supersedes the candidate.5 WS behavior above)

The running server accepts d4planner-notify/v1 hello and sends hud.committed
DB identity/epoch/revision hints only. HudHub owns bounded coalescing metadata.
Target commands use d4planner-control/v1 on BackendProcessWrapper's existing
stdin/stdout pipe to managed_backend.py and ProductionBackendRuntime.handle_control.
Native request correlation is bound to owner/child/generation; deadline expiry
retires the waiter without stopping reusable Rule Kit sessions. FE reads SQLite
on startup/reconnect/resume/notification/refresh; no HUD snapshot WS request.
