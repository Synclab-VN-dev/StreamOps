# Issue #75: MagicPath visual Golden gate

Frozen original source/preview comes from these exact MagicPath revisions, and never from production UI:
- Plugin Manager component 458351046272638976, revision 459936145191612416 (earlier 459906255415296000).
- Dashboard component 456064390102405120, revision 458892152907374592.

Reference snapshots live in originals/ and references/, their Git blob SHA1 hashes in manifest.json. Reference renderer uses those original component files in isolation; its rendering source is different from StreamOps FE. Preview JPEG files are independent audit snapshots.

CI FE-G5 captures expected-magicpath.png, actual-streamops.png, diff.png, and result.json for each viewport/state/capture position, even when the visual gate is blocked. It does not change production application or perform OBS mutations. CI compares original reference render against approved Golden (0.015 max drift), and product FE against approved Golden (0.08 max normalized RGB diff). Dimensions must match.

Rule v5: unchanged UI states rendered directly from an Owner-pinned MagicPath
revision do **not** require Owner to approve each passing screenshot. The current
manifest has `approved=false` for legacy review provenance, but that flag alone
must not block the visual gate. The gate still fails if a reference state is
missing, source/revision SHA drifts, viewport differs or pixel score exceeds 0.08.

The original MagicPath component and styles must remain byte-identical to their
stored source hashes. For the existing `blocked` scenario, the *test-only*
Vite transformer selects the React preview branch already defined inside the
pinned MagicPath revision via `?state=blocked`; it changes only initial state
selection at compile time and never changes markup, CSS, backend data, or the
stored reference source. Expected screenshots are still rendered from MagicPath,
never captured from FE as baseline. The `blocked` design now has an independently
compared FE case.

Other missing visual states remain BLOCKED. Some preview labels exist in the
MagicPath code but do not yet define realistic full backend-driven UI states.
`recovery-required` and `legacy-adopted` have no named MagicPath preview branch.
Those require a concrete UI design decision/revision before Golden coverage
can be declared complete; changing the threshold, masking pixels or generating
Golden from production is prohibited.

Browser viewports: 360x800, 390x844, 768x1024, 1440x900; modal, expanded/scroll and Dashboard card have separate cases. Functional Playwright tests do not substitute for this golden parity check.

## Design-only update approved on 2026-10-11
Only the fake OpenStream OBS Plugin example and dependent fake totals/activity labels were removed from the MagicPath source. The canonical remaining design plugin is Multiple RTMP Outputs. **The inline confirmation UI, layout and UI-state coverage are intentionally unchanged**; reapproval of matching screenshots is not required under rule v5. See previous pinned revision in the Git commit history.

## Owner-approved MagicPath Confirm placement correction (2026-10-11)
Only Confirm presentation was changed in MagicPath component `458351046272638976`: native centered `<dialog>`, opened with `showModal()`, with backdrop, Cancel / Confirm and Escape-to-close, matching existing FE semantics. Updated revision: `459936145191612416` (prior `459906255415296000`). Do not interpret this as owner approval of candidate Golden screenshots. Screenshot thresholds, missing-state blockers and all FE production runtime guards remain unchanged.
