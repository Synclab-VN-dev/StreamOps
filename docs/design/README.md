# StreamOps UI Design

**Branch:** `docs/ui-design` — standalone UI design archive. **Do not merge into `master`.**

Only the latest selected UI snapshot for each screen is kept. React/TSX files are **MagicPath reference exports**, not production application code. Markdown files describe behavior and FE handoff.

| Screen | UI reference | Design documentation | MagicPath |
| --- | --- | --- | --- |
| OBS Dashboard | [StreamOpsMobileDashboard.tsx](./obs-dashboard/StreamOpsMobileDashboard.tsx) | [Design spec](./obs-dashboard/design-spec.md), [FE mapping](./obs-dashboard/implementation-mapping.md) | https://designs.magicpath.ai/v1/smart-cliff-3265 |
| Streaming Output | [StreamOpsStreamingOutput.tsx](./streaming/StreamOpsStreamingOutput.tsx) | [Design spec](./streaming/design-spec.md) | https://designs.magicpath.ai/v1/clear-tower-8758 |
| Stream Manager v2 | [StreamOpsStreamManagerV2Preflight.tsx](./stream-manager/StreamOpsStreamManagerV2Preflight.tsx) | [UI spec](./stream-manager/ui-spec.md), [States](./stream-manager/states.md) | https://www.magicpath.ai/files/456063904129388544 |
| OBS Plugin Manager | [StreamOpsOBSPluginManager.tsx](./plugin-manager/StreamOpsOBSPluginManager.tsx) | [Handoff](./plugin-manager/handoff.md) | https://designs.magicpath.ai/v1/nicely-village-8080 |

## Latest snapshot policy

- **One TSX per screen.** For Dashboard use the latest approved #49 revision `458892152907374592`; supersedes older dashboard reference.
- Plugin Manager: approved revision `458897546841038848`. #49's manual Install/Update/Rollback review remains pending.
- Streaming Output and Stream Manager: latest exported snapshots available in the previous docs branches; verify against MagicPath before claiming any newer unpublished revisions.
- Do not keep historical UI exports, duplicated READMEs, or legacy inventory files in this branch. Git history preserves previous snapshots.
- Future design updates go directly to this branch or via PR **targeting `docs/ui-design`**, never `master`.
