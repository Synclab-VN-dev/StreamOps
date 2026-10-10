# Issue #82 — F11 capture + selective suppression (Windows diagnostics)

**Status:** standalone diagnostic with SSH->interactive task relay; Real-A/Manual UAT NOT YET VERIFIED.

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
- The diagnostic may be invoked from SSH / session 0: a new interactive Scheduled Task runs the hook in the game desktop session. No DLL injection into Diablo IV.
- Callback only queues events, no filesystem IO. Windows may silently
  remove hooks if callbacks/pump are too slow.
- Auto-exits and unhooks after timeout (default 30 s, max 300 s);
  Ctrl+C unhooks as well. If a process is killed, Windows removes its hook.
- Does NOT insert events into events.db. Production PR #70 is unchanged.
- If the block works, existing GetAsyncKeyState polling may not see the
  blocked F11; integrating later requires consuming hook events directly.

## Run from Android B over SSH to Windows A (preferred)

Updated PR #83 automatically detects a Session 0 SSH invocation and relays
into a Session 1 interactive Scheduled Task. No RustDesk or manual login to
an A terminal is needed **provided the game desktop is already logged on**.

From B Termux, update the PR #83 worktree on A and obtain the current PID:

~~~sh
A="huy@192.168.1.8"
ssh "$A" 'cd C:\Users\huy\codex-work\StreamOps-82 && git fetch origin poc/82-f11-suppress-hook && git switch --detach origin/poc/82-f11-suppress-hook'
ssh "$A" 'powershell -NoProfile -Command "(Get-Process -Name \"Diablo IV\" | Select-Object -First 1).Id"'
~~~

Replace 14872 below if the reported game PID differs. Run **one command at
a time**, and press controller A on C several times while each command
is active (60 seconds).

~~~sh
# OBSERVE: diagnose only, no key suppression
ssh "$A" 'C:\Users\huy\AppData\Local\Programs\Python\Python312\python.exe C:\Users\huy\codex-work\StreamOps-82\utility\d4planner\src\d4planner\keyboard_capture_diagnostic.py --pid 14872 --seconds 60 --diagnose'

# BLOCK: suppress keyboard F11 only while D4 is foreground
ssh "$A" 'C:\Users\huy\AppData\Local\Programs\Python\Python312\python.exe C:\Users\huy\codex-work\StreamOps-82\utility\d4planner\src\d4planner\keyboard_capture_diagnostic.py --pid 14872 --seconds 60 --diagnose --block'
~~~

Expected diagnostic categories (examples, not yet verified on Real-A):

~~~text
RELAY: control_session=0 game_session=1 active_console=1; task=...
LOG_PATH: C:\Users\huy\AppData\Local\d4planner\state\keyboard-diagnostic\f11-<id>.log
DIAGNOSTIC_SESSION worker=1 game=1 active=1
...
SUMMARY: keyboard_seen=... f11_seen=... f11_target=...
F11_DIAGNOSTIC_COMPLETE status=0
~~~

Log path on A is preserved and is readable over SSH. The controller prints
new log lines while the interactive hook runs; task deregistration occurs at
completion and on Ctrl+C. A hard SSH disconnect may interrupt the control
process before cleanup, but worker exits/unhooks within 300 seconds.

The interactive worker refuses to run unless its Session ID equals Diablo
IV's active console session. The Python worker is run by absolute source path
and does not depend on PYTHONPATH inherited from the SSH shell. The presence
of status=0 does NOT prove the UI stopped blinking; verify on C manually.

## Alternate: run on A in interactive PowerShell



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
& $py -m d4planner.keyboard_capture_diagnostic --pid $gamePid --seconds 30 --jsonl

# 2. Enable selective block and compare while still pressing gamepad A
& $py -m d4planner.keyboard_capture_diagnostic --pid $gamePid --seconds 30 --block --jsonl
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
& $py -m pytest utility\d4planner\tests\test_keyboard_capture_diagnostic.py -q
~~~

Unit tests cover per-PID allow/block, DOWN/UP, SYS keys, passthrough, FIFO
queue and fail-open. They do not replace interactive Real-A tests.

## PR strategy

- Parent PR #70 branch: probe/69-steam-input-marker.
- Integration child PR: poc/82-f11-suppress-hook, base must remain parent.
- Keep PR **draft** and ticket #82 **open** until Dev F and Manual acceptance
  pass. If PR #70 merges, retarget the child PR as appropriate.


## Diagnose: hook starts but prints no F11 events

A clean "queue_dropped=0 hook_errors=0" **does not imply keyboard events
were observed**: normal mode filters all F11 whose foreground PID is not
Diablo IV and all other keys. On the updated PR #83 branch, run:

~~~powershell
$session = (Get-Process -Id $PID).SessionId
$gameSession = (Get-Process -Id $gamePid).SessionId
"Diagnostic session=$session; D4 session=$gameSession"
& $py -m d4planner.keyboard_capture_diagnostic --pid $gamePid --seconds 60 --diagnose
~~~

While the command runs, **first press a physical keyboard key** (e.g. Space)
in the PowerShell window, then press physical F11, then focus Diablo IV and
press controller C button A multiple times. The diagnostic will print off-target F11
with targetMatch=False and add SUMMARY counters:

- keyboard_seen=0: keyboard hook received no keyboard messages at all.
  Verify the process is in the *interactive* Windows desktop/session (not
  SSH/session 0); try physical keyboard; check privilege/desktop differences.
- keyboard_seen>0, f11_seen=0: hook receives other keyboard keys but no F11.
  Steam Input dual-bind may not be active, or F11 may not traverse this Win32
  hook. First check whether **physical F11** increments f11_seen.
- f11_seen>0, f11_target=0: F11 does arrive but was filtered because another
  foreground process owns the window. Compare printed foregroundPid and
  game PID; make D4 foreground, don't weaken the game PID guard.
- f11_target>0: Diagnostic captured F11 when D4 had foreground. Next test
  --block and observe whether D4 prompts still blink. Do **not** claim blink
  fixed without watching actual game behavior.

The --diagnose option never broadens the suppression guard. Off-target
F11 is **only logged**, never blocked. This mode reports minimal aggregate
counts of other keyboard events; it does not log key content for other keys.

SSH session mismatch (PowerShell Session 0; Diablo IV Session 1) is now
handled by the automatic interactive-task relay rather than silently
missing F11 events.
