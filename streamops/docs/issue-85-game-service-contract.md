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

## Mutation security
All **game** Start/Stop/Restart and Steam WS Restart require the operator's
`STREAMOPS_GAME_CONTROL_TOKEN` environment variable (at least 24 characters).
Without it, mutations are disabled, but read-only WS/REST continues under the
repository's existing `require_access` trusted-LAN policy.

REST mutation: header `X-StreamOps-Game-Token: <token>` plus
`Idempotency-Key: <unique-per-intent>`. WebSocket mutation: create the connection
with subprotocols `["streamops-games-v1", "streamops-game-control.<token>"]`;
the accepted subprotocol is `streamops-games-v1`. Do not place tokens in URLs,
logs or committed files. The token protocol is intended for a trusted local LAN
or TLS-protected endpoint, **not** an untrusted network. This game-control token
is an additive gate; it does not retrofit authentication onto legacy APIs.
FE #86 must implement a secure operator-session credential UX separately.

Example read-only PowerShell after starting StreamOps node:
```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/v1/games
Invoke-RestMethod http://127.0.0.1:8765/api/v1/games/steam:2344520
```

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
