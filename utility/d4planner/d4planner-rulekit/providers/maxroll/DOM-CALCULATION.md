# Independent DOM Calculation Path

`src/dom-calculation` loads Native JSON into the frozen Maxroll Planner and returns
Character Stats **display values**, precision and coverage. It never instantiates,
modifies, or falls back to the CDP calculation provider. Existing application/provider
selection is unchanged; use this explicit entry point.

## One input format

Accept only `maxroll-native-build-export/v1`, `format: MAXROLL_NATIVE_STATE`, as
exported by PR175's Native JSON Export, with a valid native-state SHA256. Canonical
`d4-build/v1`, bare internal states and implicit conversion are rejected. Preserve
all native fields/options/variants. Internal loader fixtures with hidden/inherited
profiles may be normalized by Maxroll Save; they are rejected if they do not round-trip
exactly. No fields are discarded to force acceptance.

```js
const { DomCalculationPath } = require('./src/dom-calculation');
const runtime = new DomCalculationPath({ snapshotRoot, snapshotId, manifestSha256, executablePath });
try {
  const result = await runtime.evaluate(nativeBuildJson);
} finally { await runtime.close(); }
```

```sh
node scripts/dom-evaluate.js /private/config.json /private/native-build.json /private/result.json
```

Config: constructor fields above; optional `timeoutMs` (1000–120000, default 30000)
and `quietMs` (100–2000, default 400). Timeout starts with the acquired browser lease;
cold startup is timed separately. Choose an existing Calculation or UI snapshot.
There is no capture/signing/registry promotion/release. Identity verifies the selected
artifact; it is not a formula-compatibility verdict.

## Freshness and completion

1. Verify manifest and resource integrity, including actual loaded replay bytes.
   Recheck the selected artifact on each package load.
2. Acquire a new isolated context for **every** Evaluate. Browser process can stay
   warm; no old document, local storage, saved view position or metric cache survives.
3. Replay the supplied state at the captured native loader URL; require exactly one
   request. Other resources use existing offline-strict replay, with service workers
   blocked and uncaptured network requests aborted.
4. Use My Profiles → Save to read the native serializer's POST locally. Require the
   full state's fingerprint to equal the requested JSON. Respond locally with 409;
   no cloud save occurs and no successful save response is fabricated.
5. Open Stats groups; require expected Level and every applicable non-collapsible row.
   Wait for an unchanged complete vector over the quiet window; read it again after
   the barrier. Reject late change, runtime error, missing required resource, input
   mismatch or timeout. Destroy the context on success or failure.

Only standard DOM APIs, captured JSON catalogs and native loader/Save boundaries are
used. No breakpoint, minified variable, React internals or observation CDP session.
Playwright's normal browser transport is not a calculation observer.

Completion is `FRESH_DOCUMENT_NATIVE_READBACK_DOM_SETTLED`, **not** engine/epoch
attestation. A future asynchronous engine may need a documented completion interface.
No old result is returned on failure. Concurrent calls fail with `DOM_BUSY`.

Known ads/consent/analytics/fonts, anonymous account lookups, and image requests
under the captured asset origin can be missing (icons are not needed for numeric Stats);
requests still abort and remain in provenance. Missing calculation/catalog/Planner
resources fail. This optional list never enables network fallback.

## Metric contract

| Status | Meaning |
|---|---|
| DISPLAY_OBSERVED | Unique section+label row observed; percentages normalized /100. |
| NOT_RENDERED | Applicable collapsible row absent; **no zero inferred**. |
| NOT_APPLICABLE | Snapshot catalog excludes this ID for the active class. |

`rawValue` is always null. `DISPLAY_QUANTIZED` reports display resolution and conservative
half-step bounds, not reconstructed raw precision. Unknown/ambiguous labels, duplicate
rows, unsupported numbers, unresolved labels and missing mandatory rows fail closed.
English `data.enus.json` is required. Class/resource names come from snapshot data.

Default `metrics` are the existing Rule Kit catalog's 50 IDs; `additionalMetrics`
contains other visible class-specific IDs. These 50 IDs are not a universal class
schema. Optional `metricIds` selects explicit catalog IDs. Exact raw values and
calculation-context attestation remain separate CDP capabilities; no fallback exists.

## Tests and benchmark

```sh
node --test tests/unit/dom-calculation.test.js
MAXROLL_DOM_REAL_CONFIG=/private/benchmark-config.json node --test tests/real/dom-calculation.test.js
node scripts/dom-benchmark.js /private/benchmark-config.json
```

Benchmark config adds `buildFiles: {A, BItem, BEffect}` (Native JSON paths), `oracleFile`,
`outputDirectory` and optional `ui: {snapshotRoot,snapshotId,manifestSha256}`. Optional
`Sorcerer`/`RogueZero` build files exercise class-specific/missing rows. Oracle JSON is
keyed by build label: arrays of `{section,rows:[{name,value}]}`, frozen from a separate
original-Planner execution. Never generate expected from the implementation under test.

The benchmark runs 5 cold, 30 warm, 30 alternating item/effect changes and 10 A→B→A
cycles: 95 Evaluate calls. Warm means warm browser, **fresh context + native load/readback**;
it is not an in-page incremental engine benchmark. Failures/timeouts are retained.

Report min/p50/p95/max (nearest rank) for end-to-end, build apply, calculation completion
wait and DOM extraction, plus CPU/RAM. Build apply includes mount/navigation/Save
readback; engine calculation overlaps this phase. Calculation timing is subsequent
DOM completion wait, **not exclusive engine execution time**. End-to-end includes
context cleanup and cold startup, but excludes process shutdown.

Linux resource sampler reads `/proc` every 100ms for Node + observed descendants. CPU
is sampled user+system ticks, 100%=one core; short-lived processes can be missed. RAM
is peak sampled sum RSS, shared pages counted per process, not PSS. Sampling overhead
is included. Windows needs a native sampler; script rejects unsupported platforms.

Benchmark the CDP path unchanged. A pin/observation failure on a new snapshot is a
failed baseline attempt, not a latency/formula comparison. Keep identity and coverage
explicit. Keep generated reports, input JSON and screenshots outside the repository.
