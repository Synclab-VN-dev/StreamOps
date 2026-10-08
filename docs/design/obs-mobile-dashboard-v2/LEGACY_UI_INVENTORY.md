# LEGACY UI INVENTORY — OBS Management

Tài liệu này liệt kê capability và thông tin hiện có trên trang `/obs` trước redesign. Mục tiêu là tránh regression chức năng khi chuyển sang card UI mới.

## OBS Runtime

Thông tin hiện có:
- runtime state
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
- runtime error

Actions:
- Start OBS
- Stop OBS
- Restart OBS

Runtime states:
- STOPPED
- STARTING
- RUNNING_NO_WEBSOCKET
- READY
- ERROR

## Scene Profiles

Profile list:
- list profiles
- profile count
- load selected profile

CRUD:
- New
- Duplicate
- Delete
- Save
- Save As

Templates:
- template selector
- Create from template

Profile fields:
- Name
- Width
- Height
- FPS

Editor states:
- No profile
- Saved
- Modified
- Applied
- Drifted
- Failed

Runtime profile operations:
- Apply saved
- Verify
- Activate
- Review

## Sources

Global actions:
- Add source
- Refresh inventory

Source editor:
- Source name
- Source enabled
- Layer
- type-specific settings
- Remove source

Video transform:
- x
- y
- width
- height
- crop_left
- crop_top
- crop_right
- crop_bottom

Audio:
- Configure audio
- Audio enabled
- Muted
- Volume dB
- Sync offset ms
- Track 1
- Track 2
- Track 3
- Track 4
- Track 5
- Track 6

Verification per source:
- Require video signal
- Require audio signal
- Audio threshold dB
- Sample seconds

## Supported Source Types

Video / mixed:
- Game Capture
- Window Capture
- Display Capture
- Video Capture Device
- Media stream (SRT/RTSP)
- Browser
- Image
- Video file
- Existing OBS video input

Audio:
- Audio input
- Application audio
- Audio output
- Existing OBS audio input

## Source Inventory

Có thể đọc từ native Windows/OBS:
- window list
- camera list
- capture devices
- render devices
- monitor list
- OBS inputs
- input kinds
- OBS property-list values khi plugin hỗ trợ

## Canvas

Desired-state canvas:
- width
- height
- FPS
- enabled visual sources
- source position/size theo transform
- source layer

## OBS Preview

- scene screenshot thực từ OBS
- preview status
- empty/error state

## Verification

UI hiện tại render:
- overall result
- từng check: status + id + message

Backend còn có nhưng UI cũ chưa expose tốt:
- ready_for_live
- generated_at
- obs_version
- expected
- actual
- artifacts

Redesign nên preserve dữ liệu cũ và có thể expose thêm các field backend này khi expand.

## Review

- review seconds: 1–300
- queue background job
- poll queued/running
- completed/failed state
- verification result

Backend review có thể tạo:
- profile snapshot
- preview image
- recorded media sample
- media analysis

## Activity Log

Browser-session activity:
- page/profile manager loaded
- OBS status changes
- lifecycle requests/results/errors
- profile operations/results/errors
- review queue/result
- inventory/preview errors

## Safety / behavior cần preserve

- local profile CRUD dùng được khi OBS stopped;
- Apply / Verify / Activate / Review disabled/rejected khi OBS chưa READY;
- unsaved draft confirmation trước load/replace/rời trang;
- Save không mutate OBS;
- Stop/Restart OBS blocked nếu streaming/recording;
- source/profile validation từ backend;
- unowned OBS resources được preserve;
- runtime errors phải visible cho operator.
