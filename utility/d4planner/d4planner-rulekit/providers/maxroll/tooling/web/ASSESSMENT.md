# #173 — HTTP snapshot replay assessment

## Current → proposed → alternatives → impact → risks

**Current:** Rule Kit Browser Infrastructure owns Chromium leases, snapshot verification and interception; Maxroll Provider owns its codec/runtime adapter. The private editor prototype opens the original origin inside Playwright and fulfills requests from the frozen package. That interception cannot accompany Android Chrome. The application API contract remains independent of this tooling. Baseline: integration branch `docs/138-d4planner-r1-contract`, commit `1cea452f6450d1a9a2983c6b5c22b06b1b9f9a52` (PR #145). The earlier remote-desktop branch/PR #174 is not a dependency.

**Proposed:** add a transport adapter in `providers/maxroll/tooling/web/`. Reuse `FileSystemSnapshotStore.verify/loadPackage`, the interceptor's exact `resourceKey(method,url)` and the existing compatibility catalog loader. Serve those verified bytes over Node's built-in HTTP server. Rewrite the three captured origins to localhost namespaces in HTML/JS/CSS; inject `client.js` before captured scripts for dynamically constructed fetch/XHR destinations. No additional registry, snapshot store, browser worker or calculation implementation. Compatibility is resolved inside Rule Kit before the port opens.

**Alternatives:** a plain static file server cannot replay URL/method/query keyed responses, API origins or dynamic browser calls. A service worker cannot protect the first document load and adds lifecycle/state complexity. VNC is outside the owner's requested architecture. A second capture/version is neither necessary for tested interactions nor permitted as an implicit repair for missing sprites.

**User impact:** Chrome executes the original Planner on the device; SSH carries ordinary HTTP traffic. New Profile, level, equipment, skills and paragon work in desktop Chromium and mobile emulation. Missing artwork remains visible as an incomplete UI; this is not a complete redistribution of Maxroll. Native Save returns a local 405; export and the empty-socket canonical-schema issue remain outside this checkpoint. No public API, FE/HUD, BE, canonical schema or snapshot distribution policy changes.

**Risks:** frozen UI expects a production hostname, uses dynamic code evaluation, contains third-party fonts/ads, and was not captured as a complete offline application. `unsafe-inline` and `unsafe-eval` are needed by its trusted scripts; the CSP is a network boundary, not a general sandbox for arbitrary malicious HTML. Use a dedicated loopback origin and the verified private package only. No assertion of redistribution rights is made. Actual Android Chrome/device performance and touch remain NOT_RUN until Owner testing.

## Read-only snapshot audit

| Dimension | Evidence / result |
|---|---|
| Identity | `maxroll-20261023T034150Z`, game patch `3.2.1.73552` |
| Manifest SHA-256 | `638a283b8aa0cb822a35176d9d41c8d1751fb6f962ca0a2f7feaa20f1ef39e54` |
| Engine SHA-256 | `891c1f82717c50e598450575068394c6d2fe1c8d26de26f2eeed028d028997db` (`/assets/export-D12aM6KT.js`) |
| Entry | captured `https://maxroll.gg/d4/planner/1g1any0x` |
| Store | 365 resources / 363 content-addressed blobs / 56,412,954 bytes; 2 HTML, 139 JS, 11 CSS, 8 JSON, 183 WebP resources |
| Integrity | existing store verification checks manifest/blob digests; package is not modified |
| Compatibility | exact ID + manifest binding must exist in the existing Rule Kit catalog; fail-closed before listen |
| UI completeness | data/engine/profile and route manifest are present; sprites and some optional external resources are absent |
| Provenance | existing local capture and #173 audit; no new capture/download/version merge performed |
| Distribution authorization | not established by integrity or compatibility; no snapshot bytes/screenshots/native payloads published in Git/PR/Actions |

Captured origins: `maxroll.gg`, `assets-ng.maxroll.gg`, `planners.maxroll.gg`. The frozen UI constructs `planners-test.maxroll.gg` on non-production hostnames; `client.js` maps that spelling to the same captured planner origin. It never connects to either host. The captured React router `__manifest` query is replayed exactly; arbitrary uncaptured route queries return diagnostics/404.

Known missing UI resources under `/d4-tools/static/media/`: `items.5c30e3bb.webp`, `skills.1e683ef9.webp`, `aspects.80aeefac.webp`, `empty.42d63759.webp`, `charm-slot.82a3cf12.webp`, `locked-charm-slot.09f479df.webp`. The tested desktop/mobile equipment/skill/paragon controls work despite absent sprite sheets; visual completeness is BLOCKED by capture coverage. A future supplemental capture would require proof of the same version and permitted capture conditions; this change does not attempt it.

Authentication (`users/whoami`) is not captured and returns 404. Anonymous editing works. Captured Set-Cookie, CORS, cache and authentication headers are not forwarded. Only MIME/status and validated captured redirects are used. Build state lives in the native client structures/storage; Save serializes `profiles/items/skillTree/paragon` into the native POST payload. That payload is not the canonical Rule Kit schema. The test inspects it to establish actual editing behavior without changing the codec or persisting it on the server.

## Client network boundary

- Server binds only `127.0.0.1`; validates localhost Host, rejects cross-site requests and requires same-origin POST. Port preflight and final atomic bind fail on conflicts.
- Main UI runs in an iframe restricted by both parent `frame-src 'self'` and child sandbox. Top navigation/popups are not permitted. Direct browser navigation to captured HTML is redirected to the shell.
- CSP limits scripts/styles/fonts/images/connect/frame traffic to self (plus data/blob images and data fonts). Workers, objects and manifests are disabled. External DOM/CSS URLs not rewritten are blocked on the **client**, independently of Linux F's network.
- Fetch/XHR map captured origins; unknown external fetches throw. WebSocket, EventSource, workers, service-worker registration, WebRTC, beacons and popups are disabled. No production POST fallback exists.
- Missing resources return explicit 404; other writes return 405. Diagnostics contain bounded URL paths and counts, without queries, cookies or request bodies. Local reports are bounded to 2 KiB.
- Fonts/analytics can still appear as **blocked attempts** in developer tools. This is not evidence of successful external traffic. Browser checks assert all such attempts fail with CSP and no external responses/completions occur.
- Loopback HTTP is a potentially trustworthy origin in Chrome; the editor deliberately does not depend on service workers. See [MDN secure contexts](https://developer.mozilla.org/en-US/docs/Web/Security/Defenses/Secure_Contexts) and [CSP reference](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy).

## Component interaction flow

Paths below are real files, relative to `d4planner-rulekit`. Solid arrows are calls; dashed arrows are returns.

```mermaid
sequenceDiagram
    actor Owner as Android Chrome / Termux
    participant CLI as providers/maxroll/tooling/web/cli.py
    participant HTTP as providers/maxroll/tooling/web/server.js
    participant Compat as snapshot-management/compatibility/loader.js
    participant Store as browser-infra/src/snapshot/store.js
    participant Key as browser-infra/src/snapshot/interceptor.js
    participant Client as providers/maxroll/tooling/web/client.js
    Owner->>CLI: 1. start (on Linux F)
    CLI->>HTTP: 2. spawn Node with private config
    HTTP->>Compat: 3. loadCatalog; exact configured binding
    Compat-->>HTTP: 4. compatible definition or rejection
    HTTP->>Store: 5. verify / loadPackage
    Store-->>HTTP: 6. verified manifest + resource map
    HTTP-->>CLI: 7. loopback listening / readiness
    CLI-->>Owner: 8. local URL + SSH tunnel command
    Owner->>HTTP: 9. HTTP GET via SSH forwarding
    HTTP->>Key: 10. resourceKey(GET, original URL)
    Key-->>HTTP: 11. exact map key
    HTTP-->>Owner: 12. captured resource + local mapping + CSP
    Owner->>Client: 13. native UI requests in client browser
    Client->>HTTP: 14. mapped local fetch/XHR
    HTTP-->>Client: 15. captured response or explicit 404/405
    Owner->>CLI: 16. stop
    CLI->>HTTP: 17. pidfd SIGTERM (owned process)
    HTTP-->>CLI: 18. connections closed / process exits
    CLI-->>Owner: 19. STOPPED
```

Snapshot Manager's browser lease acquisition is intentionally not used: this HTTP transport needs no Chromium on F. Public Rule Kit sessions/calculation/providers continue through their existing execution boundary; none are called by this UI-only server. The original UI's own displayed calculations remain its captured code, with no new calculation engine in the adapter.

## Validation ledger (2026-11-02)

Local evidence is kept outside Git under the operator's private evidence directory; generated artifacts are not repository content.

| ID | Expected | Actual / status | Owner |
|---|---|---|---|
| W01 | Web server on F | PASS: loopback HTTP + readiness/status | F AUTO |
| W02 | Frozen UI resources | PASS: verified package replay; incomplete sprites explicitly diagnosed | F AUTO |
| W03 | Real Android renders | NOT_RUN; Pixel 7 emulation passes, not substituted | Owner MAN |
| W04 | New Profile | PASS desktop/mobile emulation; Android NOT_RUN | AUTO + MAN |
| W05 | Equipment changes | PASS Runic Skullcap, native item ID verified; Android NOT_RUN | AUTO + MAN |
| W06 | Skills/paragon | PASS Puncture 1 + node 283; native payload verified; Android NOT_RUN | AUTO + MAN |
| W07 | No online Maxroll calls | PASS client checks: all external attempts CSP-failed, zero external responses/completions; Android NOT_RUN | AUTO + MAN |
| W08 | Missing diagnostics | PASS explicit 404, counts/paths, no silent fallback | F AUTO |
| W09 | Mismatch fail-closed | PASS unknown binding rejected before listener | F AUTO |
| W10 | SSH forwarding | PASS isolated real OpenSSH tunnel, full build edits desktop/mobile; Owner route NOT_RUN | F AUTO / Owner MAN |
| W11 | Cleanup | PASS three start/reuse/status/stop cycles, ports released, conflict owner preserved | F AUTO |
| W12 | Rule Kit regression | PASS application typecheck + 37 unit/3 contract/4 E2E; infrastructure 44 unit/25 E2E | F AUTO |

Additional server tests: 4 tests covering exact route matching, rewrite behavior, binding mismatch, headers/POST, missing resources, redirects, port conflict and shutdown. Native UI tests run Chromium `153.0.8010.12`, Playwright Core `1.64.1`, Node `22.22.1`, Python `3.12`.

Initial test failures were fixed transparently: router `__manifest` namespace rejection; required eval CSP permission; mobile List text hidden while its parent control is visible; OS TIME_WAIT affecting preflight/rebind; browser-specific CSP failure spelling. Infrastructure E2E initially lacked the pinned executable environment variable; rerun with `BROWSER_INFRA_CHROMIUM_PATH` passed all 25. No acceptance was removed to bypass these failures.

Status: **local automated checks PASS; real Android acceptance NOT_RUN; CI_NOT_CHECKED**. Full original Local Build Editor/export completion is not claimed.


## Android blank-frame incident and diagnostic follow-up

Owner reported a black Planner frame in Samsung Internet **and Chrome Android**, while the shell showed 71 missing / 258 blocked. Those counters were server-global across earlier automated runs and Owner sessions; the old ring retained only 100 events and no JavaScript errors or frame lifecycle. It is impossible to reconstruct all 71/258 events or establish a root cause from that evidence. Do not attribute the blank frame to Samsung, missing sprites, CSP, or an engine incompatibility without evidence.

The follow-up adds early `error`, `unhandledrejection`, console-error and resource-error telemetry in `client.js`, plus parent-side frame geometry/readiness in `shell.js`. Each load has a non-secret random iframe name/session ID; diagnostic events are separate from network-block counters and are sent only to the same-origin loopback endpoint. They are retained in a bounded 200-event ring and the private CLI server log. URL queries are stripped; report bodies remain limited to 2 KiB. Original errors are not suppressed. The wrapper labels the counters as server totals.

No CSP/sandbox directives, origin mapping, native Maxroll code, snapshot bytes/version, calculation or export semantics changed. The owned UAT service was stopped/started using its PID-identity/pidfd CLI. After that restart and a reload, Owner explicitly reported that Android now loads and editing works. This is observed recovery, **not a proven root-cause fix**. Changes to diagnostic timing, reload/runtime state, and the iframe name cannot be distinguished causally from available evidence.

Actual Chrome Android session `8566d957-cb82-4a7c-8433-72d962113b6d` on 2026-11-02 reported a 384×655 frame, completed document, New Profile present and changing geometry during scrolling. There were zero JS_ERROR, UNHANDLED_REJECTION or CONSOLE_ERROR events in that recorded session. Its UA was Chrome/156.0.0.0 Mobile; the reduced Android/10/K UA does not establish the device's real OS version. Owner's visual/edit confirmation is the manual evidence; DOM telemetry alone is not visual acceptance. Samsung recovery has not been separately confirmed, and individual equipment/skill/paragon Android assertions were not enumerated by Owner.

W03 Chrome Android: **Owner-confirmed render recovery**. Owner also confirms editing generally; W04–W06 per-control manual coverage remains unenumerated. Previous blank-frame failure is retained in history; repeat-failure root cause remains **UNRESOLVED**. The complete fix DoD is not claimed solely from automated tests.

### Request impact classification

- External fonts/styles, Ziff/Google ads/tracking: expected client CSP blocks; fresh Linux/Android sessions render despite these blocks.
- Missing item/skill/aspect sprite sheets and individual item WebP images: visual coverage gaps; explain absent item pictures, not demonstrated as the earlier entire-frame blank cause.
- Missing whoami: cloud account UI unavailable; anonymous editing demonstrated.
- Local-HTTPS twitch request constructed by captured code: blocked. Frozen `mve` catches fetch failure and returns false; it supplies live-stream status, not Planner initialization.
- Missing favicon/touch icons and the captured HTML-MIME sponsor script: optional shell/ad failures. Browser tests explicitly classify these; unexpected console/runtime errors fail the test.
- Uncaptured application modules/router/game data would be initialization blockers; no such failure was observed in the recovered Android session. The historical aggregate alone cannot rule one out for the failing session.

### Catalog versus artwork

Read-only inspection of the captured complete `data.min.json?b8bc3970` response (9,366,658 bytes, version 3.2.1.73552) finds 12,195 raw item records and 6,380 affix records. Counts by native `type`: Helm 840, ChestArmor 836, Gloves 837, Legs 823, Boots 822, Ring 180, Amulet 127; weapon types are present too (e.g. Sword 220, Dagger 174, Bow 93). Localization `data.enus.json?90146625` contains 12,072 item entries. These are raw records, including variants/class/season and non-equipment entries, **not counts of independently selectable supported equipment**. Exact response integrity does not certify exhaustive UI/calculation support or artwork completeness. No additional capture, online asset download or snapshot mixing was performed.

### Follow-up tests

Four targeted HTTP tests pass, including separating runtime errors from blocked-request totals and stripping report URL queries. A new real Chromium synthetic test deliberately throws an initialization error, rejects a Promise and emits console.error: all three reach diagnostics with the correct session; parent navigation, popup and cross-origin frame navigation remain blocked. This synthetic test validates observability/security only, not Maxroll behavior.

The actual snapshot browser test now asserts usable frame geometry, complete document/New Profile, two reloads per desktop/mobile case, no uncaught runtime errors and no unexpected console errors before checking actual build interactions/native payload. Desktop and Pixel 7 emulation pass with 244 CSP-failed external attempts per case and zero external responses/completions. Three independent lifecycle cycles still pass. Evidence remains private under `evidence/android-fix/`; **CI_NOT_CHECKED**.
