# StreamOps Steam & Game Manager — Design handoff (#84)

**Scope:** UI/UX prototype only. NO production FE, BE, lifecycle calls or live game inventory.
**Approval:** operator approved the two-page visual design and light theme in the 2026-10-10 conversation. Individual failure-path interactions have been implemented as demo fixtures but not independently operator-certified on physical Android.
**MagicPath project:** [StreamOps UI Prototype](https://www.magicpath.ai/files/456063904129388544) (existing project; no project fork).

| Surface | Canonical MagicPath URL | Revision |
|---|---|---|
| Steam Manager | https://designs.magicpath.ai/v1/serene-winter-5786 | `459530030574370816` |
| Game Manager | https://designs.magicpath.ai/v1/sturdily-room-4179 | `459530038539325440` |

## Approved visual foundation
Use the existing OBS Plugin Manager / Stream Manager design system: `#f5f6f8` page, `text-zinc-950`, `max-w-md` mobile Steam page, `bg-white rounded-3xl border-black/5 shadow-sm` cards, `bg-zinc-50 rounded-2xl` inner sections, `bg-zinc-950 text-white` primary actions, pastel emerald/amber/red status pills, and Lucide icons. **Light theme supersedes the original dark-theme wording in #84** following operator approval. No separate global dark navigation bar, ornamental gradients or independent CSS palettes.

## Deliverables
- [SteamManager.tsx](./SteamManager.tsx): exact MagicPath generated component from approved light-theme revision; `/steam` card.
- [GameManager.tsx](./GameManager.tsx): exact generated component from final failure/timeout/reconciliation prototype; `/games` + Game Detail.
- [COMPONENT_TREE.md](./COMPONENT_TREE.md): page hierarchy and responsive behavior.
- [STATE_MATRIX.md](./STATE_MATRIX.md): state semantics, fixture walkthroughs and safety.
- [FE_HANDOFF.md](./FE_HANDOFF.md): proposed API model, capability gaps, dependencies and implementation gates.
- [screenshots/steam-manager-preview.jpg](./screenshots/steam-manager-preview.jpg) and [screenshots/game-manager-preview.jpg](./screenshots/game-manager-preview.jpg): MagicPath preview captures for these **specific revisions**. These are tool-rendered first-viewport screenshots, not independent device/browser responsive test results.

## Navigation
Steam Manager card appears between existing Steam Process Status and Activity Log. `Manage Games` goes to Games Manager; Game Manager Back returns to Steam. `Game Detail` is not a third route: overlay/page view on mobile and a right-side panel on desktop. Game Library is independent of Steam process readiness.

## Demo data and safety
Every value on MagicPath preview is **fixture**. Labels / counters / PID / uptime / game titles / launcher readiness are illustrative and must never be interpreted as real A-host status. Demo Start/Stop/Restart/Force Stop are simulated only. The Activity Log is browser-session-only. Production must not hard-code the fixtures, assume data is live, or treat configured OBS capture as active validated frames.

## Evidence and limitations
- Steam and Games MagicPath revisions built successfully; preview images verified.
- Operator approved overall page look/theme ("Oke ổn rồi") after the updated theme; manual device-specific Game Detail and individual failure-flow approval were not explicitly demonstrated.
- Negative-state fixture code covers Start FAILED, Stop TIMEOUT → UNKNOWN, stale → refresh/reconcile, external stop, no backend, session mismatch, OBS invalid frames and loading. These are UX fixtures, **not** validated backend outcomes.
- Do not merge design-only branch `docs/ui-design` into `master`. Production FE/BE must have separate tasks with unit/E2E and Dev F/manual gates.
- If any manual acceptance remains, record it transparently in [#76](https://github.com/Synclab-VN-dev/StreamOps/issues/76); do not fabricate a device test or confirmation.
