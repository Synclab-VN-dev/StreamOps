# Issue #75 — Independent FE contract and implementation evidence

## Ownership / branch policy
FE worktree is based on master (not on BE PR #52). Backend #47 / Draft PR #52 remains a separate change. Mock and production use one JS adapter and shared pure domain model. This implementation is a draft; do not mark real-A or operator acceptance PASS from fixture tests.

The existing StreamOps UI is HTML/CSS/JavaScript. The approved MagicPath TSX is design-only and cannot be imported at runtime without a separate framework migration. The implemented UI follows the approved hierarchy: overview, managed plugin cards, tools/activity.

## Verified PR #52 operations
| Business operation | REST (reference) | WS (production) | Status |
| --- | --- | --- | --- |
| inventory | GET /api/v1/obs/plugins | obs_plugin.inventory | **BE v2 implemented in PR #52** |
| approved catalog | GET /api/v1/obs/plugins/available | obs_plugin.available | **BE v2 implemented in PR #52** |
| status | GET /api/v1/obs/plugins/{plugin_id} | obs_plugin.status | implemented |
| adopt | POST /api/v1/obs/plugins/{plugin_id}/adopt | obs_plugin.adopt | implemented |
| install | POST /api/v1/obs/plugins/{plugin_id}/install | obs_plugin.install | implemented |
| update | POST /api/v1/obs/plugins/{plugin_id}/update | obs_plugin.update | implemented |
| verify | POST /api/v1/obs/plugins/{plugin_id}/verify | obs_plugin.verify | implemented |
| rollback | POST /api/v1/obs/plugins/{plugin_id}/rollback | obs_plugin.rollback | implemented |
| OBS restart | POST /api/v1/obs/process/restart | obs.lifecycle.restart on /api/v1/obs/ws | implemented |

Plugin WS requests use {"type":"request","request_id":"...","operation":"obs_plugin.adopt","payload":{"plugin_id":"..."}}. Response success has same normalized service data as REST, error {"type":"response","request_id":"...","ok":false,"error":{"code":"...","message":"..."}}. No URL/path/source/binary/release fields allowed. Inventory and catalog now have BE v2 WS operations in PR #52. The FE continues to fail closed when the backend running on the target machine has not deployed that contract; there is no REST fallback.

## Outstanding P0 BE contracts
1. Final operation names and payload/response for WS inventory and catalog.
2. Change notification (proposed obs_plugin.changed) with monotonic revision, or another race-safe observer model.
3. Explicit backend rollback eligibility and reason (including adopted baseline).
4. Read-only in-flight/recovery status and reconnect/unknown-outcome reconciliation across tabs/processes.

Absent fields fail closed: Rollback disabled; unknown outcome blocks mutation until a successful inventory/catalog refresh; unknown active-output state blocks mutation. Progress is intentionally indeterminate without genuine backend steps.

## Adopt Existing safety
- Eligibility: registry-listed plugin state UNMANAGED, installed and adoptable, OBS STOPPED, idle output, plugin WS connected, no conflicting operation.
- The FE never calls OBS stop or stops streaming/recording in an Adopt flow. Operator must separately stop OBS. OBS READY makes Adopt unavailable.
- Confirmation is explicit; Cancel has no side effect. Calling Adopt does not automatically Install or Verify.
- LEGACY_ADOPTED preserves nullable version, is not a verified approved release; installing an approved release requires separate operator action.
- Rollback never enabled unless the BE explicitly asserts backup eligibility; no self-inferred baseline.
- Errors and timeout distinguish rejected/failed from unknown outcomes; unknown outcome reconciles via read-only calls only.
- Real A: require maintenance approval, original SHA/config snapshot, real provider/release readiness, and post-test restore/evidence. Not executed by CI.

## CI / evidence
Node built-in tests exercise pure UI model and safety matrix without OBS/BE. Python route smoke tests check served HTML/assets. Mock WS flow tests must match the final BE WS list/catalog spec before acceptance can be ticked. Final acceptance also requires joined FE+BE E2E, Dev-F Real A and operator Manual UAT. Scope intentionally excludes writing a Python installer, arbitrary release URLs, and design fixture OpenStream camera plugin.
