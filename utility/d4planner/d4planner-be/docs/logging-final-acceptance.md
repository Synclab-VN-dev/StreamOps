# LOG-09 / LOG-10 reproducible final Setup acceptance

Refs #159. Assessment: **PARTIALLY_AGREE / NEEDS_DIFFERENT_SOLUTION**. Logging is
implemented; missing acceptance is principally exact-package evidence. At base
`d5ec36fc9210c6d874870c9807c57e982d3bc857`, comparing the final PR #160 source
(`1074f0f58ed1b142a4f8361770a8734e24b95722`) shows only three CI routing file
changes under `utility/d4planner`. Master contains S8 even though history was
integrated by cherry-pick. LOG-01…08 evidence is historical, not rerun here.

Existing Python/Rust/Node tests cover queue bounds, quota, retention, privacy,
fail-open, generation and export. `production_e2e.py` already provides recorded
producer input, DB/render equality, native window capture and stage timestamps.
The prior installer runners cover transaction recovery but either hard-code
versions or create production-registration fixtures. Reuse their primitives;
the LOG runner confines writes to the UAT identity and a newly created sandbox.
No production logging defaults, UI, APIs, trust or packaging architecture change.

## Build and run

Create a clean commit before building; record the base and HEAD. Use the dedicated
F builder, then a separate Windows VM without installed development runtimes:

```bash
git rev-parse HEAD
python3 utility/d4planner/script/build/build_vm.py --ref HEAD --output "$HOME/d4planner-builds/log159-final"
PYTHONPATH=utility/d4planner/d4planner-be/src python -m pytest -q utility/d4planner/d4planner-be/tests/test_logging_acceptance.py utility/d4planner/d4planner-be/tests/test_production_e2e_delivery.py
```

Copy the exact source tools, final Setup and compatible previous Setup to private
VM media. The runner's private Python/dependencies must be outside InstallRoot;
use the existing private harness/interactive task mechanism described in
`release1/windows-installer-uat.ps1`. Do not register a global Python/Node/Rust.
The private harness imports the installed BE plus these source tools. On the
isolated interactive desktop (PowerShell; substitute exact paths and SHA):

```powershell
& $HarnessPython -X utf8 $Tools\windows_logging_setup_e2e.py --sandbox C:\LOG159\run --setup-old $OldSetup --setup-new $FinalSetup --source-head $ExactHead --output C:\LOG159\evidence --benchmark-runs 10 --benchmark-samples 20
```

The runner exercises fresh final Setup, actual native logging with no snapshot,
paired overhead, uninstall, compatible old Setup, upgrade while the old app is
running, three interrupted rollback activation checkpoints, recovery/runtime
health, and final uninstall. It retains SHA inventories for logs, settings,
Targets and a user SQLite canary. Runtime-owned HUD DB may legitimately update
during launch; user DB/selection/log preservation is checked independently.
No fixture writes to production registry. Keep evidence private and shut down
only the VM/resources owned by this UAT run after retrieving evidence.

Uninstall checks the existing ownership contract: every manifest-declared file
must be removed; unrecognized files must retain their hashes. Runtime-generated
Python bytecode is not part of that manifest and can leave version directories
behind. The runner inventories this explicitly, rather than assuming an empty
InstallRoot or adding recursive deletion that could erase user files. A pilot
found 82 such `.pyc` files; the initial empty-directory assertion was incorrect.
The upgraded app is also reopened on its preserved `launcher.json`, producer DB
and selected Target before recovery/uninstall. Process and listener cleanup is
checked independently from intentionally preserved files.

The upgrade fixture seeds user inputs and closed logs, but lets the previous
runtime create its own HUD database. Copying a newer runtime's HUD DB into the
previous release is a downgrade test and correctly fails with
`HUD_STORE_SCHEMA_NEWER_THAN_RUNTIME`; an initial native run exposed this fixture
error. Keep that failed attempt separately and rerun the corrected upgrade path.
Automated launches use `--launch` so a failed start exits instead of leaving an
interactive error dialog; teardown still attempts uninstall after a stop error.

## Measurement interpretation

The default INFO arm and disabled arm use identical installed bytes and recorded
producer input. The disabled arm creates a file at `logs` in a fresh disposable
DataDir, exercising existing fail-open initialization. Its one failed directory
creation is included; this baseline is **not** a pre-S8 build and does not remove
the instrumentation call sites. No production off switch is introduced.

Order alternates by pair. One complete warmup pair is retained but excluded from
quantiles. Every capture revision must reach the actual native WebView and match
SQLite. Each run also activates Target B through native UI Automation and checks
the committed score delta. Its timing includes UI Automation invocation overhead
in both arms. Current D5 capture/Target scoring uses BE assessment; the Rule Kit
worker participates in startup/health, not each score update. Do not label these
operations as worker calculation or live-game measurements.
P50 is median; P95 uses inclusive linear interpolation. Reports retain
all samples, absolute and percentage differences, counts, durations, loss markers,
and cumulative process CPU/IO plus end-of-workload RAM. Small samples and scheduler
noise do not justify a speedup claim or a new SLA. Record regression analysis
separately; a generated report says MEASURED, never automatically LOG-09 PASS.

BE and Rule Kit READY timestamps come from INFO logs only; they are startup
diagnostics, not paired estimates. Worker process READY is distinct from missing
snapshot/calculation UNAVAILABLE. Native FE updates and end-to-end producer-to-
render timings are paired. All input is recorded/synthetic, never live-game
evidence. CPU/IO omit descendants that already exited; RAM is not a peak measure.

Keep `setup-acceptance.json`, `commands.log`, `benchmark/benchmark.json`, per-run
samples, manifests and SHA inventories in private custody. Publish only sanitized
aggregate results, exact source/base/Setup hashes, commands, exit codes, durations,
and evidence-manifest hashes in the PR/issue. Unit validator PASS cannot establish
native acceptance. CI_NOT_CHECKED; Owner MAN, trust, release and deployment gates
remain independent. Do not tick/close #159 automatically.
