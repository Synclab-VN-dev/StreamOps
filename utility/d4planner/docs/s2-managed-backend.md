# S2 managed Backend lifecycle

Source base: `459cd0e1fb41f8421cf93f5009272bfab20b5a2c`  
Contract: `d4planner-r1-contract/1.0.0-candidate.5`

The native Tauri shell owns exactly one foreground
`d4planner.managed_backend` process through `BackendProcessWrapper`. React can
request lifecycle status but never receives an executable, path, credential or
PID and does not spawn processes. The wrapper uses an injected `ProcessDriver`
and the same serialized Template Method for real and fake drivers:

```text
STOPPED/EXITED/FAILED
  -> spawn owned handle
  -> wait for validated READY protocol/version/owner/child/generation/PID
  -> READY
  -> owner shutdown over inherited stdin
  -> bounded wait
  -> terminate only the recorded child handle when the deadline expires
  -> EXITED
```

Concurrent/double `start` calls serialize on lifecycle state and return the
same READY receipt; hide/collapse only reads state. Startup failure requests
graceful cleanup and then uses the owned handle, never a process name. Tauri
exit invokes stop. The wrapper uses an event/pipe READY channel and OS child
wait primitive; it does not poll a PID or state file.

`restart_with` is one serialized lifecycle operation. It rejects reuse of the
old child identity or generation, stops the held child within the configured
deadlines, then launches a new child under the same owner with a strictly
higher generation. The native composition layer must provision the next
private descriptor before invoking it; it cannot silently recycle a stale
credential/bootstrap tuple.

## Managed entrypoint and bootstrap

The entrypoint never detaches and never creates a Scheduled Task. It receives
the descriptor path only through `D4PLANNER_BOOTSTRAP_FILE`; the credential is
inside that owner-only file and is never present in argv, READY, EXIT or error
logs. Descriptor fields pin protocol/contract, owner and child IDs, generation,
DataDir, Target folder, loopback endpoint and credential.

Tauri packaging supplies these native-only variables:

- `D4PLANNER_BACKEND_PYTHON`: absolute packaged Python executable;
- `D4PLANNER_BOOTSTRAP_FILE`: owner-only descriptor provisioned for this run;
- the allow-listed Windows runtime environment (`SYSTEMROOT`, `WINDIR`,
  `TEMP`, `TMP`, `PATH`) needed by that executable.

`D4PLANNER_BACKEND_PYTHON` must resolve to the interpreter process that remains
alive and emits READY, not a console-script or virtual-environment redirector
which launches a second Python PID. The strict READY PID check rejects an
intermediate launcher because force-stopping its handle would not prove that
the Backend child was contained. Windows tests bypass the venv redirector via
the base interpreter and an explicit source path; S7 packaging must provision
an equivalent direct executable (and separately prove process-group cleanup).

The managed process creates/opens DataDir and Target folder before READY.
Empty Target folders therefore produce READY with `targetJsonCount=0`; Target
validity/selection remains S4 domain state. S2 does not pretend sibling work is
healthy: READY reports `wsTransport=PENDING_S5` and
`ruleKitWorker=PENDING_S3`. S5 replaces that transport status when its real
listener/authentication implementation is integrated.

Closing inherited stdin is the parent-death channel and exits cleanly. A normal
owner stop requires matching owner/child/generation. Wrong ownership returns a
typed control error and cannot stop another process.

## Evidence boundary

Linux real-process tests verify PID identity, READY, empty folder, owned stop,
parent EOF, credential redaction and cleanup. Rust driver tests cover
idempotency, startup cleanup and bounded force termination with fake handles.
They are not Windows Job Object or packaged Tauri evidence. Windows process
group/job containment and physical exit behavior remain `NOT_RUN` until a
matching Windows test environment is approved.

## Acceptance handoff

| ID | Result | Evidence / boundary |
|---|---|---|
| S2-01 | PASS | `backend_process.rs` separates launch specification, driver and lifecycle template; Tauri commands are native-only and React contains no spawn/kill implementation. |
| S2-02 | PASS | Rust tests cover simultaneous/double start, spawn failure, READY failure cleanup and one owned child. Python rejects protocol, permissions and non-loopback bootstrap errors. |
| S2-03 | PASS | Real-process tests validate READY/EXIT/STOP, PID/instance/generation, empty and syntactically invalid Target folder startup, and partial sibling health without claiming S3/S5 ready. |
| S2-04 | PASS (contract/Linux) | Graceful and forced deadlines, owner matching, parent-pipe EOF and hide semantics are automated. Packaged Windows process-group behavior is separately NOT_RUN. |
| S2-05 | PASS | The new foreground module is a separate entry point and never invokes Task Scheduler or the existing standalone CLI. Targeted CLI regression recorded separately. |
| S2-06 | PASS (Linux) / NOT_RUN (Windows) | Linux tests launch a real Python process and assert its actual PID, identity and cleanup. Windows Job Object and packaged binary evidence cannot be inferred and remains a S7 runtime gate. |

The Tauri library source reaches `generate_context!` under a Linux container
with GTK/WebKit/DBus development packages; the existing checkout has no
`src-tauri/icons/icon.png`, so the macro's application-resource check prevents
a full native build. This is pre-existing packaging input, not converted to a
PASS. The isolated lifecycle module compiles and all of its Rust tests run.
