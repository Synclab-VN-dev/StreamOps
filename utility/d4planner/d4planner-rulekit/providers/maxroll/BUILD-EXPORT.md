# Maxroll native build export

`exportMaxrollBuildFromSnapshot(options)` exports an immutable, version-pinned copy of native state
that is already present in an approved Web Snapshot package. It is fixture tooling owned by the
Maxroll Provider package and is not part of the D4 Rule Kit Application API.

## Programmatic API

```js
const {
  exportMaxrollBuildFromSnapshot,
  listMaxrollBuildProfilesFromSnapshot,
} = require('@streamops/maxroll-calculation-provider');

const common = {
  url: 'https://maxroll.gg/d4/planner/1g1any0x',
  snapshotRoot: '/approved/snapshot-store',
  snapshotId: 'maxroll-20261023T034150Z',
  expectedManifestSha256: '<external trust anchor>',
};

const inventory = await listMaxrollBuildProfilesFromSnapshot(common);
const result = await exportMaxrollBuildFromSnapshot({
  ...common,
  profile: 3,
  outputPath: '/private/fixtures/rogue-midgame.json',
});
```

The list operation returns only sanitized variant inventory. Export writes a deterministic
`maxroll-native-build-export/v1` envelope containing:

- the complete native planner state with the chosen `activeProfile`;
- all shared item records and references from the captured response;
- loader metadata needed for native offline hydration;
- selected-profile section presence;
- snapshot, response and runtime asset provenance;
- native-state and complete-file SHA-256 fingerprints.

The source response is public in the approved snapshot but can include author metadata. Therefore
the exported JSON is private fixture material: do not commit, print, upload, or attach it to public
CI artifacts. Only the result object returned by the API/CLI is sanitized for logs.

## Failure contract

- `PROFILE_NOT_IN_SNAPSHOT`: URL/profile response was not captured; no network fallback occurs.
- `PROFILE_VARIANT_NOT_FOUND`: requested native or visible profile does not exist.
- `SNAPSHOT_MISMATCH`: package integrity, manifest trust anchor, or runtime asset identity failed.
- `NATIVE_BUILD_INVALID`: response/state schema or item referential integrity failed.
- `OUTPUT_EXISTS`: overwrite was refused.
- `EXPORT_FAILED`: atomic private output persistence failed.

The exporter deliberately does not translate native state into a canonical build, mutate Maxroll,
or implement the Generic Build Importer proposed by Issue #134 Phase B.
