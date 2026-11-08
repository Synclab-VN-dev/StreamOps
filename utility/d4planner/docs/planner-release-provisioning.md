# Create Build: Planner UI provisioning

Create Build reuses the validated local UI snapshot without contacting GitHub.
On a fresh installation, RuleKit discovers stable releases in
`Synclab-VN-dev/StreamOps`, selects the highest compatible semantic version,
downloads only its UI asset, decrypts and verifies it, publishes the local
selection, and starts the authenticated loopback Planner at port 6085. HUD opens
the browser only after its owned listener passes health verification.

The UI snapshot is independent of Calculation snapshots. Provisioning does not
change Calculation selection, profiles, Targets, or the application database.
An existing corrupt/unvalidated registry is an error; it is never overwritten.
An existing capture registry without an active UI must be resolved through its
capture/activation workflow. This bootstrap path only creates a missing registry.

## Release contract

- Stable, non-draft tag `d4planner-snapshots/vMAJOR.MINOR.PATCH`.
- `snapshot-pair.json`, schema `d4planner-snapshot-pair/v1`, matching version.
- UI asset `ui-snapshot-VERSION.zip.age` with byte count and SHA-256,
  snapshot ID, manifest SHA-256, `plannerProtocolVersion: d4planner-local-planner/v1`,
  and `uiTrust` (schema, coverage/validation hashes, authorization reference).
- The release producer copies trust pins from the validated captured package.
  Compatibility means the Planner UI protocol, not Calculation compatibility.
- Only the fixed repository API and approved GitHub asset CDN hosts are used.
  Trust is the repository's HTTPS release channel plus pinned asset/receipt/blob
  hashes; age encryption alone does not authenticate a publisher.
- Old Calculation-only releases and incompatible protocol versions are skipped.
  No compatible UI release produces `PLANNER_RELEASE_NOT_FOUND`; nothing launches.

## Local configuration

Both files belong under the selected DataRoot's `private` folder (default
`%LOCALAPPDATA%\StreamOps\D4Planner\private`):

- `report-config.json`: reuse its `githubToken` field for private-repository read
  access. Preserve its existing report configuration fields. Anonymous access is
  attempted if the file/token is absent. The token is sent only to api.github.com,
  never forwarded to asset CDN redirects or returned to the HUD.
- `snapshot-age-identity.txt`: one age X25519 secret identity matching the public
  recipient used to encrypt the snapshot release. Comment lines are allowed.
  A report encryption **public recipient** is not a decryption identity. Obtain
  the matching secret identity from the release owner; never put it in source,
  releases, logs, or issue attachments. Restrict file access to the current user.

Native decryption uses the installed FE executable's internal helper, not a
system Python/age binary. Missing key, inaccessible repository, download failure,
and integrity/decryption failure have separate sanitized HUD errors.

## Failure and concurrency behavior

The Planner request has a 180-second total provision/validation/start budget
(185 seconds at backend IPC, 190 at native IPC); unrelated APIs keep their budgets.
Requests share one flight; cancelling the last waiter stops provisioning before
publication. Downloads and extraction have bounded sizes. ZIP links, traversal,
Windows reserved names, case collisions, and overwrite attempts are rejected.

A cross-process exclusive `.provision.lock` serializes writers. Selection is
published through an atomic no-replace link after validation. A failure removes
only that invocation's staging files and unpublished package. An abrupt process
termination can leave a lock or orphan staging directory: fail closed and have
an operator verify that no provisioner is running before removing those specific
leftovers. Do not remove capture state or Calculation stores to retry.

No live snapshot is embedded in Setup. Successful live provisioning requires an
owner-published compatible UI release and its matching local identity; tests use
synthetic packages and do not publish releases or copy keys to user machines.
