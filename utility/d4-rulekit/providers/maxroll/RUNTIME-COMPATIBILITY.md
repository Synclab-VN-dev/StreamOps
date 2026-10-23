# Real Maxroll runtime compatibility

## Current decision

The production package now has separate `synthetic-dom-v1` and `maxroll-ui-cdp-v1` strategies.
The real strategy keeps the bounded historical `3.2.1.73552` protocol and now also exposes a
separate candidate profile for the 2026-10-23 snapshot. Targeted local adapter acceptance is
**ADAPTER_LOCAL_PASS** for the candidate profile: one offline A→B→A cycle produced 50/50 raw and
34/50 display metrics with exact rollback. The candidate remains distinct from the historical
profile and is not an approved runtime trust-policy upgrade. The adapter never falls back to the
synthetic runtime or auto-retargets a compatibility pin.

## Evidence boundary

| Identity | Historical PoC evidence | Current production revalidation |
|---|---|---|
| Game patch | `3.2.1.73552` | observed unchanged on 2026-10-23 |
| Calculation asset | `/assets/export-DOjdL1l3.js` | live asset is now `/assets/export-D12aM6KT.js` |
| Asset SHA-256 | `e796b92751d0b07be8b10eed705727467e23ba0d99eb088e87de88942c57a1f4` | live asset observed as `891c1f82717c50e598450575068394c6d2fe1c8d26de26f2eeed028d028997db` |
| Raw capture | 50/50 through render-time CDP closure | 50/50 finite values in targeted offline run |
| UI display | 34/50 | 34/50 read independently; missing displays remain `null` |
| Mutation | unsaved Rogue L50/Torment I Runic Skullcap, optional Of Dampening | targeted 22→2822→22 Fire Resistance and exact A rollback |
| Offline replay | 354-entry, ~59 MB temporary PoC package | verified 365-resource snapshot outside Git; 191 requests aborted locally with zero completed egress |
| Authorization | old research was bounded and temporary | project policy reference `StreamOps#132-owner-directive-2026-10-23` |

The PoC data is compatibility input, not current Maxroll evidence. The version profile owns the
asset identity, CDP location, closure expression and UI semantics. A changed asset digest, missing
breakpoint, different patch, ambiguous picker, partial read-back or incomplete metric set fails
closed.

## Implemented boundaries

- `MaxrollComponentFactory` injects runtime/build/extractor strategies into `MaxrollProvider`.
- Synthetic and real component factories carry an explicit `runtimeKind`; mixing a real profile
  with a synthetic factory is rejected before acquiring Chromium.
- `RealMaxrollRuntimeAdapter` uses Browser Infrastructure leases only. It does not launch or manage
  Chromium itself.
- The adapter creates a new unsaved profile for each desired-state evaluation, applies only the
  proven item/effect through UI actions, and verifies class/level/difficulty/item/modifier read-back.
- Runtime values are captured only for the current evaluation phase. A capture is single-use.
- `RealMaxrollMetricsExtractor` requires all 50 finite raw values, maps the 34 observed UI values
  independently, and never fills missing displays or promotes `OBSERVED` to `VERIFIED`.
- `tests/real/authorized-runtime.test.js` is a reusable offline-only MXP-09/MXP-10/APP-07 contract.
  It intentionally fails with `BLOCKED_AUTHORIZED_SNAPSHOT` when its trust inputs are absent.
- `snapshot:capture -- --output <folder>` creates and verifies an immutable persistent package.
  It records drift without deleting the package or pretending that capture equals real acceptance.

## Permission and safety

No Maxroll response body, bundle, cookie, token, session storage or profile data is added to the
repository or CI artifacts. An explicitly requested online capture uses a fresh anonymous context,
read-only methods and bounded allowlisted origins; it does not expose request headers to the
orchestrator. The Generic Snapshot Manager validates the persistent local package. A later approved
real test mounts it in `offline-strict` mode in a new browser process; a missing resource is aborted
without network fallback.

## Remaining blocker

The first mismatch was the Helm read-back anchor, not calculation capture: the current UI renders
the item name beside the semantic slot node rather than inside the historical slot child. The
current editor also needs an explicit close action, optional discard confirmation, asynchronous
modifier-picker readiness, and no mandatory level-reset transition. These differences live in the
new version-specific candidate profile while the generic adapter preserves fail-closed behavior.

Targeted adapter coverage is complete, but the full MXP-09 three-cycle gate, MXP-10 Application
integration and APP-07 eight-API gate were deliberately not run in this phase. They remain pending
Owner review of the candidate profile and the later full Real E2E phase; this result is not
`READY_TO_CLOSE` evidence.
