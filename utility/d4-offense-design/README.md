# d4-offense-design — BE-01 / Issue #106

Design-only research inventory and fail-closed reference fixtures for generic
Diablo IV Offensive mechanics. Independent from the approved #107 Rule DSL
implementation, which this PR does **not** modify. No Combat Simulator, no
Maxroll scraper, no runtime gameplay capture and no FE/UI changes.

## Source and audit

- [Design specification](DESIGN.md)
- [Mechanic inventory and source register](mechanics.json)
- [Three synthetic mechanism fixtures](fixtures.json)
- [Independent edge/reference vector matrix](vectors.json)
- [Fail-closed Python design gate](check.py)
- [Negative/unit regression](tests/test_design_gate.py)
- [Dedicated CI workflow](../../.github/workflows/d4-offense-design.yml)

The inventory includes report-level Maxroll research from patch
**3.2.1.73552** with GitHub comment provenance, *not* raw gitignored CDP logs.
The proposed design baseline is **3.2.3/73883**; patch promotion is forbidden
without patch-specific evidence. Synthetic arithmetic is only illustrative.

Run with Python 3.12+ and **no third-party dependencies**:

~~~bash
python utility/d4-offense-design/check.py \
  --report artifacts/d4-offense-design/ci-gates.json
python -m unittest discover \
  -s utility/d4-offense-design/tests -p 'test_*.py' -v
~~~

- Gate exit **0 PASS** means source/patch contract plus synthetic vectors
  internally consistent, **not game accurate**.
- Exit **1 FAIL** denotes a broken design vector, provenance or policy.
- Exit **2 BLOCKED** denotes missing/unreadable input.
- Report lists CI-01/02/03 gates and marks **MAN-01 PENDING**.
- Mechanic inventory includes 20 candidate topics, but total game coverage
  denominator is UNKNOWN; no invented coverage percentage.

Changes to approved #107 schema/execution semantics, official mechanic
classification, product code, runtime simulator or FE/API need separate
review/Owner approval. No GitHub settings, merge or deployment is in scope.
