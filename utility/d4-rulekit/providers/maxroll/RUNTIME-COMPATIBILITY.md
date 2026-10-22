# Real Maxroll runtime compatibility

## Current decision

The production package now has separate `synthetic-dom-v1` and `maxroll-ui-cdp-v1` strategies.
The real strategy is implemented for the bounded historical `3.2.1.73552` protocol, but the real
acceptance gate is **BLOCKED_AUTHORIZED_SNAPSHOT** in this checkout. No authorized snapshot root,
snapshot ID, external manifest digest or authorization reference is available locally. The adapter
does not fall back to the synthetic runtime.

## Evidence boundary

| Identity | Historical PoC evidence | Current production revalidation |
|---|---|---|
| Game patch | `3.2.1.73552` | BLOCKED until authorized snapshot is supplied |
| Calculation asset | `/assets/export-DOjdL1l3.js` | exact URL and SHA required by profile/store verification |
| Asset SHA-256 | `e796b92751d0b07be8b10eed705727467e23ba0d99eb088e87de88942c57a1f4` | pinned; not re-downloaded |
| Raw capture | 50/50 through render-time CDP closure | real contract exists; not run without snapshot |
| UI display | 34/50 | real contract exists; missing displays remain `null` |
| Mutation | unsaved Rogue L50/Torment I Runic Skullcap, optional Of Dampening | UI-only adapter implemented; real run blocked |
| Offline replay | 354-entry, ~59 MB temporary PoC package | no package body is in Git or this worktree |
| Authorization | old research was bounded and temporary | no current snapshot authorization artifact found in #127/#128 |

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

## Permission and safety

No Maxroll response body, bundle, cookie, token, session storage or profile data was added to the
repository. No online Maxroll request was made while implementing this strategy. The future real
test accepts only a separately provisioned local snapshot plus an external SHA-256 trust anchor and
authorization reference. Generic Snapshot Manager mounts it in `offline-strict` mode before
navigation; a missing resource is aborted without network fallback.

## Remaining blocker

Owner/authorized provisioning must supply all of:

1. `MAXROLL_AUTHORIZED_SNAPSHOT_ROOT` containing the Generic Snapshot package;
2. `MAXROLL_AUTHORIZED_SNAPSHOT_ID`;
3. `MAXROLL_AUTHORIZED_MANIFEST_SHA256` from an independent trusted handoff;
4. `MAXROLL_SNAPSHOT_AUTHORIZATION_REF` documenting permitted local execution/retention;
5. a compatible Chromium path in `BROWSER_INFRA_CHROMIUM_PATH`.

Only after `npm run test:real` passes on those inputs may MXP-09, MXP-10 and APP-07 be reported as
real PASS or the two issues be proposed `READY_TO_CLOSE`.
