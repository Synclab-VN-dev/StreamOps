# Issue #47 — Canonical OBS Plugin Manager WebSocket contract (v2)

Implementation PR #52, consumer FE #75 / PR #90. REST and WS use the **same**
ObsPluginService. No client-selected repository, URL, path, binary or credential.
The WebSocket connection is `/api/v1/obs/plugins/ws`.

## Requests

Use the existing envelope
`{"type":"request","request_id":"opaque","operation":"obs_plugin.status","payload":{"plugin_id":"obs-multi-rtmp"}}`.
Each response remains `{"type":"response","request_id":"opaque","ok":true,"data":{...}}`
or `{"type":"response","request_id":"opaque","ok":false,"error":{"code":"...","message":"..."}}`.

| WebSocket operation | Request payload | Response `data` | REST equivalent |
|---|---|---|---|
| `obs_plugin.inventory` | `{}` | `{"plugins":[status,...]}` | `GET /api/v1/obs/plugins` |
| `obs_plugin.available` | `{}` | `{"plugins":[catalog,...],"source_state":"READY"}` (or EMPTY/UNCONFIGURED) | `GET /api/v1/obs/plugins/available` |
| `obs_plugin.status` | `{"plugin_id":"obs-multi-rtmp"}` | full plugin status | `GET /api/v1/obs/plugins/obs-multi-rtmp` |
| `obs_plugin.operation_status` | `{"plugin_id":"obs-multi-rtmp"}` | operation snapshot, plugin state, rollback, recovery | `GET /api/v1/obs/plugins/obs-multi-rtmp/operation` |
| `obs_plugin.subscribe` | `{"plugin_id":"obs-multi-rtmp"}` | `{"plugin_id":"...","subscribed":true,"revision":N}` | WS only |
| `obs_plugin.adopt/install/update/verify/rollback` | `{"plugin_id":"obs-multi-rtmp"}` | existing operation result | existing REST lifecycle POST |

`inventory` and `available` reject any client payload fields, including plugin ID.
All single-plugin operations reject unknown IDs and extra fields.

## Opt-in observer events

After a successful `obs_plugin.subscribe`, a client additionally receives
`{"type":"event","event":"obs_plugin.changed","data":{"plugin_id":"obs-multi-rtmp","revision":N,"resources":["operation"]}}`.
Resources currently include `operation`, `status`, and `catalog`.
These are *invalidation hints*, not authoritative snapshots. Re-fetch inventory,
catalog, plugin status and operation status after connecting/subscribing or on
higher revision; do not use event delivery alone as proof of a mutation outcome.

The revision is monotonic **only inside a server process**. It resets on server
restart and is not durable; clients must re-fetch all state after reconnect.
Notifications reflect mutations made through the shared service (REST and WS)
and observations that change during status/catalog reads; external filesystem or
release changes with no read/operation are discovered on the next refresh, not
guaranteed as immediate pushes. Old response-only WebSocket clients receive no
unsolicited messages until they subscribe.

## Rollback and in-flight safety

Plugin status includes:
`rollback: {"available":boolean,"target_version":string|null,"reason":string|null}`,
compatibility aliases `rollback_available` / `rollback_reason` for the current
FE #75 domain model, and `revision` plus an `operation` snapshot. Rollback availability is fail-closed:
the Windows installer checks committed transaction journal, exact installed
files and verified plugin/config backups including config drift. Merely being
installed, having a version, or having `LEGACY_ADOPTED` is insufficient.
`RECOVERY_REQUIRED` is shown separately and normal Rollback is disabled; the
recovery action remains a controlled OBS-STOPPED-only procedure. REST/WS mutation
rechecks its own safety gates **after** the read-only availability query.

`operation_status` exposes:
`{"operation":{"state":"IDLE|RUNNING|SUCCEEDED|FAILED","operation_id":"...|null","operation":"...","revision":N,"error_code":"..."},"plugin_state":"...","recovery_required":false,"rollback":{...},"revision":N}`.
The last result is process-local; after restart, only journal-backed plugin
`RECOVERY_REQUIRED` is durable. On disconnect, timeout, or unknown outcome,
disable further mutations until a fresh read-only reconciliation returns. A
request timing out does not prove its worker has stopped. No stream keys, config
contents or raw exceptions may appear in operation snapshots or events.

The FE must not enable Rollback if `rollback.available` is missing or false,
and must not infer success from a disconnected WebSocket or an OBS restart.


## FE #75 integration follow-up (PR #90)

The current FE WebSocket client routes event payloads from `message.data`.
The FE must call `obs_plugin.subscribe` after every connect/reconnect, then
reconcile inventory/catalog/operation status (do not rely on push delivery alone).
It must query `obs_plugin.operation_status` for each plugin before clearing an
`unknownOutcome` state. This follow-up belongs to the independent FE PR #90;
it is **not** evidence of production UI integration in BE PR #52.
