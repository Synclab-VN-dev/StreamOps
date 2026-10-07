# D4Planner equipment golden fixture

Reference: #59

## Files

- `golden_2026-10-07.jsonl`: Real-A `speech.raw` capture exported from `d4planner logs -f --raw --from-end`.
- `golden_2026-10-07.expected.json`: human-reviewed resolver baseline for the same capture.

## Provenance

The original PowerShell `Tee-Object` export was UTF-16LE. The repository copy is transcoded to UTF-8 only so it can be consumed consistently by tests and GitHub tooling. Event order, JSON payload text, event sequence values and UI/accessibility artifacts are intentionally preserved.

Do not "clean up" HTML entities, odd punctuation or UI noise in the raw fixture. Normalization belongs in parser code and must remain testable against the raw evidence.

## Key baseline

The capture contains 929 events (`eventSeq 4020..4948`) and 28 `Item Power` anchors. Strong Wardrobe evidence resolves to 10 distinct equipped items.

Important resolver rule: exact `EQUIPPED` is context only. A current-equipment write requires strong evidence such as known slot context + valid item anchor + terminal `Unequip`. Candidate/comparison items ending in `Equip` must not overwrite current equipment.

Ring position is intentionally unresolved: both current rings use `slotFamily=ring` and `slotIndex=null` until positional evidence exists.

This draft PR intentionally adds fixture/evidence only. Production parser/projector implementation belongs to #59.
