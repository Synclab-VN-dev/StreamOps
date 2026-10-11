# Issue #75: MagicPath visual Golden gate

Frozen original source/preview comes from these exact MagicPath revisions, and never from production UI:
- Plugin Manager component 458351046272638976, revision 459906255415296000 (previous 458975004185468928).
- Dashboard component 456064390102405120, revision 458892152907374592.

Reference snapshots live in originals/ and references/, their Git blob SHA1 hashes in manifest.json. Reference renderer uses those original component files in isolation; its rendering source is different from StreamOps FE. Preview JPEG files are independent audit snapshots.

CI FE-G5 captures expected-magicpath.png, actual-streamops.png, diff.png, and result.json for each viewport/state/capture position, even when the visual gate is blocked. It does not change production application or perform OBS mutations. CI compares original reference render against approved Golden (0.015 max drift), and product FE against approved Golden (0.08 max normalized RGB diff). Dimensions must match.

Current status is approved=false: collected screenshots are CANDIDATES. Before CI can pass, the project owner must review them and explicitly approve; commit reference PNGs to goldens/, record SHA-256 for every required case and the exact approval comment URL in manifest.json. No auto-update, skip/xfail, masking of product differences, or threshold weakening.

The pinned MagicPath Plugin Manager has an internal scenario React state but no reachable scenario selector. The manifest names remaining design-state gaps (loading, empty, offline, legacy, failure/recovery). Those gaps are BLOCKED pending an owner-approved renderable design revision or explicit reviewed scope decision, and must not be silently tested against production-generated baseline.

Browser viewports: 360x800, 390x844, 768x1024, 1440x900; modal, expanded/scroll and Dashboard card have separate cases. Functional Playwright tests do not substitute for this golden parity check.

## Design-only update approved on 2026-10-11
Only the fake OpenStream OBS Plugin example and dependent fake totals/activity labels were removed from the MagicPath source. The canonical remaining design plugin is Multiple RTMP Outputs. **The inline confirmation UI, layout and UI-state coverage are intentionally unchanged**; owner Golden approval is still required. See previous pinned revision in the Git commit history.

## Owner-approved MagicPath Confirm placement correction (2026-10-11)
Only Confirm presentation was changed in MagicPath component `458351046272638976`: native centered `<dialog>`, opened with `showModal()`, with backdrop, Cancel / Confirm and Escape-to-close, matching existing FE semantics. Updated revision: `459936145191612416` (prior `459906255415296000`). Do not interpret this as owner approval of candidate Golden screenshots. The `approved=false` gate, screenshot thresholds, missing-state blockers and all FE production runtime guards remain untouched.
