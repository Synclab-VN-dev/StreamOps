# BE-01 #106 — Offensive Formula & Combat Mechanics design v0.1

**Status:** PR candidate; requires CI, Agent DF-01 and Owner MAN-01. This is not an
approved Diablo IV combat engine, gameplay capture implementation, ruleset, or
a claim of complete game accuracy. #107's shipped DSL/CI-03 stays unchanged.

## Version and evidence boundary

- Design reference: **3.2.3 / 73883**, patch identity sourced from Blizzard
  notes [blizzard-patch-3-2-3] in mechanics.json.
- Observed Maxroll: **3.2.1 / 73552**, Season 15; game version differs
  from the reference baseline. Its formula asset was reported as
  export-DOjdL1l3.js, SHA-256
  e796b92751d0b07be8b10eed705727467e23ba0d99eb088e87de88942c57a1f4.
  This is Agent-reported runtime evidence, not a Blizzard authoritative source.
- Refer to mechanic/source IDs and ticket #106 Agent reports linked in mechanics.json.
  Gitignored Agent raw evidence resides on F; no raw CDP bytes are committed here.
- **NO cross-patch promotion.** For patch 3.2.3, 3.2.1 observations remain
  observational research/fixture evidence, not approved formula rules.
- Missing interpretation yields UNKNOWN/UNVERIFIED with no numeric fallback.

## Definitions — do not conflate these quantities

| Term | Meaning | Status |
|---|---|---|
| rawWeaponAverage | minDamage + (maxDamage - minDamage)/2, before modifiers | sample-scoped observations, not all weapon routing |
| sheet/headline damage | planner's stat/UI expression, may be speed-scaled | P1-R/V/V2 runtime vectors, only patch 3.2.1 |
| perSkillEventDamage | magnitude of an individual skill event at a target | rank/weapon samples observed, not a sustained rate |
| sustainedSkillDps | time-horizon expected or simulated damage / elapsed seconds | **UNKNOWN** game-specific cast cadence/resource/cooldown/proc behavior |
| crit expected value | damage weighting from chance and conditional multiplier | **SYNTHETIC** illustration until rules/patch supplied |
| proc expected contribution | probability-weighted child event contribution | **SYNTHETIC**, not a guarantee a proc triggers an additional cast |

### Explicitly bounded Maxroll observations

1. **Headline on one recorded build:** average effective weapon 3456;
   stat factor 1 + 2402.25*1.25/1000 = 4.0028125; additive factor
   1 + 2.1355 = 3.1355; pre-speed 43375.62906; *1.2 = 52050.754872;
   UI 52051. This is a patch/profile-specific calculation observed in
   [maxroll-p1r], not generic DPS.
2. **Weapon and rank controlled examples:** Battle Bow avg 3450, speed 1.10,
   headline 3795; Crossbow avg 4218, speed 0.90, headline 3796.
   Penetrating Shot rank 1/2/3 UI samples 5175, 5692, 6210
   ([maxroll-p1v]). Rank 2's derived raw ~5692.62375 points toward
   truncation on that positive tooltip path but the historical runtime raw and
   formatter have **not** been independently captured. Headline has a
   distinct rounding path. Do not declare universal rounding.
3. **Additive All Damage:** independent UI changes +30%/+60% produced
   headline raw 4933.60725 / 6072.132; displayed 4934 / 6072.
   Distinguish this stat branch from the full All Damage UI row or
   per-event skill raw, which was source-derived only ([maxroll-p1v2]).
4. **Main-Hand bonus:** Necromancer axe+shield fixture changed
   Main_Hand_Damage_Percent_Bonus 0→1, headline raw
   1948.703625→3897.40725 and UI 1949→3897
   ([maxroll-p1v2]). One nonzero vector, not a universal formula.
5. **Do not promote:** Multiplier x12%/x20% item label did not activate
   canonical Maxroll state, therefore invalid fixture, not evidence of zero
   multiplicative behavior. Crit Chance -93.8% on a profile is an anomaly,
   not an accepted negative-chance rule. No Maxroll sustained-skill-DPS
   runtime/UI oracle was found.

## Proposed stage/event graph (ENGINE CONVENTION, not asserted Blizzard timing)

1. Build/patch gate: load TargetBuild equipment, affixes, stats, active skills,
   paragon/glyph/charm/season flags and *pin source patch*. Missing critical
   sources abort numeric promotion, rather than assume inactive/zero.
2. Pre-skill: resolve skill ranks, variants and tag transforms before
   tag-filtered rules; reject unknown or conflicting effect precedence.
3. Cast eligibility: input rotation, resource/cooldown, animation lock,
   minimum cast spacing, actor and target. Snapshot semantics must come from a
   verified per-rule declaration or remain UNKNOWN.
4. On-cast: create skill events, projectile children and source provenance;
   do not count a triggered skill as the same event as a direct cast.
5. Pre-hit/on-hit: evaluate target selection/hit probability and
   patch-scoped damage/modifier buckets, then crit/vulnerable/overpower/armor.
   Damage types and hit counts are per event, not single actor-wide scalars.
6. Post-hit: schedule proc/triggered child events only with explicit chance,
   inherited tags, per-cast/per-hit gating, ICD, bounded depth and cycle guard.
7. On-tick/state expiration: queue periodic DoT, summons and buff/stack
   changes; snapshot-vs-dynamic, same-timestamp ordering and stack refresh
   policies are UNKNOWN until rule-specific evidence. Synthetic test
   conventions don't establish real Blizzard event order.
8. Aggregate by time and provenance: directSkillDamage, triggeredDamage,
   periodicDamage, separate per-skill DPS and totalModeledDps plus assumptions.
   Never call a sheet value sustained DPS.

## Candidate I/O contract (DESIGN ONLY; not API transport)

**Input** must include gamePatch+build, selected target build JSON,
ruleRegistryVersion/hash, scenario (boss-single-target or AoE with targets),
timeHorizonSeconds > 0, rotationPolicy (ordered priority/skill/event),
randomSeed and/or expectationPolicy, actor state (resource/cooldown/time),
target properties (armor/resist/vulnerable/immune), skill/attack cadence
assumptions and source provenance. All percentages carry explicit units:
ratio 0.2 ≠ percent 20. Typed IDs for class/skill/slot, and rule IDs from
the #107 DSL contract; arbitrary executable code is forbidden.

**Output** must identify patch/rule/graph hash and supported vs UNKNOWN
calculations. Provide raw event contributions (direct/triggered/periodic,
per target), window damage, perSkillDirectDps, perSkillTriggeredDps,
periodicDps, totalModeledDps, confidence and missing-rule diagnostics.
Probability-weighted *expected* damage and fixed-seed simulated damage
must have distinct output tags; neither may be presented as a verified
Blizzard benchmark solely because the synthetic unit tests passed.

**Failure semantics:** target immune -> damage zero **only if a verified
rule/scenario marks immunity explicitly**; missing rules -> UNKNOWN/BLOCKED,
not zero. Patch mismatch, cycles, unknown crit caps/inheritance/timing
fail closed; no silently truncated DPS. The 3.2.1 data must never
be silently evaluated as baseline 3.2.3.

## Formula/operator reference examples (SYNTHETIC, no game claim)

- Independent additive bucket: factor = 1 + sum(bonus ratios).
- Independent multiplier group: factor = product(factors).
- Expected crit illustration: base * (1 + min(chance, cap)*extraCritRatio).
  Clamping is a **synthetic test convention only**; negative observed crit
  on Maxroll is not proof this is Diablo IV behavior.
- Multi-hit expected value: perHit * hits * hitProbability.
- Proc illustration: directHit + procChance * childHit
  for one permitted child and no ICD; 0% and 100% are tested.
- DoT illustration: tickDamage * tickCount, with exact tick timing,
  snapshots, expiration boundaries and clipping **unverified**.
- Buff expected uptime illustration:
  baseHit*(1+uptime*(min(stacks,cap)*perStackBonus)), not a rotation model.
- Event sorting in synthetic example: (timestamp, phase, stable ID).
  This is a deterministic engine design convention, **not verified game
  internal order**. Unknown simultaneous expiration policy stays UNKNOWN.

## Coverage and closure matrix

The file mechanics.json enumerates 20 **candidate** mechanic topics in
nine groups. There is no sourced complete denominator for all D4
skill/affix/aspect/unique/paragon/glyph/charm/set/class/season interactions;
therefore global coverage percentage is **NULL/UNKNOWN**, never "100%".

- **#106**: versioned design inventory, source provenance, synthetic fixtures,
  independent arithmetic tests, unknown/bounded scope and Owner design review.
- **#108 G2/G3/G4**: semantic checks, rule-specific independent validation and
  patch coverage audit with an actual sourced denominator.
- **#109**: rule-source ingestion, validity and patch registry.
- **#110**: dynamic rule resolution and typed formula graph for arbitrary builds.
- **#111**: event-based combat simulator, sustained DPS, time/rate assumptions,
  multi-build E2E, RNG variance, DoT, ICD and proc fidelity.
- **#102** FE scoring adapter: distinct, previously unapproved integration;
  no FE changes as part of this ticket.

## #106 acceptance policy

- CI-01: machine-check source IDs, scope, patch guard, taxonomy and missing
  mechanic representation. A PASS is **design inventory consistency only**.
- CI-02: at least three independent synthetic families (direct modifier,
  proc-chain, buff-stack), plus additive/multiplicative/crit/multihit/DoT,
  0/100/cap/immunity/order/cycle/patch edge vectors. Independent Decimal
  arithmetic prevents simply trusting a saved expected value.
- CI-03: regression for missing sources, synthetic→official promotion,
  runtime patch mismatch and UNKNOWN numeric fallback, with deterministic
  reports. A PASS does **not** imply Maxroll/Blizzard formula correctness.
- DF-01: Agent verifies matrix, source links, raw report artifacts and
  repeatable negative regression, then comments to #106.
- MAN-01: Owner reviews and explicitly approves **design**; no PR merge
  or release without additional approval.

The current CLI report always records MAN-01=PENDING while in a draft PR.
