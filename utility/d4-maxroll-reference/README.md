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
