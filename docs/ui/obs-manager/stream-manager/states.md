# Stream Manager V2 - State Matrix

| State | UI meaning | Primary action |
|---|---|---|
| IDLE | Khong stream | Start neu readiness PASS |
| STARTING | Start accepted, cho backend | Cho status; khong gia dinh LIVE |
| LIVE | Backend xac nhan live | Stop |
| RECONNECTING | Dang phuc hoi ket noi | Stop; cho backend recovery |
| STOPPING | Stop accepted | Disable duplicate Stop |
| FAILED | Destination loi doc lap | Start/Retry neu contract cho phep |

Start enabled = shared preflight PASS + destination READY + runtime allows start.

Mixed state hop le: YouTube LIVE, Twitch RECONNECTING, Facebook IDLE, TikTok FAILED. Khong co global FAILED chi vi mot destination loi.

## FE acceptance
- Bam visual approved tren MagicPath.
- Co OBS Session, Shared Preflight, Destinations va Stream Activity.
- Preflight FAIL block Start.
- Destination readiness block dung destination.
- Start/Stop transition chi chot state theo backend.
- Mixed states doc lap.
- Credential da luu khong hien plaintext.
- Add/Edit/Delete co validation/error.
- Stream Activity co timestamp + event + context.
- Reload/reconnect reconcile backend state.
- Co empty/loading/service unavailable/runtime failure/recovery.
- Responsive behavior giu dung hierarchy cua MagicPath.

Thay doi UX dang ke can quay lai design review #50.
