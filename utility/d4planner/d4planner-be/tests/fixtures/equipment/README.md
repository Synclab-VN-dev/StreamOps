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

## Issue #199 Staff replay

`staff_real_a_2026-11-11.jsonl` comes from the event evidence attached to #199
(`issue-199-31bfae76-83c9-4e49-8bc0-1f94a6469dca.zip.age`). It contains the
78 events at sequences 377–454, including the input marker, Two-Handed header,
Staff of Lam Esen tooltip, terminal Unequip at 419, and navigation to Boots.
Speech text, timestamps, order and sequence numbers are preserved. The export
normalizes the envelope to eventSeq/sessionId, substitutes a fixture session ID,
and omits machine/process identifiers and redundant rawSpeech arrays.

The preceding character-selection evidence is in a different capture session;
this fixture deliberately does not claim a verified active character class.

`staff_full_a_2026-11-13.jsonl` is the second #199 capture: 1,278 speech
and 72 Steam Input marker events, covering 9 equipped and 11 bag items. It
preserves speech/order/timestamps, substitutes a fixture session ID and omits
process/window details. Staff is completed at sequence 513, with bag comparison
copies later in the stream. No active class/character identity is asserted.

`verified_equipment_layouts.json` is derived from the installed validated
Maxroll UI snapshot recorded in its provenance. Provider slots 7/6 denote the
main/off-hand pair; 8–12 are other weapon topologies and are not collapsed into
that pair. The production adapter reads this evidence from the selected verified
snapshot, not this fixture. Staff is mapped only when every compatible class
agrees on the same supported main/off-hand topology. Unavailable or ambiguous
layout evidence withholds the new projection without affecting raw capture.
Talisman support is tracked separately in #202.
