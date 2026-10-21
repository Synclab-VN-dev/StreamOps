# Reproduce the Maxroll JSON-to-Calculated-Stats PoC

Run from the StreamOps repository root on Linux F. The commands assume the
scoped Maxroll automation permission recorded in `poc/poc-results.json` still
applies.

## Prerequisites

- Python 3.12 or compatible Python 3.
- Node.js 22 or compatible Node.js.
- Chrome for Testing at
  `/home/huy/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome`.
- `playwright-core` 1.64.1 available through
  `/tmp/issue106-f4.Z3XkXq/node_modules` or `NODE_PATH`.
- Network access to the approved Maxroll planner URL.

No Maxroll account, cookies, token, SSH tunnel, Windows A, or system package
installation is used.

## Validate syntax

```bash
python3 -m py_compile \
  docs/research/maxroll-calculation-p0/poc/maxroll_poc.py
node --check \
  docs/research/maxroll-calculation-p0/poc/maxroll_adapter.js
jq -e . \
  docs/research/maxroll-calculation-p0/poc/build.schema.json \
  docs/research/maxroll-calculation-p0/poc/build-a.json \
  docs/research/maxroll-calculation-p0/poc/build-b.json
```

## Calculate A and B

```bash
python3 docs/research/maxroll-calculation-p0/poc/maxroll_poc.py \
  --input docs/research/maxroll-calculation-p0/poc/build-a.json \
  --output docs/research/maxroll-calculation-p0/poc/stats-a.json

python3 docs/research/maxroll-calculation-p0/poc/maxroll_poc.py \
  --input docs/research/maxroll-calculation-p0/poc/build-b.json \
  --output docs/research/maxroll-calculation-p0/poc/stats-b.json
```

Each invocation must report 50 metric IDs, 50 raw values, 34 display values,
the observed patch `3.2.1.73552`, and cleanup `PASS`. A successful command
replaces only its requested output after the browser adapter returns valid JSON.

## Inspect the bounded delta

```bash
jq -s '
  (.[0].metrics | map({key:.metricId,value:.}) | from_entries) as $a |
  (.[1].metrics | map({key:.metricId,value:.}) | from_entries) as $b |
  [$a | keys[] as $id |
    select($a[$id].rawValue != $b[$id].rawValue or
           $a[$id].displayValue != $b[$id].displayValue) |
    {metricId:$id,
     rawA:$a[$id].rawValue,rawB:$b[$id].rawValue,
     displayA:$a[$id].displayValue,displayB:$b[$id].displayValue}]
' \
  docs/research/maxroll-calculation-p0/poc/stats-a.json \
  docs/research/maxroll-calculation-p0/poc/stats-b.json
```

The observed changed IDs are Fire Resistance and the two cataloged Toughness
rows. This command compares provider output; it does not calculate any Diablo IV
formula.

## Invalid input

```bash
python3 docs/research/maxroll-calculation-p0/poc/maxroll_poc.py \
  --input invalid-build.json --output invalid-stats.json
```

An invalid contract exits 2 with a `validation error` and does not report a
successful output.

## Safety boundary

The adapter always creates a local unsaved New Profile, blocks non-read network
methods, and closes the browser context. Do not add Save/Publish, account
profiles, cookie/token reads, private-state writes, or unsupported runtime
mutation to the reproduction flow.
