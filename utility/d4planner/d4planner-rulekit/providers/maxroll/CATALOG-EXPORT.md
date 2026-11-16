# Private Game Catalog export — Issue #208

This feature **only** exports version-pinned Diablo IV game catalog data already inside a verified, authorized local Maxroll Snapshot. It does not build a character, optimize equipment, recapture data, execute game calculations or publish any assets.

## Local-only CLI

Run from `utility/d4planner/d4planner-rulekit/providers/maxroll` with the pre-existing, locally installed **private** snapshot:

```sh
npm run catalog:export -- \\
  --snapshot-root /private/snapshot-store \\
  --snapshot-id maxroll-20261023T034150Z \\
  --manifest-sha256 <trusted-external-sha256> \\
  --list-families

npm run catalog:export -- \\
  --snapshot-root /private/snapshot-store \\
  --snapshot-id maxroll-20261023T034150Z \\
  --manifest-sha256 <trusted-external-sha256> \\
  --families classes,items,itemTypes,affixes,skills,paragonBoards,paragonGlyphs \\
  --output /private/catalog-output/game-catalog.json
```

Omit `--families` to export all 16 approved game-data families; the CLI prints only inventory or sanitized output metadata and never prints the exported data. `--output` must be a private, writable local path. The exporter creates a file with restricted permissions, refuses overwrite and never accesses Maxroll or other network services. Do not put outputs under the Git working tree, CI artifact paths, public releases, cloud AI prompts or other shared/public storage without a separate provenance/rights review.

## Output contract

`d4-game-catalog-export/v1` contains:

- `game`: Diablo IV, pinned patch and Season 15.
- `provenance`: snapshot ID, validated manifest digest, game catalog digest and game data version.
- `selectedFamilies`, `counts`, `data`: selected allowlisted catalog families and their stable native IDs/payloads.

Allowed families: `classes`, `items`, `itemTypes`, `affixes`, `oldAffixes`, `skills`, `skillTrees`, `paragonBoards`, `paragonGlyphs`, `paragonNodes`, `stones`, `mercenaries`, `warPlans`, `temperingRecipes`, `itemSets`, `attributes`.

Read-only programmatic provider exports: `listCatalogFamilies(options)`, `exportCatalogFromSnapshot(options)`; `makeExport(catalog, families)` remains module-local tooling for tests and composition. The exporter reuses the snapshot-bound `loadMaxrollEntityCatalog` compatibility and integrity guard; it cannot export a wrong/unverified snapshot. Future snapshot versions require their own explicit approved compatibility binding and updated contract. Raw engine JavaScript, profiles, save state, anonymous user records, and snapshot blobs are not included in the exported object.

This data is **not** a verified combat mechanics model, AI-ready semantic rule graph or guaranteed current-season catalog. It only represents the pinned game data as captured. The `provenance` field is descriptive, not a substitute for trust/approval to distribute.

## Testing

```sh
npm ci
npm run typecheck
npm run test:unit
npm run test:contract
```

Local pinned-snapshot acceptance must separately execute both CLI modes above against an approved private snapshot and verify counts, stable IDs, output hashes, overwrite refusal and negative trust tests. Those tests cannot be certified from synthetic unit fixtures alone. **Do not upload the generated JSON or snapshot to GitHub/CI.**
