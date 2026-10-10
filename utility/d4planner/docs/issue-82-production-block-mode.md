# Production integration — F11 marker capture and optional blocking (#82 / PR #83)

## User commands (same UX as PR #70)

Call on the Windows host A using its Python environment / installed d4planner
CLI, including from Termux B over SSH. Existing Scheduled Task launcher starts
the D4Planner Supervisor in the logged-on interactive console (Session 1),
even if SSH entered Windows in Session 0.

~~~powershell
# Default: capture F11 with existing GetAsyncKeyState polling, NO blocking
d4planner start -d

# Opt-in: capture F11 by the POC-proven WH_KEYBOARD_LL hook, and block F11
# only while Diablo IV owns the foreground. Gamepad A passes normally.
d4planner start -d --block

# Status should show: Input marker  F11 / BLOCK / ACTIVE
d4planner status
d4planner status --json

# Canonical mixed speech + F11 events, ordered in events.db
d4planner logs -f --raw --from-end
d4planner logs -f --from-end

# Stop Supervisor + hook, drain events, close SQLite
d4planner stop
~~~

The optional --speech / --isolated flags may be used as before. When launched
without -d, Ctrl+C only detaches the CLI from log follow; it does **not**
stop the Supervisor or release the hook. Use d4planner stop explicitly.
Changing observe/block mode on a running Supervisor is rejected with a
stop/start instruction; no hidden mutation or duplicate hook installation.

The default remains OBSERVE for backwards compatibility. If --block startup
fails, the runtime returns nonzero / publishes ERROR (not misleading ACTIVE).
Status includes marker mode, hook method, and Session ID under
extras.inputMarker. Pretty input events show [BLOCKED] when the hook suppressed
the keyboard marker. The source raw event remains input.marker.raw with
the same session/eventSeq chronology as PR #70; only BLOCK adds optional
suppressed=true and captureMethod=keyboardHook.

## Architecture

~~~text
C gamepad A -> Steam Link on A -> gamepad A -> Diablo IV
                              -> keyboard F11
                                  |
      D4Planner Supervisor (existing interactive Session 1)
                                  |
                 selected marker backend (one ONLY)
                  /                         \
     OBSERVE / GetAsyncKeyState        BLOCK / WH_KEYBOARD_LL
     normal game keyboard flow         hook captures, swallows F11
                  \                         /
                   -> common MarkerSample queue
                           -> Supervisor (only SQLite writer)
                           -> state/events.db
                               + speech.raw from NVDA
~~~

The hook core is shared between POC and production:
- runtime/keyboard_hook.py: POC-proven Win32 hook, bounded FIFO, PID filter,
  KEY DOWN/UP policy and message pump.
- poc_keyboard_suppress.py: CLI/SSH one-off POC which now imports same core.
- runtime/input_marker.py: HookInputMarkerCapture adapter with its own
  short-interval Windows message-loop thread and POC-sample conversion to
  EventDraft. It never writes SQLite or mutates character.db.
- runtime/supervisor.py: chooses exclusive backend, runs lifecycle/status/
  flush/shutdown and synchronizes game PID changes.
- cli.py -> windows.py -> daemon.py: --block propagated into the *existing*
  interactive Supervisor Scheduled Task (no second long-lived task).

## Safety contract and limits

- ONLY F11 + correct foreground Diablo IV PID is swallowed. Keyboard input
  in other foreground windows, other keys and original gamepad signals pass.
- WH_KEYBOARD_LL does not identify Steam Input specifically. **Physical F11
  is also swallowed while Diablo IV is foreground**.
- If game PID is unknown, policy passes all F11. After Diablo IV restarts,
  the Supervisor's game health check updates the target PID; there can be
  a brief no-block interval (up to one configured health poll).
- Windows can silently remove a low-level hook if the callback times out;
  there is no guaranteed API signal. A live thread and ACTIVE status are not
  proof that Windows has retained the hook forever. Keep callback nonblocking.
- Blocking can prevent F11 from surfacing in GetAsyncKeyState. Do not run
  both marker backends in the same Supervisor runtime.
- The hook thread has a ready handshake, clean exit/Unhook and drains marker
  samples before SQLite shutdown. Worker unexpected exit/error publishes
  ERROR and marks the required BLOCK mode invalid.
- Raw event evidence does NOT mean Equip. No semantic equipment transition,
  automatic inventory mutation or second event database is added.

## Acceptance gates — no second user manual if POC baseline holds

1. Unit: policy scopes F11+foreground, intercepts DOWN/UP, physically
   preserves other keys, conversion preserves timestamp/sequence metadata,
   concurrency queue and fail-open tests.
2. E2E: --block handoff into existing Scheduled Task, Supervisor startup
   readiness handshake, speech+suppressed markers in SQLite, no character
   mutation, PID change, stop/unhook, hook failure returns nonzero.
3. Regression: default start -d observation unchanged; existing #70
   speech/marker tests must remain PASS; no duplicate polling in BLOCK mode.
4. Real-A Dev F: use controller C -> Steam Link -> A with --block and
   normal gamepad A. Check F11 suppression and game no longer changing
   keyboard/gamepad prompts, event stream, stop/start, and PID restart.
   Save command logs/status/video. Report test gap instead of assuming
   real controller coverage from generated Win32 keyboard test input.
5. POC Manual UAT was completed by the user for the original hook behavior
   and is accepted as the human baseline only if production uses that
   same core and Dev F's real integration evidence is equivalent.

**Do not mark Real-A production acceptance PASS from CI alone.**
PR remains draft until integration evidence is attached and reviewed.
