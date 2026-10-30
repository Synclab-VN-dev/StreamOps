# D4Planner Release 1 Equipment HUD

Native Tauri HUD for #143, derived from the previously accepted transparent
overlay feasibility work. The UI now follows approved MagicPath revision
`464988421014827008` and renders only S1 Equipment contract data.

See [docs/release1-hud.md](docs/release1-hud.md) for data-source, native-window,
MagicPath Golden and acceptance boundaries.

The native shell owns the versioned managed Backend lifecycle and passes its
private loopback bootstrap to the strict S5 WebSocket data source. Production
never falls back to fixture or demo data. NVDA, game hooks, Steam Link and OBS
integration remain out of scope.

## Developer verification

```text
npm install
npm test
npm run build
cd src-tauri && cargo test && cargo check
```

Source/native binary: `d4planner-hud.exe`. S7 vẫn đóng gói thành
`app/d4planner-fe.exe`, Root `D4Planner.exe`; application/DataRoot và Tauri
identifier giữ nguyên. Workflow artifact/portable alias cũ giữ tương thích consumer. `scripts/local/d4-overlay-poc.ps1` still provides Doctor,
Run, Test, Build, Smoke, SmokeRuntime, SmokeLaunch and Stop operations.

## In-game test — Dev F and owner

- Configure Diablo IV as Borderless Windowed (not exclusive fullscreen).
- Verify card remains visible when game has focus.
- Set PASSIVE, then use game directly through the HUD location.
- Toggle INTERACTIVE, drag HUD, return to PASSIVE and resume gameplay.
- Verify Ctrl+Shift+F11 exits. If shortcut fails, use Windows Task Manager.
- Record screenshot/video, game window mode and PASS/FAIL in issue #71.

CI PASS does not prove the overlay works with D4, actual mouse input reaches
the game, or physical F10/F11 presses work with the game focused.
OBS Game Capture, Steam Link and controller integration are out of scope.

## Developer build & tests (Windows A)

From the StreamOps root:

    .\scripts\local\d4-overlay-poc.ps1 Doctor
    .\scripts\local\d4-overlay-poc.ps1 Run
    .\scripts\local\d4-overlay-poc.ps1 Test
    .\scripts\local\d4-overlay-poc.ps1 Build
    .\scripts\local\d4-overlay-poc.ps1 Smoke
    .\scripts\local\d4-overlay-poc.ps1 SmokeRuntime
    .\scripts\local\d4-overlay-poc.ps1 SmokeLaunch
    .\scripts\local\d4-overlay-poc.ps1 Stop

Smoke verifies PE x64 and SHA256 only.
SmokeRuntime launches actual EXE with --self-test, verifies topmost, frameless,
fixed size, both global hotkeys registered, OS cursor mode round trip,
restores INTERACTIVE, produces JSON and exits within timeout.
SmokeLaunch requires an interactive Windows desktop session: opens a normal
GUI window and requests WM_CLOSE; must terminate cleanly without force.

Build requires Node 22+, Rust MSVC, Windows C++ build tools / Windows SDK,
and WebView2. CI artifact requires neither Node nor Rust on Windows A.

The managed lifecycle contract, private bootstrap descriptor and local test
boundary are documented in
[`../d4planner/docs/s2-managed-backend.md`](../d4planner/docs/s2-managed-backend.md).

## Automated test boundaries

- React tests mock Tauri IPC and event delivery, including event races,
  failed IPC rollback, drag restrictions and disabled duplicate submits.
- Rust tests verify exact shortcut definitions, key press/release routing,
  reversible mode transitions and state rollback on OS errors.
- Native runtime E2E launches the actual EXE and verifies window APIs;
  timed-out/hung GUI is treated as failure rather than silently skipped.
- StreamOps Tests workflow runs Python D4Planner and server regression
  suites for overlay PRs, rather than reporting green skipped-only suites.
- Even full CI PASS cannot verify in-game focus, physical mouse passthrough,
  or physical global keyboard event handling under Diablo IV.

CI artifact is retained for 14 days; rebuild on PR when it expires.

The HUD starts interactive, is draggable by its header, and uses
`Ctrl+Shift+F10` to recover/toggle click-through. `Ctrl+Shift+F11` is the safe
exit shortcut. Physical Windows/game, mixed-DPI, mouse passthrough and
`window_capture` acceptance are manual S7 gates; Linux component tests are not
reported as proof of those behaviors.


## Ownership sau refactor #160

- `src/`: React HUD; `src-tauri/`: Tauri native FE quản lý Backend.
- `native-launcher/`: Root bootstrap/session/quota/retention/export.
- `runtime-logging/`: Rust logger cho Root/Tauri, không thay BE/Rule Kit ghi log.
- `lifecycle-tests/`: production lifecycle tests.

BE giữ Python logger be.log; Rule Kit giữ Node logger rulekit.log.
Không đổi lifecycle, JSONL, quota, privacy hoặc UI.
`vn.synclab.d4planner.overlaypoc` là persistent identity lịch sử, cố ý giữ nguyên.
