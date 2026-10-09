# Stream Manager V2 - UI/Behavior Spec

Design reference: https://www.magicpath.ai/files/456063904129388544

Visual target: **Stream Manager V2 - Multi Stream + Preflight + Stream Activity**.

## OBS Session
Hien thi OBS readiness, active scene/profile, canvas va aggregate destination. Aggregate chi mang tinh thong tin; moi destination van co state rieng.

## Shared Preflight
Preflight la gate dung chung truoc khi Start. Toi thieu: OBS READY, WebSocket CONNECTED, active scene, active profile, video capture ACTIVE, audio ACTIVE. Neu fail, Start bi block va UI chi ro check loi.

## Destination readiness
Moi destination co readiness rieng cho configuration/endpoint va credential. Destination chua ready khong duoc Start du shared preflight PASS.

## Runtime
Moi destination doc lap. Start: IDLE -> STARTING -> LIVE. Start accepted khong dong nghia LIVE; chi backend status moi xac nhan LIVE.
Stop: active -> STOPPING -> IDLE theo backend status.
FAILED/RECONNECTING cua mot destination khong lam mat LIVE state cua destination khac.

## Destination management
Add: display name, type/platform hoac Custom RTMP, endpoint, credential, validation, Save/Cancel.
Edit: non-secret config duoc hien; credential da luu chi hien Configured. Khong hien plaintext stream key. Dung Replace stream key.
Delete: confirmation va xu ly active destination theo backend contract.
FE dung public StreamOps destination_id, khong expose plugin target ID, OBS outputName hay Vendor implementation detail.

## Stream Activity
Co card Stream Activity expand/collapse nhu MagicPath. Timeline ghi event quan trong voi timestamp va destination/context: LIVE, reconnecting, connection failed, preflight result.

## Stats va reconcile
LIVE hien thi cac stats backend cung cap nhu bitrate, FPS, duration, bytes/frames.
Phan biet service/backend/plugin unavailable voi destination failure.
Reload/reconnect phai reconcile tu backend, khong giu optimistic state cu.

## API mapping
FE consume public StreamOps contract cua #48 cho CRUD/start/stop/status/stats. REST va WebSocket la transport/entry point; runtime status backend la authoritative.
