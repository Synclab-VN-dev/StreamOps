# Snapshot release (#180)

Owner clarification, 2026-11-05: snapshot release and Rule Kit adoption are
separate operations. Each release captures a fresh Calculation/UI pair. The release
checks capture completeness, immutable resource integrity, matching runtime hashes
and UI acceptance. A difference from an older Rule Kit reference is recorded as
`calculationReferenceStatus`, never used as a release compatibility gate.
`ruleKitReadiness` remains `NOT_ASSESSED`, including for matching reference pins.

Assessment: AGREE / FIX_REQUIRED. Existing capture and UI tooling are reused.
The release does not load a production Registry, require a profile/entry approval,
run the reference-specific eight-API suite or import into an active Rule Kit store.
Those are adoption checks. Release tooling stays outside the execution-index inputs;
existing trust/compatibility logic and execution identity remain unchanged.

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

Set `sourceUrl` and `authorizationRef` to the approved anonymous capture source.
The checked-in config does not invent that authorization. No Registry/profile or
preapproved snapshot ID is needed for release. `distribution` is
`{permission: "PUBLIC_APPROVED", version, reference}` for the exact publish version
and both snapshot types. Never commit private data or credentials.

A clean committed checkout is required by the existing real UI acceptance. Capture
stores and temporary config are generated on the executing machine, outside its
checkout; no F path is a CI prerequisite. Tool bootstrap reuses the age v1.3.2
archive/hash and pinned Playwright infrastructure already used by this repository.

## Verification and publish

Build captures both packages, checks integrity and pair matching, and creates two
ZIPs. Each ZIP has its native snapshot ID as the single root directory, containing
manifest/anchor/blobs; the UI root also contains coverage and validation receipts.
Calculation ZIPs do not claim to be approved Rule Kit import packages and do not
contain a fabricated profile or Registry entry. ZIP bytes are deterministic;
ciphertext is intentionally randomized by age.

After decryption the pipeline checks every entry/hash, re-verifies both native
snapshot stores and repeats offline UI/Native JSON acceptance. Raw data and tool
output stay private; only ciphertext, pair metadata, checksums and sanitized
receipts are exported. Failed integrity, mismatched pair provenance/runtime or UI
validation failures still block release.

Publish requires explicit manual master intent and exact-version distribution
approval for the pair, independently of Rule Kit compatibility approval. Existing
tags/releases are rejected. Assets are uploaded to a draft, downloaded and compared
before publication. Failure leaves a draft for inspection; there is no overwrite,
automatic cleanup of releases or retry bypass.

No GitHub Actions dispatch, merge, release or Windows A deployment is authorized by
these local commands. SR-01..07 require an actual successful product build; unit
fixtures alone are not acceptance. SR-08 requires separately approved publication.
