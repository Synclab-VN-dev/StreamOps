# Issue #119 — attested slot/transition evidence consumer (CI-only contract)

The version-3 materializer consumes structured canonical SQLite `event_log`
records **only if an independent future producer can obtain trustworthy in-game
selected-container identity, visible slot indexes including empty cells, stable
item observation references, scan boundaries and a gap-free scan assertion.**

**No current Real-A NVDA `speech.raw` or `input.marker.raw` record supplies
this attestation.** A `CHEST n` utterance or a `Take/Equip` label is
not sufficient. This is a fail-closed *consumer*, not a new game controller,
UI, WebSocket, REST API, or runtime injector. Nothing in this PR starts,
restarts or deploys an observer on machine A.

## Canonical event types

All records must share the existing event-log `session_id`, monotonically
increasing `event_seq`, and have `source="verified-grid-v1"`:

- `items.scan.begin`: `scanId`, nonempty `characterId`, `container`
  (`inventory`, `stash`, `equipment`), `tab` (integer only for stash;
  null otherwise), `expectedSlots` (1–512), and a full `proof` with
  `observer="grid-observer-v1"`, `selectedContainerVerified=true`,
  `allSlotsAddressable=true`, `emptySlotsVisible=true` and
  `captureGapFree=true`.
- `items.scan.cell`: `scanId`, zero-based `slot`, `empty=true` for
  an explicitly observed empty slot, or `empty=false` plus an
  `observationId` referencing a **previously captured same-session**
  `speech.raw` item anchor (`obs:<session>:<sourceSeqStart>`) and optional
  `trackingToken` from a trusted observer. Never derive tokens from
  matching name, rarity, power, or affixes.
- `items.scan.end`: `scanId`, `expectedSlots`, `captureGapFree=true`.
  The consumer only commits `COMPLETE` when it has exactly the
  0..expectedSlots-1 grid positions with no repeated slot, invalid value,
  non-observation item or missing cell.
- `items.action.verified`: independent non-speech action evidence with
  `observer="grid-observer-v1"`, `confirmed=true`, `operation`
  (`move`, `equip`, `unequip`, `remove`), `trackingToken`,
  `characterId`; removal also needs `reason` (sell/salvage/drop/destroy).
  **Plain keyboard markers are never considered confirmation.**
- `items.move.verified`, `items.equip.verified`,
  `items.unequip.verified`: explicit matching four complete scans
  (`sourceBefore`, `destinationBefore`, `sourceAfter`,
  `destinationAfter`), integer source/destination slots, stable tracking
  token, and `actionSeq` referring to the verified action **between before
  and after scans**. Source slot must contain the tracked item before and be
  empty after; destination must be empty before and contain tracked item after.
- `items.remove.verified`: matching two full before/after scans of one
  container, a verified removal action between them, stable tracking token,
  and an explicit removal reason. Incomplete/partial scans never imply
  removal or pickup.

The materializer never mutates canonical `events.db`; it writes versioned
`owned_grid_scans`, `owned_grid_cells`, `owned_grid_current`,
`owned_grid_actions` and append-only `owned_grid_history` into the
existing `character.db` under the same checkpoint transaction as speech
observations. Replay is idempotent. Equal-looking physical items are
preserved by different slots and opaque observer tokens.

## Identity / status gate

Even a complete, independently attested grid for `characterId="A"`
does **not** prove that A is the active player when reading the CLI later.
`d4planner items` continues returning only known-high-confidence legacy
equipment by default. `items status --json` exposes the completed scans
under `coverage.verifiedScopes`, with `characterId` group and
`lastScanAt`; `coverage.overall` stays `PARTIAL` until the current
character is reliably selected. Internal `owned_items_scans.current()`
exposes the item positions for a specifically attested historical scope.
The unverified candidate list still requires `--include-unverified`.

`d4planner items history --json` and JSONL export include both raw tooltip
observations and attested `SCAN` / `MOVE` / `EQUIP` / `UNEQUIP` /
`REMOVAL` records. None is labelled `pickedUpAt` unless explicit pickup
evidence exists (not yet supported). Contradictory, stale, unsupported,
malformed, overlapping, missing-cell or cross-character assertions are
ignored or marked `INCOMPLETE/INVALID`, never elevated to confirmed.

## Acceptance split

CI synthetic fixtures establish that the *consumer* and its failure gates
behave correctly, **not** that NVDA can produce these direct attestations on
Windows A. Dev F must separately prove this on the deployed A environment;
the existing capture shows only tooltip/chest list names and is still
`PARTIAL`. The owner alone approves any changed external contract,
actual gameplay manipulation, deployment and eventual merge.
