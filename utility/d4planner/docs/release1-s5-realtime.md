# D4Planner Release 1 — S5 realtime transport

Source contract: `d4planner-r1/1.2.0` at
`459cd0e1fb41f8421cf93f5009272bfab20b5a2c`.

This workstream implements the loopback WebSocket transport and the FE HUD
data source. Domain operations remain injected ports: Target discovery and
activation are owned by S4, while process ownership and credential handoff are
owned by S2. The server never reads a Target file for the FE and the FE has no
DB, file, REST-polling, or scoring fallback.

## Production boundary

- `D4PlannerWebSocketServer` binds loopback only, accepts one configured
  origin, enforces a 256 KiB message limit and bounded inbound queues, and
  disables timer pings as a data-fetch mechanism.
- `D4PlannerProtocolSession` authenticates a private credential before any
  operation. It validates protocol version, generation, correlation, Target
  IDs, hashes, list revision, and snapshot request context. Errors expose
  stable codes and sanitized messages.
- `HudHub.publish_after_commit` is the only push entry point. Snapshot and
  subscription creation share one lock, so no committed revision can be lost
  at the boundary. Each slow subscriber has a one-message queue; overflow is
  coalesced to `resync.required` instead of accumulating unbounded HUD state.
- `HudWebSocketDataSource` preserves its revision high-water mark across a
  reconnect to the same runtime instance/generation. It rejects stale,
  duplicate, wrong-generation, wrong-correlation, wrong-subscription, and
  non-contiguous data. A known-context mismatch triggers bounded protocol
  discovery without applying the mismatched snapshot.
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
| S5-04 | Origin, credential, version/generation, malformed JSON, safe errors, loopback bind, and private credential constraints | PASS |
| S5-05 | One-entry coalescing queues, 500-update burst, old-commit rejection, no-polling data source, and TEST_ONLY P50/P95 measurement | PASS |
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
