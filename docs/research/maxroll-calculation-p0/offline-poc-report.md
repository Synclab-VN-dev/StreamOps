# Maxroll Offline and Local Calculation Runtime PoC

## L1 checkpoint verdict

**L1_WARM_OFFLINE_PASS.** After the bounded fixture was loaded online, Maxroll
continued to recalculate all 50 raw Character Stats while Chromium was offline.

| Level | Status | Coverage/parity |
|---|---|---|
| L1 Warm Offline | PASS | 50/50 raw, 34/50 display, A and B both match the committed online outputs |
| L2 Cold Offline | NOT_RUN_AT_L1_CHECKPOINT | Pending dependency-minimization test |
| L3 Standalone Local | NOT_RUN_AT_L1_CHECKPOINT | Pending permission and runtime-interface assessment |

This checkpoint reuses commit
`76c852dbc93585686859e420acd75e1a38f114f6`; the already-PASS online tests
were not repeated.

## Runtime identity

- Maxroll patch: `3.2.1.73552`.
- Chrome for Testing: `153.0.8010.12`.
- Playwright Core: `1.64.1`.
- Active calculation asset: `/assets/export-DOjdL1l3.js`.
- Asset length: 3,374,547 bytes.
- Asset SHA-256:
  `e796b92751d0b07be8b10eed705727467e23ba0d99eb088e87de88942c57a1f4`.
- The asset was hashed in memory and was not retained or committed.

## Warm-offline procedure and result

One isolated Chromium context was used:

1. Load the approved planner URL online.
2. Create the unsaved local Rogue L50 fixture and calculate A.
3. Call Playwright `context.setOffline(true)`.
4. Confirm `navigator.onLine === false` and perform a cache-busting remote
   fetch; it failed with `TypeError: Failed to fetch`.
5. Apply `Dampening / Of Dampening` through the UI to calculate B.
6. Remove it to return to A.
7. Repeat B -> A three times without reconnecting.

All seven snapshots contained the 50 catalog IDs and 50 runtime raw values.
The blank fixture rendered 34 display values, matching the online PoC.

| State | Fire Resistance raw/display | Normalized output |
|---|---:|---|
| A online warmup | `22` / `22` | Same as committed online A |
| B1/B2/B3 offline | `2822` / `2,822` | One unique B hash; same as committed online B |
| A1/A2/A3 offline | `22` / `22` | One unique A hash; exact rollback to warmup A |

No saved output was used as a calculation input. The committed online outputs
were read only after capture for parity comparison.

## Network evidence

- Six requests were attempted after offline activation; all six failed or were
  blocked.
- The explicit cache-busting request failed with
  `ERR_INTERNET_DISCONNECTED`/`Failed to fetch`.
- Two item-frame image requests failed during A1, but calculation still
  returned 50 raw values.
- Analytics POSTs were blocked by the existing non-read request guard.
- One already in-flight Primis advertising script reported HTTP 200 about
  28 ms after offline activation, before the explicit probe and before any
  offline calculation phase.
- **Zero remote responses completed during B1/A1/B2/A2/B3/A3.**

The one late ad response is retained in evidence rather than silently removed.
It does not correlate with a calculation phase or supply Character Stats.

## Performance

| Measurement | Actual |
|---|---:|
| Browser launch | 166.10 ms |
| Online warm load | 7,613.15 ms |
| Offline calculation min/mean/median/max | 1,333.95 / 1,379.85 / 1,381.83 / 1,425.96 ms |
| CDP TaskDuration delta min/mean/max | 0.8050 / 0.8413 / 0.8738 s |
| CDP JS heap observed range | 128,915,884–159,673,260 bytes |

`TaskDuration` and `JSHeapUsedSize` are browser-runtime proxies, not host-wide
CPU utilization or total Chromium RSS.

## Dependency findings at L1

The exact calculation breakpoint executes in `export-DOjdL1l3.js`. Profile and
item state are required. No remote calculation response is required after the
runtime is warm. Game-data JSON, locale data, planner/UI modules, workers, WASM,
and the minimum cold-start dependency set remain unresolved; they are tracked
without inference in `runtime-dependency-inventory.json`.

Failed item-frame image requests prove those resources are UI-only for this
calculation path. Advertising, consent, and analytics resources are optional.

## Diagnostic corrections

The first harness invocation stopped before launching Chromium because direct
Node execution lacked `NODE_PATH`. Reusing the baseline dependency path
`/tmp/issue106-f4.Z3XkXq/node_modules` resolved it.

The next run initially used an overly strict assertion that no response of any
kind could finish after offline activation. Evidence showed one pre-existing ad
response outside calculation. The verifier was corrected to fail on remote
responses correlated with calculation phases while retaining every post-offline
response in the log. The final run then passed with zero calculation-phase
responses.

## Safety

- Published planner/build mutation: false.
- Save/Publish: not invoked.
- Cookies, tokens, storage, request headers/bodies: not read.
- Proprietary bundle retained or committed: false.
- Production code and CI: unchanged/not run.
- PR/merge/deploy: none.

## Next WHAT / WHO / WHY / HOW

| WHAT | WHO | WHY | HOW |
|---|---|---|---|
| Determine L2 minimum assets | Dev F | Warm execution does not prove a new browser can start offline | Record only resource identities/fingerprints, build a localhost test boundary, block all outbound traffic before navigation, and fail if any required remote request succeeds |
| Clarify independent asset-execution permission | Owner/Maxroll | Prior permission proves scoped browser automation, not necessarily redistribution or standalone execution | Confirm that temporary local serving/execution of Maxroll-owned assets is allowed; do not commit the bundles |
| Evaluate L3 Node compatibility | Dev F after permission | Current flow depends on browser/React state | Identify a supported calculation entry point and its browser globals; run only if allowed and do not rewrite formulas |
