# STREAMING UI SPEC — /obs/stream

## 1. Scope

Streaming Management là page riêng tại `/obs/stream`.

Mục tiêu:
- quản lý Streaming Destination;
- bind một saved Scene Profile;
- chạy preflight;
- Start/Stop streaming;
- hiển thị live output health;
- phục hồi đúng state sau browser reload/WebSocket reconnect;
- giữ cùng visual language với OBS Management tại `/obs`.

Không duplicate các card OBS Runtime, Sources, Canvas & Preview, Verification hoặc Review.

## 2. Navigation

Header:
- backlink `← OBS Management` → `/obs`;
- title `Streaming`;
- page-level state pill.

Page-level state pill phải phản ánh server state, ví dụ:
- IDLE
- READY
- STARTING
- LIVE
- STOPPING
- OBS_NOT_READY
- RECOVERY_REQUIRED
- RESTORE_FAILED

Không tạo state machine riêng chỉ để phục vụ UI.

## 3. Visual contract

Streaming page phải reuse design system của OBS Mobile Dashboard:
- light operational dashboard;
- background `#f5f6f8`;
- white operational cards;
- large rounded corners;
- subtle border/shadow;
- compact status pill;
- summary visible khi card collapsed;
- primary action màu near-black;
- secondary action nền trắng;
- destructive action dùng red treatment;
- PASS / WARN / FAIL luôn có text, không phụ thuộc màu.

Primary mobile target: 360–430 px portrait.
Desktop vẫn usable, content không cần full-width.

## 4. Destination card

Collapsed summary:
- Name
- Type
- Credential configured/missing

Expanded:
- Destination selector
- descriptor-driven settings
- current phase-1 type: Custom RTMP
- Server URL
- credential state
- Replace credential
- Remove credential
- Save destination
- secondary CRUD menu/action

Credential:
- public settings và secret tách riêng;
- plaintext Stream Key chỉ tồn tại trong input trước khi submit;
- sau save phải clear input;
- UI chỉ render configured/missing;
- không có action show current secret.

Khi destination đang được active managed session sử dụng:
- edit/delete/credential mutation disabled ở FE;
- backend conflict vẫn là final authority.

## 5. Stream Setup card

Collapsed summary:
- saved Scene Profile
- Canvas
- FPS

Expanded:
- chỉ chọn saved Scene Profile;
- hiển thị saved/verification/runtime context cần thiết;
- không Start bằng unsaved Scene Profile draft.

Nếu Scene Profile đang có unsaved changes ở `/obs`:
- streaming start phải block;
- UI phải giải thích Save/discard trước khi Start;
- không copy toàn bộ draft sang streaming page.

## 6. Preflight card

Collapsed summary:
- OBS readiness
- profile result
- output readiness
- overall PASS/WARN/FAIL

Expanded render toàn bộ gate backend trả về, gồm tối thiểu:
- `obs_ready`
- `profile`
- `destination`
- `destination_enabled`
- `credential`
- `destination_adapter` nếu có
- `output_engine` nếu có
- `profile_verify` nếu có

Backend là final authority.
UI phải support PASS / WARN / FAIL ngay cả khi backend hiện tại chủ yếu trả PASS/FAIL.

## 7. Live Control / Live Status card

### IDLE / READY

Collapsed:
- Destination
- Profile
- State

Expanded:
- Destination
- Scene Profile
- Preflight result
- Start Streaming

Start:
- anti-double-submit;
- disable khi blocking condition tồn tại;
- snapshot sau mutation là source of truth.

### STARTING / STOPPING

- action tương ứng bị khóa để tránh duplicate mutation;
- state rõ ràng;
- không giả định transition đã thành công trước snapshot.

### LIVE

Collapsed:
- Destination
- Uptime
- output metric quan trọng

Expanded:
- Output active
- Reconnecting
- Duration/Uptime
- Bytes sent
- Congestion
- Skipped frames
- Total frames nếu cần
- Active FPS
- CPU usage nếu relevant

Backend hiện không cung cấp instantaneous bitrate chuẩn.
Nếu FE tính từ `bytes_sent / duration`, label phải là `Avg bitrate`, không ghi đơn giản là `Bitrate`.

Stop Streaming:
- destructive/attention action;
- không đặt cạnh Start trong cùng state;
- anti-double-submit.

## 8. Recovery states

UI phải render rõ:
- OBS_NOT_READY
- RECOVERY_REQUIRED
- RESTORE_FAILED

Trong recovery:
- không cho tạo session live mới cho tới khi backend cho phép;
- hiển thị server-owned state;
- không tự reset local UI về IDLE chỉ vì request lỗi;
- destination/config mutation vẫn phải tuân theo active-session guard.

## 9. Stream Activity card

Collapsed:
- last event
- warning/error count

Expanded:
- Live socket connected/reconnected
- destination saved
- preflight result
- STARTING/LIVE
- STOPPING/IDLE
- recovery/error events

Không log:
- Stream Key
- credential plaintext
- server URL ghép với key
- private restore config

## 10. Realtime behavior

Streaming business state dùng `/api/v1/live/ws`.

Events:
- `stream.snapshot`
- `stream.heartbeat`

Rules:
- fresh snapshot là source of truth;
- browser reload khi đang LIVE phải recover đúng active session;
- reconnect phải reconcile toàn bộ destination/profile/output state;
- không business polling `GET /api/v1/live/status` khi Live WS healthy;
- mutation disabled cho tới khi socket/request path sẵn sàng.

## 11. Two-page responsibility

### /obs

Chỉ có card Streaming dạng overview:
- summary state;
- expanded overview;
- `Open Streaming`.

### /obs/stream

Sở hữu full streaming workflow:
- Destination
- Stream Setup
- Preflight
- Live Control / Live Status
- Stream Activity

Không biến `/obs` thành một bản duplicate của streaming page.

## 12. E2E acceptance

Browser tests phải cover:
- `/obs` có Streaming card, default collapsed;
- card summary readable và route tới `/obs/stream`;
- `/obs/stream` không render các OBS-only cards;
- destination CRUD/credential lifecycle;
- secret không leak;
- saved profile selection;
- unsaved-profile start block;
- preflight PASS/FAIL;
- Start → STARTING → LIVE;
- no duplicate Start;
- LIVE metrics;
- reload/reconnect recover LIVE;
- Stop → STOPPING → IDLE;
- no duplicate Stop;
- OBS_NOT_READY / RECOVERY_REQUIRED / RESTORE_FAILED;
- active destination mutation blocked;
- mobile 390×844 không horizontal overflow;
- one OBS domain socket và one Live domain socket theo domain/page đang sử dụng;
- zero business REST polling while healthy WebSockets are active.

## 13. Reference-only warning

MagicPath reference dùng React/Tailwind để mô tả visual/interaction.

Production StreamOps hiện dùng vanilla HTML/CSS/JS. Không:
- thêm React chỉ để copy prototype;
- thêm Tailwind chỉ để copy prototype;
- hard-code demo destination/profile/metric;
- dùng mock local state thay cho backend snapshot.
