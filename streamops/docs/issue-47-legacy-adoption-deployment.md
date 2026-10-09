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

## Deployment identity and staging

CI creates the artifact `streamops-node-deployment-<40-char-commit>`. It contains
the StreamOps wheel, binary dependency wheels, and `deployment-manifest.json`
with the source commit, sizes, and SHA-256 values.

On Windows A, stage without touching the running service:

```powershell
pwsh -File scripts\devices\a-windows\prepare-streamops-node-deployment.ps1 `
  -BundleRoot C:\approved-transfer\streamops-node-deployment `
  -ExpectedCommit <exact-pr-head>
```

The script verifies every bundle file, creates an immutable venv under
`.streamops\deployments\<commit>`, installs offline, and writes no production
environment variables. The running commit is taken from that deployment's
hash-pinned metadata, not the checkout HEAD.

Read-only validation before an approved window:

```powershell
pwsh -File scripts\devices\a-windows\test-obs-plugin-deployment-readiness.ps1 |
  Set-Content issue47-deployment-readiness.json
```

The output includes the Scheduled Task action, running Python/deployment commit,
OBS output state, three Plugin Manager APIs, managed release count, and plugin
file hashes. It omits process command lines and all environment values.

## Activation and server rollback

Only after maintenance approval, with OBS streaming and recording both false:

```powershell
pwsh -File scripts\devices\a-windows\activate-streamops-node-deployment.ps1 `
  -DeploymentRoot C:\path\to\.streamops\deployments\<exact-pr-head> `
  -RollbackDeploymentRoot C:\path\to\.streamops\deployments\<previous-commit> `
  -MaintenanceApproved -ExpectEmptyCatalog
```

Activation captures the existing Scheduled Task XML and idle-output evidence,
switches only the StreamOps server runtime, and configures the process with:

```text
STREAMOPS_OBS_PLUGIN_SOURCE_PROVIDER=github-release
STREAMOPS_OBS_PLUGIN_SOURCE_LOCATION=Synclab-VN-dev/StreamOps-OBS-Plugins
```

It validates:

```text
GET /api/v1/obs/plugins
GET /api/v1/obs/plugins/obs-multi-rtmp
GET /api/v1/obs/plugins/available
```

If activation fails, the prior task definition is restored automatically. Manual
server rollback uses the captured `task.xml` and `output-idle.json` with
`rollback-streamops-node-deployment.ps1 -MaintenanceApproved`. None of these
deployment scripts invokes plugin adopt/install/update/rollback.

## Gates remaining before real mutation UAT

- Obtain maintenance approval and a current backup/rollback approval for A.
- Configure the protected GitHub environment `obs-plugin-release` and a
  fine-grained release-repository token with only required contents permissions.
- Land the release-only workflow/infrastructure on `master` without merging the
  unaccepted Plugin Manager feature. Keep runtime feature code on the Draft PR.
- Publish no artifact until custom v1 is built from the approved StreamOps source
  commit with license and provenance; v2 must contain a real source change and a
  different DLL SHA-256.
- Configure the GitHub provider on A and prove an empty repository reports
  `source_state=EMPTY`, never upstream content.
- Re-run read-only baseline hashes immediately before maintenance. Then stop OBS
  explicitly, adopt legacy, verify the backup/journal, and only afterward approve
  installation of v1.

Until those gates have real evidence: deployment is **NOT READY** and plugin
mutation UAT is **NOT READY**.
