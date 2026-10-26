# D4Planner Release 1 delivery gate (S7)

This directory contains the independent package and one-shot acceptance gate
for `R1-EQUIPMENT-20261025`. It does not include sibling implementation
artifacts and cannot certify Windows/runtime/visual/manual acceptance on Linux.

`package-plan.json` pins the S1 contract, approved MagicPath revision, Rule Kit
snapshot manifest, Playwright version, artifact owners and persistent paths.
The builder requires all sibling-produced artifacts, rejects missing files,
symlinks and unsafe paths, then writes a deterministic ZIP whose generated
manifest hashes every file. It never downloads `latest`, captures Maxroll, or
substitutes a synthetic executable.

The installer keeps application files separate from DataDir. Upgrade replaces
the application directory while preserving `targets/` and `state/`; it never
wipes a database or user Target to recover from an error. The included Target
fixture under the S1 contract remains synthetic test data and is not selected
as a production Target automatically.

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
