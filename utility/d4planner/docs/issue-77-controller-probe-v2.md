# #77 — Steam Link controller visibility, Phase 1: Raw Input

This is a **read-only investigation**, not a production input provider.

## Fixed topology

```text
Xbox controller --Bluetooth--> Android C --Steam Link--> Windows A
                                                   |-- Steam / Steam Input
                                                   |-- Diablo IV
                                                   +-- D4Planner probe (outside game)
```

Do not connect the controller directly to A. Do not create keyboard/F-key
markers, alter Steam Input bindings, install input drivers, or inject/hook D4.

## CI gate (run on PR branch)

```powershell
cd utility/d4planner
python -m pip install -e ".[dev]"
python -m pytest tests/test_controller_probe_v2.py -q
python -m pytest -q
```

Linux CI covers pure logic, fake adapters, and fake scheduled-task relay. A Windows
CI runner additionally validates 64-bit native ctypes structure sizes. Neither
CI nor fake adapters prove that Steam Link forwards HID to a separate process.

## Real-A setup for Dev F

1. Check out `probe/77-controller-probe-v2` on Windows A in a separate
   worktree to avoid disturbing a running StreamOps/D4Planner production session.
2. Install that checkout in its own Python environment
   (`python -m pip install -e utility/d4planner`).
3. Confirm controller stays paired to **C**, Steam Link C -> A is active,
   Steam identifies the controller, and Diablo IV responds to controller
   actions in the game.
4. Run from the Windows desktop first, then repeat over the existing
   B -> F -> A SSH chain using the same checkout / Python interpreter.

```powershell
d4planner controller-probe-v2 --seconds 30
# Or with the environment's interpreter:
python -m d4planner.cli controller-probe-v2 --seconds 30
```

When launched via SSH, the command should report control session 0, an active
interactive console session, and the **probe process session equal to that
active session**. A mismatched session invalidates the evidence.

During each 30s probe, press deliberately with pauses:
A, B, X, Y, D-pad Up/Down/Left/Right, LB and RB. Release each
button fully before pressing the next. Run a second time to compare raw
control identities. If available, test Start/Back/LS/RS separately too.

Look for `Backend RawInput` status and raw
`device=...` / `control=...` `DOWN` and `UP` transitions.
A HID device entry without transitions is **not** a PASS. A raw event from
another local controller is **not** Steam Link evidence. If possible,
disconnect any unrelated local controllers for the comparison.

## Required evidence in PR and issue

- OS build, Python bitness, command, PR head SHA, process/active session IDs
- Steam Link/controller/Diablo IV simultaneous connection evidence
- RawInput runtime, device identity, usagePage/usage, YES/NO, exact event log
- Per-control matrix: A/B/X/Y, D-pad and LB/RB, plus second-run consistency
- Diablo IV still accepts controller input during probe
- No keyboard/mouse synthesis, cursor blink, input mode switch, Steam/D4 restart
- Confirm no `input.controller.raw`, `input.marker.raw`, or equipment writes
- The scheduled probe task and process terminate after the timeout
- Decision: **RawInput usable -> stop** or **RawInput unusable -> WGI phase**

## Interpretation

- `NO_DEVICE`: no relevant HID gamepad/joystick enumerated.
- `DEVICE_PRESENT_BUT_NO_EVENTS`: HID present, no observable button changes.
- `EVENTS_OBSERVED`: at least one raw transition was logged; this is
  **only a technical candidate**. Real-A multi-button, Steam Link attribution,
  and side-effect checks determine whether it is a usable backend.
- `UNAVAILABLE`: native API/runtime could not load; not a controller visibility result.
- `ERROR`: backend failed; do not silently interpret it as `NO_DEVICE`.

The D-pad may appear as a HID hat-switch value rather than four buttons.
The POC does not normalize Xbox A/B/X/Y names or claim a stable production
mapping. Neutral hat values are filtered only for the common 0..7 direction
encoding; use Real-A evidence to decide whether additional caps-based decoding
is required.

If RawInput is not usable, implement Windows.Gaming.Input in this branch
with the same `BackendResult` contract, without changing the above safety
boundaries. GameInput and DirectInput remain conditional later phases.

**Out of scope**: semantic Equip correlation, production EventStore writes,
EquipmentResolver and `character.db` mutations, APK/bridge on C.
