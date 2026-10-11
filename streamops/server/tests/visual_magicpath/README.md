# MagicPath pinned references — #86

These **original MagicPath assets** were retrieved via the connected MagicPath component service for the exact locked revision IDs in issue #86. The two `reference_source/src/*Manager.tsx` files and `index.css` are unmodified source snapshots. Git blob digests in `manifest.json` are verified by tests; do not substitute a production UI screenshot as a reference. The JPEGs are **single compressed preview images**, preserved for audit only. They are not automatically treated as 4-viewport goldens.

`reference_source` is a standalone, test-only React/Vite/Tailwind renderer. It is **not** bundled into the StreamOps runtime wheel, nor merged with the production frontend. CSS/runtime dependencies are test-only.

Golden candidate generation: launch Vite from `reference_source` and run Playwright fixture; render both original reference and production UI at the 4 fixed viewports, capture reference/actual/diff and publish CI artifacts. Approvals are **explicit**. `approved:false` means no owner-approved Golden exists; a visual approval gate must fail until there is a reviewed and version-controlled artifact. Production screenshots may never replace the MagicPath source or preview digests.

The original MagicPath prototype contains mock fixtures and selectable scenarios. The production pages must not contain those controls; test code maps reference scenarios to deterministic WS fixtures where supported. Visual comparison may identify differences requiring FE correction; a failing comparison is not permission to weaken thresholds or update the reference.

## Promoting candidates to approved Goldens

1. Review every FE-G5 `expected-magicpath.png`, `actual-streamops.png`, `diff.png` triplet, plus the original MagicPath previews. These screenshots are candidates, never automatically approved.
2. After explicit **owner** approval, copy each expected screenshot to `goldens/<design>-<scenario>-<width>x<height>.png` and commit every file (all REQUIRED_SCENARIOS).
3. Commit SHA-256 of each Golden to `manifest.json approval.expected_sha256`. Set `approved=true`, `approved_by`, `approved_at`, and `review_url` pointing to the specific owner's written approval. Protect these files with repository PR review rules.
4. CI then checks *both* rerendered original MagicPath source and FE screenshots against the approved files. Missing images/reviews, hash drift, source drift (>.015), FE diff (>.08), or self-updated Goldens must fail. There is no `--update-snapshots` path.


## #86 design-alignment update — 2026-10-11

Owner approved three **design changes**, not new Golden images or a merge:
- **Steam Manager** (MagicPath component 459507753589833728, new revision **460004034603028480**) now includes Node capture readiness in the expanded Steam Process card and a realistic Steam Restart confirmation with Save-progress warning, button label `Restart`. The MagicPath screen remains demo-only: no real Steam command is issued from the preview.
- **Game Manager** (component 459507767749795840, new revision **460004044581269504**) displays Force Stop **disabled** for V1. Its action handler also refuses `force`.
- Old revisions **459530030574370816** and **459530038539325440** remain immutable, together with the **19 previously owner-approved Golden PNGs**. No baseline hashes or tolerances have been changed.

Updated independent source snapshots live under `reference_source_v2`. `review_manifest_v2.json` records the exact new component revision IDs and Git blob SHA-1 hashes, plus the explicit `approved:false` for **new** review candidates. The FE-G5 suite renders legacy tests from `reference_source` and **10 new candidate comparisons** from `reference_source_v2` on port 5179, emitting **Expected/Actual/Diff** without elevating candidate images to Golden.

**Pending:** Owner review of the new expected screenshots as Golden baselines; E2E-10 cannot be ticked complete until the full expected/actual/geometry tests pass under an approved manifest on one exact PR HEAD. Any differences must be corrected in production UI or returned for design review, **not** accepted by loosening thresholds. Force Stop remains disabled, and no real Steam/game lifecycle UAT is authorized.
