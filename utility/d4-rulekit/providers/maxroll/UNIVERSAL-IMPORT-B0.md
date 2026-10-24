# Universal Diablo IV build import — B0 vertical slice

## Decision

`B0.1 GO` and `B0_VERTICAL_SLICE_PASS / UNIVERSAL_COVERAGE_PENDING`.

The approved snapshot contains a versioned game-data catalog and a native profile loader. The
catalog covers all eight class records and the entity families needed by the planner. Existing CDP
attestation can read the applied profile and resolved items directly from the calculation frame,
then bind 50 raw metrics to one calculation epoch. This makes a data-driven codec feasible.

B0 does **not** demonstrate universal input coverage. Both approved references are variants of one
Rogue source profile. Cross-class shapes, legal entity combinations, non-empty War Plans, and some
semantic taxonomies remain unverified. The machine-readable inventory is
[`UNIVERSAL-IMPORT-B0-COVERAGE.json`](UNIVERSAL-IMPORT-B0-COVERAGE.json).

## Investigation

Three bounded approaches were considered:

1. Wrap the complete native response as canonical JSON. Rejected: it retains server/editor
   metadata and unrelated profiles, and is not an independent build model.
2. Convert the selected build to semantic sections with stable native entity IDs, validate IDs
   against the pinned catalog, and reconstruct the minimum native state. Selected and implemented.
3. Apply every entity through UI interactions. Rejected for the universal path because it would be
   slow, selector-heavy, and incomplete for combinations not exposed by one editor flow.

The selected codec emits `d4-build/v1alpha1`. It separates character/context, equipment,
skills, Paragon, effects, world progression, and calculation options. Item registry references,
loadout positions, editor notes, other profiles, and response metadata are not copied into the
canonical build. Unknown native/canonical fields and missing catalog entities fail closed.

## Real proof

The local real test downloads the pinned encrypted Release independently, verifies ciphertext and
package hashes, and uses the already-approved offline snapshot. For each reference:

```text
native export -> canonical build -> reconstructed one-profile native state
              -> offline-strict loader -> exact call-frame read-back
              -> coherent 50-metric calculation -> pinned expected comparison
```

| Fixture | G1–G4 | Semantic read-back | Raw | Display | Reference parity | Egress | Cleanup |
|---|---|---|---:|---:|---|---:|---|
| Rogue Midgame | PASS | EXACT | 50/50 | 51/51 | EXACT | 0 | PASS |
| Rogue Endgame | PASS | EXACT | 50/50 | 50/50 | EXACT | 0 | PASS |

The same codec implementation handles both variants. It reconstructs one selected profile and 18
referenced items instead of retaining six profiles and the 596-entry source item registry. Runtime
read-back is exact for the reconstructed supported sections, and every raw/display value equals the
independently attested reference shipped in the encrypted package.

No independent expected-output pair exists for a single controlled mutation in the approved B0
fixture package, so the optional mutation proof remains `BLOCKED_INDEPENDENT_MUTATION_REFERENCE`.
The importer output was not used to invent that expected value.

## Remaining work and estimate

| Workstream | Estimated initial effort | Principal evidence still required |
|---|---:|---|
| B1 schema/lossless codec | 24–40 h | all versioned section shapes and unknown-field policy |
| B2 catalog resolvers | 60–120 h | taxonomy and legal ranges for every entity family |
| B3 whole-build loader | 32–56 h | neutral loader envelope and multi-class state creation |
| B4 exact read-back | 40–80 h | semantic read-back for every declared canonical section |
| B5 metrics gate | 16–24 h | independent per-input references and drift matrix |
| B6 eight-API integration | 32–48 h | preview/commit/reset mutations across sections |
| B7 universal matrix | 80–160 h plus data acquisition | independently authorized classes, property/combination tests |

The next implementation step is B1 plus the catalog-inventory portion of B2. Owner authorization is
required before acquiring a new snapshot or independent class fixture. The eight Application APIs,
Browser Infrastructure, engine formulas, snapshot, Release, and CI trust policy remain unchanged.
