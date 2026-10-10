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
