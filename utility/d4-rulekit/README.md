# d4-rulekit — Issue #107

A **standalone** Python package for OpenStream D4 Rule DSL **schema contract (G1)**.
There is no game capture, network crawler, formula evaluator, AI model, or combat simulator.
The execution source is **Maxroll-only** on Owner-pinned patch/build 3.2.1.73552. The contract is not a verified formula engine.

## Why independent?

`utility/d4planner` contains NVDA capture/CLI; `utility/d4-rulekit` contains versioned rule
definitions and deterministic schema validation only. Agent/crawler, semantic gate (G2),
calculation gate (G3), coverage (G4), formula graph and DPS simulator belong to #108–#111.

## Install and run

```bash
python -m pip install -e 'utility/d4-rulekit[dev]'
d4-rulekit schema-check
d4-rulekit validate utility/d4-rulekit/fixtures/valid/*.json
python -m pytest -q utility/d4-rulekit/tests
```

Exit status: 0 = G1 PASS, 1 = schema INVALID, 2 = unreadable JSON/BLOCKED.
Each CLI run can save a deterministic JSON report with `--report path.json`.

## Contract review

- [Rule Schema v1 candidate](src/d4_rulekit/schemas/rule-v1.schema.json)
- [Execution contract](docs/execution-contract.md)
- [Operator catalog](docs/operators.md)
- [Versioning](docs/versioning.md)
- [Fixtures](fixtures/valid/)

Examples are **synthetic only**. A schema-valid rule is not verified to match real D4 game
mechanics, to resolve references, or to calculate DPS. Never promote synthetic examples to
production data. Missing rules must be reported; do not silently assume zero impact.

No changes to FE, MagicPath, StreamOps runtime, OBS, or GitHub repo settings.

## CI-03: Maxroll-only pinned execution contract (parity BLOCKED)

- **Canonical semantics:** `contracts/execution-v1.json` (not the JSON Schema).
- **Active evidence:** `docs/maxroll-baseline-3.2.1.73552.md`. The old Blizzard register is HISTORICAL/RETIRED, not an active oracle.
- **Active reference manifest:** `references/3.2.1.73552/ci03-reference-vectors.json`; 0 approved Goldens, 50 UI display candidates under partial inputs. Old 3.2.3 references are historical and excluded.
- **Negative regression:** `tests/test_execution_contract.py`.
- **Workflow:** `.github/workflows/d4-rulekit.yml` executes G1 and CI-03 independently.

```bash
python -m d4_rulekit.contract_check \
  --contract utility/d4-rulekit/contracts/execution-v1.json \
  --references utility/d4-rulekit/references/3.2.1.73552/ci03-reference-vectors.json \
  --report artifacts/d4-rulekit/ci03-contract.json
```

Returns exit 0 (structural/contract PASS), 1 (contract FAIL), 2 (missing data BLOCKED). The report deliberately states `maxrollParity=BLOCKED_NO_APPROVED_GOLDEN`, so CI-03 PASS must never be interpreted as Maxroll formula parity.
`gameAccuracy=NOT_VERIFIED_BY_CI03` always: implementation is **not** a combat simulator.
