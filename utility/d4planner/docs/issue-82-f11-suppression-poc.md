# Issue #82 — F11 capture + selective suppression (Windows POC)

**Status:** implemented as a **standalone opt-in diagnostic**; Real-A/Manual UAT NOT YET VERIFIED.

## Why
PR #70 emits two Steam Input bindings for controller A on C: original gamepad A
and additional keyboard F11 marker. The production runtime polls F11 with
GetAsyncKeyState (read-only), which does not prevent Diablo IV from receiving
F11. This may cause alternating keyboard/gamepad prompts ("blink").

The new isolated proof-of-concept captures F11 inside the low-level keyboard
hook callback, queues an observation, and optionally returns nonzero to block
F11. It never modifies XInput/gamepad A, Steam Input configuration, the
production InputMarkerCapture or either SQLite database.

## Safety and limitations
- **Observe-only by default.** Blocking requires the explicit --block option.
- Hook operates globally in the user's desktop but only blocks F11 when
  foreground process PID matches the **validated Diablo IV.exe PID**.
- Other keys and F11 when other programs have foreground pass through.
- There is **no reliable Steam Input provenance** in WH_KEYBOARD_LL:
  LLKHF_INJECTED does not identify the originating app. **Physical F11 is
  also blocked when Diablo IV is foreground.**
- Win32 hook suppression does not guarantee suppression on D4's Raw Input
  or other input paths: zero blink requires proof on Real-A.
- Start in interactive Windows session 1, not SSH/service session 0.
  No DLL injection into Diablo IV.
- Callback only queues events, no filesystem IO. Windows may silently
  remove hooks if callbacks/pump are too slow.
- Auto-exits and unhooks after timeout (default 30 s, max 300 s);
  Ctrl+C unhooks as well. If a process is killed, Windows removes its hook.
- Does NOT insert events into events.db. Production PR #70 is unchanged.
- If the block works, existing GetAsyncKeyState polling may not see the
  blocked F11; integrating later requires consuming hook events directly.

## Run on A, in interactive PowerShell

Check out the child branch poc/82-f11-suppress-hook in a **separate**
working tree. Make sure the Steam Input profile still dual-binds controller
A to the original gamepad A + keyboard F11.

~~~powershell
$env:PYTHONPATH = (Resolve-Path .\utility\d4planner\src).Path
$gamePid = (Get-Process -Name 'Diablo IV' -ErrorAction Stop |
    Select-Object -First 1).Id
$gamePid
$py = 'C:\Users\huy\AppData\Local\Programs\Python\Python312\python.exe'

# 1. Observe and record initial blink without blocking
& $py -m d4planner.poc_keyboard_suppress --pid $gamePid --seconds 30 --jsonl

# 2. Enable selective block and compare while still pressing gamepad A
& $py -m d4planner.poc_keyboard_suppress --pid $gamePid --seconds 30 --block --jsonl
~~~

If Python differs, change $py. If PID executable check fails, stop and verify
the actual game PID; do not remove the validation. To save evidence append
a pipe to Tee-Object -FilePath <capture.log> (header/summary are not JSON).

## Acceptance matrix (manual)

| Check | OBSERVE | BLOCK |
|---|---|---|
| Gamepad A still drives Diablo IV | Required | Required |
| F11 captured DOWN and UP | Required | Required |
| Game UI icons blink | Record baseline | **Must be absent** |
| Other keyboard keys | Pass | Pass |
| Physical F11 with D4 foreground | Pass | Block (known tradeoff) |
| Physical F11 with other app foreground | Pass | Pass |
| Quit / Ctrl+C | Unhook | Unhook |
| Queue drops or hook errors | 0 expected | 0 expected |

Capture a short video of the D4 controller prompts in both modes, using
comparable key presses. Inspect quick taps, holds and F11 UP. If marker is
suppressed but icon still blinks, don't claim success: Steam Input/Diablo IV
may use another input path. Do not enable suppression by default.

## Automated unit checks

~~~powershell
$env:PYTHONPATH = (Resolve-Path .\utility\d4planner\src).Path
& $py -m pytest utility\d4planner\tests\test_keyboard_suppress_poc.py -q
~~~

Unit tests cover per-PID allow/block, DOWN/UP, SYS keys, passthrough, FIFO
queue and fail-open. They do not replace interactive Real-A tests.

## PR strategy

- Parent PR #70 branch: probe/69-steam-input-marker.
- POC child PR: poc/82-f11-suppress-hook, base must remain parent.
- Keep PR **draft** and ticket #82 **open** until Dev F and Manual acceptance
  pass. If PR #70 merges, retarget the child PR as appropriate.
