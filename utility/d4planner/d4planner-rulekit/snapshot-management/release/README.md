# Snapshot release (#180)

The `d4planner-snapshots` product uses existing CI discovery and build/publish jobs.
No shared workflow or CI engine change is required. Build uses the `read`
capability and needs only a public age recipient, with no private key or secret.

Each build invokes the existing capture workflow in `all` mode to capture and
validate Calculation and UI snapshots. It packages each native snapshot root into
a ZIP and encrypts it with `age --encrypt --recipient`. Rule Kit adoption is a
separate operation. This adapter adds no compatibility, signature, decryption or
replay checks.

## Release from the GitHub Actions web UI

After this change is merged into master, configure one **repository Variable** at
**Settings → Secrets and variables → Actions → Variables → New repository variable**:

Name: `D4_SNAPSHOT_RELEASE_CONFIG`

Value (JSON, single-line or formatted; replace the placeholders):

```json
{
  "sourceUrl": "https://maxroll.gg/d4/planner/<build-id>",
  "ageRecipient": "<public age X25519 recipient>"
}
```

The source must be an anonymous, approved Maxroll Planner build URL with an
alphanumeric build ID. A query string, alternate host, credentials, or HTTP URL
is rejected. `ageRecipient` must match the private identity held by the release
consumer; it is **not** an `AGE-SECRET-KEY-…`. No private identity belongs in this
Variable or in Actions. Variables are configuration, not secret storage.

Then open **Actions → CI → Run workflow**:

| Input | Value |
| --- | --- |
| Branch | `master` |
| operation | `publish` |
| component | Leave empty |
| product | `d4planner-snapshots` |
| version | A new version, e.g. `1.0.0` |

One publish run captures and validates both snapshots, builds encrypted artifacts,
then publishes those exact verified artifacts. The release title is
`d4planner-snapshot-1.0.0`; its tag remains `d4planner-snapshots/v1.0.0`.
Existing tags/releases cannot be overwritten. Use a stable `MAJOR.MINOR.PATCH`
version for the Planner release discovery flow.

For a build-only check, select `operation = build`: it produces a CI artifact,
not a GitHub release. A later `publish` run builds again; it does not consume a
previous run's artifact. Both operations use the same repository Variable.
Editing this Variable is enough to change future capture configuration; no
source commit is needed.

The workflow transports GitHub Variables generically through `CI_VARIABLES_JSON`.
Only the snapshot pair build consumes this configuration, through
`ctx.variable('D4_SNAPSHOT_RELEASE_CONFIG')`. Adding another repository Variable
for another component does not require changes to `main.yml`. Missing, oversized,
malformed, duplicate-key or invalid configuration is blocked before capture,
without falling back to `release/config.json`. Basic field validation runs before
tool installation; the age binary additionally verifies the recipient checksum
before installing capture dependencies. The JSON limit is 16 KiB. The two
fields above are required; additional fields are rejected. Error codes identify
the field, for example `BLOCKED_SNAPSHOT_CONFIG_SOURCE_URL` or
`BLOCKED_SNAPSHOT_CONFIG_AGE_RECIPIENT`. `BLOCKED_SNAPSHOT_CONFIG_MISSING` means
that the repository Variable is absent/empty. Capture/validation failures still
block publication.

The build loads configuration once for both packages; publish uses the verified
build artifact without reading the Variable again. The existing manual-master
publish authorization and token scopes remain unchanged. There is no new Secret,
workflow input, or permission requirement.

The Planner consumer in PR #188 accepts this existing release format. It verifies
archive hashes, decrypts the UI package and checks the enclosed manifest and
coverage/validation receipts before activation. No additional Planner-specific
release metadata or republishing of existing snapshot releases is required.

`authorizationRef` is no longer a release configuration field. Remove it from
existing release JSON before running this version. New UI receipts/trust metadata
omit it; old UI receipts remain readable. Manifest, resource, coverage and
validation hashes and the automated validation status remain enforced.

## Local builds

Local builds continue reading `release/config.json` or the file selected by
`SNAPSHOT_RELEASE_CONFIG`. Configure the same two fields in that file. The
committed example's null source URL is intentionally not runnable.
Actions does not accept this local file override. The JSON repository Variable
is used only in Actions.

Local invocation from a clean committed checkout:

```sh
python3 .github/workflows/ci.py plan --changed --base HEAD \
  --product d4planner-snapshots --operation build --output /tmp/snapshot-plan
python3 .github/workflows/ci.py run \
  --plan /tmp/snapshot-plan/plan.json --version 1.0.0 \
  --output /tmp/snapshot-run
```

The adapter installs the existing capture dependencies, Chromium, Pillow and the
pinned age binary if needed. Temporary config, capture stores and plaintext ZIPs
stay outside the checkout and are removed after the build. Each ZIP contains its
snapshot ID directory with manifest, anchor and blobs; UI also includes the
existing coverage and validation receipts. Capture logs are excluded.

Build exports only two `.zip.age` files, `snapshot-pair.json` with source/capture
identifiers and encrypted asset hashes, and `SHA256SUMS`. Publish consumes the
artifact verified by the existing CI Context and uses Application Release's
existing release-absence and exact-source-tag helpers, then creates the GitHub
Release under `d4planner-snapshots/v<version>`. Existing CI authorization controls
publish; building alone does not publish. No additional workflow or approval gate
is introduced.
