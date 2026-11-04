# Unified DataRoot — issue 165

Engineering assessment: AGREE with the storage/ownership contract. The implementation
must fail closed on migration cases it cannot prove safe. Passing recorded fixtures
is not live-game acceptance. Base: `8d6ed9baf39cad60dc555e50d9a3ddb8cfaa3d74`.
No work for #178, automatic capture, scoring, or Rule Kit trust changes is included.

## Resolution and ownership

Windows default: `%LOCALAPPDATA%\StreamOps\D4Planner`.
Standalone non-Windows default: `~/.local/share/StreamOps/D4Planner`.
Installed launcher reads `active.json.dataDir`; explicit `D4PLANNER_DATA_ROOT`
and legacy `D4PLANNER_HOME` must agree with registration. Relative paths,
parent traversal, symlinks/junctions and mixed state/Rule Kit paths fail closed.
Explicit `D4PLANNER_STORAGE_ISOLATED=1` plus `D4PLANNER_DATA_ROOT` permits a
validated UAT root disjoint from installation and registered data. The shared
Python/Rust fixture matrix is `tests/fixtures/unified-storage-cases.json`.
Windows ownership/access uses the same packaged `runtime/storage_acl.ps1` in
launcher, BE and addon: current-user ownership or Administrators ownership with
an elevated administrator token; SYSTEM/admin/current-owner ACLs are allowed,
foreign write principals are blocked without changing any ACL.
The resolver does not create directories. Python CLI and daemon use
`runtime/storage.py`; the NVDA build includes that exact file. Native launcher
implements the same contract in `src/storage.rs` and forwards the resolved root
through Tauri's environment allowlist to BE. An already-running NVDA consumer
must acknowledge the same canonical root/PID before capture can report READY. Explicit daemon `--home --isolated`
starts an isolated lifecycle without inheriting unrelated parent roots.

| Storage | Canonical path | Owner |
|---|---|---|
| Equipment capture / events | `state/character.db`, `state/events.db` | BE capture |
| Public HUD | `state/hud.sqlite3` | BE writer; Tauri query-only reader |
| Capture/runtime/selection/journal/PATH metadata | `state/` | corresponding BE service |
| Original session evidence and capture logs | `sessions/<timestamp>-<id>/` | capture |
| Target builds | `targets/` | authorized tool/user; BE validation |
| Registry/profiles/trust/store/staging | `rulekit/` | Rule Kit official APIs |
| Three app logs | `logs/<run-id>/{fe,be,rulekit}.log` | S8 component loggers |
| Log locks/quota | `logs/.control/` | S8 runtime |
| NVDA controller assets/cache | `runtime/nvda-controller/` | capture runtime |
| Launcher settings | `launcher.json` | launcher/authorized config |
| Bootstrap and migration metadata | `private/` | launcher/migrator |

`D4PLANNER_DATA_DIR` is **DataRoot/state**, never DataRoot. Rule Kit receives
`D4_RULEKIT_DATA_ROOT=DataRoot/rulekit`. Equipment repository opt-in remains
explicit; external read-only sources retain their existing ownership. Installer,
Python, Node and Chromium remain outside DataRoot. S9 remains selected-log-only;
no DataRoot upload/export has been added.

## LEGACY mapping and explicit migration

LEGACY `%LOCALAPPDATA%\d4planner/{state,sessions,runtime,logs}` maps to the same
relative path under DataRoot, except LEGACY `cache/**` maps to
`runtime/nvda-controller/cache/**`, a root controller DLL maps to
`runtime/nvda-controller/`, and `logs/event-migration.jsonl` maps to
`state/event-migration.jsonl`. Existing canonical targets, Rule Kit, HUD and logs
are preserved. Unknown files are inventoried conservatively, never deleted.
Byte-identical collisions skip; different destination bytes block without merge.

Use the installed Python CLI (or `python -m d4planner.cli`) in an offline window:

```powershell
d4planner storage paths
d4planner storage migrate --source C:\LegacyData --target C:\CanonicalData --report C:\Evidence\plan.json
d4planner storage migrate --action apply --manifest C:\Evidence\plan.json --report C:\Evidence\apply.json
d4planner storage migrate --action verify --manifest C:\Evidence\apply.json --report C:\Evidence\verify.json
d4planner storage migrate --action rollback --manifest C:\Evidence\apply.json --report C:\Evidence\rollback.json
```

Each report path must be new and outside both roots. Dry-run writes only the
explicit report. Processes/tasks are never stopped by migration. Windows
preflight conservatively requires no other Python/Node/launcher/HUD/NVDA process
and no enabled D4Planner scheduled task. Owner/ACL checks reject foreign owners
and foreign write permissions. Share-read file leases exclude writes/deletion
while staging/publishing. Non-Windows production migration is blocked; tests use
an injected offline probe only for isolated temporary fixtures.

Source is retained as the original backup. Known `runtime.sessionDir`,
`capture.rawSpeechPath`, `capture.diagnosticsPath`, and opt-in equipment repository
paths inside the approved source are rebased with before/after evidence. External
equipment paths are inventoried/verified but remain external and opt-in.
Historical session and log bytes are never rewritten. Staging verifies SHA-256, SQLite
integrity/schema/row counts/user_version; publication uses atomic no-overwrite
links and checkpoints intent before each file. `private/storage-migration.json` plus the source migration marker
block new runtimes during interrupted publication. Use its manifest for explicit
rollback, then rerun preflight. Never delete the journal to bypass recovery.
Rollback checks every published hash and SQLite sidecar before any removal; new
writes cause BLOCKED/manual recovery, never restoration of an old DB over new data.
A completed pointer in the preserved source rejects stale legacy CLI/NVDA
consumers rather than silently opening the old data. Known generated helper
scripts under `runtime/bin` are retained only in the source and listed as
`SKIP_RUNTIME_GENERATED`; the canonical runtime regenerates them. Existing
scheduled tasks must remain disabled until explicitly rebound to the canonical
runtime. The migrator does not silently re-enable or replace tasks.
A verified receipt allows the default resolver to recognize a preserved legacy
source; changes to legacy source bytes require renewed migration review.

Conservative blockers currently requiring explicit recovery/review: nonempty WAL
or rollback journals (checkpoint offline with the owning subsystem), unknown legacy absolute metadata fields, active source locks, and unknown
source entries. Restore managed User PATH explicitly before migrating metadata
that still refers to legacy controller paths; the migration does not edit User PATH. No regex path rewriting,
implicit external DB adoption, or automatic source cleanup is performed.

## Acceptance and current limits

Run `python tools/storage_acceptance.py --output <new-evidence-directory>` from
this BE directory. Use `--only UDR-06` for a targeted rerun into a new directory.
Reports contain exact source HEAD/tree status, commands, exits and per-case logs.
Tests run only in temporary fixture directories. UDR IDs are stable; each report
distinguishes local test evidence from the full ticket gate.

Packaged Windows install/reinstall/upgrade/uninstall, native process/ACL/race
validation, NVDA integration with a real addon and game, and full lifecycle coverage remain
acceptance gates until native evidence proves them. Do not interpret unit PASS
as all ten ticket gates passing. CI_NOT_CHECKED; no Actions query/trigger.

Native regression on the enrolled dedicated builder (never machine A):

```sh
python utility/d4planner/d4planner-be/tools/storage_vm_acceptance.py --output /absolute/new-evidence
python utility/d4planner/d4planner-be/tools/storage_vm_acceptance.py --suite storage --output /absolute/new-targeted-evidence
```

The wrapper holds the existing builder lock and records source snapshot identity.
It checks the installed Python version, runs Windows tests, an actual offline
migration/rollback fixture with no process/ACL probe substitution, and native
Rust launcher/S8/S9 tests. Failed/disconnected runs remain available for diagnosis.
No native test failure is converted into PASS or hidden by Linux results.

To run local and native checks together, including a checksum-bound Setup from the
same committed HEAD:

```sh
python utility/d4planner/d4planner-be/tools/storage_acceptance.py --output /absolute/new-evidence --windows-vm --setup /absolute/build/D4Planner-Setup-1.2.8.exe --old-setup /absolute/previous/D4Planner-Setup-1.1.1.exe
```

The local report links the native source identity, migration manifest (source and
target SHA-256/SQLite checks), subprocess exits and S8/S9 logs. The Setup driver
uses a fresh private sandbox and the installer UAT identity, verifies persisted
bytes across upgrade/reinstall/viewer-only/uninstall, and compares production
registration before/after. It refuses to take over an existing UAT registration.
`ticketGate: NOT_RUN` is retained as a deliberate reminder that test-suite PASS
is evidence to review against the entire UDR row, not automatic Owner acceptance.
