# d4-rulekit — Issue #107

A **standalone** Python package for OpenStream D4 Rule DSL **schema contract (G1)**.
There is no game capture, network crawler, formula evaluator, AI model, or combat simulator.
The contract is a **candidate**, not Owner-approved Blizzard mechanics.

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
