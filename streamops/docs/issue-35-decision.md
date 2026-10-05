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
- `start_target` returned `{status: start_requested}` for target `3915494840`, but repeated state
  polling remained `isRunning=false` with an empty status.
- The API-created target persisted `output-param=null` and no video/audio config references. OBS
  logged a failed JSON parse of `null`, then displayed the interactive warning:
  `Cannot reuse encoder when it's not in streaming or recording.`
- The Vendor API did not return the encoder failure; it was observable only through the OBS UI.
  Core start/stop therefore failed, and start-all, repeated control, reconnect, and fault-isolation
  phases were intentionally not run.

## Capability matrix

| Capability | Native OBS + upstream | Upstream Vendor | Candidate Vendor |
| --- | --- | --- | --- |
| list | NO | NO | YES |
| stable target identity | NO | unavailable | PARTIAL — stable through rename; restart not reached |
| start one | not safely callable | unavailable | NO |
| stop one | not safely callable | unavailable | BLOCKED |
| start all | UNKNOWN | unavailable | NOT RUN |
| stop all | UNKNOWN | unavailable | NOT RUN |
| add | unavailable | unavailable | YES |
| update | unavailable | unavailable | YES |
| delete | unavailable | unavailable | NOT RUN |
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

## Restore verification

After the failed candidate phase, A was restored to the original config and upstream DLL SHA-256
`6AEEF452B81781F9D1C28699DD1246E045F8295664BFF56336DA2EF17F8CF181`. OBS returned `READY`,
obs-websocket reconnected, the upstream plugin returned `LOADED`, streaming and recording were false,
and no `issue35-*` target, receiver, listener, modal-inspection task, or orphan test process remained.
