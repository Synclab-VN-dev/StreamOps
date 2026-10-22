# Persistent Chromium browser infrastructure

Provider-agnostic Node.js infrastructure for one managed headless Chromium
process, disposable `BrowserContext`/`Page` leases, and immutable local web
snapshots. It belongs to D4 Rule Kit infrastructure but contains no Diablo IV
or provider behavior.

## Boundary

The package owns browser launch, shutdown, explicit restart, context capacity,
FIFO queueing, acquisition timeout/cancellation, lease expiry, lazy CDP
sessions, crash invalidation, safe diagnostics, status and counters. Its
snapshot capability owns read-only resource capture, content-addressed local
storage, integrity verification and strict offline replay.

It does **not** own URLs, selectors, build/profile mutations, calculation
semantics, provider retries, Character Stats, transport/IPC, or Python adapter
code. A future provider may depend on this package; this package must never
depend on a provider.

## Requirements

- Linux or another Playwright-supported OS.
- Node.js 20 or newer; local/CI baseline is Node 22.
- `playwright-core@1.64.1` and its pinned Chromium revision.
- The executable is supplied with `executablePath`, or installed in the
  Playwright cache so `playwright-core` can resolve it.

Install dependencies and Chromium when not already available:

```bash
npm ci --prefix utility/d4-rulekit/browser-infra
npx --prefix utility/d4-rulekit/browser-infra playwright-core install chromium
```

Linux F reuses the existing local Playwright Core and Chromium by setting
`NODE_PATH` and `BROWSER_INFRA_CHROMIUM_PATH`; no re-download is necessary.

## API example

```js
const { BrowserInfrastructure } = require('./src');

const browsers = new BrowserInfrastructure({
  executablePath: process.env.BROWSER_INFRA_CHROMIUM_PATH,
  maxContexts: 2,
  maxQueue: 16,
  acquireTimeoutMs: 5_000,
  leaseTimeoutMs: 60_000,
  cleanupTimeoutMs: 5_000,
});

await browsers.start();
try {
  const title = await browsers.withLease({}, async lease => {
    await lease.page.goto('http://127.0.0.1:8080/fixture');
    const cdp = await lease.createCDPSession();
    await cdp.send('Runtime.enable');
    return lease.page.title();
  });
  console.log(title);
} finally {
  await browsers.stop();
}
```

## Lifecycle contract

- `start()` and `stop()` are idempotent and serialized.
- One Chromium process is kept alive across normal lease releases.
- Every successful lease owns a new context and page; release is idempotent.
- CDP creation is lazy and cached per lease.
- Capacity is `active contexts + contexts being created`; waiters use a bounded
  FIFO queue.
- One acquisition deadline covers queue wait plus context/page creation. Timeout
  or abort creates no hidden retry; a late resource is closed before its
  reservation is returned.
- Because Playwright does not expose cancellation for an in-flight
  `newContext()`/`newPage()`, a timed-out or cancelled creation automatically
  recycles that browser generation. Existing leases and queued acquisitions
  fail closed; provider callbacks are never replayed. New acquisitions are
  accepted after the replacement browser reaches `running`.
- `withLease()` releases in `finally`, including consumer exceptions.
- Browser disconnect invalidates all outstanding leases and queued requests.
  Recovery is explicit through `restart()`; caller/provider logic is not
  replayed.
- Restart invalidates old handles before launching the replacement process.
- Closing a context outside the lease API invalidates that lease.
- Context cleanup must resolve within `cleanupTimeoutMs` before its capacity is
  returned. A rejected or timed-out close yields `CLEANUP_FAILED` and starts a
  controlled browser recycle. If browser shutdown also cannot be confirmed,
  state remains `degraded`, no replacement process is launched, and a bounded
  `restart()` is available after the underlying close condition is resolved.

Stable error codes are `NOT_RUNNING`, `CAPACITY_EXCEEDED`, `QUEUE_TIMEOUT`,
`LEASE_EXPIRED`, `BROWSER_DISCONNECTED`, `CLEANUP_FAILED`, `CANCELLED`, and
`INVALID_CONFIG`.

`getStatus()` returns lifecycle state, Chromium PID when CDP exposes it, active
leases, queue depth, restart count and uptime. `getMetrics()` returns actual
launch/lease/crash/timeout/cancellation counters and timings. RSS is not
reported because this implementation does not measure it reliably.

Logger events contain only component/event/state and resource identifiers such
as lease ID. They never include page URL, content, cookies, headers or tokens.
Consumer logger failures are isolated as best-effort diagnostics and cannot
change lifecycle state or leak ownership of the browser process.

## Generic web snapshots

The snapshot lifecycle is composed with, but independent from, the browser
lifecycle:

```text
WebSnapshotManager
  |-- BrowserInfrastructure (capture lease only)
  |-- SnapshotStore
  |     `-- FileSystemSnapshotStore (immutable manifest + SHA-256 blobs)
  `-- NetworkInterceptor
        `-- SnapshotMount (offline-strict routing on one lease)
```

`WebSnapshotManager` exposes `capture`, `save`, `load`, `list`, `verify`, and
`mount`. `SnapshotMount` exposes idempotent `unmount` and replay diagnostics.
The manager depends on the store contract, so another persistence backend can
replace `FileSystemSnapshotStore` without changing capture or replay callers.

```js
const {
  BrowserInfrastructure,
  FileSystemSnapshotStore,
  WebSnapshotManager,
} = require('./src');

const browser = new BrowserInfrastructure({
  executablePath: process.env.BROWSER_INFRA_CHROMIUM_PATH,
  contextOptions: { serviceWorkers: 'block' },
});
const snapshots = new WebSnapshotManager({
  browser,
  store: new FileSystemSnapshotStore({ rootDir: '/var/tmp/web-snapshots' }),
});

await browser.start();
const draft = await snapshots.capture({
  snapshotId: 'example-v1',
  site: 'example',
  version: 'v1',
  url: 'https://example.test/app',
  allowedOrigins: ['https://example.test'],
  capturePolicy: {
    // Optional generic decision: default | exclude | redact | include-sensitive.
    responsePolicy: response => response.contentType === 'application/octet-stream'
      ? { action: 'exclude' }
      : { action: 'default' },
  },
  interact: async ({ page }) => page.click('#load-lazy-content'),
});
await snapshots.save(draft);

// A second site or a new version is a distinct immutable package.
await snapshots.save(await snapshots.capture({
  snapshotId: 'another-site-v2',
  site: 'another-site',
  version: 'v2',
  url: 'https://assets.example.test/dashboard',
  allowedOrigins: ['https://assets.example.test'],
}));
console.log(await snapshots.list({ site: 'another-site' }));

await browser.withLease({}, async lease => {
  const mounted = await snapshots.mount(lease, 'example-v1');
  await lease.page.goto('https://example.test/app');
  console.log(mounted.getDiagnostics());
  await mounted.unmount();
});
```

Capture defaults to credential-free `GET`/`HEAD` requests on explicitly
allowlisted HTTP(S) origins. Authorization/cookie headers, sensitive query
parameters, unsafe response headers, authenticated sessions, write methods,
WebSockets and service workers are excluded or blocked. These defensive
browser-global blocks remain for the disposable lease lifetime; release the
lease after snapshot use. Consumers may provide
generic interaction and resource-policy callbacks; the infrastructure has no
site selectors or domain knowledge.

The default response policy recursively replaces values for common sensitive
JSON keys (tokens, secrets and a small generic PII key set) with
`[REDACTED]`. A redirect `Location` containing a sensitive query/fragment key
fails capture with `SENSITIVE_RESPONSE`. A caller may explicitly return
`exclude`, supply a replacement body/headers with `redact`, or deliberately
opt in with `include-sensitive`. The latter is an explicit authorization and
must not be used for shareable snapshots. Generic filtering cannot identify
all PII, secrets embedded in arbitrary HTML/binary bodies, or site-specific
identifiers; callers must add `sensitiveJsonFields`,
`sensitiveResponseNames`, or a response policy for their data contract.

Saved packages use `web-snapshot/v1`, one immutable directory per snapshot ID,
content-addressed SHA-256 blobs, and a `manifest.sha256` anchor. Save writes the
manifest, anchor and blobs in a temporary directory followed by an atomic
rename. Duplicate IDs, modified metadata, corrupt manifests, missing/tampered
blobs, limit violations and partial writes fail with typed snapshot errors.
The co-located anchor detects accidental corruption and a manifest-only edit;
it is not a signature and cannot protect against an attacker who can rewrite
both the package and its anchor. A signed/external trust registry is required
for that threat model. `verify()` returns `manifestSha256` so an authorized
consumer can pin it in an independent registry. Captured website assets are runtime data and must not be
committed to Git.

Replay is `offline-strict`: after routes are installed the complete browser
context is forced transport-offline, so page, Dedicated Worker, WebSocket and
Service Worker traffic cannot fall through to the network. Every HTTP request
must additionally resolve from the verified package and a miss is aborted,
never continued to the Internet. A context with an already-running Service
Worker is rejected; `unmount()` removes routes and restores online transport.
Redirect
metadata is retained exactly in the manifest. Chromium does not re-intercept a
redirect follow-up emitted by a route-fulfilled 3xx response, so replay uses a
controlled local redirect transition for documents and resolves subresource
redirects to their captured target. This prevents network escape while
preserving the captured redirect chain as evidence. Use
`contextOptions: { serviceWorkers: 'block' }`; the mount also installs a
defensive registration block. A fresh Chromium process/profile is supported;
browser disk cache is not part of the contract.

Default limits are 100 snapshots per store, 5,000 resources per snapshot,
32 MiB per resource and 256 MiB total. Capture additionally has a 30-second
default timeout. Configure lower limits for untrusted or constrained jobs.

## Runtime cost

Default architecture is one Chromium process, up to two active contexts and a
bounded queue. Each lease creates and closes one context/page; the browser is
not relaunched per request. Context creation cost and memory depend on the
consumer page and must be measured by that provider. This package does not
invent memory/RSS metrics.

## Automated verification

```bash
cd utility/d4-rulekit/browser-infra
NODE_PATH=/path/to/node_modules \
BROWSER_INFRA_CHROMIUM_PATH=/path/to/chrome \
npm test
```

Unit tests use deterministic fakes. E2E tests launch real headless Chromium and
use only an ephemeral HTTP server on `127.0.0.1`; no provider or Internet is
required. Tests emit ignored local `artifacts/{unit,e2e}.{json,junit.xml}`.
CI uploads the same evidence even on failure.

The Python Rule Kit may receive an IPC/transport adapter in a later ticket.
This issue intentionally defines no Python-to-Node transport.
