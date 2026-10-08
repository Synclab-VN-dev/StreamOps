# StreamOps UI design registry

**Canonical review branch:** `docs/issue-49-plugin-manager-handoff` (PR #73). After merge, `master` becomes the canonical source of UI design documentation. Avoid separate long-lived docs branches.

| Area | Spec / handoff | UI source | Notes |
| --- | --- | --- | --- |
| OBS Dashboard v2 | [Dashboard design](./obs-mobile-dashboard-v2/README.md) | [Dashboard reference](./obs-mobile-dashboard-v2/reference/StreamOpsMobileDashboard.tsx) | Earlier dashboard reference; historical baseline |
| Streaming Output | [Streaming spec](./obs-mobile-dashboard-v2/STREAMING_UI_SPEC.md) | [Streaming UI reference](./obs-mobile-dashboard-v2/reference/StreamOpsStreamingOutput.tsx) | Stream output design |
| Stream Manager v2 | [Stream Manager docs](../stream-manager/README.md) | [Stream Manager UI](./stream-manager-v2/reference/StreamOpsStreamManagerV2Preflight.tsx) | Already present in master; identical files verified |
| OBS Plugin Manager #49 | [Approved handoff](./issue-49-obs-plugin-manager-handoff.md) | [Approved Plugin Manager UI](./issue-49-ui-export/StreamOpsOBSPluginManager.tsx) | Approved MagicPath revision; pending manual flow review |
| OBS Dashboard with Plugin Manager card | [#49 handoff](./issue-49-obs-plugin-manager-handoff.md) | [Dashboard UI export](./issue-49-ui-export/StreamOpsMobileDashboard.tsx) | **Latest approved dashboard export**; use this for #49 integration |

## Rules

1. Keep designs grouped under `docs/design/` and implementation guidance near its feature docs.
2. Update one consolidated docs branch/PR at a time; after merging, start changes from latest `master`.
3. Do not merge old docs branches wholesale; copy verified files only to avoid unrelated historical commits.
4. MagicPath exports are design references, not production-ready FE or backend-integrated code.
5. The older OBS Dashboard reference is retained for history; for Plugin Manager integration, prefer the #49 Dashboard export.
