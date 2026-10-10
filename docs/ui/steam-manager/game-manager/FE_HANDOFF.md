# Production FE / BE handoff (#84)

## Current code vs missing capability
| Area | Existing server | Implementation needed |
|---|---|---|
| Steam process | `GET /api/v1/steam/status`; `POST /api/v1/steam/restart` | Preserve semantics. Do not alias to game lifecycle. |
| Steam page | `streamops/server/web/steam.html`, `steam.js` | Embed GameManager summary, leaving Process Status / Big Picture restart / Activity Log intact |
| Games page | No `/games` production page | Route + list/detail + responsive navigation |
| Game lifecycle | No generic game registry/discovery API verified in StreamOps | Dedicated backend GameService / provider adapters / Windows session-safe process detector |
| OBS | Existing OBS status/scene APIs | Capture health adapter with verified frames, not merely configured input |
| D4Planner | Separate optional runtime | Optional tool card; absence is NOT a game failure |

## Proposed API model (NOT implemented)
```ts
type ProcessState = "RUNNING"|"STOPPED"|"STARTING"|"STOPPING"|"FAILED"|"UNKNOWN";
type WindowState = "FOREGROUND"|"BACKGROUND"|"NOT_DETECTED"|"UNKNOWN";
type CaptureState = "VERIFIED_ACTIVE"|"CONFIGURED_ONLY"|"INACTIVE"|"ERROR"|"UNKNOWN";
type Selection = "SELECTED"|"NOT_SELECTED"|"UNKNOWN";
type GameObservation = {
  id: string; title: string; provider: "steam"|"battlenet"|"epic"|"standalone"|"unknown";
  registered: boolean; process: ProcessState; processPid: number|null;
  windowsSessionId: number|null; interactive: boolean|null; window: WindowState;
  capture: CaptureState; selectedForStream: Selection;
  observedAt: string|null; stale: boolean; uptimeSeconds: number|null;
  capability: {start: boolean;stop: boolean;restart: boolean;forceStop: boolean};
  actionUnavailableReason?: string;
};
type GameOperation = {operationId:string; action:"start"|"stop"|"restart"|"forceStop";
  phase:string; status:"pending"|"success"|"failed"|"unknown"; updatedAt:string;
  reasonCode?:string};
```

Proposed read routes: `GET /api/v1/games`, `GET /api/v1/games/{id}`, `GET /api/v1/games/{id}/observations`.
Proposed mutation routes: `POST /api/v1/games/{id}/{start|stop|restart}`; force-stop separate, role-gated and disabled by default. Confirm exact path/method/body in BE ticket before FE binds it.
Use stable game ID and provider IDs, idempotency key and operationId; reconcile response via observed process state instead of optimistic success. Enforce session check, concurrent-operation lock and typed errors. Do NOT accept arbitrary executable paths or shell commands from UI.
No hard-coded Diablo IV path or Steam-only assumption. Multi-game and multiple-instance semantics require BE design choice.

## FE expectations
1. Use theme and layout from OBS Plugin Manager (light `zinc`, white rounded-3xl, pastel state pills, black primary buttons, Lucide).
2. Replace **all** fixture values; missing data stays Unknown. Keep mock controls out of production.
3. Read game inventory/process/window/capture/selection separately. Each has an observedAt/stale indication.
4. Reuse the host's existing health and authenticated API client. Keep Activity Log labeled session-local unless persistent storage is explicitly implemented.
5. Show explicit pending, failure, timeout, retry/reconcile. Stop is graceful by default; Force Stop requires explicit separate confirmation.
6. Preserve Steam Big Picture behavior; avoid implicitly restarting Steam while games run.
7. Test narrow mobile viewport (360/390px), tablet (768px) and desktop, keyboard focus and back navigation.
8. Unit + E2E + Dev F Windows smoke + operator manual before marking production ready.

## Follow-ups
- Open a dedicated **BE GameService / Windows lifecycle** issue with contract, source of truth, and safety acceptance.
- Open a separate **FE Game Manager** issue that depends on BE contract, including two-page integration.
- Manual-device design UX review goes in [#76](https://github.com/Synclab-VN-dev/StreamOps/issues/76) when not yet individually signed off.
- **Never merge** `docs/ui-design` into `master`; cherry-pick approved implementation artifacts into production FE work if required.
