# D4Planner Tauri Overlay — Issue #71 POC

Goal: test whether a transparent, always-on-top Windows HUD can run on top
of Diablo IV (Borderless Windowed) without blocking normal gameplay.

Mock-only React UI; no backend, NVDA, game hooks, Steam Link or OBS integration.
Design reference (not pixel-perfect):
https://designs.magicpath.ai/v1/crisply-year-9521

## Download from GitHub Actions (no Node or Rust necessary)

1. Open PR for issue #71, select Checks -> D4 Overlay POC (Windows EXE).
2. After workflow success, download artifact d4planner-overlay-poc-win-x64.
3. Extract ZIP. On Windows A, double-click d4planner-overlay-poc.exe.
4. HUD starts in INTERACTIVE mode; drag it via the header.
5. Press Ctrl + Shift + F10 to toggle PASSIVE (mouse click-through).
   Press again to return to INTERACTIVE.
6. Press Ctrl + Shift + F11 to exit (emergency recovery).

Windows WebView2 Runtime is required (preinstalled on most modern Windows 10/11).
Portable EXE is unsigned and may trigger Windows SmartScreen. Review
repository/CI run before accepting an unsigned program; no installer required.
Do not launch EXE directly from inside ZIP.

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
