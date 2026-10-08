# D4Planner Tauri Overlay — Issue #71 POC

Goal: test whether a transparent, always-on-top Windows HUD can run on top
of Diablo IV (Borderless Windowed) without blocking normal gameplay.

Mock-only React UI; no backend, NVDA, game hooks, Steam Link or OBS integration.
Design reference (not pixel-perfect):
https://designs.magicpath.ai/v1/crisply-year-9521

## Download from GitHub Actions (no Node or Rust necessary)

1. Open PR for issue #71, select **Checks** -> **D4 Overlay POC (Windows EXE)**.
2. After the workflow succeeds, download artifact **d4planner-overlay-poc-win-x64**.
3. Extract the ZIP. On Windows A, double-click **d4planner-overlay-poc.exe**.
4. The HUD starts in INTERACTIVE mode; drag it via the header.
5. Press **Ctrl + Shift + F10** to toggle PASSIVE (mouse click-through).
   Press it again to return to INTERACTIVE.
6. Press **Ctrl + Shift + F11** to exit at any point (emergency recovery).

Windows WebView2 Runtime is required (preinstalled on most modern Windows 10/11).
The portable EXE is unsigned and may trigger Windows SmartScreen. Review the
repository/CI run before accepting an unsigned program; no installer required.
Do not launch the file from inside the ZIP.

## In-game test

- Configure Diablo IV as Borderless Windowed (not exclusive fullscreen).
- Verify card is still visible when the game has focus.
- Set PASSIVE, then use the game directly through the HUD location.
- Toggle INTERACTIVE, drag HUD, return to PASSIVE and resume gameplay.
- Verify Ctrl+Shift+F11 exits. If recovery shortcut is unavailable, use
  Windows Task Manager to end d4planner-overlay-poc.exe.
- Record screenshot/video, actual window mode and PASS/FAIL in issue #71.

**CI PASS does not prove in-game behavior.** OBS Game Capture, Steam Link and
Xbox controller capture are not covered by this POC.

## Developer build (Windows A)

From the StreamOps root:

    .\scripts\local\d4-overlay-poc.ps1 Doctor
    .\scripts\local\d4-overlay-poc.ps1 Run
    .\scripts\local\d4-overlay-poc.ps1 Test
    .\scripts\local\d4-overlay-poc.ps1 Build
    .\scripts\local\d4-overlay-poc.ps1 Smoke
    .\scripts\local\d4-overlay-poc.ps1 Stop

Build requirements: Node 22+, Rust stable (MSVC target), Windows C++ build
tools / Windows SDK, WebView2. The script handles npm packages and icon
generation, with builds under src-tauri/target.

The Tauri backend owns click-through and global hotkey handling. React uses
Tauri IPC to request interaction changes; it never listens to browser keydown
for the recovery shortcut. Startup is rejected if shortcuts are unavailable,
to avoid leaving a click-through-only window without a recovery method.
