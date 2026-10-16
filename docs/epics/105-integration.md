# Epic #105 — integration branch and acceptance ledger

Canonical owner review PR: Epic #105 `feat/105-epic-integration` → `master`.
All children target this branch; parent PR remains Draft. Child PR merges into Epic are **not** merges into master or owner approval of product accuracy.

## Owner-locked computation pipeline

```text
Target Build JSON + exact-patch Rule Registry
  → Rule Resolver
  → Dynamic Formula Graph [ALL Maxroll Character/Skill Metrics + simulationContext]
  → [#108 independent Maxroll Character Metrics parity CI gate]
  → Event-Based Combat Simulator [OFFENSE ONLY]
  → Offensive Metrics [per-skill/triggered/periodic/total modeled DPS]
  → [Future score consumer, OUTSIDE Epic #105]
```

Graph must emit per-metric IDs, groups, units, raw/display, status, source/effect trace, patch, and UNKNOWN diagnostics; simulationContext carries trigger, conditional, stack, resource and timing semantics. The simulator must consume Graph results without reimplementing stat calculations. The #108 gate is a validation gate, **not an extra runtime stage**.

An overall score (0–100), Torment readiness, Defense/Sustain combat simulation, and FE Current-vs-Target scoring are **out of scope** of Epic #105. Do not invent score weights or baselines; separate BE↔FE scoring contract / #102 remains required. Maxroll UI metrics are the pinned validation reference, not an official sustained-DPS oracle.

## Single-PR-per-ticket topology

- #106: PR #113 (canonical); nested #114 already merged into #113.
- #107: PR #115 (rebaseline); original Schema v1 PR #112 already merged into master.
- #108: PR #116 (fail-closed structural Golden/Parity gate; real parity BLOCKED).
- #109: no PR; patch-aware Rule Registry needs source-graded rules.
- #110: no PR; actual Dynamic Formula Graph missing.
- #111: no PR; offense-only Event-Based Combat Simulator missing.

Any B1 sub-PR targets its ticket's canonical PR branch first. Every canonical child PR targets this Epic branch, **never independently master**. Only the Epic parent PR is presented for final Owner review/merge when all acceptance is met.

## Strict evidence / integration gates

- Owner-pinned source cohort: Maxroll `3.2.1.73552` (not a claim of globally latest). Historical `3.2.3/73883` design/Blizzard records are **inactive** for Maxroll parity. Do not silently copy between patches.
- Per fixture, enumerate all captured visible Maxroll metrics including Core, Offensive, Defensive, Resistances, Utility, class-specific; independently observed expected Golden must match complete patch/class/level/build/gear/skills/conditions. No self-generated or AI-generated Golden.
- Unsupported or unknown item/effect/skill/formula must remain `UNKNOWN/UNVERIFIED/BLOCKED`, never a fallback zero or invented score. Archived observations, synthetic vectors and approved independent real Golden have separate grades.
- A child PR can enter Epic only with source/evidence for its **bounded implementation scope**, exact-HEAD CI/unit/negative regression and no false product PASS. The Epic may contain incomplete modules but must expose their blockers, never mark Epic accepted until real E2E passes.
- Owner delegates routine engineering, archived source audit and CI to ChatGPT. Dev F only for targeted, unautomatable environment/browser evidence; Owner is contacted for such checkpoints and actual new design/contract changes.
- No implementation of new unverified game formulas or expansion of scoring scope. Do not automatically merge Epic to master, deploy, run Steam/OBS/D4, change rulesets or FE/MagicPath.
- #105 final gates: all 6 child acceptance records; #108 independent Maxroll Golden-vs-Graph parity with meaningful group coverage; #110 complete enumerated stats; #111 two mechanically distinct Target Build E2E with reproducible DPS breakdown, patch/source/hash traces and fail-closed negative cases.

## Working status before integration

| Ticket | PR | Evidence-backed implementation | True Maxroll/product gate |
|---|---|---|---|
| #106 | #113 | Offensive design; Rogue 50-ID catalog; audited bounded source evidence | 0 fully verified / 27 bounded / 23 partial, not full formula parity |
| #107 | #115 | Maxroll rebaseline candidate, CI scoped PASS | independent Golden unavailable |
| #108 | #116 | negative/structural Golden gate, CI scoped PASS | BLOCKED: approved Golden and Graph actual missing |
| #109 | TBD | not implemented | PENDING |
| #110 | TBD | not implemented | PENDING |
| #111 | TBD | not implemented | PENDING |

No new formula, score, simulator, Golden or approved API is created by this integration document. Parent remains Draft until all evidence and Owner checkpoints are complete.
