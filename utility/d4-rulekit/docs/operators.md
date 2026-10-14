# Operator catalog v1 (proposed)

All operators live in the `$defs.action.oneOf` discriminated union. The catalog is a
**contract proposal**: individual runtime semantics and patch-accurate formulas require
the Owner checkpoint and downstream G2/G3 validation.

| Operator | Mathematical/state intention | Phase considerations |
|---|---|---|
| `modify_stat` | typed add/multiply/set/cap over stat and scope | bucket, priority, snapshot, patch |
| `modify_skill` | change coefficient, cost, timing, projectile/summon parameters | pre_transform/pre_cast |
| `transform_tags` | alter skill tag/category/element classification | before tag-based applicability |
| `deal_damage` | create scoped damage event (not instant DPS scalar) | event time/target |
| `spawn_projectile` | create projectile entities with target and hit model | may yield zero/many hits |
| `trigger_skill` | schedule explicit triggered skill cast | resource/proc inheritance |
| `apply_state` | add buff/debuff/stack with expiration model | state lifecycle |
| `remove_state` | revoke buff/debuff/stack | state lifecycle |
| `modify_resource` | add/consume/set class resource | cast feasibility |
| `modify_cooldown` | adjust remaining cooldown or charges | cast scheduling |
| `spawn_entity` | create minion/companion/etc. with independent state | tick/AI events |
| `heal` | apply healing event to target | life cap and effects |
| `grant_barrier` | create Barrier with duration/stack semantics | defensive state |
| `emit_event` | enqueue typed event with parent provenance | recursion guard |
| `override_rule` | replace/disable a selected rule | priority/conflict detection |

## Requirements before engine execution

- Operators are never executed by `eval`, `exec` or sandboxless script expressions.
- Do not conflate damage additive buckets with true independent multipliers.
- A projectile-count modifier cannot directly be replaced by a DPS multiplier.
- Effects tagged `verified` require **independent** game-mechanics evidence; unverified input
  cannot silently receive certified DPS/accuracy.
- G2 must check field types, units, reference existence, valid order/phase and impossible stacks.
- Exact `math`, `stage`, `who`, `snapshot` allowable enum definitions: inspect
  the actual JSON Schema as source of truth, not this summary.
