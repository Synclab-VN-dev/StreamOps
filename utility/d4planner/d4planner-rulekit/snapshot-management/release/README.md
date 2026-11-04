# Snapshot release (#180)

Assessment: AGREE / FIX_REQUIRED for the simplified ZIP + age contract. Capture
already supports `--mode all`, UI acceptance and exact runtime comparison, but
COMPLETE does not approve Calculation. Existing encrypted-fixture packaging only
accepts Calculation files and cannot package a native UI snapshot unchanged.
The new product composes existing capture, Rule Kit trust/import and acceptance;
it adds no signing keys, signatures or compatibility definitions. Release tooling
lives outside the execution-index inputs so existing execution identity is preserved.

## Entrypoint

`ci.release.py` owns product `d4planner-snapshots`. Both local `ci.py` execution and
Actions invoke its `run(ctx)`. `main.yml` only routes a manual private build and a
separate publish job. The new private-build capability uses the existing fixture
age identity, with read-only GitHub permissions. Actions private builds require
manual master dispatch and matching source/product/version. PR/push cannot run it.

Local reproduction (outputs must be outside the repository):

```sh
python .github/workflows/ci.py plan --changed --base HEAD \
  --product d4planner-snapshots --operation build --output /tmp/snapshot-plan
CI_TRUSTED_EXECUTION=1 python .github/workflows/ci.py run \
  --plan /tmp/snapshot-plan/plan.json --version 1.0.0 \
  --output /tmp/snapshot-run
```

Load `AGE_IDENTITY_SECRET` from the existing private key using a local launcher;
do not put the value on the command line or in tracked files. Local-only
`SNAPSHOT_RELEASE_CONFIG` can point to an authorized private config. This override
is rejected on Actions; CI reads the committed `release/config.json`.

The checked-in config deliberately has no fabricated authorization or bindings.
Set `sourceUrl` and `authorizationRef` to the approved anonymous capture source.
`registry` and `profile` are `{url, sha256}` descriptors for existing approved
inputs, not a request to generate new ones. Set `entryId` and `realProfileId` to
existing Rule Kit bindings. `distribution` is `{permission: "PUBLIC_APPROVED",
version, reference}` for the exact publish version and both snapshot types.
Never commit private data or credentials. Missing inputs remain BLOCKED.

A clean committed checkout is required by the existing real UI acceptance. Capture
stores and temporary config are generated on the executing machine, outside its
checkout; no F path is a CI prerequisite. Tool bootstrap reuses the age v1.3.2
archive/hash and pinned Playwright infrastructure already used by this repository.

## Verification and publish

Build captures both packages, rejects drift, verifies the existing production
Registry/profile binding, runs real-provider/eight-API acceptance, then creates
separate deterministic ZIPs. Ciphertext is intentionally randomized by age.
After decryption it checks every entry/hash, imports Calculation into an owned
scratch consumer and repeats offline Calculation/UI acceptance. It never activates
an end-user snapshot. Raw data and tool output stay private; only the four approved
candidate files and sanitized blocked/publish receipts are exported.

Publish additionally requires explicit manual master intent, the existing signed
Calculation distribution permission and the exact-version pair distribution
reference. Existing tags/releases are rejected. Assets are uploaded to a draft,
downloaded and compared before publication. Failure leaves a draft for inspection;
there is no overwrite, automatic repair, cleanup of releases or retry bypass.

No GitHub Actions dispatch, merge, release or Windows A deployment is authorized by
these local commands. SR-01..07 require an actual successful product build; unit
fixtures alone are not acceptance. SR-08 requires separately approved publication.
