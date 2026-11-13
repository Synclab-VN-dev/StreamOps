# HUD Web and authenticated local API (#201)

Owner scope supersedes the initial issue's loopback/read-only restrictions: the phone may monitor and control Backend/Capture on the same private LAN. Window pin/drag/click-through/hotkeys remain desktop-only. Create Build opens the Rule Kit-owned Planner. Calculation, canonical schemas and snapshot selection are unchanged.

## Ownership and installation

The `src-hud-server` Rust library runs in the Tauri process. `src-tauri/src/hud_web.rs` supplies typed callbacks to existing native Backend/Report logic. It does not expose Tauri IPC or BE credentials. Closing HUD stops both listeners before native Backend shutdown. No separate HUD daemon, firewall mutation, or public listener is installed.

The same embedded React build is served. `src/platform/web.ts` maps browser actions to explicit REST routes; `web-data-source.ts` receives complete public projections through WebSocket. The server subscribes to BE notification WS and reads the validated native public SQLite projection. Runtime liveness observations supplement notifications; clients never poll a REST display endpoint.

The second listener is an authenticated HTTP transport to the verified Rule Kit Planner. It does not load snapshots or launch Node. Captured Planner scripts run on a different port/origin from HUD; HUD rejects requests from that origin. Only the exact loopback URL returned by native `planner.ensureReady` is forwarded. Readiness is coalesced for concurrent resources for at most two seconds and checked anew on opening a document. Cookies/Bearer credentials never reach Node; redirects to another origin are rejected. HTML/CSS/JS rewrite only the verified upstream origin; native build payloads are not rewritten.

## One-time provisioning

Use the existing D4Planner data root. Before LAN use, provision a TLS certificate whose IP SAN matches the PC's reserved LAN address, and trust its issuing CA on the phone. Do not disable certificate validation. This tooling does not change network/firewall policy; allow the two selected ports only on the Windows Private network if necessary.

```text
python scripts/configure-web.py --data-root C:\D4PlannerData --address 192.168.1.20 --certificate C:\Private\hud-cert.pem --private-key C:\Private\hud-key.pem
```

Defaults: HUD port 6090, Planner transport port 6091. Without an address override, bind is 127.0.0.1; non-loopback plaintext HTTP is rejected. Missing config leaves Desktop unchanged and creates no listener. Configuration, token and TLS key must remain in owner-protected private storage, outside Git/release artifacts. The provisioning script refuses overwrites and never prints the token.

Restart HUD, open `https://192.168.1.20:6090/` on the phone, and enter the token from `private/hud-web-owner-token.txt`. No SSH tunnel. After login, use the existing menu: Runtime Manager controls Backend/Capture; Create Build opens a new browser tab after READY. Allow pop-ups for this site. The PC must keep HUD running. Native snapshots must already be provisioned according to Rule Kit policy.

To revoke a credential, remove its entry from private `hud-web-config.json` and restart HUD; existing server sessions do not survive restart. Tokens are stored only as SHA-256 in server config and never in browser localStorage or URLs. Browser sessions last one hour, with HttpOnly/SameSite cookies and CSRF protection. Subjects must be unique. For read-only monitoring grant `hud.read`; for automation grant only necessary additional permissions. Keep `hud.read` on browser credentials for session lifecycle.

## API

All mutations require same-origin browser Origin + session CSRF, or a separate Bearer credential for automation. Host is exact configured host:port. No wildcard CORS. JSON body limit is 64 KiB; authentication failures, permissions and bounded concurrent dispatch fail closed.

| Route | Method | Permission |
|---|---|---|
| `/api/v1/session` | POST / GET / DELETE | credential login / session / hud.read |
| `/api/v1/health` | GET | hud.read |
| `/api/v1/hud/stream` | WS | hud.read, exact Origin |
| `/api/v1/targets` | GET | hud.read |
| `/api/v1/targets/select` | POST | target.select |
| `/api/v1/runtime/{backend,capture}/{start,stop,restart}` | POST | runtime.control |
| `/api/v1/planner/open` | POST | planner.open |
| `/api/v1/reports/preview` | POST | report.preview |
| `/api/v1/reports/{UUID}` | GET / DELETE | report.read / report.preview |
| `/api/v1/reports/{UUID}/submit` | POST | report.submit |

Health/envelopes use `d4planner-hud-web/v1`; Target and Report success payloads preserve their existing schemas. Errors contain `{schemaVersion,error:{code,state}}`; private exception text is never returned. `OPERATION_TIMEOUT` does not imply cancellation of a native operation: its permit remains held until completion. Retry report operations using the same report ID after uncertain outcomes.

Preview body: `{ "selection": { "fe": true, "be": true, "rulekit": true, "evidence": false, "evidenceConsent": false } }`. Submit body: `{ "description": { "issueType": "Other", "title": "…", "actual": "…", "expected": "…", "steps": "…" }, "consent": true }`.

Report collection/encryption/GitHub submission remain in the existing Report library and Python gateway. Draft ownership is private metadata; Web subjects cannot read/discard Desktop or other users' drafts. Pending remote outcomes remain durable and cannot be canceled. Terminal receipt metadata is retained for up to seven days with a hard bound. Raw event collection remains UNAVAILABLE until its existing production binding is implemented. Neither API nor diagnostics returns plaintext logs, filesystem paths, bootstrap secrets, or arbitrary file selections.

## Local QA

```text
npm ci
npm test
npm run build
cargo test --manifest-path src-hud-server/Cargo.toml
cargo test --manifest-path report-issue/Cargo.toml
cargo build --manifest-path src-hud-server/Cargo.toml --example browser_fixture
python scripts/web-acceptance.py --output /private/new-acceptance-directory
```

The browser acceptance fixture explicitly uses synthetic native callbacks and is not Windows-native evidence. It serves real HTTP/WS and the shared production React build. Use private evidence directories. Windows native build/lifecycle, PC/Web visual parity, and real phone UAT must be recorded separately. An implementation screenshot is not a MagicPath Golden. No GitHub Actions are required or checked.
