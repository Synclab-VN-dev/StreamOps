# W3 review correction evidence

Scope: PR #126 review findings W3-R1, W3-R2 and W3-R3. All reproduction
commands ran on reviewed commit `07aef84e3413b3a3ec86a8132797ef252edfa502`
with test-only changes applied before implementation changes.

## Fail-first evidence

| Finding | Command | Expected | Actual on old implementation | Reproduced? |
|---|---|---|---|---|
| W3-R1 | `node --test --test-name-pattern='W3-R1' tests/e2e/snapshot.test.js` | Worker WebSocket/SW have zero outbound and context is transport-offline | Both default and `serviceWorkers: allow` cases reported `navigator.onLine=true`. The tested Worker WebSocket and SW requests did not reach counters on this Chromium build | **PARTIAL**: missing enforced offline policy reproduced; the hypothesized Worker/SW leak itself was **NOT_REPRODUCED** |
| W3-R2 | `node --test --test-name-pattern='W3-R2' tests/unit/snapshot.test.js` | Changed status/header rejected | 2/2 tests failed with `Missing expected rejection`; `verify()` accepted both metadata edits | **YES** |
| W3-R3 | `node --test --test-name-pattern='W3-R3' tests/e2e/snapshot.test.js` | No private fixture value in draft/package | Test failed `true !== false`; raw JSON token/PII and redirect fragment token were observable | **YES** |

The first R3 fixture iteration exposed an unrelated `networkidle` issue for an
image redirect and was replaced by two direct source fixtures. It is not used
as bug evidence.

## Findings and corrections

| Finding | Severity | Root cause | Impact tới user nếu không sửa | Fix | Evidence | Status |
|---|---|---|---|---|---|---|
| W3-R1 | P1 | Route interception was HTTP-level and offline-strict had no context transport invariant; SW safety relied on consumer config/init script | A future Chromium/site path could reach a changing server, so a pinned snapshot might become nondeterministic or fail when truly offline | Mount installs routes, rejects contexts with pre-existing SW, then calls `context.setOffline(true)` before navigation; unmount restores transport. Capture also closes routed WebSockets. Tested default and `allow` SW modes plus Dedicated Worker WebSocket counter | Real E2E `W3-R1 SNAP-04/05/12...` 2/2 PASS; source counters unchanged; `navigator.onLine=false` | PASS |
| W3-R2 | P2 | Only resource bodies had hashes; valid-looking manifest metadata had no pinned digest | Status/MIME/redirect behavior could differ from the captured version while verification falsely reported valid | Atomic package now includes `manifest.sha256`; load/verify/mount validate it before trusting metadata, and `verify()` exposes the digest for optional external pinning | Status 200→201 and content-type tamper tests PASS; mount also rejects tampered package | PASS |
| W3-R3 | P1/P2 | Request filtering and response-header allowlist did not inspect response bodies or sensitive redirect destinations | Tokens/PII could silently enter backups or shared snapshots | Safe default redacts generic sensitive JSON keys and rejects sensitive Location query/fragment. Generic response policy supports `exclude`, explicit replacement `redact`, and deliberate `include-sensitive`; custom sensitive-name extensions are supported | Unit JSON/location policy PASS; real capture verifies default redaction, fail-closed redirect, exclude/redact/opt-in contracts and persisted package | PASS |

## Post-fix local gates

```text
Unit:                 41/41 PASS
Real Chromium E2E:   22/22 PASS
Python Rule Kit:     38/38 PASS
INF-01..INF-14:      14/14 LOCAL_PASS
SNAP-01..SNAP-14:    14/14 LOCAL_PASS
Manual UAT:          0
Progress:            28/28 acceptance IDs = 100% locally verified
```

Local generated reports remain ignored at:

- `utility/d4-rulekit/browser-infra/artifacts/unit.{json,junit.xml}`
- `utility/d4-rulekit/browser-infra/artifacts/e2e.{json,junit.xml}`

## Trust model and remaining risks

- `manifest.sha256` is an integrity checksum stored atomically beside the
  package. It detects corruption and manifest-only edits. It is not a digital
  signature or external trust anchor; an attacker who can rewrite both files
  remains outside this threat model.
- Generic JSON key filtering cannot identify every PII field or secrets inside
  arbitrary HTML, text, images or binary formats. The data owner must add
  sensitive names or a response policy. `include-sensitive` is intentionally
  explicit and should not be used for shareable packages.
- Strict replay now has two layers: context transport-offline plus exact local
  HTTP fulfillment/abort. Browser-global SW/WebSocket defensive overrides stay
  active for the disposable lease; release remains the full isolation boundary.

## WHAT / WHO / WHY / HOW

- **WHAT:** close transport, metadata-integrity and sensitive-response gaps.
- **WHO:** infrastructure enforces generic safety; providers/data owners supply
  additional response rules for domain-specific PII.
- **WHY:** keep offline snapshots deterministic and safe to verify/store.
- **HOW:** transport-offline contexts, pre-existing SW validation, manifest
  checksum anchor and composable response decisions with safe defaults.
