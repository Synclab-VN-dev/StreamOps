# D4Planner Release 1 delivery gate (S7)

This directory contains the independent package and one-shot acceptance gate
for `R1-EQUIPMENT-20261025`. It does not include sibling implementation
artifacts and cannot certify Windows/runtime/visual/manual acceptance on Linux.

`package-plan.json` pins the S1 contract, approved MagicPath revision, Rule Kit
external Rule Kit Snapshot Management contract, Playwright version, artifact owners and persistent paths.
The builder requires all sibling-produced artifacts, rejects missing files,
symlinks and unsafe paths, then writes a deterministic ZIP whose generated
manifest hashes every file. It never downloads `latest`, captures Maxroll, or
substitutes a synthetic executable.

The installer keeps application files separate from DataDir. Upgrade replaces
the application directory while preserving `targets/` and `state/`; it never
wipes a database or user Target to recover from an error. The included Target
fixture under the S1 contract remains synthetic test data and is not selected
as a production Target automatically.

## Application / Snapshot split

Application Setup does not contain a Maxroll snapshot/profile, plaintext or
encrypted. Rule Kit owns the external `DataRoot/rulekit` store and signed registry,
compatibility, import/activation/switch/rollback. BE only forwards its API/status.
Without a snapshot the app/Equipment remain available; calculation is UNAVAILABLE.
Production trust activation awaits the Owner-pinned public key/key ID. No automatic
fallback or acceptance of a newly signed but unverified binding. See
[Windows installer](WINDOWS-INSTALLER.md) and [Release CI](RELEASE-CI.md).

## Owner HUD-03 manual launch

The production launcher defaults to an isolated DataDir, an empty Target
folder, no Equipment capture database and a dynamically bound loopback port.
It never injects the recorded synthetic fixture or selects a Target. With no
Target/Equipment data the native HUD must show `SELECT TARGET`/`NO DATA`, never
a fabricated score. It uses only runtimes bundled in the verified package.

After installing the package, launch it from an interactive desktop:

```powershell
pwsh -NoProfile -File <install>\D4Planner\app\start-d4planner.ps1 `
  -InstallRoot <install>\D4Planner -DataRoot <isolated-data> -WsPortMode Dynamic
```

Stop gracefully with the global `Ctrl+Shift+F11` shortcut, or from another
terminal use the ownership-checked recovery command:

```powershell
pwsh -NoProfile -File <install>\D4Planner\app\stop-d4planner.ps1 `
  -DataRoot <isolated-data>
```

`Ctrl+Shift+F10` toggles interactive/click-through mode. The window starts
interactive, draggable and always-on-top. The stop script validates PID,
executable path and process start time, requests a normal window close, and
fails closed rather than killing by process name. For an Owner-approved UAT
mapping, use `-WsPortMode FixedApprovedUat -ApprovedPort <approved-port>`; an
unavailable fixed port fails startup. Attaching a capture database additionally
requires `-EnableReadOnlyEquipmentRepository`, its explicit path, and explicit
`-CharacterId` / `-CharacterDisplayName` values. Omitting either identity fails
before the native process starts; HUD-03 without a DB requires none of them.

## Commands

Build only after reviewed sibling artifacts are staged at the exact paths in
the plan:

```text
python utility/d4planner/tools/release1_delivery.py build \
  --plan utility/d4planner/release1/package-plan.json \
  --source <reviewed-staging> --output <private-output>/d4planner-r1.zip
```

Provision or upgrade only after package verification. Application files and
persistent data must be separate:

```text
python tools/release1_delivery.py install --package d4planner-r1.zip \
  --app-dir <install>/D4Planner --data-dir <LocalAppData>/d4planner

python tools/release1_delivery.py rollback --app-dir <install>/D4Planner \
  --data-dir <LocalAppData>/d4planner
```

Run the acceptance matrix in one shot, or choose a targeted subset. A resume
report reuses only prior PASS cases; it never upgrades BLOCKED/FAIL/NOT_RUN.
Automated runtime/visual/performance cases execute only commands declared in a
reviewed `d4planner-e2e-executors/v1` manifest. Each command runs without a
shell, inside the isolated staging tree, with a bounded timeout and a private
per-case log. A missing executor remains `PENDING_DEPENDENCY`; a nonzero exit
is `PRODUCT_FAILURE`, and a timeout is `HARNESS_FAILURE`.

```text
pwsh -NoProfile -File utility/d4planner/release1/d4planner-r1-uat.ps1 \
  -Package <private-package> -Output <private-evidence>/report.json \
  -ExecutorManifest <reviewed-staging>/executors.json

# targeted resume is not a full pass
pwsh -NoProfile -File utility/d4planner/release1/d4planner-r1-uat.ps1 \
  -Package <private-package> -Output <private-evidence>/resume.json \
  -Case S7-PKG-01,S7-PRE-01 -Resume <private-evidence>/report.json
```

Evidence directories must remain private and are not committed. The runner
classifies missing Windows as `ENVIRONMENT_FAILURE/BLOCKED`, missing sibling
runtime or Golden evidence as `PENDING_DEPENDENCY/BLOCKED`, product/package
integrity errors as `PRODUCT_FAILURE/FAIL`, unselected cases as `NOT_RUN`, and
MAN-01…03 as `OWNER_MANUAL/NOT_RUN`. It does not choose a port, start services,
touch Windows A, or operate Steam, OBS, Diablo IV or NVDA.

## Acceptance boundary

- S7-07 runner/package behavior can be tested locally.
- S7-01 Windows installation remains NOT_RUN until the integrated package is
  built and provisioned on an approved Windows environment.
- S7-02…06 depend on S2–S6 integration, approved visual Golden, Windows/runtime
  evidence and defined workloads. Linux package tests do not satisfy them.
- MAN-01…03 always require Owner action and review.

### Resume provenance and rollback recovery

Resume binds each selected automated PASS to its case specification, shared runner
SHA-256, resolved executable/script bytes, approved port and isolated staging/evidence
context, in addition to the existing plan/package/component bindings. Executor
`inputFiles` (paths relative to staging) must list separately imported external
assertion/configuration files; packaged dependencies remain bound by the package.
Changing another case's executor does not invalidate an unchanged case. Legacy
reports without provenance are rerun, not upgraded into current PASS evidence.
Scenario evidence must still exist, satisfy current required fields and match its
recorded SHA-256. Before rerunning a case, prior scenario evidence is retained in
`.previous-evidence`; it cannot stand in for missing fresh output. Preflight is
always rechecked. MAN-only/zero-PASS runs return NOT_RUN with nonzero exit; mixed
successful automated subset plus MAN remains SUBSET_PASS_MAN_PENDING, never manual
acceptance. These hashes establish local provenance, not a signed trust attestation.

Rollback uses the same `upgrade-journal.json` and owned transaction directory as
installation. Until journal commit, normal root-launcher startup remains blocked.
Recovery aborts an interrupted rollback to the verified pre-rollback application
(version, launcher hash and active metadata), then rollback can be retried. It
checks current DB schema compatibility read-only, never restores an old DB, and
never copies back/deletes Targets, Settings or the external Rule Kit snapshot store.
A tampered recovery payload/backup fails closed with its journal preserved. Cleanup
removes only transaction-owned files and retains unknown files. No new Rule Kit
compatibility or distribution policy is defined by this recovery mechanism.

## D5 DB-first delivery

Contract candidate.6 replaces the candidate.5 full-HUD WebSocket wire protocol.
The public HUD DB is `DataRoot/state/hud.sqlite3`; launcher passes that absolute
state directory as `D4PLANNER_DATA_DIR` independently of the private BE bootstrap.
`D4Planner.exe --viewer` opens the same FE without BE bootstrap/start and permits
missing optional Python/Node/Chromium resources. Existing resources still undergo
integrity checks. Default installed mode is integrated; failed Backend startup
leaves FE available. No second Python command entrypoint exists.

Worker is `backend/site-packages/d4planner/rulekit/worker.js`. The internal Rule Kit
bootstrap and composition modules are explicitly in the public source allowlist.
Private snapshots and keys remain excluded. Schema migration accepts private HUD
v2 and v3; the public projection format is d4planner-hud-db/v1. Upgrade/rollback
must preserve state/Targets/settings; FE never migrates or recreates a failed DB.

The native HUD E2E selects Target through owned-window UI Automation, exercising
Tauri → managed IPC; its WS observer only validates committed revision metadata.
Golden, Owner MAN, installer/Windows-native and live capture gates remain separate
from synthetic input tests. This document is not evidence that those gates passed.
