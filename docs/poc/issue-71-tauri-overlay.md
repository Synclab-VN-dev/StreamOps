# Issue #71 — Tauri overlay feasibility POC

Reference: https://designs.magicpath.ai/v1/crisply-year-9521
Mock-only: no backend, NVDA, OBS, Steam Link, controller or game hooks.

## Automated coverage

| Level | Cases | Evidence |
| --- | --- | --- |
| React unit/IPC | Initial state, PASSIVE/restore, concurrent actions, failed IPC, startup race, drag restrictions, failed subscription/cleanup | npm test |
| Rust unit | Exact hotkeys, key-down/up routing, ignoring unrelated hotkeys, mode round trip, native failure rollback, resync | cargo test |
| Windows runtime E2E | Launch actual EXE; topmost, frameless, fixed size, both hotkeys registered, native cursor round trip, recover, exit without hang | PowerShell SmokeRuntime |
| Packaging | Valid x64 Windows PE, SHA256, uploaded portable EXE | GitHub artifact |
| Regression | Actual D4Planner and StreamOps server Python test suites execute (not SKIPPED) | Tests workflow |

## Real-A acceptance (not replaced by CI)

| Owner | Check | Evidence |
| --- | --- | --- |
| Dev F | GUI startup and normal close on interactive desktop (SmokeLaunch) | command output |
| Dev F | HUD overlays Diablo IV in Borderless Windowed when game focused | screenshot/video |
| Dev F | PASSIVE truly allows physical mouse input through to the game | video |
| Dev F | Physical Ctrl+Shift+F10 toggles even while D4 focused; dragging works | video/log |
| Dev F | Physical Ctrl+Shift+F11 exits from PASSIVE without stuck process | evidence |
| Owner | Game stays usable; GO/NO-GO | acceptance comment |

No automated PASS proves exclusive fullscreen support, Steam Link,
OBS visibility, or actual Diablo IV input behavior.
