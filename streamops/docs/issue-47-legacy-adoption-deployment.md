# Issue #47 — Legacy adoption and Windows A deployment gate

## Adoption contract

`POST /api/v1/obs/plugins/obs-multi-rtmp/adopt` is the only operation that
turns an existing unmanaged plugin tree into managed legacy state. It accepts no
body or query parameters and has the matching WebSocket operation
`obs_plugin.adopt`.

Adoption requires all outputs idle and OBS fully stopped. StreamOps does not stop
or restart OBS for this operation: the maintenance operator must do that
explicitly. Status and inventory never adopt automatically. Adoption records file
lengths and SHA-256 values plus config path/length/SHA-256 metadata; it never reads
config contents into the journal and never assigns an unproved version or source
commit.

Config backup bytes stay inside the local transaction backup so rollback can
restore them byte-for-byte; they are never serialized into the journal, API,
logs, CI artifacts, or operator evidence. The backup directory must inherit the
same access controls as the StreamOps data directory.

The transaction states distinguish `legacy_adopted` from
`approved_release_installed`. Backup bytes are verified before the pointer is
committed. Install/update use a recoverable two-phase journal, and an unfinished
transaction produces `RECOVERY_REQUIRED`; no later mutation proceeds until an
explicit rollback/recovery while OBS is stopped. Both exact and mismatched legacy
trees retain a byte-for-byte rollback baseline. Exact approved bytes are promoted
only after the approved artifact and manifest are independently verified, without
rewriting the existing files.

## StreamOps Node operator entrypoint (PR #52 simplification)

Windows A is operated through **one PowerShell script** from the selected, approved
checkout (production or isolated PR worktree):

```powershell
.\scripts\devices\a-windows\streamops-node.ps1 start
.\scripts\devices\a-windows\streamops-node.ps1 status
.\scripts\devices\a-windows\streamops-node.ps1 stop
```

- `start` creates/reuses only the specified repo-owned Scheduled Task and DataDir
  and launches `streamops.cli runserver` in the interactive Windows session.
  It performs health/capture checks and rejects an unexpectedly occupied port.
- `status` verifies task, PID/session and API health without modifying runtime.
- `stop` targets only the specified repo-owned task/runtime. It does **not**
  stop OBS, Steam, Diablo IV or a third-party process.
- An internal `__run` dispatch is used **only by the Scheduled Task**. Operator
  commands remain `start | stop | status`.
- The managed GitHub Release Source defaults to
  `Synclab-VN-dev/StreamOps-OBS-Plugins`. A read-only token can be entered via
  secure prompt; a one-use DPAPI handoff with owner-only ACL transfers it to
  the interactive Scheduled Task. No token is printed in logs or task arguments.

For an isolated PR test node, provide `-TaskName StreamOps-PR52-Manual`,
`-DataDir .streamops/pr52/node`, `-Port 18752` and `-BindHost 127.0.0.1`;
check that the port is unoccupied **before** invoking start. Never redirect a
production task to a test checkout.

**Out of scope in this PR:** Transactional StreamOps *Node version*
upgrade/activation/rollback and its wheelhouse deployment artifact. The former
staged-deployment scripts and associated packaging steps have been removed.
This does **not** remove OBS **plugin** install/update/rollback or the separately
approved OBS plugin release packaging workflow. Merging source code is not
authorization to deploy a new Node or publish a plugin release.

## Operational safety

- Do not invoke `start` to change an active production Node without approved
  maintenance. The start command can replace an unhealthy/mismatched task.
- All real OBS plugin install/update/adopt/rollback mutations are still subject
  to their existing maintenance approvals and idle-output/recovery guards.
- For read-only Plugin Manager checks, use `status` and the REST/WS status or
  catalog APIs. For Vendor readiness, use `scripts/e2e/issue47_probe_vendor.py`.
- For remaining D09 streaming-only Real-A UAT, see issue #75 DEV-F-13:
  do not auto-enable public multi-RTMP targets or relax `syncStart` safeguards.

The original rollout/approval policy remains: no automatic production change
from a PR merge or a passing GitHub Action.
