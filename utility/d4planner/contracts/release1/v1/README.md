# D4Planner Release 1 integration contract

Contract revision: `d4planner-r1-contract/1.0.0-candidate.6`

This directory is the versioned S1 handoff for issue #138 and scope baseline
`R1-EQUIPMENT-20261025`. It specifies contracts only; it does not implement a
Windows process wrapper, WebSocket server, assessment runtime, or HUD.

## Normative files

| File | Purpose |
| --- | --- |
| `adr-001-integration-boundaries.md` | Ownership, lifecycle state machine, sequences, security/capacity rules |
| `interfaces.ts` | Language-neutral ports; opaque payload references to schemas, not duplicate wire types |
| `schemas/target.schema.json` | D4Planner target envelope and assessment policy; references canonical Rule Kit `d4-build/v1` unchanged |
| `schemas/hud.schema.json` | Committed Equipment-only HUD read model |
| `schemas/ws.schema.json` | Notification-only authenticated loopback messages |
| `db-first.md`, `schemas/hud-db.schema.json`, `hud-db.sql` | Public SQLite projection and compatibility |
| `schemas/command.schema.json` | Managed BE IPC business commands |
| `schemas/process-event.schema.json` | Reviewable lifecycle trace events |
| `fixtures/` | Synthetic examples and independent truth/sequence vectors |
| `ui-data-dictionary.md` | UI field provenance and MagicPath delta constraints |
| `decisions-and-dependencies.md` | One decision table and S1/S2-S7 acceptance ownership |


JSON Schemas use JSON Schema Draft 2020-12 and are closed by default. The
canonical build is validated against
`utility/d4-rulekit/providers/maxroll/d4-build-v1.schema.json`; policy fields
remain in the D4Planner envelope and are never added to that Rule Kit schema.

## Compatibility and activation

- `schemaVersion`, `policy.version`, `protocolVersion`, and the contract
  revision are exact compatibility keys. An unknown major/version is rejected.
- A target list entry is a point-in-time descriptor. Selection sends only
  `targetId` plus the listed SHA-256. The backend resolves within its configured
  root, reads bytes again, validates both schemas and semantic uniqueness, and
  activates only if the bytes still match that hash.
- The approved policy is `r1-equipment-weights/1.0.0`: core weight `3`,
  non-core weight `1`, linked to the Owner decision in #138. Synthetic fixtures
  remain labelled synthetic; approval of policy does not make them game data.
- Skills, Paragon, Charms and other non-Equipment canonical fields are preserved byte-for-byte
  as target content but are outside Equipment scoring in Release 1.

## Local verification

From the repository root:

```bash
python -m pip install -e "utility/d4planner[dev]"
python -m pytest -q utility/d4planner/tests/contracts/test_release1_contract.py
```

These are schema and deterministic contract-model tests. They are not Windows
process, real WebSocket, Chromium, capture, game, OBS, or Steam Link E2E tests.

## Reading and ownership

Read the ADR for invariants, the schemas for serialized payloads, interfaces for
ports, the UI dictionary for field-to-view mapping, and decisions/dependencies
for approval and acceptance ownership. Fixtures are synthetic examples, not a
second contract. TypeScript payload aliases identify exact schema pointers; they
are opaque until validated and deliberately do not duplicate partial field lists.
For example, the HUD schema requires producedAt, health, recommendation,
provenance and score.evaluationCounts in addition to identity/equipment/score.

Historical review traces (REV-01–08, Linux base-vs-PR failures and CI harness
rationale) are preserved in the [archived handoff comment](https://github.com/Synclab-VN-dev/StreamOps/pull/145#issuecomment-6463875984).
The Issue87 isolated CI harness and its tests remain in this PR because the S1
schema validator dependency must be installed in that harness's private venv;
removing them would restore the known collection failure. They are not a change
to production process lifecycle.

## Historical documentation cleanup — 2026-10-28

Wire revision remains candidate.5: no schema, fixture, scoring policy, API or
serialized required-field changes. Removed incomplete duplicate payload sketches
from interfaces, consolidated history below, and archived review-run evidence in
PR comments. Target-entry minimum length and content-hash semantics are unchanged;
S4 producer failures belong to #147, not a schema relaxation.

## 1.0.0-candidate.6 — 2026-10-31

D5 replaces full-HUD WS with a versioned public SQLite projection, notification-only
WS and correlated Target commands on the owned BE pipe. FE viewer-only is independent
of BE readiness. See [normative DB-first contract](db-first.md). D1–D4 and the eight
Rule Kit Application APIs are unchanged. Runtime gates require downstream evidence.

<details>
<summary>Contract candidate history</summary>


## 1.0.0-candidate.5 — 2026-10-25

- Fixed S1-REV-08: `hello.accepted` now distinguishes a reconnect to the same
  runtime instance/generation from a new backend identity. Same-backend
  reconnect preserves the HUD revision high-water mark and known context while
  clearing connection-bound correlation/subscription/recovery state.
- Marked the retained assessment non-current until an authoritative resync
  confirms or advances it. Older snapshots, and snapshots/updates from the old
  connection, cannot roll state back.
- Kept fresh discovery/reset semantics only when runtime instance or generation
  changes, allowing the new backend's revision sequence to restart safely.
- Added HELLO_ACCEPTED-driven vectors for stale/equal/newer snapshots,
  subsequent updates, backend restart, late old-connection traffic and
  REV-07 context-change recovery after reconnect.

## 1.0.0-candidate.4 — 2026-10-25

- Fixed S1-REV-07: a fresh, correlated known-context snapshot that reveals an
  active character/Target change is not applied directly. It consumes the old
  request, invalidates the old assessment and starts bounded active-context
  discovery with a revision floor at the observed authoritative revision.
- Added discovery reason/attempt fields, finite operation timeout/retry policy,
  late-response rejection and exhaustion behavior. Recovery accepts subsequent
  incremental updates only on the newly established subscription.
- Added schema-to-reducer and synthetic sequence coverage for TARGET_ONLY→BOUND,
  Target A→B, unchanged context, stale/correlation/instance/generation guards,
  post-recovery updates and bounded timeout exhaustion.

## 1.0.0-candidate.3 — 2026-10-25

- Split snapshot requests into `DISCOVER_ACTIVE_CONTEXT` for a newly connected
  FE and `RESYNC_KNOWN_CONTEXT` for exact-context recovery. Discovery accepts
  the BE's one active character/Target context while retaining correlation,
  instance, generation, revision and internal binding validation.
- Allowed contiguous committed updates to transition STARTUP/TARGET_ONLY to the
  one active character and to invalidate a reidentified character's old result;
  no character selector/profile management was added.
- Made incompatible `EQUAL` type/unit pairs UNKNOWN and non-evaluable before
  value comparison, including Python's `True == 1` edge case.
- Applied D3: latency is ASAP with no deliberate delay/polling or invented SLA;
  retain stage timestamps/P50/P95. HUD capture reuses StreamOps
  `window_capture`; real-window verification remains S6/S7.

## 1.0.0-candidate.2 — 2026-10-25

- Applied Owner-approved D1/D2, Pin always-on-top semantics and MagicPath
  revision `464988421014827008` from #138 comment `6394334041`.
- Added discriminated startup/target/character/bound/unavailable HUD contexts;
  removed fake-ID requirements and invalidated stale bindings on context change.
- Split authoritative snapshots from incremental updates. Same-generation
  correlated snapshots now recover gaps/reconnects without accepting stale,
  wrong-generation, wrong-context or late responses.
- Replaced untyped scalar criteria with typed comparator operands, explicit
  source group/occurrence and multi-parameter `ALL` aggregation. One criterion
  remains one weight and at most one issue.
- Embedded BE-produced display labels/text and capture provenance needed to
  render the approved Equipment/Compare UI without FE catalog/file/DB lookup.
- Removed Coverage as a HUD presentation requirement. Evaluation counts remain
  internal metadata for score audit and diagnostics.

## 1.0.0-candidate.1 — 2026-10-25

- Initial S1 candidate reviewed at `b6c7c901f8474414c78e895aa1176cf962e865e9`.

</details>
