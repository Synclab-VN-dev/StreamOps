# #106 Maxroll Character Stats capture contract — candidate v1

**Purpose:** deterministic shape and integrity checks for data independently observed on Maxroll in a disposable read-only browser on Linux F. This is a **design artifact / capture interface** for #106 F1 and #108 Golden Registry; not a formula solver, live scraper, game-truth claim, or Maxroll parity PASS.

- **versionEvidence:** exact observed Maxroll app/runtime version AND game patch/build, fixture URL, UTC capture time and browser evidence. Owner selected **Maxroll 3.2.1.73552** as active game patch/build baseline on 2026-10-16 (see [#107 decision](https://github.com/Synclab-VN-dev/StreamOps/issues/107#issuecomment-6203600278)). A separate app semantic version is **not mandatory** for this Owner-pinned baseline. It is NOT a claim that this is globally latest.
- **fixture:** class/level, selected profile/variant/context, build fingerprint, SHA256 of captured input snapshot, explicit COMPLETE/PARTIAL state and missing inputs.
- **groups:** enumerate ALL headings/visible stats on the pinned fixture, including Core, Offensive, Defensive, Resistances, Utility, class-specific and any new headings. Every row needs stable metric ID (or explicit unresolved ID), display text, unit, direct evidence ID and status. Raw numbers must only come from independently observed Maxroll runtime, never inferred from rounded UI.
- **coverage:** `visibleCount` and `totalVisibleMetrics` are per-fixture denominators; they must match enumerated rows. Global game coverage remains null, never 100% asserted.
- **formulaStatus:** UNKNOWN, SOURCE_OBSERVED or CAUSALLY_VERIFIED. A source trace is not causal verification; F1 read-only is NOT formula verification.
- **goldens:** frozen expected values must originate from Maxroll independently of StreamOps model output. Review/approval and hashes are prerequisites; synthetics cannot be promoted. CI checks artifact structure, NOT the real-world authenticity of claimed review signatures or parity.
- **patch:** never silently compare mismatched app/game versions or use Blizzard-sourced values as active Maxroll expected.

The checked-in `examples-synthetic.json` is illustrative only. It has fake data, unknown versions and `NOT_APPROVED`. It **must never** count as a Maxroll golden.

Offline CLI (Python 3.12 stdlib):

```bash
python utility/d4-maxroll-reference/check.py utility/d4-maxroll-reference/examples-synthetic.json --report artifacts/d4-maxroll-candidate.json
python -m unittest discover -s utility/d4-maxroll-reference/tests -p 'test_*.py' -v
```

`PASS_CANDIDATE_ONLY` = shape/denominator valid, **not version verified, input complete, golden approved, formula verified or graph parity**. `PASS_GOLDEN_RECORD_INTEGRITY` = record's required metadata present, NOT a Maxroll comparison. `FAIL` = validation errors. `BLOCKED` = missing/unreadable file. Published captured data must have an evidence manifest and be separately reviewed before #108 uses it in a metric parity gate.

No #107 schema/operator changes, no #113 modifications and no merge/release approval.

### Owner-pinned Maxroll patch policy

In Golden-record integrity mode, a capture can declare `versionEvidence.status=OWNER_PINNED_GAME_BUILD` with `gamePatch=3.2.1`, `gameBuild=73552`, `appVersion=null`, and `ownerBaselineEvidence=https://github.com/Synclab-VN-dev/StreamOps/issues/107#issuecomment-6203600278`. This only waives the separate app-semver requirement; it **does not waive complete and independently captured build inputs, immutable manifest hash, independent review or source attribution**. CI validates record shape, never self-certifies genuine Maxroll evidence or numeric formula parity.

## F2 research-only formula catalog

- Machine-readable: `f2-formula-catalog.json`, maintained separately from F1 synthetic fixture and approved-Golden registry.
- F2 source: https://github.com/Synclab-VN-dev/StreamOps/issues/106#issuecomment-6204088473
- Owner pin: **Maxroll 3.2.1.73552**, Rogue Penetrating Shot Endgame variant #3, same F1 input SHA.
- Inventory denominator: **50 visible stats** in this fixture (Summary 2; Core 5; Resistances 8; Offensive 20; Defensive 7; Utility 7; PvP 1). This dataset has **9 explicitly cataloged individual metric rows**, not 50 verified formulas. The six reported resistance component raw/display observations remain evidence in the F2 issue report; exact canonical inventory ID mapping and causal formulas are still pending.
- Each catalog record stores **source-graded reported raw/display values** separately from potential formula hypotheses, with unknown contributor/dependency/order fields. Fields not established by F2 are empty/UNKNOWN, not inferred as zero.
- Weapon Damage, Weapon Speed, Attack Speed Bonus are labeled **bounded evidence from previously tested disposable vectors**; not a causal replay on the pinned published Rogue fixture. Additive All Damage has bounded evidence, but its multiplier side remains unverified.
- Toughness mean and negative Critical Strike Chance arithmetic are **single-fixture explanations only**; not engine formulas. Negative raw Crit Chance remains negative as observed; no imagined clamp.
- Raw CDP artifacts remain local on Dev F; repository values are based on sanitized agent evidence and await independent inspection. `approvedGoldenCount=0`; no full metric or formula parity.
- No new Rule DSL operators or changes to #107, #113 or #115; #108 owns approved Golden parity, #109 rule registry, #110 Graph output, #111 offense-only simulator.

Offline gate:

```bash
python utility/d4-maxroll-reference/check_f2.py utility/d4-maxroll-reference/f2-formula-catalog.json --report artifacts/d4-maxroll-f2-catalog.json
python -m unittest discover -s utility/d4-maxroll-reference/tests -p 'test_*.py' -v
```

`PASS_RESEARCH_CATALOG_ONLY` means structural/provenance integrity **only**, not that Maxroll expected has been matched or all 50 formulas are solved. Wrong patch, absent source, fabricated Golden/parity, unsupported formula promotion or fake 100% coverage fail closed.


## F8 — 50-ID source inventory & formula-verification taxonomy (Owner approved 2026-10-16)

**Scope:** F8 is an _evidence inventory_, not the implementation of #110, an approved #108 Golden, or full formula coverage. F2's original 9 source-grade rows remain untouched. F8 imports the *50 exact Maxroll metric IDs* from F5's independently archived source report and one F5 published-f1 raw/display snapshot. Raw/display numbers are explicitly labeled **agent-reported source observations, not independently approved expected Goldens**.

| Evidence/source | Immutable anchor |
|---|---|
| Canonical F5 ID/legacy-status map | \`Synclab-VN-dev/synclab-agent@8fdf59a988b0425e789248a5f1898ef67b27314d\` — \`rogue-50-f5-gap-evidence.json\`, \`all50Status\` |
| Raw/display example | Same commit, \`rogue-50-f5-full50-snapshots.json\`, candidate \`published-f1\` |
| F7/F7.1/F7.2 bounded causal Fire DR research | [#106 F7.2 independent review](https://github.com/Synclab-VN-dev/StreamOps/issues/106#issuecomment-6212668905) |
| Taxonomy proposal & full 50-row mapping | [#106 50-status handoff](https://github.com/Synclab-VN-dev/StreamOps/issues/106#issuecomment-6215051801) |

**User-approved metric-level formula labels**, _separate from_ \`maxrollGraphParity\`:
- \`PARTIAL\`: incomplete causal inputs/ordering/branch proof; never interpret as zero or a valid DPS operand.
- \`BOUNDED_VERIFIED\`: source-backed observed/causal behavior restricted to explicit patch/fixture/inputs/precision. Not necessarily whole stat formula.
- \`VERIFIED\`: within an explicitly pinned support scope, every applicable input/helper/order/cap/condition branch has independent numeric evidence and regression tests. None of the 50 qualifies yet.
- \`BLOCKED\`: reserved for *branch/gate reason*, never a fourth metric-level label. The numeric validation status in #108 is independent (\`PASS/FAIL/BLOCKED/UNVERIFIED/NOT_APPLICABLE\`).

**F8 snapshot:** 0 VERIFIED; 27 BOUNDED_VERIFIED (26 F5 legacy VERIFIED conservatively *regraded, not fully re-audited* + one F7.2 Fire Resistance); 23 PARTIAL. This is a **provisional working classification**. The 26 old rows must undergo a per-metric evidence/branch audit before any higher confidence or \`VERIFIED\` promotion. F7.2 only validated rounded Rogue Resistance→DR candidate displays (67 recorded observations across L50/60/70, not 67 independent experiments), not exact unrounded helper or 90% cap. 0 approved Golden; 0/50 #108 Graph parity actual comparisons performed. Older 26 VERIFIED/24 PARTIAL source grades are preserved side by side.

**Input limitations:** Published Rogue variant has partial build reconstruction (4/13 sockets, seven unresolved Paragon labels, conditional state gaps). The catalog retains \`knownInputs/applicableEffects/dependencies=[]\` and \`orderStatus=UNKNOWN\` where no causal source-specific mapping is established; those are **gaps for follow-up**, not assertions that an item has no contributions. A source-reported output from incomplete inputs cannot establish a complete reproducible Formula Graph Golden.

Run offline:
\`\`\`bash
python utility/d4-maxroll-reference/check_f8.py utility/d4-maxroll-reference/f8-character-metric-catalog.json --report artifacts/d4-maxroll-f8-inventory.json
python -m unittest discover -s utility/d4-maxroll-reference/tests -p 'test_*.py' -v
\`\`\`

\`PASS_SOURCE_INVENTORY_ONLY\` means 50 unique IDs, preserved history, no unsupported status promotion, correct patch/fixture provenance and fail-closed incomplete-coverage policy. It **does not** mean 50 formula solutions or Maxroll parity. Dedicated negative tests cover dropped/duplicate/changed IDs, wrong groups, wrong patch, fake Goldens and formula helper/cap promotions.

**Handoff:**
- **#108:** use the 50-ID denominator only for the *pinned F5 fixture*, and collect **independently reviewed, input-COMPLETE** Golden expected values. Reject a partial F1 source fixture for complete parity. Source status is not Graph-vs-Maxroll parity status.
- **#109:** turn *supported, independently reviewed* hypotheses into patch-pinned candidate DSL rule data with evidence grades; unknown inputs stay unresolved. Do not convert this inventory into an active Rule Registry automatically.
- **#110:** use IDs/groups/open gaps to design \`FormulaGraphResult\` output and contribution traces. Do not treat F8 source-reported raw/display as independently calculated Graph results or silently fill unknown metrics with zero.
- **#111:** consumes #110 resolved stats + simulation context; no stat aggregation duplicated and no unsupported verified DPS.
- **#106 next evidence work:** independently audit the 26 legacy bounded rows, and obtain targeted causal dependency evidence only when it changes a required rule. Do not run 23-stat broad browser research or modify #107 schema. Merge/release still require separate authorization.
