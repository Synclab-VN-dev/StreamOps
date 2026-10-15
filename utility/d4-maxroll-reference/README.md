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
