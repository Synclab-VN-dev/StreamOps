# Reproduce L1 Maxroll warm-offline calculation

Run from the StreamOps repository root on Linux F. This procedure requires the
same scoped Maxroll permission used for the browser PoC.

## Prerequisites

- Chrome for Testing at
  `/home/huy/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome`.
- Playwright Core 1.64.1 under
  `/tmp/issue106-f4.Z3XkXq/node_modules`.
- The baseline A/B inputs and online outputs from commit `76c852d`.

## Run

```bash
NODE_PATH=/tmp/issue106-f4.Z3XkXq/node_modules \
node docs/research/maxroll-calculation-p0/poc/warm_offline_poc.js \
  --output docs/research/maxroll-calculation-p0/evidence/offline-poc/warm-offline-run.json \
  --evidence-dir docs/research/maxroll-calculation-p0/evidence/offline-poc
```

Expected terminal summary:

- `status = L1_WARM_OFFLINE_PASS`;
- three offline cycles;
- one unique A output and one unique B output;
- `navigator.onLine=false` for every offline snapshot;
- explicit offline fetch failed;
- zero remote responses during calculation phases;
- raw coverage 50/50;
- exact A rollback and A/B online parity;
- Fire Resistance delta `+2800`.

## Verify evidence

```bash
jq '{status,environment,acceptance,performance,evidence}' \
  docs/research/maxroll-calculation-p0/evidence/offline-poc/warm-offline-run.json

jq '.network | {
  offlineActivatedAt,
  explicitProbe,
  attemptedAfterOffline,
  failedAfterOffline,
  responsesAfterOffline
}' docs/research/maxroll-calculation-p0/evidence/offline-poc/warm-offline-run.json
```

The harness must not be changed to ignore a response associated with an active
calculation phase. A response that finishes outside a phase remains evidence
and requires explicit classification.

## Scope boundary

This reproduces warm offline only. It does not download or retain a Maxroll
bundle, does not prove cold offline startup, and does not prove Node/standalone
compatibility.
