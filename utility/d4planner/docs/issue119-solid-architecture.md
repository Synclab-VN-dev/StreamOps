# Issue #119 / PR #120 — SOLID v3 Unified Item Current (DEV)

**Scope:** Back-end CLI materialized item projection. This is an incremental
architecture refactor on `feat/119-owned-items-cli`, not a claim of release.
All player data on A must be treated as live unless the owner explicitly
authorizes touching a named isolated PR DEV HomeDir.

## Processing contract

```text
Durable event_log (events.db) -- source never rewritten by projector
    -> Supervisor._flush_ingress (session/new events)
    -> OwnedItemsRepository.sync(equipment_projector=...)
        -> one ordered canonical batch / shared character.db connection
           -> Bag/context/verified-grid evidence projection
           -> EquipmentProjector context + ordered resolver pipeline
              (same connection; no second independently committed writer)
           -> CurrentItemReducer
              -> injected _SqliteItemPort
              -> item_current (confirmed physical entities only)
           -> item_projection_state revision, cursor, checkpoint
        -> single commit or rollback + restore mutable Equipment UI context
    -> CLI item / --attach / filters (read-only committed snapshot)
```

All three producers (Bag-selected, Equipment, verified-grid) now submit
`CurrentItemIntent` to the same pure `CurrentItemReducer`; producer-specific
recognition stays in the producer. Unconfirmed EQUIPPED comparison/name-only
hints remain in `owned_item_observation` audit and do not create physical
`item_current` rows. Neither an `Equip` nor an `Unequip` action *label*
means a confirmed player action.

The equipment resolver pipeline already uses a Template Method and ordered
specialized strategies. `slot_policy.py` is a pure, injectable extension
policy: an equipped item must have a type compatible with its slot even if UI
context is stale. `Two-Handed` belongs to `main_hand`, never `boots`.

## All five SOLID principles

| Rule | Enforced boundary |
| --- | --- |
| S | UI event context, parsed observation, evidence decisions, reducer, DB writer, and CLI presentation have distinct reasons to change |
| O | Extend `EquipmentResolver` / `SlotTypeRule` or item evidence producers instead of editing SQL or adding special cases to the CLI |
| L | New resolver outputs must follow `Resolution` and remain fail-closed for insufficient evidence; all `CurrentItemIntent` implementations use the same reducer invariants |
| I | `SlotTypeRule` and `ItemWritePort` are narrow protocols; strategies never receive unrelated DB/NVDA capabilities |
| D | `current_reducer.py` only imports standard Python; its persistence port is supplied by `item_current.py` |

SOLID is an engineering policy, not an automatic guarantee that every possible
NVDA trace has already been recognized correctly.

## Invariants and limits

1. **Only physically CONFIRMED** source-backed observations enter
   `item_current`; comparison candidates are retained in audit. Repeated
   tooltip or re-running a committed batch cannot create an extra row.
2. **No stale slot inheritance:** Item type incompatible with slot => no
   equipment write. Unknown/unsupported types fail closed. Add explicit rules
   rather than bypassing type checks.
3. **No fabricated moves:** An `Equip` label or button marker alone cannot
   move/delete current state. Explicit verified-grid proofs are separate.
4. **Same transaction:** Bag, Equipment, verified-grid, revision, session
   checkpoint and projector checkpoint commit atomically from the Engine.
   Failure rolls back rows and restores mutable equipment parser context.
5. **No name-only global dedupe:** Two physically distinct rings/items with
   identical names/rolls can exist. Fingerprints are observation matching aids,
   not globally unique physical IDs. Cross-container identification of the
   *same physical item* still needs attested tracking/action proof.
6. **Coverage is PARTIAL** without a complete verified scan. A missing tooltip
   is not a sale, salvage or pickup.

## How to extend with new case C

1. Preserve the owner-provided log as an immutable fixture with event
   provenance and independent expected state. Differentiate a derived
   speech fixture from a canonical `events.db` export.
2. First demonstrate RED on the original implementation while all previously
   supported golden tests remain authoritative.
3. Add a narrow `BaseResolver` / `SlotTypeRule` or new evidence producer.
   Return a `Resolution` or `CurrentItemIntent` only; never write SQL from a
   new recognition strategy. Reject ambiguity conservatively.
4. Test LSP, extension order, replay/idempotency, same-name distinct physical
   items, item/slot compatibility, cross-session freshness, crash/rollback
   and all earlier golden cases A/B.
5. CI PASS on **exact PR HEAD**, then isolated Real-A UAT with manually
   confirmed inventory/equipment reference. A green synthetic suite is not
   Real-A evidence.

## Current regression evidence

- Owner October 18 21:38 derived Real-A sequences:
  `test_issue119_solid_replay.py` covers Feet -> Two-Handed Staff,
  unknown slot -> Staff, comparison before equipment scan, and repeat reads.
- `test_issue119_atomic_pipeline.py` covers single shared transaction,
  injected mid-batch failure/rollback, and new-version replay.
- `test_issue119_reducer_contract.py` covers pure reducer decisions,
  protocol replaceability, evidence/slot invariants, rings, and grid scoping.
- Historic 929-event Equipment golden and other #119/#59/#62 regressions
  remain mandatory.

## DEV schema policy and deferred release gate

Projection version 3 is **clean DEV bootstrap**. Version 2 databases are
refused explicitly; they are **not silently migrated or wiped**. Use a
dedicated isolated PR120 DEV HomeDir and fresh `character.db` for test.
Neither the CI nor the UAT runner deletes the user's active A DB.

Before the first release, plan separately: versioned migrations, data retention,
backup/rollback, an operator-approved upgrade procedure, and evidence for
migrating old physical identities. No legacy migration is required to accept
this development refactor.

## Pending gates

- Real-A manual equivalence: exact HEAD, session, current Equipment vs Inventory,
  duplicate and slot truth, partial stash/coverage. Manual acceptance is pending.
- The supplied 1,606-line speech paste is a derived fixture, NOT a complete
  canonical event export; an exhaustive 14-item end-to-end golden still needs
  full session event provenance and independently confirmed exact inventory.
- A stable cross-container physical ID when no verified tracking token exists
  remains inherently unprovable from name/roll alone. The resolver must stay
  conservative rather than inventing identity.
- Supervisor uses one atomic batch for current, but diagnostics and other
  non-item services still have separate lifecycles; no claim of cross-database
  transactions between `events.db` and `character.db`.
- PR remains Draft; no merge/release/deploy or Windows A reset authorized.
