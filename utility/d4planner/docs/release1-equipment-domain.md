# Release 1 Equipment domain (S4 / #141)

This module implements the independent Backend domain for the S1 contract
`d4planner-r1-contract/1.0.0-candidate.5`. It is intentionally transport- and
process-neutral: S5 owns WebSocket delivery and S2/S3 own managed processes.

## Production boundaries

`TargetRepository` owns a configured directory, never a client-supplied path.
It validates the Release 1 envelope and canonical build with JSON Schema plus
semantic links, lists safe IDs and exact-byte hashes, then re-reads and
revalidates the bytes before atomic activation. The persisted selection binds
target ID, hash, policy version, and a monotonic selection revision. Missing,
changed, duplicate, invalid, oversized, excessive, or symlinked files fail
closed and never silently select another Target.

`EquipmentAssessmentService` consumes a confirmed, typed
`EquipmentSnapshot`. Its producer must use the existing Equipment projector and
an authoritative stable-ID mapper. Raw tooltip labels are not accepted as
identity and fuzzy matching is forbidden. This separation preserves the
existing equip/replace/unequip ownership semantics while preventing a display
name from becoming scoring identity. Until the authority mapper has identified
an entity and completeness, the producer emits incomplete evidence and the
scorer returns `UNKNOWN`.

Each criterion is scored once even when it has multiple parameters. Core and
non-core weights are the approved 3 and 1 from the selected policy. `UNKNOWN`
is excluded from the denominator; `WARN` and `FAIL` are included. Item x/y,
FAIL issues, WARN count, diagnostic evaluation counts, and recommendation are
independent fields. Skills, Paragon and Charms are preserved in the selected
Target but are not read by the scorer. The target sample item's name is never
used to identify Current equipment.

`DurableHudStore` is the transaction boundary. It compares the complete
runtime/character/current/target/hash/selection/policy binding inside an
immediate SQLite transaction, assigns the HUD revision, and records the
snapshot before publishing. Duplicate work for the same binding is idempotent;
late work is rejected. A publish failure leaves the committed snapshot pending
for S5 snapshot/resync. Migrations are additive and reject a database created
by a newer runtime; lock failure is fail-closed and never wipes data.

## Integration sequence

```text
existing capture/projector -> stable-ID/evidence mapper -> EquipmentSnapshot
configured Target folder   -> TargetRepository.activate (bytes/hash recheck)
snapshot + active Target   -> EquipmentAssessmentService
complete binding           -> DurableHudStore transaction
committed HUD revision     -> S5 publisher / durable resync
```

The mapping arrow is an explicit integration boundary, not a test fallback.
Synthetic typed fixtures exercise the domain only and are labelled synthetic.
Real Windows capture-to-HUD integration remains dependent on the actual mapper
and sibling integration plan; these unit/contract tests are not Real-A E2E.

## Local verification

From the repository root:

```bash
python -m pytest -q utility/d4planner/tests/test_release1_equipment_domain.py
python -m pytest -q utility/d4planner/tests/contracts/test_release1_contract.py
python -m pytest -q utility/d4planner/tests/test_equipment_projector.py
python -m compileall -q utility/d4planner
```
