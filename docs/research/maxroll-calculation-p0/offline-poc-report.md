# Maxroll Offline and Local Calculation Runtime PoC

## Verdict

| Level | Status | Actual |
|---|---|---|
| L1 Warm Offline | **PASS** | 50/50 raw, 34/50 display, three A→B→A cycles, exact online parity |
| L2 Cold Offline — Chromium disk cache only | **BLOCKED** | Fresh offline process could not retrieve the planner document from disk cache; app did not boot, 0/50 |
| L2 Cold Offline — ephemeral local archive | **PASS_BOUNDED_POC** | Fresh process calculated three A→B→A cycles from a RAM-only first-party archive; 50/50 raw and online parity |
| L3 Standalone Local Provider | **PASS_BOUNDED_POC** | Separately provisioned temporary package; independent Python CLI processes calculated A→B→A fully offline |

This work reuses the verified online PoC at
`76c852dbc93585686859e420acd75e1a38f114f6`. It does not re-run production
tests or implement Diablo IV formulas.

## Runtime identity

- Maxroll patch: `3.2.1.73552`.
- Chrome for Testing: `153.0.8010.12`.
- Playwright Core: `1.64.1`.
- Active calculation asset: `/assets/export-DOjdL1l3.js`.
- Asset length: 3,374,547 bytes.
- Asset SHA-256:
  `e796b92751d0b07be8b10eed705727467e23ba0d99eb088e87de88942c57a1f4`.
- No Maxroll-owned response body or bundle is committed.

## L1 — warm offline

After loading the fixture online, the harness activated Playwright offline
mode, verified a cache-busting fetch failed, and performed three UI-supported
B→A cycles. All six offline calculations returned the 50 catalog IDs. A and B
each had one normalized output; every rollback restored A exactly. Fire
Resistance changed from raw/display `22`/`22` to `2822`/`2,822` and back.

Zero remote responses completed during calculation phases. The single response
that completed after offline activation was an already in-flight advertising
script, 28 ms after activation and before any calculation phase.

## L2a — disk-cache-only cold start

The harness seeded a temporary persistent Chromium profile online, closed it,
then launched a fresh process with offline mode enabled before navigation.
The source document advertised `cache-control: public, max-age=300`, while the
calculation asset and game-data JSON advertised one-year caching. Nevertheless,
Chromium did not serve the main planner document in this cold process:

- `navigator.onLine === false`;
- zero remote responses completed;
- `https://maxroll.gg/d4/planner/1g1any0x` failed with
  `ERR_INTERNET_DISCONNECTED`;
- the app did not boot and calculation was not attempted;
- coverage: 0/50.

An earlier diagnostic used Playwright routing, which disables HTTP cache. The
final harness removed that confounder before recording this result. Disk cache
alone is therefore not a usable local-runtime contract.

## L2b — ephemeral local archive

To test runtime feasibility without committing proprietary assets, the harness:

1. loaded the approved planner read-only and captured first-party GET responses
   into process memory only;
2. blocked all non-read requests;
3. closed the online browser completely;
4. launched a fresh Chromium process and enabled offline mode before navigation;
5. locally fulfilled archived requests and aborted every miss—no request was
   allowed to continue to the network;
6. created the unsaved JSON fixture through supported UI actions;
7. calculated A→B→A for three cycles and cleared the archive after the run.

The bounded archive contained 354 entries / 59,025,550 bytes. It is a working
superset, not the minimum calculation dependency set. Forty-two misses were
aborted, predominantly optional WebP/frame assets and Google Fonts. The app and
calculation still passed:

- fresh browser process: yes;
- archive created before the cold process and never written to disk: yes;
- explicit unarchived cache-busting fetch: failed as expected;
- outbound responses during cold startup/calculation: zero;
- cycles: three;
- runtime raw coverage: 50/50 every snapshot;
- display coverage: 34/50 every snapshot;
- A unique outputs: one; B unique outputs: one;
- A online/local parity: 50/50; B online/local parity: 50/50;
- A rollback: exact.

`navigator.onLine` reports `true` on the route-fulfilled document despite the
context being placed offline. This browser API value is recorded, not hidden.
The outbound boundary is established independently: every HTTP request was
either fulfilled from RAM or aborted, no route called `continue()`, the
unarchived probe failed, and zero outbound responses completed.

## L3 — standalone assessment

Option A, local browser runtime, passes as a bounded PoC. The provisioning
harness wrote a versioned runtime package to an explicit `/tmp` directory. The
provisioning browser then exited. Three independent commands consumed that
package:

```text
python local_maxroll_poc.py --runtime-dir <temporary-package> --input build-a.json --output stats-a-local.json
python local_maxroll_poc.py --runtime-dir <temporary-package> --input build-b.json --output stats-b-local.json
python local_maxroll_poc.py --runtime-dir <temporary-package> --input build-a.json --output stats-a2-local.json
```

Each process put Chromium offline before navigation and used a fail-closed local
resolver: an HTTP request was either fulfilled from the integrity-checked
package or aborted; no fallback network path exists. Each run also required an
unarchived cache-busting request to fail.

Results:

- runtime package manifest SHA-256:
  `b95e64628ad00014cb0bc0a4f1b85c16af5fde93962fcdda1e1e7a487dbf6a11`;
- 354 URL entries, 352 unique blobs, 59,025,550 logical bytes;
- A1: 50/50 raw, 34/50 display, Fire Resistance `22`;
- B: 50/50 raw, 34/50 display, Fire Resistance `2822`;
- A2: 50/50 raw, 34/50 display, Fire Resistance `22`;
- normalized A online/local/A2 parity: 50/50, exact;
- normalized B online/local parity: 50/50, exact;
- temporary package cleanup: PASS.

No package asset is committed. Therefore this is a local provider PoC, not a
redistributable or production-ready runtime. Reproduction requires a separate
authorized provisioning phase for the same Maxroll patch.

Option B, Node.js, is BLOCKED. The observed raw values are captured from a
render-time closure inside the browser/React module graph. No supported exported
calculation function accepting build JSON was identified. Running minified site
code directly under Node would require reconstructing browser/module state and
would not be a stable supported interface.

## Dependency findings

- Required for the proven calculation: calculation bundle, game-data state,
  in-memory build state, and the current browser/React execution context.
- Required for the current JSON adapter: planner UI, locale/item identity data,
  and DOM events.
- Reference-only: published profile load response; A/B are subsequently built
  in an unsaved New Profile.
- UI-only for this path: missed item/frame images and fonts.
- Optional: advertising, consent, telemetry and analytics.
- Web Workers: not observed in the bounded instrumented flow.
- WASM: no `.wasm` URL or `application/wasm` response observed; embedded WASM
  was not ruled out.
- Remote calculation endpoint: not required and none was observed.

See `runtime-dependency-inventory.json` for classifications and provenance.

## Performance

| Measurement | Warm offline | Ephemeral local cold browser |
|---|---:|---:|
| Browser launch | 166.10 ms | 150.59 ms |
| Initial load | 7,613.15 ms online warm load | 7,509.64 ms local archive load |
| Calculation min | 1,333.95 ms | 1,258.44 ms |
| Calculation mean | 1,379.85 ms | 1,368.90 ms |
| Calculation max | 1,425.96 ms | 1,590.22 ms |
| Raw coverage | 50/50 | 50/50 |
| Online parity | 50/50 A and B | 50/50 A and B |

L1 additionally records CDP `TaskDuration` and JS heap proxies. These are not
host-wide CPU or total-process RSS measurements.

## Safety

- Published build mutation: false.
- Save/Publish: not invoked.
- Cookies, tokens, session/local storage: not read.
- Non-read requests: blocked by the harness.
- Proprietary response bodies: RAM-only during the successful L2 run, cleared
  afterward, not committed.
- Production source and CI: unchanged/not run.
- PR/merge/deploy: none.

## Remaining WHAT / WHO / WHY / HOW

| WHAT | WHO | WHY | HOW |
|---|---|---|---|
| Define production package policy | Owner + Maxroll | The PoC package is temporary and not redistributable by default | Define permitted retention, distribution, patch lifecycle and integrity/signing policy |
| Generalize the standalone Python CLI | Dev F after provider scope | Current input mapping is intentionally bounded to the one-item A/B schema | Add supported input groups incrementally while preserving UI/runtime provenance and fail-closed outbound behavior |
| Minimize the 354-entry superset | Dev F | 59 MB proves feasibility but not the smallest provider | Remove dependency groups under fail-closed outbound routing; keep a group only when boot/calculation/parity requires it |
| Define a supported calculation entry point | Maxroll + Owner | CDP closure capture is version-fragile | Prefer a documented browser module/API boundary over Node reconstruction of private React state |

The next gate is not formula research. It is a packaging/interface and input-
coverage decision for the already-proven Maxroll local browser calculation
runtime.
