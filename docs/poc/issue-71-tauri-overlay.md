# Issue #71 — Tauri overlay feasibility POC

Reference: https://designs.magicpath.ai/v1/crisply-year-9521

Mock-only; no changes to D4Planner Python backend, OBS, NVDA, game files,
controller input, or Steam Link.

## Acceptance matrix — unverified until real Windows A session

| Owner | Check | Evidence |
| --- | --- | --- |
| CI/unit | Rust/React Windows compilation | workflow URL |
| CI/unit | Mode unit tests | workflow URL |
| CI/smoke | Valid portable x64 PE, SHA256, uploaded artifact | workflow URL |
| Dev F | Start EXE in logged-in Windows desktop | screenshot/log |
| Dev F | Overlay over Diablo IV in Borderless Windowed mode | screenshot |
| Dev F | PASSIVE passes mouse to underlying game | manual/video |
| Dev F | Toggle INTERACTIVE and drag, then resume PASSIVE | video/log |
| Dev F | Emergency global shortcut exits | manual evidence |
| Owner | Gameplay usable / GO or NO-GO | UAT comment |

A successful CI build DOES NOT prove the overlay works in the game.
