# Reproduce Maxroll offline/local calculation PoC

Run from the StreamOps repository root on Linux F. These commands use Chrome
for Testing at `/home/huy/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome`
and Playwright Core 1.64.1 from the prior authorized research environment.

## L1 warm offline

```bash
NODE_PATH=/tmp/issue106-f4.Z3XkXq/node_modules \
node docs/research/maxroll-calculation-p0/poc/warm_offline_poc.js \
  --output docs/research/maxroll-calculation-p0/evidence/offline-poc/warm-offline-run.json \
  --evidence-dir docs/research/maxroll-calculation-p0/evidence/offline-poc
```

Expected: `L1_WARM_OFFLINE_PASS`, 50/50 raw values, three exact B→A
rollbacks, and zero remote responses during calculation phases.

## L2 disk-cache-only diagnostic

```bash
NODE_PATH=/tmp/issue106-f4.Z3XkXq/node_modules \
node docs/research/maxroll-calculation-p0/poc/cold_offline_cache_poc.js \
  --output docs/research/maxroll-calculation-p0/evidence/offline-poc/cold-offline-cache-run.json \
  --evidence-dir docs/research/maxroll-calculation-p0/evidence/offline-poc
```

Expected for the tested browser: `L2_COLD_OFFLINE_BLOCKED_BOOTSTRAP_FETCH`.
The fresh offline process fails at the planner document and must not claim a
calculation result.

## L2 ephemeral local archive

This test temporarily holds first-party response bodies in process memory. It
does not write or commit the archive. It closes the online browser, launches a
fresh offline browser, locally fulfills every archived request, and aborts all
misses.

```bash
NODE_PATH=/tmp/issue106-f4.Z3XkXq/node_modules \
node docs/research/maxroll-calculation-p0/poc/ephemeral_local_runtime_poc.js \
  --output docs/research/maxroll-calculation-p0/evidence/offline-poc/ephemeral-local-runtime-run.json \
  --evidence-dir docs/research/maxroll-calculation-p0/evidence/offline-poc
```

Expected: `L2_COLD_OFFLINE_PASS_EPHEMERAL_ARCHIVE`, 50/50 raw values on all
seven snapshots, one A hash, one B hash, exact online parity, failed
unarchived network probe and zero outbound responses.

## Inspect sanitized evidence

```bash
jq '{status,acceptance,performance,evidence}' \
  docs/research/maxroll-calculation-p0/evidence/offline-poc/warm-offline-run.json

jq '{status,acceptance,coldOffline: {
  failures: .coldOffline.failureEndpointCounts,
  navigatorOnline: .coldOffline.navigatorOnline
}}' docs/research/maxroll-calculation-p0/evidence/offline-poc/cold-offline-cache-run.json

jq '{status,archive: {
  entries: .archive.entries,
  bytes: .archive.bytes,
  retained: .archive.retained
}, local: {
  acceptance: .local.acceptance,
  snapshots: [.local.snapshots[] | {id,coverage,outputSha256}],
  explicitOfflineProbe: .local.explicitOfflineProbe
}}' docs/research/maxroll-calculation-p0/evidence/offline-poc/ephemeral-local-runtime-run.json
```

## L3 standalone local Python CLI

Provision the runtime package separately into a temporary directory. This step
is online; subsequent CLI processes are offline and have no network fallback.

```bash
runtime_dir=$(mktemp -d /tmp/maxroll-local-runtime.XXXXXX)

NODE_PATH=/tmp/issue106-f4.Z3XkXq/node_modules \
node docs/research/maxroll-calculation-p0/poc/ephemeral_local_runtime_poc.js \
  --output docs/research/maxroll-calculation-p0/evidence/offline-poc/ephemeral-local-runtime-run.json \
  --evidence-dir docs/research/maxroll-calculation-p0/evidence/offline-poc \
  --runtime-dir "$runtime_dir"

python3 docs/research/maxroll-calculation-p0/poc/local_maxroll_poc.py \
  --runtime-dir "$runtime_dir" \
  --input docs/research/maxroll-calculation-p0/poc/build-a.json \
  --output /tmp/stats-a-local.json

python3 docs/research/maxroll-calculation-p0/poc/local_maxroll_poc.py \
  --runtime-dir "$runtime_dir" \
  --input docs/research/maxroll-calculation-p0/poc/build-b.json \
  --output /tmp/stats-b-local.json
```

Expected for each local calculation: 50/50 raw, 34/50 display, calculation
mode `LOCAL_RUNTIME_PACKAGE_OFFLINE`, fail-closed archive resolution and
`explicitUnarchivedFetch=FAILED_AS_EXPECTED`. Delete the temporary runtime
directory after the test; do not add it to Git.

## Scope boundary

The Python CLI demonstrates a bounded local browser provider, not a production
or redistributable Maxroll runtime package. The package is a temporary 59 MB
working superset created by a separate authorized provisioning phase. Do not
persist it in this repository or silently allow an archive miss to access the
network.
