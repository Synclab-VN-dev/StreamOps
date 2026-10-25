# Contract changelog

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
