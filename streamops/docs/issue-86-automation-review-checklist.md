# #86 — Automation & owner review checklist

**Context:** FE PR [#89](https://github.com/Synclab-VN-dev/StreamOps/pull/89) is Draft and independent from BE PR [#88](https://github.com/Synclab-VN-dev/StreamOps/pull/88). Work done by `synclab-automation-system`. No code is merged into `master`; no release/deployment or unattended action on Windows A.

## Scope of automatic checks

- FE-G1 Store/WS: snapshot/revision/epoch/unknown, cached replay, reconnect, handler cleanup, operation resolution.
- FE-G2 Steam regression: Steam status, restart confirmation, card order, activity, no REST.
- FE-G3 Game list: 0/1/3/10+ fixtures, providers, Unicode/search/sort, missing data and observation.
- FE-G4 Lifecycle: Start/Stop/Restart via **fake** WS backend, explicit consent/cancel, idempotency key, operation ID, progress, terminal success/failure/unknown, disabled actions, read-only reconcile. **Never execute game lifecycle on CI hosts.**
- FE-G5: 19 owner-approved Golden screenshots, SHA-256 validated PNGs from MagicPath pinned revisions, negative mutation/geometry test, per-state reference/actual/diff artifacts, no baseline update.
- FE-G6: wheel and browser E2E packaging regressions.

**Acceptance policy:** CI passing a mock WebSocket is NOT equivalent to real BE #85 integration or Dev F/manual acceptance. Only tick each item when all its subcriteria have evidence on the same HEAD.

## Decisions requested from owner (not implicit permissions)

### A. WS contract extension needed for #86 E2E-06
The [#85 contract](https://github.com/Synclab-VN-dev/StreamOps/blob/feat/85-game-service/streamops/docs/issue-85-game-service-contract.md) defines Steam WS `steam.status`, `steam.lifecycle.restart`, `steam.snapshot`, and `steam.heartbeat`; it does **not** specify a `node.status` field/event or Node capture readiness in Steam payload.

Suggested minimal contract decision (BE #85 owner approval required):
- Reuse a **documented, existing Node status WebSocket** if present; otherwise add a versioned, typed **read-only** Node status observation to `steam.snapshot` (or a dedicated `node.snapshot` only if the BE owner chooses), with stale/UNKNOWN semantics and no HTTP fallback.
- FE cannot invent the field or mark E2E-06 DONE before the BE contract is agreed. Any BE patch must be a separate, authorized PR.

### B. GitHub branch required status checks needed for #86 E2E-13
Automatic workflows currently produce `Tests / windows` and `Game Manager Golden Visual (FE-G5) / FE-G5 / Original MagicPath visual parity & owner approval`. To make them **required** in repository policy, the owner must approve a separate Ruleset / Branch Protection change. The automation account must **not** change repository settings without authorization. Verify exact check names in GitHub UI before setting required statuses; don't make SKIPPED pass or disable approval gates.

### C. New Golden / visual coverage
Owner has approved **exactly 19 original MagicPath render candidates**, including 4 fixed viewports. Additional screenshot Goldens for modal-confirmation, failed/timeout, expanded detail, scrolling states, or further structural/icon changes should be presented as a **separate review artifact** with before/after reference/actual/diff; do not silently update the existing 19 reference files or loosen the 0.08 mean RGB tolerance.

### D. Real Windows A / Android B smoke acceptance (DEVF-01..06, MAN-01..05)
For safe preflight, do read-only route/assets/WS tests first. Validate on A that two browser consumers receive independent real WS pushes; on B check mobile layout, touch, safe area, focus, scroll, typography and Golden evidence. Document selected commit, session, time, machine, logs; redact game-control tokens.

**Do not Start/Stop/Restart Diablo IV or Steam on A without an explicit owner-approved test window** and clear instruction about whether gameplay/OBS is active. A permission to review the Golden is not permission to interrupt a live game. No force stop in V1. Real-device/manual items remain pending until owner and Dev F record actual evidence.

## Review order
1. Inspect [FE PR #89](https://github.com/Synclab-VN-dev/StreamOps/pull/89) file diff, CI details and 19 Golden screenshots.
2. Review automation tests and confirm no false pass/softening; verify two CI workflows successful on the **same HEAD**.
3. Decide Node WS contract and GitHub required checks explicitly (separately scoped approval).
4. Schedule read-only Dev F A/B evidence, then any real lifecycle in a separate authorized window.
5. Owner review/manual acceptance; only then discuss whether PR is ready for merge. Merge and release require separate explicit approval.
