# Issue #35 — Gate 3 technical decision

Decision: **the current source candidate is not production-safe as-is; a reviewed plugin patch is
required before further runtime acceptance.**

## Real-A evidence

- Upstream/native does not expose stable, unambiguous per-target output identity. Idle/restarted
  targets may be absent from `GetOutputList`; when present, targets share `multi-output`.
- Upstream `obs-multi-rtmp` 0.7.4.0 does not register `sorayuki.multi_rtmp`.
- Candidate DLL SHA-256:
  `B149D3A38E4A107C0B09157C4D75608B563FE22333016456AEE7C0AA30BC0D71`.
- Candidate Vendor API successfully listed, added, updated, renamed, and persisted target IDs through
  rename. Credential update responses did not echo the stream key.
- A narrow identity-only probe created `issue35-identity`, renamed it once, and observed plugin target
  ID `929382080` before rename, after rename, immediately before OBS restart, and after OBS restart plus
  obs-websocket reconnect. The ID remained stable at all four checkpoints. The probe did not call any
  start/stop request, create a receiver, or stream.
- After restart, obs-websocket became reachable slightly before the candidate re-registered
  `sorayuki.multi_rtmp`; the probe therefore used a bounded Vendor-readiness wait before the final
  `list_targets`. The candidate log then confirmed successful Vendor registration and all 16 requests.
- `start_target` returned `{status: start_requested}` for target `3915494840`, but repeated state
  polling remained `isRunning=false` with an empty status.
- The API-created target persisted `output-param=null` and no video/audio config references. OBS
  logged a failed JSON parse of `null`, then displayed the interactive warning:
  `Cannot reuse encoder when it's not in streaming or recording.`
- The Vendor API did not return the encoder failure; it was observable only through the OBS UI.
  Core start/stop therefore failed, and start-all, repeated control, and fault-isolation phases were
  intentionally not run. WebSocket reconnect was exercised only by the non-streaming identity probe.

## Capability matrix

| Capability | Native OBS + upstream | Upstream Vendor | Candidate Vendor |
| --- | --- | --- | --- |
| list | NO | NO | YES |
| stable target identity | NO | unavailable | YES — stable through rename and OBS restart/WebSocket reconnect |
| start one | not safely callable | unavailable | NO |
| stop one | not safely callable | unavailable | BLOCKED |
| start all | UNKNOWN | unavailable | NOT RUN |
| stop all | UNKNOWN | unavailable | NOT RUN |
| add | unavailable | unavailable | YES |
| update | unavailable | unavailable | YES |
| delete | unavailable | unavailable | YES for the identity probe target |
| LIVE/FAILED state | unavailable | unavailable | NO — encoder failure not surfaced |
| stats/error | unavailable | unavailable | NOT RUN |
| credential update | unavailable | unavailable | YES |
| secret-safe response | unavailable | unavailable | YES for exercised responses |

## Required patch boundary

A future reviewed patch must make API-created targets startable without relying on an already-active
main stream/recording encoder, initialize valid output settings, and surface asynchronous start
failure through Vendor state/error data instead of an interactive modal plus unconditional
`start_requested`. The patch must then repeat the complete Real-A matrix, including receiver fault
isolation and WebSocket reconnect.

This PR does not implement that patch, change the production StreamOps backend/UI, select a public
plugin target ID contract, or authorize distribution of the GPL candidate.

## StreamOps contract impact

### Backend

- StreamOps must own a durable destination ID. Neither the plugin target name nor OBS `outputName`
  is a public identity; the plugin target ID is an internal adapter mapping only.
- Each destination needs a persisted lifecycle/state record, including its last runtime error and
  enough adapter state to reconcile after OBS, obs-websocket, or plugin reconnects.
- A successful asynchronous start request means only that the command was accepted. The backend must
  not publish `LIVE` until runtime state confirms that the output is actually active.
- Runtime failures must be persisted and exposed in a structured form. Stream keys and other
  credentials must never be logged, included in state/events, or returned by destination APIs.
- The current candidate violates the required runtime contract: it returns `start_requested` while
  encoder setup fails, remains non-running, and does not expose the failure through Vendor state/error
  data. Production integration remains blocked until a reviewed candidate provides an observable
  runtime transition or error.

### WebSocket contract

- Publish state and events per StreamOps destination ID, independently of plugin target names/IDs.
- Model the lifecycle as `IDLE`, `STARTING`, `LIVE`, `RECONNECTING`, `STOPPING`, and `FAILED` (or an
  equivalent model with the same distinctions).
- Separate command acknowledgement from runtime transitions: request acceptance may move a
  destination to `STARTING`, but only runtime confirmation may move it to `LIVE`.
- Emit a structured error/event for asynchronous failures and push reconciliation updates whenever
  OBS, obs-websocket, or plugin state changes. A connected obs-websocket does not by itself guarantee
  that the Vendor API has finished registering.
- Credential and stream-key fields must be absent from snapshots, acknowledgements, events, and
  errors.

### UI

- Key destinations by the StreamOps destination ID and render state independently for each one; do
  not bind UI identity directly to a plugin target ID, target name, or OBS `outputName`.
- Start/stop controls must show transitional states and must not display an accepted start request as
  `LIVE`.
- If runtime start fails after acknowledgement, transition the destination to `FAILED` and display
  the sanitized error while preserving a clear recovery/retry path.
- Never render or return stream keys or credentials.

## Restore verification

After the failed candidate phase, A was restored to the original config and upstream DLL SHA-256
`6AEEF452B81781F9D1C28699DD1246E045F8295664BFF56336DA2EF17F8CF181`. OBS returned `READY`,
obs-websocket reconnected, the upstream plugin returned `LOADED`, streaming and recording were false,
and no `issue35-*` target, receiver, listener, modal-inspection task, or orphan test process remained.
The later identity-only probe ended in the same clean state; the original config was restored
byte-for-byte with SHA-256 `8C79FE05F7115721F929C96D5F4EFA3020C3C63572906EEF0D95896909A50FC5`.
