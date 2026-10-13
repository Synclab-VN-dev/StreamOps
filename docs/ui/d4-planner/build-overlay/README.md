# D4 Planner — Build Overlay: approved MagicPath design handoff

> **DESIGN REFERENCE ONLY** · Issue [#66](https://github.com/Synclab-VN-dev/StreamOps/issues/66) · separate canonical branch `docs/ui-design`; never merge the design-only branch into `master`.

## Source of truth

- **Project:** [D4 Planner — Build Summary Overlay](https://www.magicpath.ai/files/458763473602621440) (`458763473602621440`)
- **Component:** D4 Planner — Compact Build HUD (`458765764401446912`)
- **Pinned approved revision:** `458808549301174272` (generated name `finely-wood-8539`)
- **MagicPath preview:** https://designs.magicpath.ai/v1/finely-wood-8539
- **Non-canonical copy:** project `458820053983432704`; do not choose as Golden source.

MagicPath selected revision controls visual hierarchy, spacing, colors, layout and interactions. Any conflicting text, historic #66 concept or prototype is **superseded**. Changing the pinned revision, UX or API contract requires Owner approval. Reference TSX is exported directly from the selected MagicPath revision, **not** manually recreated or modified to match production.

## Contents

| Path | Purpose |
| --- | --- |
| `D4PlannerCompactBuildHUD.tsx` | Canonical, byte-for-byte generated component TSX (design reference; not integrated app) |
| `reference/src/App.tsx` | Unmodified MagicPath app scaffold; imports original generated path |
| `reference/src/index.css` | Unmodified MagicPath styling |
| `reference/src/components/generated/D4PlannerCompactBuildHUD.tsx` | Unmodified generated-path copy to preserve scaffold resolution |
| `ui-spec.md` | Layout, visual tokens and exact interactions |
| `state-matrix.md` | Functional state/actions and explicitly unapproved states |
| `implementation-mapping.md` | UI modules/data mapping and production dependencies |
| `golden-manifest.json` | Provenance/hash and case-level visual baseline availability |
| `golden/approved-revision/default-expanded.jpg` | **Native compressed MagicPath revision preview**, not a deterministic per-viewport E2E capture |

## Handoff boundaries

- Design shows mock data (Charge Bolt 78/100; Equipment/Charms; Current vs Target). It does **not** supply Target Build JSON, scoring rules, API/WebSocket contract or persistent user interactions.
- Tauri POC [#71](https://github.com/Synclab-VN-dev/StreamOps/issues/71) passed technical feasibility only; real physical input/Owner GO-NO-GO remain in [#76](https://github.com/Synclab-VN-dev/StreamOps/issues/76). It does not prove Steam Link or OBS capture support.
- No production FE/BE/OBS/Game code or MagicPath content changed by this handoff. A separate production ticket must own integration and tests.

## Golden policy

`golden/approved-revision/default-expanded.jpg` was obtained from MagicPath `view_component(componentId, revisionId)`; it is native to the pinned revision. This compressed canvas preview has no controlled browser viewport/interaction capture metadata and is **REFERENCE_ONLY**, not a pixel-diff PASS.

All additional viewport/state Goldens must be rendered directly from the pinned MagicPath revision. Until available, their manifest status stays `BLOCKED_NO_CAPTURE` and downstream FE visual gate stays **BLOCKED**; do not synthesize screenshots from production or loosen thresholds. Compare canonical SHA-256 values in `golden-manifest.json` before promoting any new evidence.

## Review checklist

1. Confirm project/component/revision and original source hashes match this manifest.
2. Review light translucent 248px summary plus 252px section and 330px compare side-panels, collapse/expand, filters, Pin mock, semantic statuses.
3. Separate approved mock behavior from unapproved gaps and missing Golden states; do not mark functional/visual FE checks PASS.
4. Review this docs-only PR against `docs/ui-design`; Owner approval required before merge.
