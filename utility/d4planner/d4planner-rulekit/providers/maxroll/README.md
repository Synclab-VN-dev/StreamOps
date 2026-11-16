# Maxroll Calculation Provider

The independent Native JSON → offline Planner → DOM display-value path is documented in
[DOM-CALCULATION.md](./DOM-CALCULATION.md). It has an explicit entry point and no fallback
to or changes in the CDP path below.

Universal canonical/native import status and its measured coverage are documented in
[`UNIVERSAL-IMPORT.md`](./UNIVERSAL-IMPORT.md) and
[`UNIVERSAL-IMPORT-COVERAGE.json`](./UNIVERSAL-IMPORT-COVERAGE.json).

Build export and engine/input/output attestation are documented in
[`BUILD-EXPORT.md`](./BUILD-EXPORT.md) and
[`BUILD-ATTESTATION.md`](./BUILD-ATTESTATION.md).

Version-pinned Calculation Provider for D4 Rule Kit. It composes the generic Chromium and Web
Snapshot infrastructure from Issue #124 and exposes the provider/session port expected by Issue
#127. It does not own Application registry, revision, preview tokens, cache or delta logic.

```text
MaxrollProvider
  -> MaxrollPatchProfile (snapshot/runtime/asset pin)
  -> MaxrollComponentFactory (synthetic or real strategy injection)
  -> MaxrollSession (desired-state and recovery lifecycle)
  -> MaxrollBuildMapper (bounded input support)
  -> MaxrollRuntimeAdapter (UI apply/read-back + CDP)
  -> MaxrollMetricsExtractor (freshness and completeness)
  -> BrowserInfrastructure / WebSnapshotManager
```

## Supported scope

The initial profile contract is deliberately bounded to the previously evidenced fixture:

- game patch `3.2.1.73552`;
- Rogue, level 50, Torment I;
- Runic Skullcap in Helm;
- optional `of-dampening` effect mutation;
- 50 raw Character Stat IDs and 34 independently displayed values.

Every other class, level, item slot, skill, Paragon, rune, charm or change type is
`UNSUPPORTED_INPUT`; it is never silently ignored. `OBSERVED` provider output is not Formula or
Golden `VERIFIED` evidence.

## Runtime safety

- Snapshot ID and external manifest SHA-256 are pinned and verified before acquiring Chromium.
- The active runtime asset SHA-256, runtime version and game patch are checked fail-closed.
- Offline-strict snapshot routing is mounted before navigation; missing requests are aborted.
- Desired state is applied through the runtime UI contract and read back before metric extraction.
- Every extraction requires a new phase marker and the complete profile metric catalog.
- A timeout/cancel, browser disconnect or failed recovery invalidates and cleans the session.
- No login, Save/Publish, credential extraction/persistence or formula implementation exists in
  this package. Live capture uses only browser-managed anonymous state in a fresh context and never
  exposes request headers to the orchestrator or artifacts.

The repository contains only a synthetic Maxroll-shaped website used to test architecture and real
Chromium lifecycle. It contains no Maxroll asset body. A separate `maxroll-ui-cdp-v1` strategy now
implements the bounded historical UI/CDP protocol. Snapshot provisioning is automated by Issue
#132 only when explicitly requested by the Owner; real acceptance still fails closed when the live
runtime differs from that historical pin.

Issue #132 provides an explicit, Owner-requested persistent capture command:

```bash
npm run snapshot:capture -- --output /private/snapshot-store/maxroll-YYYYMMDD
```

It launches an anonymous Chromium context, captures only allowlisted read-only resources through the
generic Snapshot Manager, atomically saves `manifest.json`, `manifest.sha256` and content-addressed
`blobs/`, verifies every blob, then writes `capture-report.json` and `resource-inventory.json`.
The output folder must not already exist and is never removed after a successful capture. A runtime
different from the historical pin is retained with `CAPTURED_UNVALIDATED` / `PATCH_DRIFT`; this is
not a Real E2E PASS. Snapshot assets stay outside Git and must not be uploaded as CI artifacts.

Automatic sync, fetch and runtime upgrade are disabled. The live workflow is manual-only; PRs do
not contact Maxroll. See `RUNTIME-COMPATIBILITY.md` and `REAL-REPRODUCE.md`.

## Export a build embedded in a live guide

The same CLI accepts public `https://maxroll.gg/d4/build-guides/<slug>` URLs:

```bash
npm run build:export -- \
  --url https://maxroll.gg/d4/build-guides/dance-of-knives-rogue-guide \
  --list-profiles

npm run build:export -- \
  --url https://maxroll.gg/d4/build-guides/dance-of-knives-rogue-guide \
  --output /private/builds/dance-of-knives-endgame.native.json
```

This mode fetches the guide HTML and parses the literal Remix loader data without
executing page scripts. It requires exactly one planner-page block with matching
D4 planner identity and valid native item references. Redirects stay on Maxroll
guide URLs; requests have a 30-second deadline and an 8 MiB response limit.
Unsupported guide formats, multiple/missing planners and invalid data fail explicitly.

The default variant is the embedded `data.activeProfile`, matching a fresh guide
view. A browser's locally saved variant is not available to the CLI. The embedded
planner link's fragment is preserved as provenance, **not** reinterpreted using
the offline planner export's visible-variant numbering. Use `--profile <native-index>`
from `--list-profiles` to override. Guide section anchors do not select variants.

The native export retains every profile, item, and native field, with the selected
profile active. It includes the guide URL, original planner URL, retrieval time,
response hash and native-state integrity hash. Account/author metadata is omitted.
It is labelled `LIVE_GUIDE_EMBED`, `snapshotVerification: NOT_PERFORMED` and
`calculationStatus: NOT_ASSESSED`: it does not assert compatibility with an installed
snapshot, canonical conversion or calculation attestation. Snapshot flags cannot
be combined with guide mode. Existing offline planner URL export remains unchanged.

Outputs are private (0600), created atomically without overwrite, and must stay
outside Git. No snapshot is installed, activated, or changed by this command.

## Offline native build export

Issue #134 adds provider tooling—not an Application API—to inventory and export native build state
already present in an approved snapshot. The exporter verifies the complete snapshot package and an
external manifest trust anchor, resolves only the captured `profiles/load/d4/<id>` response, checks
native item references, and writes an immutable `maxroll-native-build-export/v1` file atomically.
It never fetches a missing URL and refuses to overwrite an existing fixture.

```bash
npm run build:export -- \
  --url https://maxroll.gg/d4/planner/1g1any0x \
  --snapshot-root /approved/snapshot-store \
  --snapshot-id maxroll-20261023T034150Z \
  --manifest-sha256 <trusted-sha256> \
  --list-profiles

npm run build:export -- \
  --url https://maxroll.gg/d4/planner/1g1any0x \
  --snapshot-root /approved/snapshot-store \
  --snapshot-id maxroll-20261023T034150Z \
  --manifest-sha256 <trusted-sha256> \
  --profile 3 \
  --output /private/fixtures/rogue-midgame.json
```

`--profile` is the native index printed by `--list-profiles`. A numeric URL fragment is also
supported as a one-based visible-variant selector when `--profile` is omitted. The exported file
contains complete proprietary native state and loader metadata needed for exact offline replay; it
must remain in a private, Git-ignored location. CLI output contains only sanitized hashes,
selection metadata and provenance. This tool does not claim a canonical D4 build format or generic
import support and does not alter the eight Application APIs.

The two GB-E1-ATT input/output pairs are available only as a pinned age-encrypted test artifact.
See [`BUILD-FIXTURE-RELEASE.md`](BUILD-FIXTURE-RELEASE.md) for the direct Release links, ciphertext
checksum, separately provisioned-key workflow, and manifest verification requirements. Plaintext
fixtures and the ciphertext itself are intentionally absent from Git.

Phase B0 established the initial native-to-canonical-to-native slice without wrapping a native
response or hardcoding either fixture. The current B1-B7 contract and evidence are documented in
[`UNIVERSAL-IMPORT.md`](UNIVERSAL-IMPORT.md); the historical checkpoint remains in
[`UNIVERSAL-IMPORT-B0.md`](UNIVERSAL-IMPORT-B0.md).

Issue #134 has a release-pinned local acceptance runner. It downloads the encrypted snapshot plus
the immutable r01/r02 build/reference packages, verifies every trust anchor, decrypts only inside
private temporary directories, runs selected bounded suites, and removes plaintext on every exit:

```bash
npm run acceptance:issue134 -- \
  --identity /private/fixture.agekey \
  --age-bin /approved/age \
  --chromium /approved/chromium \
  --resume all
```

`--resume` also accepts comma-separated `static,synthetic,multiclass,mutations,application,regression`.
`--resume all` always runs all eight real mutation shards and ignores inherited
`MAXROLL_TEST_CLASS`. For targeted debugging, select the mutation group and classes explicitly:

```bash
npm run acceptance:issue134 -- \
  --identity /private/fixture.agekey \
  --age-bin /path/to/age \
  --chromium /path/to/chromium \
  --resume mutations \
  --mutation-classes Rogue,Sorcerer
```

Targeted runs report `PARTIAL_PASS`; only an unfiltered `--resume all` can report `FULL_PASS`.
Every mutation class is a separate bounded shard. Missing, failed or timed-out shards fail the
aggregate rather than being treated as skipped acceptance.
The runner never captures or syncs Maxroll and writes only a sanitized ignored report under
`artifacts/issue134-acceptance.json`.

The owner-triggered multi-class capture command is documented in
[`MULTICLASS-FIXTURES.md`](MULTICLASS-FIXTURES.md). It captures seven current Season 15 planner
sources read-only, verifies their executing engine, replays each through the pinned offline
snapshot, and combines them with the verified Rogue evidence for 8/8 class coverage. Fixture
plaintext remains outside Git. The resulting eight pairs are distributed only through the pinned
age-encrypted artifact documented in
[`MULTICLASS-FIXTURE-RELEASE.md`](MULTICLASS-FIXTURE-RELEASE.md).

The pinned CI test fixture is published only as an age/X25519-encrypted ZIP plus its ciphertext
checksum. `npm run fixture:encrypted` verifies the source snapshot, packages/encrypts it, or
decrypts a pinned Release asset into a temporary directory for full manifest/blob verification.
Only the public recipient is stored in source; the identity is held in the
`MAXROLL_FIXTURE_AGE_IDENTITY` GitHub Secret and is never logged or uploaded. The dedicated workflow
is `workflow_dispatch` only, so fork pull requests cannot execute untrusted code with that secret.
The captured runtime is selected explicitly as the `d12am6kt-candidate` profile for acceptance; it
is not silently promoted over the historical default. Local encrypted-Release Real E2E now passes,
while production trust-policy approval remains an Owner decision.

## Local tests

```bash
npm ci
npm run typecheck
npm run test:unit
npm run test:contract
BROWSER_INFRA_CHROMIUM_PATH=/path/to/pinned/chrome npm run test:e2e
```

`npm run test:real` is deliberately outside the default synthetic gate. It requires all explicit
snapshot trust/provenance inputs documented in `REAL-REPRODUCE.md` and fails rather than skips when
they are absent.

`npm run e2e:real:offline -- --identity ... --age-bin ... --chromium ...` is the preferred full
acceptance entry point. It provisions only the pinned encrypted Release, verifies it, selects the
candidate profile explicitly, runs MXP-09/MXP-10/APP-07, and removes plaintext temporary data.
Trusted CI adds `--ephemeral-identity`, restricts the normal workflow to `master`, and removes secret
material from the real-test child environment. Pre-merge execution requires the separately reviewed
default-branch bootstrap workflow plus approval of the exact candidate SHA in the protected
Environment; a matching feature-branch name alone is never sufficient.

The package sets npm `install-links=true` so the sibling file dependency is packed into this
package's `node_modules` on a clean install. This lets `browser-infra` resolve its own declared
`playwright-core` dependency without relying on a pre-existing sibling `node_modules` directory.

Tests are deterministic and bounded. The E2E suite starts a local synthetic origin, captures it with
the generic Snapshot Manager, then evaluates three A→B→A cycles from offline-strict replay with zero
origin requests. It also exercises all eight D4 Rule Kit Application APIs through provider dependency
injection, including immutable preview, commit, reset and cleanup. This is architecture/lifecycle
evidence only. `snapshot:capture` produces a verified but unvalidated runtime package; a separate
offline `test:real` run with a compatible reviewed profile is required for real acceptance.

The MXP-08 E2E writes local launch/load/calculation/queue/RSS observations to ignored
`artifacts/performance.json`; these measurements are evidence, not performance thresholds.

The synthetic CI job probes the browser already installed on the pinned GitHub runner image and
runs `npm run smoke:browser` before the suites. The smoke launches through Browser Infrastructure,
navigates a local `data:` document, releases its lease and verifies browser shutdown. Missing or
incompatible browsers fail explicitly; CI does not silently download a replacement or skip E2E.

See `REAL-MAXROLL-GAP-ANALYSIS.md` before creating a real patch profile. The current selectors and
UI protocol belong to the synthetic Phase A runtime and are not asserted to exist on Maxroll.

Capture completeness uses scope policy v2: after the read-only interaction, observe at least 5 seconds
and require 1 second of eligible-request quiescence. Eligible requests and response-body reads must
finish within the operation deadline. A failed/missing entity body fails closed; GET `/api/twitch`
remains in scope. The capture report records actual routed request nodes, navigation attribution,
pending/failure counts and a manifest-bound coverage proof validated by Rule Kit's content inventory.
This proves the bounded navigation/interaction profile, not every possible future website interaction.
A legacy capture without that proof stays UNVERIFIED; do not retrofit a claim of complete coverage.
Completeness and content version remain independent from compatibility, trust and distribution.

### Private game data catalog export (Issue #208)

Run from this provider directory using an existing snapshot and its independently
pinned manifest SHA-256. This CLI is offline and has no network fallback:

```bash
npm run catalog:export -- --snapshot-root /private/snapshots \
  --snapshot-id maxroll-20261023T034150Z --manifest-sha256 "$MANIFEST_SHA256" \
  --list-families
npm run catalog:export -- --snapshot-root /private/snapshots \
  --snapshot-id maxroll-20261023T034150Z --manifest-sha256 "$MANIFEST_SHA256" \
  --output /private/catalog.json
```

Add `--families items,skills,paragonBoards` for a subset. The only supported keys
are `classes`, `items`, `itemTypes`, `affixes`, `oldAffixes`, `skills`, `skillTrees`,
`paragonBoards`, `paragonGlyphs`, `paragonNodes`, `stones`, `mercenaries`, `warPlans`,
`temperingRecipes`, `itemSets`, `attributes`. Counts come from the selected verified
catalog; they are not fixed baseline requirements. List mode writes inventory
counts only and accepts no output path.

Programmatic provider APIs: `listMaxrollCatalogFamilies(options)` and
`exportMaxrollGameDataCatalog({...options, outputPath})`, where options contain
`snapshotRoot`, `snapshotId`, `expectedManifestSha256` and optional `families`.
The approved codec contract is checked in addition to snapshot integrity. Export
v1 currently uses the approved D12 codec/patch/season contract; unsupported snapshots
fail rather than being labelled compatible.

JSON `maxroll-game-data-catalog/v1` preserves catalog keys, stable IDs and complete
selected family data, with provenance hashes, patch, canonical schema/codec/season
contract and actual counts. It excludes loader/profile data, snapshot assets and
engine bytes. Presence of 16 families does not prove valid combinations, class
eligibility or optimal builds. No extra relationships are inferred.

Output is canonical deterministic JSON with no timestamp, created atomically with
mode 0600 (subject to host filesystem support), never overwritten. Keep output in
a private directory. Console reports counts/hash/size only; errors report a code.
Never commit/upload exports or snapshot contents to GitHub, releases or CI artifacts.

Private offline evidence can be repeated with:

```bash
MAXROLL_AUTHORIZED_SNAPSHOT_ROOT=/private/snapshots \
  node --test tests/adapter-real/catalog-export.test.js
```

This test requires the approved pinned snapshot, uses temporary private output and
removes it afterwards. Synthetic unit/contract tests do not establish real snapshot
success; report the real offline result separately.

### Manual CI export

Actions → **CI** → **Run workflow** on master:
`operation=test`, `component=d4planner-catalog-export`.
This separate manual component uses the existing fixture capability/secret binding;
regular PR CI does not download private snapshots. No workflow wrapper modification
is required. The fixture capability requires trusted master, so a PR branch cannot
run the hosted secret-bearing job before merge.

Repo variable `D4PLANNER_CATALOG_EXPORT_CONFIG` is a JSON string:

```json
{
  "snapshot": "maxroll-20261023T034150Z",
  "manifestSha256": "638a283b8aa0cb822a35176d9d41c8d1751fb6f962ca0a2f7feaa20f1ef39e54"
}
```

Optional `families` is an array of exact family keys. The snapshot selector also
accepts `https://github.com/Synclab-VN-dev/StreamOps/releases/tag/test-fixture/enc-e2e-20261023-r01`.
Only this approved pinned fixture currently resolves to a supported codec. Other
IDs/links fail closed; a release URL alone does not establish trust or compatibility.
Input still uses `MAXROLL_FIXTURE_AGE_IDENTITY` and verified age v1.3.2 to decrypt
the encrypted snapshot. The legacy `ageRecipient` field is optional and accepted
only when it matches the approved fixture recipient; it no longer controls output.

The job runs the CLI twice, checks deterministic bytes, list/count consistency and
overwrite refusal. Under the Owner-approved exception for public Actions artifacts,
it uploads **plain `catalog.json`** and sanitized `report.json` through
`ctx.artifact()`. The report includes SHA-256, actual family counts and source commit.
No output decryption step is needed. Input snapshot, identity, raw config and other
intermediate files remain temporary/private and are removed on success and failure.
This exception applies only to the catalog output; other encryption remains intact.
Artifacts follow the shared workflow retention (currently 30 days).
