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
