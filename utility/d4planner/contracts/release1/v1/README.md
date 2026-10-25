# D4Planner Release 1 integration contract

Contract revision: `d4planner-r1-contract/1.0.0-candidate.5`

This directory is the versioned S1 handoff for issue #138 and scope baseline
`R1-EQUIPMENT-20261025`. It specifies contracts only; it does not implement a
Windows process wrapper, WebSocket server, assessment runtime, or HUD.

## Normative files

| File | Purpose |
| --- | --- |
| `adr-001-integration-boundaries.md` | Ownership, lifecycle state machine, sequences, security/capacity rules |
| `interfaces.ts` | Language-neutral TypeScript-shaped ports for S2-S6 |
| `schemas/target.schema.json` | D4Planner target envelope and assessment policy; references canonical Rule Kit `d4-build/v1` unchanged |
| `schemas/hud.schema.json` | Committed Equipment-only HUD read model |
| `schemas/ws.schema.json` | Loopback WebSocket application messages |
| `schemas/process-event.schema.json` | Reviewable lifecycle trace events |
| `fixtures/` | Synthetic examples and independent truth/sequence vectors |
| `ui-data-dictionary.md` | UI field provenance and MagicPath delta constraints |
| `decisions-and-dependencies.md` | One decision table and S1/S2-S7 acceptance ownership |
| `review-handoff.md` | S1 review findings, correction evidence and base-vs-PR regression comparison |

JSON Schemas use JSON Schema Draft 2020-12 and are closed by default. The
canonical build is validated against
`utility/d4-rulekit/providers/maxroll/d4-build-v1.schema.json`; policy fields
remain in the D4Planner envelope and are never added to that Rule Kit schema.

## Compatibility and activation

- `schemaVersion`, `policy.version`, `protocolVersion`, and the contract
  revision are exact compatibility keys. An unknown major/version is rejected.
- A target list entry is a point-in-time descriptor. Selection sends only
  `targetId` plus the listed SHA-256. The backend resolves within its configured
  root, reads bytes again, validates both schemas and semantic uniqueness, and
  activates only if the bytes still match that hash.
- The approved policy is `r1-equipment-weights/1.0.0`: core weight `3`,
  non-core weight `1`, linked to the Owner decision in #138. Synthetic fixtures
  remain labelled synthetic; approval of policy does not make them game data.
- Skills, Paragon, effects and other canonical fields are preserved byte-for-byte
  as target content but are outside Equipment scoring in Release 1.

## Local verification

From the repository root:

```bash
python -m pip install -e "utility/d4planner[dev]"
python -m pytest -q utility/d4planner/tests/contracts/test_release1_contract.py
```

These are schema and deterministic contract-model tests. They are not Windows
process, real WebSocket, Chromium, capture, game, OBS, or Steam Link E2E tests.

See `CHANGELOG.md` for candidate-to-candidate review corrections.
