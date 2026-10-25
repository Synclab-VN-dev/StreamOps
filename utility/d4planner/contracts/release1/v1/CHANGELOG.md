# Contract changelog

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
