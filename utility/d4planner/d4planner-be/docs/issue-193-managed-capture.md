# HUD-owned capture runtime (#193)

The native HUD still owns `d4planner.managed_backend`. The Backend now starts a
foreground `d4planner.daemon --managed-by-hud --block --controller-profile xbox16`
child using the same canonical DataRoot. This is not a Scheduled Task.

The child's stdin is a lifetime pipe. EOF requests a graceful supervisor stop.
The existing DataRoot singleton guards against a second producer. A conflict is
reported as BLOCKED; the Backend does not adopt, stop, or write a stop request for
a different supervisor. Status is correlated with a per-launch token (Windows
venv launchers can have a different PID from the actual Python interpreter).

Managed mode never launches Diablo IV and never restarts an existing NVDA.
It starts a missing NVDA directly only when running in the active desktop session,
without requiring legacy CLI Scheduled Tasks. Existing dependency/version, Tolk,
DataRoot acknowledgement, Steam PATH freshness, foreground/session and BLOCK
checks remain in force. An existing NVDA requiring an addon refresh produces an
explicit restart instruction. NVDA is not stopped by name on Backend shutdown.
The packaged backend now includes the reviewed NVDA addon source.

`equipmentCapture` is no longer optimistically READY when no producer exists.
Optional `health.captureRuntime` carries the supervisor state/detail to the HUD;
the HUD renders waiting-for-game and dependency errors without inventing scores.
Both FE and BE must be delivered together for the additive HUD contract field.

## Evidence and limits

Before implementation, Windows VM regressions failed on unconditional READY and
on automatic game launch. A further regression demonstrated the legacy Scheduled
Task dependency before replacing it in managed mode. Ownership, dependency
failure, no automatic game launch, and existing NVDA preservation are covered.
A native child-process smoke on the VM verifies the real missing-NVDA diagnostic
and singleton cleanup, not successful live game capture.

Raw capture and equipment projection remain distinct from identified HUD data.
The current producer repository does not expose a verified character identity;
this change does not invent one from a session ID or an operator-provided name.
The existing explicitly configured equipment adapter remains available. A running
capture runtime is therefore not proof that a character/score is available.
Live D4 input/character E2E is not claimed by VM tests without Steam/D4.

## Desktop VM follow-up

Interactive Setup and desktop-shortcut launch reproduced and verified the missing
NVDA error in the actual HUD. Installing NVDA exposed an additional native
boundary defect: the environment allowlist omitted APPDATA/USERPROFILE, so addon
lookup failed with `Could not determine home directory`. A Windows Rust regression
failed on the missing APPDATA value before extending the shared OS-context
allowlist. Unrelated environment secrets remain excluded.

The native installer's `--backend-self-test` now explicitly marks its disposable
Backend generations as capture probes. They report NOT_STARTED_HEALTH_PROBE and
must not configure NVDA, change User PATH, or start live capture. Normal desktop
launch does not inherit this probe switch from the parent environment. A separate
Windows regression demonstrates that probes do not provision a capture child.

A real NVDA launch also exposed a missing `PROCESSOR_ARCHITECTURE` variable:
NVDA exited before publishing its DataRoot receipt. The native environment
regression failed before passing through the Windows architecture variables.
The DataRoot acknowledgement check remains mandatory.
