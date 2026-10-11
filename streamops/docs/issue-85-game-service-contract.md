# GameService V1 contract — Issue #85 (BE for independent #86 FE)

## Transport boundary
WebUI uses WS only: `/api/v1/games/ws` and `/api/v1/steam/ws`. REST is a mirror
for CLI/diagnostics. GameService is the single implementation; no FE dependency
or MagicPath design branch is merged into the backend.

Game WS operations: `games.list`, `games.get`, `games.lifecycle.start`,
`games.lifecycle.stop`, `games.lifecycle.restart`, `games.operations.get`,
`games.reconcile` (read-only), `games.catalog.refresh`. `games.lifecycle.force_stop`
is deliberately disabled. Steam WS operations: `steam.status`,
`steam.lifecycle.restart`.

Events: `games.snapshot`, `games.changed`, `games.operation`,
`games.catalog.changed`, `games.heartbeat`. Steam events are
`steam.snapshot` and `steam.heartbeat`.

Request:
```json
{"type":"request","request_id":"req-1","operation":"games.lifecycle.start","payload":{"game_id":"steam:2344520","idempotency_key":"click-1"}}
```
Accepted async response:
```json
{"type":"response","request_id":"req-1","ok":true,"data":{"operation_id":"op-...","game_id":"steam:2344520","action":"start","status":"PENDING","phase":"QUEUED","code":null}}
```
The controller should fetch `games.operations.get` using `{"operation_id":"op-..."}`
after reconnect or any missed operation event. The browser must never automatically
retry lifecycle commands on reconnect. Status must be **observed**, never inferred
from an accepted start/stop command.

## Revision, epoch, recovery
`games.snapshot` is delivered first on every connection. It carries
`revision`, `epoch`, `stale`, `observed_at`, `games` and
`resync_required`. Each meaningful game change and operation event carries
a monotonically increasing `revision`. Ignore stale event revisions within the
same epoch; when epoch changes after node restart, reset client revision tracking
and use the new full snapshot. Snapshot may coalesce under backpressure;
`resync_required=true` signals the client to reload operation results.

Four independent dimensions: process `RUNNING/STOPPED/STARTING/STOPPING/FAILED/UNKNOWN`,
window `FOREGROUND/BACKGROUND/NOT_DETECTED/UNKNOWN`, OBS
`VERIFIED_ACTIVE/CONFIGURED_ONLY/INACTIVE/ERROR/UNKNOWN`, selectedForStream
`SELECTED/NOT_SELECTED/UNKNOWN`. OBS/stream information deliberately stays
`UNKNOWN` until the corresponding status can be verified; a game being
registered, installed or running does not imply OBS capture success.

## Internal API access policy (owner-approved personal deployment)
StreamOps is a single-operator, trusted-network system. **None of its internal
REST or WebSocket APIs require a token, login, credential header, or auth
subprotocol**, including GameService Start/Stop/Restart and Steam WS Restart.
CLI and WebUI share the same GameService state and response contract. The
optional `streamops-games-v1` WebSocket subprotocol is for protocol negotiation,
**not authentication**. Operation `Idempotency-Key` (REST) and
`idempotency_key` (WS) are still required for game lifecycle requests to prevent
duplicate execution; they are **not security credentials**.

This is an explicit owner-approved trusted-LAN policy, not a claim that the
unprotected API is safe on untrusted networks. Do not expose StreamOps
management ports to the public Internet. Network isolation/firewall changes,
if desired, require separate approval; no infrastructure changes are included
in PR #88. All process identity, approved game allowlist, desktop session,
graceful WM_CLOSE, and disabled Force Stop gates remain in effect.

Token-free operator CLI example from Windows A:
```powershell
$base = "http://127.0.0.1:18788"
Invoke-RestMethod "$base/api/v1/games"
Invoke-RestMethod -Method Post -Uri "$base/api/v1/games/steam:2344520/actions" \
    -ContentType "application/json" \
    -Headers @{ "Idempotency-Key" = [guid]::NewGuid().ToString() } \
    -Body '{"action":"start"}'
```
Every accepted lifecycle request is asynchronous. HTTP 202 and operation ID
do not mean success: check the operation terminal result and observed game
state before marking real-host acceptance PASS.

## Safety scope
Only allowlisted `steam:2344520` (Diablo IV) in V1. Static registry contains
neither ownership nor runtime assertions. Windows observer verifies the Steam
appmanifest, process image path under installed directory, PID + creation time,
active Windows console session and visible window before graceful close.
Windows GameProcess uses `WM_CLOSE`, **never** `taskkill` or Steam shutdown.
A failed or ambiguous check disables mutation with a typed reason.
Start invokes the pre-verified Steam executable using a fixed `-applaunch`
argument. Stop waits for verified process exit; Restart is stop → verify → start →
verify. No unattended production game lifecycle tests.

`STREAMOPS_GAME_PROVIDER_MODE` accepts `static` (default), `shadow`, or
`merged`. The static seed remains the safety authority in all modes.
The optional discovery adapter is not enabled in production V1; independent
fixtures exercise the future extension. Unsupported or conflicting discovery
must never override the static safety policy.

## Independent integration with #86
BE can merge without FE code. FE can develop against the JSON contracts and
synthetic WS fixtures in its own branch. Integration requires only the merge
of both branches; `docs/ui-design` remains a design-only branch, never merged.
Before production acceptance on A: verify interactive session, Steam library
discovery, read-only state changes to 2 WS clients and operator-approved real
game lifecycle; do not mark Dev F/owner manual gates PASS without evidence.
