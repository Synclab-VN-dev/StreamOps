# W3 generic web snapshot acceptance

Local evidence captured on `2026-10-22T04:59:57Z` from branch
`feat/124-generic-web-snapshot`, based on merged W1/W2 commit
`79d359eaaca82294bb8768b54e89e46b6e8ad265`.

## Architecture and public contract

```text
WebSnapshotManager
  +-- BrowserInfrastructureContract
  +-- SnapshotStoreContract
  |     `-- FileSystemSnapshotStore
  `-- NetworkInterceptor
        `-- SnapshotMount
```

The public APIs and TypeScript declarations are `capture`, `save`, `load`,
`list`, `verify`, `mount`, and idempotent `unmount`. The manager uses
composition and does not change the W1/W2 public contract. Capture policy,
store and replay are provider-independent; no provider URL, selector or
business type exists in the package.

## Local acceptance

| ID | Automated evidence | Local status |
|---|---|---|
| SNAP-01 | Static HTML/CSS/JS/image/font capture, save and replay | LOCAL_PASS |
| SNAP-02 | SPA dynamic import, JSON GET, navigation and cold replay | LOCAL_PASS |
| SNAP-03 | A-v1, A-v2, B-v1, immutable IDs and concurrent isolation | LOCAL_PASS |
| SNAP-04 | New Chromium PID/context; SPA replay; source counters unchanged | LOCAL_PASS |
| SNAP-05 | Missing/wrong-site request aborted; no `continue()` | LOCAL_PASS |
| SNAP-06 | SHA-256 verify, modified/missing blob and duplicate ID | LOCAL_PASS |
| SNAP-07 | Auth/Cookie/POST/secret URL blocked; Set-Cookie stripped | LOCAL_PASS |
| SNAP-08 | Mount isolation, idempotent cleanup, restart and cleanup failure | LOCAL_PASS |
| SNAP-09 | Temp + atomic rename, corrupt/partial package and disk failure | LOCAL_PASS |
| SNAP-10 | Count/size/store limits, timeout/cancel and concurrency | LOCAL_PASS |
| SNAP-11 | Redirect metadata, 404/status/body, MIME/query and conflict rules | LOCAL_PASS |
| SNAP-12 | Service workers blocked; new process/profile does not use cache | LOCAL_PASS |
| SNAP-13 | Static, SPA and dynamic multi-origin synthetic consumers | LOCAL_PASS |
| SNAP-14 | INF regression, real Chromium E2E and Python Rule Kit regression | LOCAL_PASS / CI_PENDING |

INF-01 through INF-14 remain `LOCAL_PASS`. Manual UAT is `0`.

## Commands and results

```bash
cd utility/d4-rulekit/browser-infra
BROWSER_INFRA_CHROMIUM_PATH=/home/huy/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome npm test

python3 -m venv /tmp/streamops-w3-python.<temporary>/venv
/tmp/streamops-w3-python.<temporary>/venv/bin/python -m pip install -e 'utility/d4-rulekit[dev]'
/tmp/streamops-w3-python.<temporary>/venv/bin/python -m pytest -q utility/d4-rulekit/tests
```

- Node.js `22.22.1`; Playwright Core `1.64.1`.
- Chrome for Testing `156.0.8078.4`, real headless process.
- Unit: `37/37 PASS` (24 W1/W2 + 13 W3).
- Real Chromium E2E: `19/19 PASS` (9 W1/W2 + 10 W3).
- Python Rule Kit: `38/38 PASS`.
- Full Node unit + E2E wall time: `19.02s`.
- Peak measured resident set for the full `npm test` command tree: `216,984 KiB`.
- JUnit/JSON evidence: ignored local `artifacts/{unit,e2e}.{junit.xml,json}`.

## Boundaries and remaining risks

- Replay is intentionally `offline-strict`; an uncaptured resource aborts.
- Service Workers are blocked. Sites that require SW, writes, WebSockets,
  streaming, authentication or server-side execution are outside this version.
- Playwright invokes one route handler for an HTTP redirect chain. To prevent a
  fulfilled 3xx from escaping to the network, replay retains the exact 3xx and
  `Location` in the manifest, uses a captured local document transition, and
  resolves subresource redirects from the captured target. Tests assert source
  request counters do not change.
- The filesystem store serializes saves per store instance. Coordination among
  multiple OS processes writing the same root is not part of this version;
  deploy one store writer per root or provide a locking/object-store adapter.
- Website asset retention and redistribution require caller authorization;
  no captured website body is committed to Git.

## WHAT / WHO / WHY / HOW

- **WHAT:** reusable immutable website snapshots and strict offline replay.
- **WHO:** infrastructure provides lifecycle/storage/routing; future providers
  supply allowed origins and generic capture interactions.
- **WHY:** pin an authorized website runtime without depending on a changing
  origin or Chromium disk cache.
- **HOW:** isolated browser leases, read-only policy, SHA-256 blobs, atomic
  manifests, verified mount-before-navigation and fail-closed routing.
