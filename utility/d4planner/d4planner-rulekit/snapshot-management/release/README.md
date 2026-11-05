# Snapshot release (#180)

The `d4planner-snapshots` product uses existing CI discovery and build/publish jobs.
No shared workflow or CI engine change is required. Build uses the `read`
capability and needs only a public age recipient, with no private key or secret.

Each build invokes the existing capture workflow in `all` mode to capture and
validate Calculation and UI snapshots. It packages each native snapshot root into
a ZIP and encrypts it with `age --encrypt --recipient`. Rule Kit adoption is a
separate operation. This adapter adds no compatibility, signature, decryption or
replay checks.

Configure `sourceUrl` and `authorizationRef` in `release/config.json` with the
approved anonymous source before a hosted build. They are intentionally unset;
the existing capture tool validates them. `ageRecipient` is public. Local builds
may use `SNAPSHOT_RELEASE_CONFIG` pointing to an equivalent config outside the
repository; Actions uses the committed config.

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
