# StreamOps UI Design

**Canonical branch:** `docs/ui-design` — standalone design-only branch, **never merge into `master`**.

This repository tree follows the actual UI navigation hierarchy, not GitHub ticket IDs.

```text
/obs  OBS Manager
  ├── /obs/stream   Stream Manager
  └── /obs/plugins  Plugin Manager
```

- [OBS Manager](./obs-manager/README.md) — current Dashboard design and component
- [Stream Manager](./obs-manager/stream-manager/README.md) — multistream + preflight, includes historical Streaming Output behavior notes
- [Plugin Manager](./obs-manager/plugin-manager/README.md) — approved plugin UI and handoff

**Rules:** one canonical TSX export per current screen; only design documents and MagicPath reference exports; old revisions available in Git history. New changes should target this branch, not `master`. TSX files are **design references, not production code**.
