# Real Maxroll runtime compatibility

## Current decision

The production package now has separate `synthetic-dom-v1` and `maxroll-ui-cdp-v1` strategies.
The real strategy is implemented for the bounded historical `3.2.1.73552` protocol. Issue #132 now
provisions and removes an authorized ephemeral snapshot automatically, but the real acceptance gate
is **BLOCKED_PATCH_DRIFT**: the live application asset identity changed. The adapter does not fall
back to the synthetic runtime or auto-retarget its compatibility pin.

## Evidence boundary

| Identity | Historical PoC evidence | Current production revalidation |
|---|---|---|
| Game patch | `3.2.1.73552` | observed unchanged on 2026-10-23 |
| Calculation asset | `/assets/export-DOjdL1l3.js` | live asset is now `/assets/export-D12aM6KT.js` |
| Asset SHA-256 | `e796b92751d0b07be8b10eed705727467e23ba0d99eb088e87de88942c57a1f4` | live asset observed as `891c1f82717c50e598450575068394c6d2fe1c8d26de26f2eeed028d028997db` |
| Raw capture | 50/50 through render-time CDP closure | real contract exists; not run without snapshot |
| UI display | 34/50 | real contract exists; missing displays remain `null` |
| Mutation | unsaved Rogue L50/Torment I Runic Skullcap, optional Of Dampening | UI-only adapter implemented; real run blocked |
| Offline replay | 354-entry, ~59 MB temporary PoC package | no package body is in Git or this worktree |
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
- `e2e:real:live-capture` supplies those inputs automatically from a verified ephemeral capture and
  fails before offline execution if the live identity differs from the independent checked-in pin.

## Permission and safety

No Maxroll response body, bundle, cookie, token, session storage or profile data is added to the
repository or CI artifacts. The online phase uses a fresh anonymous context, read-only methods and
bounded allowlisted origins; it does not expose request headers to the orchestrator. The Generic
Snapshot Manager validates the temporary package, then mounts it in `offline-strict` mode in a new
browser process. A missing resource is aborted without network fallback and cleanup runs on PASS or
FAIL.

## Remaining blocker

The current asset change must be investigated as a new version-specific profile. A probe using the
new asset identity resolved the old breakpoint far enough to capture calculations but failed exact
desired-state read-back, so hash replacement alone is not compatible evidence. Dev F must identify
the changed UI/read-back contract, add a reviewed profile/adapter strategy and rerun the one-command
gate. Only after it passes may MXP-09, MXP-10 and APP-07 be reported as real PASS or the issues be
proposed `READY_TO_CLOSE`.
