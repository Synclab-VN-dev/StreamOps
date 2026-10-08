# OBS Plugin Manager — UI Design Handoff (#49)

**Status:** Design approved by operator on 2026-10-08. Implementation pending.  
**Scope:** UX/UI only. Backend #47 / PR #52; FE integration is a separate implementation task.

## Design sources (existing MagicPath project)

| Surface | URL | Approved revision |
| --- | --- | --- |
| OBS Dashboard | https://designs.magicpath.ai/v1/smart-cliff-3265 | `458892152907374592` |
| OBS Plugin Manager | https://designs.magicpath.ai/v1/nicely-village-8080 | `458897546841038848` |

The design was updated **in place**, not recreated. Use the final revision of the Plugin Manager; earlier revisions contain prototype-only "Design & developer tools" cards and placeholder Unicode icons, which were intentionally removed from the main UI.

## Exported UI source (actual MagicPath TSX)

The approved UI component source is committed alongside this document:

- [StreamOpsMobileDashboard.tsx](./issue-49-ui-export/StreamOpsMobileDashboard.tsx) — OBS Dashboard with Plugin Manager navigation card.
- [StreamOpsOBSPluginManager.tsx](./issue-49-ui-export/StreamOpsOBSPluginManager.tsx) — approved dedicated Plugin Manager UI, including manager overview, plugin cards, Activity Log and state fixtures.

These are **raw MagicPath React/TSX component exports for design handoff**, not a ready-to-run integrated StreamOps FE. They require the existing React/Tailwind/Lucide dependencies, route wiring and real API bindings. Do not treat prototype fixtures as live data.

## Information architecture

```text
OBS Dashboard
  └─ Plugin Manager summary card (collapsed by default)
       └─ Manage / Open Plugin Manager → /obs/plugins

OBS Plugin Manager page
  ├─ Header: OBS readiness + back navigation
  ├─ Manager overview: Managed / Installed / Attention + Refresh
  ├─ Managed plugins
  │    ├─ OpenStream OBS Plugin (prototype fixture; NOT BE-supported in #47)
  │    └─ Multiple RTMP Outputs (obs-multi-rtmp; BE scope #47)
  └─ Manager tools
       └─ Activity Log (session-local FE log)
```

## Visual and component rules

- Reuse the mobile-first OBS Dashboard visual language: `#f5f6f8` background, white `rounded-3xl` cards, restrained neutral borders, compact typography, status pills.
- **Manager overview** is the aggregate controller, **Managed plugins** contains plugin-specific expandable cards, **Manager tools** contains utilities. Do not render all three as undifferentiated plugin cards.
- Use Lucide iconography, not raw Unicode glyphs. Current design: `Puzzle` (plugins section), `SlidersHorizontal` (tools section), `Camera` (OpenStream camera plugin), `RadioTower` (multi-RTMP).
- Plugin cards default collapsed; expansion reveals compatibility, release metadata, verification and available actions.
- Advanced source commit, SHA-256, install path and manifest details belong in the expanded details, not the collapsed summary.
- Show only actions permitted by the current state. Disabled mutations during active output must explain why.
- Avoid showing prototype-only scenario controls, FE notes, hard-coded fixture counters or developer tools in production.

## State / interaction matrix

| State | Primary UI | Allowed interaction | Expected behavior |
| --- | --- | --- | --- |
| NOT_INSTALLED | Not installed | Install | Confirm → validate release → backup/stage → install |
| INSTALLED / VERIFIED | Verified + version | Verify; rollback if baseline exists | Refresh verification or restore a valid backup |
| UPDATE_AVAILABLE | Installed and available versions | Update | Confirm → validate → backup → update |
| INSTALLING / UPDATING | Progress and current step | No duplicate mutation | Display in-progress status, reconcile on reconnect |
| RESTART_REQUIRED | OBS restart banner | Restart OBS | Use existing OBS Process API; reconnect then verify |
| RESTARTING_OBS | Expected restart / reconnect | Wait / refresh | Do not treat expected disconnect as unexpected failure |
| VERIFYING | OBS + WS + Vendor checks | Wait | Show verification progress and outcome |
| VERIFY_FAILED | Typed failed check | Retry verify / recovery | Preserve error context, do not claim success |
| ROLLING_BACK | Restoring previous release | Wait | Preserve backup and progress |
| ROLLBACK_SUCCEEDED | Previous version restored | Verify | Show restored version and final health |
| ROLLBACK_FAILED | High-severity recovery error | Inspect / guided retry | Do not silently retry destructive operations |
| OUTPUT_ACTIVE | Streaming / recording blocks mutation | Refresh; Verify | Disable install/update/rollback; never stop live output |
| OBS_OFFLINE / WS_UNAVAILABLE | Reconnect notice | Retry status | Reconcile with BE after connection returns |
| VENDOR_UNAVAILABLE | Plugin loaded but Vendor probe failed | Verify / troubleshoot | Distinguish OBS READY from plugin READY |
| LOADING / EMPTY / ERROR | Loading / no managed plugin / request failure | Refresh / retry | No fake success or hard-coded inventory |
| MULTIPLE_PLUGINS | List of expandable cards | Select per plugin | Aggregate Managed/Installed/Attention from real inventory |

**Prototype coverage:** MagicPath provided visual mock states; it does not prove actual API behavior or persistence.

## UI ↔ backend contract (#47)

- Inventory/status: plugin id, display name, installed flag, installed version, available version, state, restart requirement, compatibility, last verification. Aggregate counts must be computed from backend data.
- REST and WS share `ObsPluginService`; operations: `status`, `install`, `update`, `verify`, `rollback`.
- WS names: `obs_plugin.status`, `obs_plugin.install`, `obs_plugin.update`, `obs_plugin.verify`, `obs_plugin.rollback`. Correlate request and response with `request_id`.
- Update is transactional, **not** an alias of install. BE owns provenance validation, backup, verification and recovery.
- Restart OBS via existing OBS Process API; do not create duplicate plugin-manager restart logic.
- BE must reject mutation while streaming/recording and return a typed error; UI must not auto-stop outputs.
- Activity Log is a **frontend session log** derived from operation responses; no persistent log API required for #49.
- Do not request or display stream keys or other credentials.

## Plugin identity and fixtures

- `obs-multi-rtmp` / **Multiple RTMP Outputs** is the required backend-supported plugin in #47.
- **OpenStream OBS Plugin** is a separate camera-rotation plugin shown as a future/generic UI fixture; it must not be presented as actually managed until added to the backend registry/allowlist.
- Version numbers, counts and sample activity entries shown in the prototype are **not live data**. FE must replace all fixtures with backend state and event-driven session logs.

## FE handoff checklist

1. Reuse existing OBS Dashboard card and route navigation pattern.
2. Implement `/obs/plugins` from approved MagicPath design.
3. Build generic plugin-card component with stable plugin id, typed status, expandable details and actions.
4. Bind inventory, installed/available versions, readiness and aggregate counts to backend.
5. Bind Install / Update / Verify / Rollback to shared REST/WS contract; add confirmations, progress, error handling and reconciliation.
6. Reuse OBS Process API for restart; verify after reconnection.
7. Implement real session-local Activity Log, replacing static demo entries.
8. Cover all state matrix scenarios with component tests and manual review.

## Acceptance boundary

This document is the **handoff artifact** for #49. It does not assert FE implementation, BE completion, or manual approval of every individual Install/Update/Rollback interaction. The last manual review item in #49 remains unchecked pending operator review.
