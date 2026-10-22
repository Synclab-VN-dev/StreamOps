# Authorized real runtime test

This is an offline test contract, not a snapshot acquisition workflow. Provisioning and permission
are Owner-controlled and intentionally outside this repository.

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
