# S2 managed Backend lifecycle

Source base: `1d160d744e91e8d35d51bfcc00ba731a5b5d86e7`
Reviewed S2 baseline: `68fda9a5badae9a218dea135c860443ef85ad49e`  
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
same READY receipt; hide/collapse only reads state. FAILED permits another start
only after the owned child exit is confirmed. Cleanup/observation errors retain
the handle and invalidate READY; stop may retry bounded cleanup. No new child
or generation replaces an unconfirmed old child. A confirmed exit resolves
cleanup even if sending shutdown/termination raced with process exit. Startup failure requests
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
parent EOF, credential redaction and cleanup. The Rust StdProcessDriver also launches the actual Python module, deserializes
its emitted READY, checks PID and stops the owned child. Negative tests mutate
the actual Python READY emission to verify required fields/types and all
protocol/identity guards. Fault injection covers six cleanup failure scenarios
and watcher observation failure; these use fake handles.
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
| S2-05 | PASS (source) / BASELINE_FAILURE (CLI Linux) | The new foreground module is a separate entry point and never invokes Task Scheduler or the existing standalone CLI. CLI suite: 42 PASS, 1 platform failure: PATH restore expects 4 but Linux returns 2 (`PATH management requires Windows`). Same assertion reproduced at reviewed baseline; no CLI change. |
| S2-06 | PASS (Linux) / NOT_RUN (Windows) | Linux tests launch a real Python process and assert its actual PID, identity and cleanup. Windows Job Object and packaged binary evidence cannot be inferred and remains a S7 runtime gate. |

Historical native-build limitation (not rerun for this lifecycle-only fix): the Tauri library source reaches `generate_context!` under a Linux container
with GTK/WebKit/DBus development packages; the existing checkout has no
`src-tauri/icons/icon.png`, so the macro's application-resource check prevents
a full native build. This is pre-existing packaging input, not converted to a
PASS. The isolated lifecycle module compiles and all of its Rust tests run.

## Reproduce local S2 review regression

Run from repository root with Rust and Python 3 available (Python needs the
project dev dependencies for pytest; the Rust real-subprocess test needs stdlib
only). `S2_TEST_PYTHON` can select the direct Python interpreter.

```sh
cargo test --locked --manifest-path utility/d4planner-overlay-poc/lifecycle-tests/Cargo.toml -- --nocapture
cargo check --locked --manifest-path utility/d4planner-overlay-poc/lifecycle-tests/Cargo.toml
PYTHONPATH=utility/d4planner/src python3 -m pytest -q utility/d4planner/tests/test_managed_backend.py utility/d4planner/tests/contracts/test_release1_contract.py
PYTHONPATH=utility/d4planner/src python3 -m pytest -q utility/d4planner/tests/test_cli_runtime.py
git diff --check
```

The small Cargo harness imports the production lifecycle source directly; it is
not a second implementation or a native Tauri GUI build. At review baseline,
seven existing Rust tests passed and four new tests failed (missing real Python
health fields, lost ownership, incorrect failure state). After the fix all 11
Rust tests pass, including ten real Python subprocess scenarios (one valid,
nine negative). Python managed + S1 contract tests: 56 PASS. No Windows-native,
Owner MAN or S3–S7 integration rerun is claimed. CI_NOT_CHECKED.
