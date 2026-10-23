# Maxroll Calculation Provider

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
