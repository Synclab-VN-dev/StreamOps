# Persistent Chromium browser infrastructure

Provider-agnostic Node.js infrastructure for one managed headless Chromium
process and disposable `BrowserContext`/`Page` leases. It belongs to D4 Rule
Kit infrastructure but contains no Diablo IV or provider behavior.

## Boundary

The package owns browser launch, shutdown, explicit restart, context capacity,
FIFO queueing, acquisition timeout/cancellation, lease expiry, lazy CDP
sessions, crash invalidation, safe diagnostics, status and counters.

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
- `withLease()` releases in `finally`, including consumer exceptions.
- Browser disconnect invalidates all outstanding leases and queued requests.
  Recovery is explicit through `restart()`; caller/provider logic is not
  replayed.
- Restart invalidates old handles before launching the replacement process.
- Closing a context outside the lease API invalidates that lease.

Stable error codes are `NOT_RUNNING`, `CAPACITY_EXCEEDED`, `QUEUE_TIMEOUT`,
`LEASE_EXPIRED`, `BROWSER_DISCONNECTED`, `CANCELLED`, and `INVALID_CONFIG`.

`getStatus()` returns lifecycle state, Chromium PID when CDP exposes it, active
leases, queue depth, restart count and uptime. `getMetrics()` returns actual
launch/lease/crash/timeout/cancellation counters and timings. RSS is not
reported because this implementation does not measure it reliably.

Logger events contain only component/event/state and resource identifiers such
as lease ID. They never include page URL, content, cookies, headers or tokens.
Consumer logger failures are isolated as best-effort diagnostics and cannot
change lifecycle state or leak ownership of the browser process.

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
