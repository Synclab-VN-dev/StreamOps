# Persistent authorized capture and offline real runtime test

An Owner-requested capture is persisted with one command:

```bash
npm --prefix utility/d4-rulekit/providers/maxroll run snapshot:capture -- \
  --output /private/snapshot-store/maxroll-YYYYMMDD
```

It discovers an existing Chromium/Chrome executable, captures the public planner with a fresh
read-only context, and atomically saves an immutable `web-snapshot/v1` package. The command verifies
the manifest and every content-addressed blob before writing its report. The folder contains
`manifest.json`, `manifest.sha256`, `blobs/`, `capture-report.json` and
`resource-inventory.json`; it must not already exist and is not deleted after success.

Capture success is `CAPTURED_UNVALIDATED`, never Real E2E PASS. A patch or asset different from the
historical pin is reported as `PATCH_DRIFT` while the valid package is retained for review. The
snapshot folder must remain outside Git and must not be uploaded as a GitHub Actions artifact.
Automatic capture on pull requests is disabled; online capture occurs only after an explicit Owner
request.

Authorization policy reference: `StreamOps#132-owner-directive-2026-10-23`. This names the project
decision and does not claim a separate Maxroll agreement identifier.

The command does not auto-retarget the historical `3.2.1.73552` profile.

## Offline real acceptance contract

The lower-level command remains available for diagnostics with an already provisioned package:

```bash
cd utility/d4-rulekit/providers/maxroll
npm ci

export BROWSER_INFRA_CHROMIUM_PATH=/approved/chromium
export MAXROLL_AUTHORIZED_SNAPSHOT_ROOT=/approved/local/snapshot-store
export MAXROLL_AUTHORIZED_SNAPSHOT_ID=approved-snapshot-id
export MAXROLL_AUTHORIZED_MANIFEST_SHA256=<64-hex-external-trust-anchor>
export MAXROLL_SNAPSHOT_AUTHORIZATION_REF=<owner-or-maxroll-approval-reference>

npm run test:real
```

`MAXROLL_SOURCE_URL` is optional and defaults to the bounded historical planner URL. It must match
the saved snapshot manifest. The test does not capture, download or update website assets. Use the
manifest anchor written by `snapshot:capture` as the trust input only after reviewing the captured
runtime identity and compatibility status.

The command runs two bounded tests with 150-second per-test timeouts and a three-minute suite
process bound:

1. three exact A→B→A cycles with 50 raw and 34 display metrics;
2. all eight Application APIs through the real provider.

Missing trust inputs are a hard failure named `BLOCKED_AUTHORIZED_SNAPSHOT`; no test is skipped and
no synthetic fallback is selected.

## Encrypted Release fixture

The immutable Release asset is encrypted to the public age recipient pinned in
`src/encrypted-fixture.js`. Local packaging and round-trip verification use:

```bash
npm run fixture:encrypted -- package \
  --snapshot /private/snapshot-store/maxroll-20261023T034150Z \
  --output-dir /private/release-staging \
  --age-bin /approved/age --identity /private/fixture-identity

npm run fixture:encrypted -- verify \
  --encrypted /private/release-staging/ci-data-pack-20261023-r01.zip.age \
  --checksum /private/release-staging/ci-data-pack-20261023-r01.zip.age.sha256 \
  --age-bin /approved/age --identity /private/fixture-identity
```

The plaintext ZIP exists only inside a mode-restricted temporary directory and is removed on both
success and failure. The Release must contain only the `.zip.age` ciphertext and its `.sha256` file.
The workflow never resolves `latest`, captures a website, or runs on pull requests.

Full local acceptance downloads that exact immutable Release, verifies the ciphertext trust anchor,
decrypts into a private temporary directory, verifies every snapshot resource, selects the candidate
profile by exact asset identity, runs the real tests, and removes all plaintext with one command:

```bash
npm run e2e:real:offline -- \
  --identity /private/fixture-identity \
  --age-bin /approved/age \
  --chromium /approved/chromium
```

The pinned tag is `test-fixture/enc-e2e-20261023-r01`. The command does not accept a snapshot path,
does not contact Maxroll, and does not retain the downloaded ciphertext or decrypted snapshot after
completion. It emits only sanitized acceptance summaries under ignored `artifacts/`.

## Trusted CI boundary

The repository workflow is manual-only and accepts secrets only on `refs/heads/master` through the
protected `maxroll-fixture-trusted` Environment. Feature-branch name matching is not a trust signal.
For a pre-merge candidate, a separate one-purpose bootstrap workflow on the default branch must pin
both the exact reviewed branch and its exact commit SHA. Environment approval is the checkpoint at
which a reviewer authorizes that immutable candidate to receive the decrypted fixture.

The workflow passes `--ephemeral-identity`: after successful decryption and integrity validation,
the one-use identity file is deleted before the candidate test child starts. Token, credential,
identity, password, private-key and secret variables are removed from the child environment. The
candidate necessarily receives the decrypted fixture to execute the approved test, which is why
exact-SHA review and Environment approval are both required. Environment deployment-branch rules
and required reviewers live in GitHub Settings and cannot be proven by repository source alone.
