# Automated live capture to authorized real runtime test

The primary real acceptance command now performs the whole ephemeral lifecycle:

```bash
npm --prefix utility/d4-rulekit/providers/maxroll run e2e:real:live-capture
```

It discovers an existing Chromium/Chrome executable, captures the public planner with a fresh
read-only context, verifies the immutable snapshot and the independently checked-in patch/asset
pin, stops the online browser, then starts the existing `test:real` contract in a fresh browser
against an `offline-strict` mount. The temporary snapshot is removed on PASS and FAIL. Only
sanitized JSON/JUnit summaries are retained; captured website resources are never placed in Git or
CI artifacts.

Authorization policy reference: `StreamOps#132-owner-directive-2026-10-23`. This names the project
decision and does not claim a separate Maxroll agreement identifier.

Any patch, asset hash, breakpoint, selector or read-back drift fails closed. The command does not
auto-retarget the historical `3.2.1.73552` profile.

## Low-level pre-provisioned contract

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
the saved snapshot manifest. The test does not capture, download or update website assets.

The command runs two bounded tests with 150-second per-test timeouts and a three-minute suite
process bound:

1. three exact A→B→A cycles with 50 raw and 34 display metrics;
2. all eight Application APIs through the real provider.

Missing trust inputs are a hard failure named `BLOCKED_AUTHORIZED_SNAPSHOT`; no test is skipped and
no synthetic fallback is selected.
