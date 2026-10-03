# IMPLEMENTATION MAPPING — OBS Mobile Dashboard v2

## 1. Production Web UI hiện tại

Các file chính:

- `streamops/server/web/obs.html`
- `streamops/server/web/obs.js`
- `streamops/server/web/obs-process.js`
- `streamops/server/web/app.css`

Agent phải inspect các file này trước khi sửa.

## 2. OBS Runtime

Status:
- `GET /api/v1/obs/process/status`

Actions:
- `POST /api/v1/obs/process/start`
- `POST /api/v1/obs/process/stop`
- `POST /api/v1/obs/process/restart`

Backend:
- `streamops/server/api/obs_process.py`
- `streamops/server/obs/manager.py`

Payload status hiện có:
- `state`
- `process.running`
- `process.pid`
- `process.started_at`
- `process.uptime_seconds`
- `process.session_id`
- `process.active_console_session_id`
- `process.interactive`
- `process.executable_path`
- `process.expected_executable_path`
- `websocket.connected`
- `websocket.host`
- `websocket.port`
- `websocket.obs_version`
- `websocket.obs_websocket_version`
- `output.streaming`
- `output.recording`
- `last_operation`
- `error`

Safety:
- Stop/Restart chỉ khi state READY.
- Stop/Restart bị block nếu streaming hoặc recording.
- Start/Stop/Restart phải preserve serialization và session safety hiện tại.

## 3. Scene Profiles

CRUD:
- `GET /api/v1/scene-profiles`
- `POST /api/v1/scene-profiles`
- `GET /api/v1/scene-profiles/{profile_id}`
- `PUT /api/v1/scene-profiles/{profile_id}`
- `DELETE /api/v1/scene-profiles/{profile_id}`
- `POST /api/v1/scene-profiles/{profile_id}/duplicate`

Runtime actions:
- `POST /api/v1/scene-profiles/{profile_id}/apply`
- `POST /api/v1/scene-profiles/{profile_id}/verify`
- `POST /api/v1/scene-profiles/{profile_id}/activate`
- `POST /api/v1/scene-profiles/{profile_id}/review`
- `GET /api/v1/scene-profiles/{profile_id}/preview`

Review status:
- `GET /api/v1/scene-reviews/{job_id}`

Templates:
- `GET /api/v1/scene-profile-templates`
- `POST /api/v1/scene-profile-templates/{template_id}/instantiate`

Backend:
- `streamops/server/api/obs.py`
- `streamops/server/services/obs_scene.py`
- `streamops/server/profile_store.py`
- `streamops/server/scene_profiles.py`

## 4. Source Catalog & Inventory

Catalog:
- `GET /api/v1/obs/source-catalog`

Inventory:
- `GET /api/v1/obs/inventory`

Backend:
- `streamops/server/scene_profiles.py`
- `streamops/server/services/source_inventory.py`
- `streamops/server/platform/windows/obs_inventory.py`

Production source picker phải render từ API catalog thay vì duplicate catalog bằng hard-code.

Inventory có thể cung cấp:
- windows
- cameras
- capture devices
- render devices
- monitors
- existing OBS inputs
- plugin property items khi OBS hỗ trợ

Nếu inventory một phần bị lỗi, UI phải preserve saved value và hiển thị trạng thái/error phù hợp như behavior hiện tại.

## 5. Profile source model

Mỗi source có thể gồm:
- `id`
- `name`
- `obs_name`
- `type`
- `enabled`
- `layer`
- `settings`
- `transform`
- `audio`
- `verification`

Transform video:
- x
- y
- width
- height
- crop_left
- crop_top
- crop_right
- crop_bottom

Audio:
- enabled
- muted
- volume_db
- sync_offset_ms
- tracks 1–6

Verification:
- video_signal
- audio_signal
- audio_threshold_db
- sample_seconds

## 6. Verification result

Backend result có:
- `scene`
- `status`
- `ready_for_live`
- `generated_at`
- `obs_version`
- `checks[]`
- `artifacts`

Mỗi check có:
- `id`
- `status`
- `message`
- `expected`
- `actual`

UI mới nên expose expected/actual khi expand check.

## 7. Review result

Review chạy background job.

States:
- queued
- running
- completed
- failed

Artifacts có thể gồm:
- profile snapshot
- preview image
- recorded media sample
- media analysis

UI không được giả định filename cố định trong production; render artifact data từ response/result khi có.

## 8. Existing browser behavior cần preserve

- polling OBS runtime status;
- activity log;
- unsaved draft guard;
- discard confirmation;
- runtime scene actions disabled nếu OBS không READY;
- profile CRUD vẫn dùng được khi OBS stopped;
- editor state Saved / Modified / Applied / Drifted / Failed;
- preview refresh sau runtime operations;
- review polling;
- backend validation/error message phải hiển thị cho operator.

## 9. Implementation constraint

Reference component là React/Tailwind prototype.

Production hiện tại là vanilla HTML/CSS/JS. Agent không được tự động:
- thêm React;
- thêm Tailwind;
- thay toàn bộ frontend stack;
- tạo parallel OBS management page.

Chỉ refactor framework khi có ticket riêng và operator phê duyệt.


## 10. Streaming UI split

Production UI phải tách hai route:

- `/obs`: OBS Management Dashboard.
- `/obs/stream`: Streaming Management.

### 10.1 /obs

`/obs` giữ nguyên các domain OBS hiện tại và thêm card `Streaming` để hiển thị summary.

Card này không sở hữu full streaming form. Nó chỉ cần:
- destination hiện tại;
- selected/saved Scene Profile;
- preflight/live state;
- navigation `Open Streaming` → `/obs/stream`.

### 10.2 /obs/stream

Page này chỉ render domain streaming:
- Destination;
- Stream Setup;
- Preflight;
- Live Control / Live Status;
- Stream Activity.

Không duplicate các card OBS Runtime, Sources, Canvas, Verification hay Review.

### 10.3 Live transport

Streaming business flow dùng domain WebSocket riêng:

- OBS domain: `/api/v1/obs/ws`
- Live domain: `/api/v1/live/ws`

Khi Live WebSocket healthy:
- không polling `GET /api/v1/live/status` cho business state;
- fresh `stream.snapshot` là source of truth;
- reconnect/reload phải reconcile lại destination/profile/live state từ server.

Expected browser invariant sau ticket #25:

```text
1 x /api/v1/obs/ws
1 x /api/v1/live/ws
0 x business REST polling while sockets are healthy
```

### 10.4 Streaming operations

Live WebSocket operations:
- `destinations.list`
- `destinations.get`
- `destinations.create`
- `destinations.update`
- `destinations.delete`
- `destinations.set_credential`
- `destinations.delete_credential`
- `live.preflight`
- `live.start`
- `live.status`
- `live.stop`

Destination type catalog hiện có qua `GET /api/v1/stream-destination-types`. Nếu backend bổ sung catalog operation qua Live WebSocket thì FE nên ưu tiên cùng transport realtime để giữ invariant không business REST polling.

### 10.5 Credential rule

Public destination settings và credential phải tách riêng:
- UI không render plaintext credential sau khi save;
- chỉ hiển thị `credential_configured`;
- không ghi secret vào Activity Log, DOM diagnostic, error message hoặc restore metadata công khai.

### 10.6 Active session mutation guard

FE phải disable update/delete/credential mutation của destination đang được managed live session sử dụng.

Backend vẫn là final authority và phải reject unsafe mutation bằng typed conflict (HTTP 409 hoặc equivalent WS error) trong ít nhất:
- STARTING
- LIVE
- STOPPING

Nên giữ guard cho tới khi managed session/recovery metadata được cleanup hoàn toàn.
