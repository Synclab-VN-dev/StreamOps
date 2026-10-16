# #108 Maxroll Rogue full Character-Stats parity gate — Owner baseline 3.2.1.73552

**Contract:** 50 visible Character Stats from the pinned Rogue Penetrating Shot Endgame level-70 variant `#3` (not a claim that Maxroll has only 50 stats across classes). This is an **offline strict acceptance gate**, not a formula evaluator, browser scraper or a source of fake Goldens.

**Actual evidence today:** F1 contains 50 Maxroll UI display-value candidates, F2 contains several CDP raw-value observations and limited causal source vectors. The input snapshot is still **PARTIAL** (9 unmapped sockets, 7 Paragon semantic labels and conditional states); **0 reviewed/approved Goldens, 0 complete 50-formula Graph outputs**. A prepared gate cannot truthfully claim 50/50 formula accuracy.

The gate takes **four independently owned artifacts**:
1. `rogue-3.2.1.73552-fixture.json` — exact Owner patch/build, class, level, variant, input fingerprint, full 50 metric denominator and per-category counts. Input completeness must become VERIFIED `COMPLETE` based on independent capture, not changed to silence a failing test.
2. `golden.json` (provided later by Dev F via reviewable sanitized Maxroll evidence) — 50 stat IDs, category, displayed values and raw only when observed independently, exact fixture+patch, each metric UI evidence ref, approval and original immutable capture manifest hash; SHA-256 of canonical `{fixture,metrics,vectors}` payload, `capturedPayloadSha256`. **Never compute these expected values using Formula Graph, AI inference, a synthetic vector or current actual output.**
3. `actual.json` (provided later by #110 graph) — same 50 identified stats, computed raw/display and trace under same exact pinned inputs/patch, graph and rule-registry hashes, plus computed outputs for independent changed-input vectors.
4. `formulas.json` (provided later by #109/#110) — precisely 50 metric formula IDs, expression references with cited evidence, `CAUSALLY_VERIFIED` status only after independent test, >=2 changed-input reference vector IDs for each.

**Comparison:** exact displayed string (preserving Maxroll format), optional exact Decimal raw comparison only if raw was independently observed. No guessed tolerances or auto-fixing negative Critical Strike Chance. Baseline 50 rows plus at least 2 independent changed-input 50-row vector snapshots. Each vector must have distinct source fingerprint, complete inputs, Maxroll source and evidence; formula references must match real vector IDs. Unequal dual wield, additive/multiplicative branches and conditional states must be reflected in vectors or correctly remain unverified.

**Statuses:**
- `BLOCKED` if missing inputs, Golden, formula, graph, references, patch/source/fixture mismatch, or incomplete 50 metric denominator. **This is the correct current result.**
- `FAIL` if independently accepted expected != computed Graph actual on any metric/vector (display or supported raw).
- `PASS` only after every entry and reference gate satisfies same-version fixture coverage, 50/50 baseline and independent vectors with no diff. It means **Maxroll parity for this fixed Rogue fixture and tested variations only**, not entire game or official Blizzard correctness.

**CI:** synthetic comparator/negative tests validate the harness only. The run deliberately invokes the *real pinned fixture without Goldens and actual* and expects exit 2 and `BLOCKED`. The GitHub Action can be SUCCESS as a **guardrail workflow** while Maxroll full parity itself is BLOCKED. Do not confuse these two statuses.

```bash
python -m unittest discover -s utility/d4-maxroll-parity/tests -p 'test_*.py' -v
python utility/d4-maxroll-parity/gate.py \
  --fixture utility/d4-maxroll-parity/rogue-3.2.1.73552-fixture.json \
  --report artifacts/maxroll-50-parity-readiness.json
# Exits 2 / BLOCKED until genuine reviewed Golden + Formula Graph available
```

This PR does **not** modify #107 DSL schema, the existing #113/#114/#115 drafts, #110 implementation, FE, MagicPath or release pipelines. Never merge without separate explicit Owner approval.
