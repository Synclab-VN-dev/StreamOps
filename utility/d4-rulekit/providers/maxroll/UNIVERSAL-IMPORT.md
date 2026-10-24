# Universal Diablo IV Build Import

## Status

The pinned `3.2.1.73552` implementation now has a production-shaped universal path:

`d4-build/v1 -> catalog resolver -> native state -> offline loader -> semantic read-back -> attested metrics`

This is **not** a claim of universal coverage. The implementation is fail-closed and the
current overall status is `PARTIAL / BLOCKED_COVERAGE`. See
`UNIVERSAL-IMPORT-COVERAGE.json` for measured numerators and denominators.

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
- `MaxrollRuntimeAttestationObserver`: exact live calculation-frame profile/item read-back, executing engine
  identity, coherent calculation epoch, 50 raw metrics, observed display rows, and egress evidence.
- `UniversalMaxrollComponentFactory`: dependency-injected composition with the existing Provider
  and the unchanged eight Application APIs.

## Confirmed behavior

- Scratch canonical states are encoded for all eight catalog class IDs without a native fixture.
- The native loader response envelope is generated deterministically from the canonical class and
  season plus the pinned planner route. It contains neutral account/search metadata and does not
  copy an exported fixture envelope or source account identity.
- Both approved Rogue profiles use the same codec/loader implementation.
- Midgame and Endgame keep exact G1-G4, raw, display, zero-egress, and cleanup evidence.
- A real Application session exercises all eight APIs and an A -> B -> A reset using the two
  independently attested profile outputs.
- Stateful CDP observation remains attached for the session and replaces expected input semantics
  only while no capture is active. This avoids stale execution context reuse between evaluations.

## Known coverage blockers

The pinned game catalog is rich but is not a complete legal-build specification:

1. Affix `itemLabels` are picker/acquisition metadata, not an authoritative legality relation.
   Valid Unique affixes in the approved fixture contradict a simple label-intersection rule.
2. Sixty equippable item records and one glyph lack complete eight-class filter evidence.
3. No dedicated specialization catalog or versioned conditional-options schema was found.
4. Rune/charm/stone identities exist, but a complete semantic taxonomy is not proven.
5. Only Rogue has an independently captured real fixture. Seven classes remain
   `BLOCKED_INDEPENDENT_FIXTURE`; synthetic/catalog tests do not replace real acceptance.
6. The proven calculation frame exposes `profile` and resolved `items`, but not native top-level
   `season/options` under the same object. A bounded probe failed closed, so exact read-back for
   those global fields remains unverified rather than being inferred from the request.

These gaps prevent `UNIVERSAL_IMPORT_DONE`. Inputs using unverified semantic relationships must
remain rejected or coverage-qualified until an authorized independent fixture/schema supplies the
missing evidence.

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
