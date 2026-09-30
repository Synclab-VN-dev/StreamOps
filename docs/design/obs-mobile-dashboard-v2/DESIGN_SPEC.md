# DESIGN SPEC — OBS Mobile Dashboard v2

## 1. Design principle

UI mới dùng mô hình **collapsible operational cards**:

- tất cả card mặc định collapsed;
- collapsed card không chỉ hiện title, mà phải là mini-dashboard riêng cho domain đó;
- mỗi card hiển thị 3–4 summary field có ý nghĩa riêng;
- expand card phải giữ đầy đủ dữ liệu/action tương ứng của UI hiện tại;
- card lỗi có thể highlight mạnh; không tự động làm mất khả năng truy cập thông tin khác.

## 2. Card structure

### 2.1 OBS Runtime

Collapsed summary:
- Runtime state: READY / STARTING / RUNNING_NO_WEBSOCKET / STOPPED / ERROR
- Uptime
- Streaming
- Recording

Expanded:
- PID
- Started
- Uptime
- Windows Session
- Active Console Session
- Interactive
- Executable
- WebSocket
- WebSocket Endpoint
- OBS Version
- obs-websocket Version
- Streaming
- Recording
- Last Operation
- Start OBS
- Stop OBS
- Restart OBS
- error state/message khi có

### 2.2 Scene Profile

Collapsed summary:
- profile đang chọn
- editor state: Saved / Modified / Applied / Drifted / Failed
- canvas: width × height @ FPS
- số source

Expanded:
- profile selector
- New
- Duplicate
- Delete
- Template selector
- Create from template
- Name
- Width
- Height
- FPS
- Save
- Save As
- Apply saved
- Verify
- Activate
- Review

Runtime action phải disable khi OBS chưa READY, giống behavior hiện tại.

### 2.3 Sources

Collapsed summary:
- số source configured
- số source enabled
- số source types trong catalog / inventory status

Expanded:
- Add source
- Refresh inventory
- danh sách source hiện tại
- từng source là sub-card/details riêng, mặc định collapsed

Mỗi source expanded phải preserve:
- source name
- source type
- enabled
- layer
- typed source settings
- transform: x/y/width/height/crop left/top/right/bottom
- audio config nếu hỗ trợ
- mute
- volume dB
- sync offset ms
- tracks 1–6
- video/audio signal verification
- threshold
- sample seconds
- remove source

### 2.4 Add Source picker

Picker phải lấy catalog từ backend, không hard-code production behavior.

Catalog hiện tại gồm 13 loại:

Video:
1. Game Capture
2. Window Capture
3. Display Capture
4. Video Capture Device
5. Media / SRT / RTSP
6. Browser
7. Image
8. Video File
9. Existing OBS Video Source

Audio:
10. Audio Input Device
11. Application Audio
12. Audio Output Capture
13. Existing OBS Audio Source

Với các field hỗ trợ inventory, lựa chọn phải dùng dữ liệu từ OBS/native inventory:
- windows
- monitors
- cameras
- capture devices
- render devices
- existing OBS inputs

### 2.5 Canvas & Preview

Collapsed summary:
- canvas/resolution
- FPS
- scene/profile context hoặc preview availability

Expanded:
- tab hoặc segmented control `Layout`
- tab hoặc segmented control `OBS Preview`
- layout canvas phải phản ánh transform/layer của source
- preview phải dùng preview endpoint hiện có

### 2.6 Verification

Collapsed summary:
- PASS / WARN / FAIL
- ready_for_live
- số PASS/WARN/FAIL
- last verification context/time nếu có

Expanded:
- toàn bộ checks
- check id
- status
- message
- expected
- actual
- generated_at
- obs_version nếu có

Không được làm mất dữ liệu `expected` / `actual` đã có ở backend.

### 2.7 Review

Collapsed summary:
- review state
- requested/measured duration nếu có
- media result
- artifact count

Expanded:
- review seconds
- Run Review
- queued/running/completed/failed state
- result checks
- artifacts:
  - profile.json
  - preview
  - recorded sample
  - media analysis
- lỗi review nếu có

### 2.8 Activity Log

Collapsed summary:
- last event
- warning/error count trong browser session
- timestamp gần nhất nếu phù hợp

Expanded:
- preserve full browser-session activity log hiện tại.

## 3. Interaction rules

- Click/tap header card để toggle expand/collapse.
- Summary luôn visible khi collapsed.
- Không làm mất unsaved-change guard khi đổi profile hoặc rời trang.
- Local profile CRUD vẫn hoạt động khi OBS stopped.
- Runtime scene actions chỉ hoạt động khi OBS READY.
- Stop/Restart OBS vẫn bị block khi streaming hoặc recording.
- Save chỉ persist profile; không tự mutate OBS.
- Apply, Activate, Verify, Review giữ nguyên semantic hiện tại.
- Source picker và editor phải usable trên mobile viewport.

## 4. Responsive requirements

Primary target: mobile portrait khoảng 360–430 px.

Desktop vẫn phải usable:
- không kéo content thành một cột quá hẹp trên desktop;
- có thể tăng max width hoặc grid hợp lý;
- không thay đổi information hierarchy chỉ vì desktop rộng hơn.

## 5. Visual requirements

- clean operational dashboard;
- ưu tiên scan nhanh state/status;
- summary text ngắn;
- diagnostic data để phía sau expand;
- status color phải có text, không dựa riêng vào màu;
- button target đủ lớn cho touch;
- focus state/accessibility phải giữ được.

## 6. Non-goals

- Không redesign backend model.
- Không thêm Start/Stop Streaming nếu API hiện tại chưa có.
- Không hard-code Gaming/Camera/BRB thành scene cố định.
- Không đưa React/Tailwind vào production chỉ vì reference component dùng React/Tailwind.
