# Universal Diablo IV Build Import

## Status

The pinned `3.2.1.73552` implementation now has a production-shaped universal path:

`d4-build/v1 -> catalog resolver -> native state -> offline loader -> semantic read-back -> attested metrics`

The implementation is fail-closed and is complete for build state expressible by the pinned
engine/schema contract. Eight real fixtures are representative acceptance evidence; catalog,
schema-branch and deterministic property tests cover inputs beyond that fixture corpus. See
`UNIVERSAL-IMPORT-COVERAGE.json` for the separately measured coverage dimensions.

## Trust boundary

User-authored canonical builds contain the game patch but do not provide trusted snapshot,
engine, or catalog provenance. Those identities come from the provider configuration and the
verified local snapshot. `MaxrollD12CanonicalCodec` refuses a catalog whose snapshot, manifest,
data version, or resource digest differs from the pinned contract.

`d4-build/v1` can therefore be authored from scratch. An exported build may contain optional
source provenance for audit, but the codec never treats it as a trust anchor.

## Components

- `MaxrollD12CanonicalCodec`: deterministic native/canonical conversion and validation.
- `MaxrollEntityCatalog`: stable-ID resolution and catalog-derived compatibility checks.
- `UniversalMaxrollBuildMapper`: desired-state changes for whole build, equipment, skills,
  Paragon, effects, and calculation options.
- `NativeStateMaxrollRuntimeAdapter`: whole-state hydration through the captured native loader;
  no item-picker automation and no network fallback.
- `MaxrollRuntimeAttestationObserver`: exact live calculation-frame profile/item read-back,
  versioned World Effects/season UI read-back, executing engine identity, coherent calculation
  epoch, all applicable raw metrics, observed display rows, and egress evidence.
- `UniversalMaxrollComponentFactory`: dependency-injected composition with the existing Provider
  and the unchanged eight Application APIs.

## Confirmed behavior

- Scratch canonical states are encoded for all eight catalog class IDs without a native fixture.
- The native loader response envelope is generated deterministically from the canonical class and
  season plus the pinned planner route. It contains neutral account/search metadata and does not
  copy an exported fixture envelope or source account identity.
- All eight classes traverse Canonical JSON -> published schema -> Application -> real Provider ->
  pinned offline engine with exact independent-reference raw parity.
- Scratch canonical states for all eight classes load without copying a native fixture.
- Real per-class A -> B -> A covers equipment, skills, Paragon, effects and calculation options;
  `build.replace` and all eight public APIs have exact vector/state assertions.
- Applicable raw metrics are discovered from the pinned runtime definition/UI completion signal;
  counts vary by class (44-53) and are never padded or truncated to 50.
- Shared calculation options and season are read independently from the runtime UI. Missing UI
  controls are explicitly `notApplicable`; present controls must match exactly.
- Stateful CDP observation remains attached for the session and replaces expected input semantics
  only while no capture is active. This avoids stale execution context reuse between evaluations.

## Validation authority

The codec uses authoritative catalog relations where they exist: stable IDs, item body slots,
class skill trees, Paragon boards/nodes/glyphs, mercenary trees and War Plan trees. It deliberately
does not reinterpret picker/acquisition metadata such as affix `itemLabels` as legality rules.
Relations not declared authoritatively in the catalog are delegated to the pinned native loader,
then accepted only after exact applied-state read-back and a fresh coherent calculation epoch.
This preserves valid engine-representable builds without inventing game rules.

Future engine fields, IDs or option controls fail closed and require a new version profile/schema;
they are not silently dropped. This is the intended version boundary, not a whitelist of fixtures.

## Application changes

The Application public surface is unchanged. Provider change records supported by the universal
profile are:

- `build.replace`
- `equipment.setSlot`
- `skill.setRank`
- `paragon.setBoards`
- `effect.set`
- `calculationOption.set`

Every candidate is converted to native state before execution, so invalid patch, entity, slot,
class, board, glyph, duplicate allocation, and malformed numeric inputs fail before Chromium is
asked to calculate.

## Evidence classification

Metrics returned by the runtime are `OBSERVED`. Exact agreement with the approved independent
Rogue reference is reference parity; it is not independent formula verification.

CI was not queried or triggered for this work (`CI_NOT_CHECKED`).
