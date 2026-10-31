# CI-03 decisions and constraints (candidate v1)

## Runtime semantics vs Blizzard mechanics

`contracts/execution-v1.json` is the **canonical machine-readable interpretation contract**.
The rules' `rule-v1.schema.json` validates shape; the execution contract binds all 15
operator discriminators to classes, declares event identities and fail-closed behavior.
Neither JSON file is a self-executing engine.

### Decisions supported now
1. Modifier actions and damage events are disjoint: `modify_stat` contributes a scoped
   modifier, whereas `deal_damage` schedules a typed event. No double counting.
2. Operator coverage is exact: schema action set == contract operator set.
3. Missing patch policy, override conflict, unverified snapshot/proc inheritance cannot silently
   generate a verified damage multiplier.
4. Gear multiplier reference aggregation is `1+sum(eligible values)`, not one product per
   gear affix. Inclusion in the eligible group is decided by the **patch-specific rule source**.
5. Storm Shephard **specific** 3.0.4 set bonuses may co-exist; not a universal set rule.
6. Historical Vulnerable 1.2 arithmetic is an isolated regression vector, not a 3.2.3 default.

### Engine implementation convention, NOT a proven Blizzard algorithm
Simultaneous events are sorted lexicographically by simulated timestamp, phase index,
priority and stable IDs for reproducibility only. This is an internal tie-break;
when the actual ordering can alter gameplay/DPS, it is flagged UNVERIFIED until
Blizzard evidence or independent empirical data resolves it.

### Open game-specific semantics (fail closed; covered downstream)
- Arbitrary damage bucket membership and unique Aspect multipliers.
- Source-dependent proc eligibility, trigger chains, ICD and inheritance; Lucky Hit
  and crit-roll inheritance are not guessed.
- Snapshot-at-cast vs dynamic tick values for DoTs, summons and channels.
- Exact Overpower stack consumption priorities, outgoing damage, and damage mitigation.
- Same-time state expiry vs damage hit order that could change numerical outcome.

Those uncertainties are **not test PASS for combat accuracy**. CI-03 validates the
explicit contract and its bounded official reference facts. G2/G3/G4 remain #108.

### Owner checkpoint
Current PR #112 schema candidate was approved prior to CI-03, but `execution-v1.json`
and these new interpretation decisions are material contract additions. They require
a scoped new Owner review before freezing v1 and merging. No authority for merge/deploy.
