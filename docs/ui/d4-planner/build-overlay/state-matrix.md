# Interaction and state matrix — design vs implementation

All controls listed as `MOCK_IMPLEMENTED` occur in pinned MagicPath component source. `DESIGN_GAP` means **no approved UI state**, not an instruction to invent a screen. Visual evidence status is independently tracked in `golden-manifest.json`.

| ID | Initial state / operator action | UI result in approved component | Design | Native image Golden |
| --- | --- | --- | --- | --- |
| S00 | First load | Summary expanded: 78/100; 3 issues; Equipment and Charms | MOCK_IMPLEMENTED | REFERENCE_ONLY |
| S01 | Click header | Collapsed card; next upgrade; closes panels | MOCK_IMPLEMENTED | BLOCKED_NO_CAPTURE |
| S02 | Click collapsed header | Expanded summary | MOCK_IMPLEMENTED | BLOCKED_NO_CAPTURE |
| S03 | Click Equipment | 252px Equipment panel; issue/status list | MOCK_IMPLEMENTED | BLOCKED_NO_CAPTURE |
| S04 | Click Charms | 252px Charms panel, including UNKNOWN | MOCK_IMPLEMENTED | BLOCKED_NO_CAPTURE |
| S05 | Click active section again or X | Close section and item compare | MOCK_IMPLEMENTED | BLOCKED_NO_CAPTURE |
| S06 | Click item | 330px Current vs Target comparison | MOCK_IMPLEMENTED | BLOCKED_NO_CAPTURE |
| S07 | Toggle Affixes | Affix detail open/close, mismatched type distinct from low value | MOCK_IMPLEMENTED | BLOCKED_NO_CAPTURE |
| S08 | Filter Issues only / All | Hide/show PASS affixes while retaining WARN/FAIL | MOCK_IMPLEMENTED | BLOCKED_NO_CAPTURE |
| S09 | Toggle Effects | Current and target effect text, mismatch | MOCK_IMPLEMENTED | BLOCKED_NO_CAPTURE |
| S10 | Click compare X / switch section | Item close or selection reset | MOCK_IMPLEMENTED | BLOCKED_NO_CAPTURE |
| S11 | Click Pin overlay | `Pinned` label toggles; in-memory only | MOCK_IMPLEMENTED | BLOCKED_NO_CAPTURE |
| S12 | Loading / stale / no target / partial / offline | No render contract in selected revision | DESIGN_GAP | BLOCKED_UNDESIGNED |
| S13 | Auto-collapse / window dragging / OS click-through | Not defined in this React design | RUNTIME_GAP | BLOCKED_UNDESIGNED |
| S14 | Healthy Build score / variable item-specific recommendation | Production data/logic not defined in mock | CONTRACT_GAP | BLOCKED_UNDESIGNED |

## Validation handoff

- Automatable once production FE exists: interaction toggles, ARIA expanded/pressed, semantic status, list filters, selection reset and error handling under agreed contract.
- Golden reference capture must be driven from **MagicPath** at this exact revision for each state and viewport; current static preview alone does not prove pixel geometry for S01–S14.
- FE E2E/visual CI for mobile/tablet/desktop cannot be marked PASS without corresponding approved captures and stable viewports; do not manufacture expected screenshots from FE output.
- Owner manual review remains necessary for in-game overlay UX and any design change, as separate from Dev F automation.
