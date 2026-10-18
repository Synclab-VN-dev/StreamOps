# Issue #119: P0 real-A inventory/stash + mapped-key evidence probe

This is a **read-only feasibility gate**, NOT the finished \`d4planner items\` CLI.
Owner-approved CLI scope is #119; no REST/WS/UI. The final owned-item
repository/CLI remains unimplemented until real NVDA inventory/stash context has
been validated. Do not report observed tooltips as owned, picked up or complete.

## Supported baseline and safety

- Reuse the **already running** D4Planner supervisor. The probe never starts,
  stops, changes input blocking, kills or injects into Steam / Diablo IV / NVDA.
- The supervisor owns the **canonical** \`state/events.db\` writer. The probe
  opens a separate SQLite **mode=ro** + query-only connection.
- \`speech.raw\` and \`input.marker.raw\` carry the same session/eventSeq.
  Controller input means the **16 configured Xbox16 virtual-key bindings**
  (F1–F12 plus DPAD virtual keys); NOT all physical keyboard keys and NOT
  authenticated physical-controller origin. Keyboard \`DOWN/UP\` are logged by
  the existing D4Planner hook only while Diablo IV is in foreground.
- Requires running \`xbox-steaminput-18-v1\` profile with \`inputMarker.state=ACTIVE\`,
  \`configuredDigitalCount=16\`, effective speech capture and live supervisor;
  otherwise **BLOCKED**, no silent mode/profile switch.
- If you are using another input layout, run only the **Preflight** and
  review its report. Switching controller profile requires a separate
  **explicit operator decision** and usual D4Planner lifecycle process;
  don't stop a live session automatically.
- While capturing, do not type passwords, private chat or unrelated messages.
  Review raw speech before sharing evidence, since captured in-game speech
  can contain other game-visible text.

## Machine A / Windows PowerShell 7

Keep production checkout and active D4Planner process untouched; fetch branch
into a **separate worktree** (worktree must not already exist):

~~~powershell
cd C:\Workspace\StreamOps
git fetch origin feat/119-owned-items-cli
git worktree add C:\Workspace\StreamOps-I119 origin/feat/119-owned-items-cli
cd C:\Workspace\StreamOps-I119
~~~

The runner accepts the branch checkout OR detached HEAD pinned using
\`-ExpectedHead <40-character-commit-sha>\`. The usual
\`origin/feat/119-owned-items-cli\` checkout may produce a detached HEAD;
pass the SHA printed by \`git rev-parse HEAD\`, or create a local branch
with a distinct name only after checking the worktree's correct ref. The runner
will NOT mutate the repo or restart the game.

~~~powershell
# Safe read-only preflight; produces report.json and ZIP even on BLOCKED.
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\acceptance\issue119-probe.ps1 -Mode Preflight -ExpectedHead (git rev-parse HEAD)

# If preflight PASS, enter game and run the interactive 3-stage capture.
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\acceptance\issue119-probe.ps1 -Mode Capture -ExpectedHead (git rev-parse HEAD)
~~~

Stages, with operator pressing ENTER before and after each:
1. INVENTORY: navigate several inventory cells and one equipped/non-equipped
   item, allow NVDA to speak each item's tooltip.
2. STASH tab 1: browse items and empty cells. Note where navigation starts/ends.
3. STASH tab 2: browse items and empty cells. Observe whether NVDA speaks tab
   identifier / empty grid boundaries. Press mapped controller buttons during
   each stage to capture edges, if it is safe within the menu.

The script saves a unique \`%TEMP%\d4planner-issue119-yyyyMMdd-HHmmss.zip\`;
paste the path or upload the ZIP for analysis. If there is a failure, send the
ZIP with \`report.json\`; do not manually restart production components.

Each stage outputs:
- \`events.jsonl\`: exact ordered canonical speech + input events;
- \`speech.jsonl\`, \`input.jsonl\`: filtered views, no alteration of sources;
- \`item-anchors-unverified.json\`: name/type/power-only **OBSERVED** anchors,
  \`ownership=UNVERIFIED, location=UNKNOWN\`;
- \`summary.json\`: start/end seq, missing-seq count, observed key IDs and edge
  states, speech count, profile/queue checks and **coverage UNVERIFIED**.

\`PASS\` in \`configured_input_edges_observed\` proves **some** mapped input events
were observed, not that all 16 controls were pressed; \`PASS\` in
\`controller_16_key_profile\` proves only that the profile was configured/active.
The final API completeness gate will require Real-A proof of each context/tab,
snapshot boundaries, ownership, duplicate items, and movement.

## P0-06 blocked on 2026-10-17: status diagnostics revision

Owner-supplied ZIP from baseline HEAD b0c9075470815588ea9ffca0e649f4b2e8708871
contained **only report.json**, five PASS checks and P0-06 BLOCKED, without
\`d4planner status --json\` stdout/stderr/exit code. Therefore the actual
cause cannot be established from the first ZIP. It could be a missing CLI,
CLI startup error or a stale / stopped supervisor (which deliberately returns
a nonzero CLI exit code). Never assume a product failure from this evidence.

The revised runner writes:
- \`status-before.stdout.txt\`: exact JSON/raw stdout;
- \`status-before.stderr.txt\`: exact CLI stderr;
- \`status-before.invocation.json\`: command resolution, exit code and errors;
- \`status-before.json\`: parsed status, **even when exit code=2 and JSON is valid**.

\`P0-06 PASS\` now means CLI emitted a valid status JSON contract, **not**
that the runtime is healthy; \`P0-07 PASS\` requires \`RUNNING\`, alive
supervisor, effective capture lease and zero exit. Missing CLI/invalid JSON
remains P0-06 BLOCKED. P0-07 is BLOCKED for stale/absent runtime.

### How to repeat only the blocked Preflight (no gameplay changes)

~~~powershell
cd C:\Workspace\StreamOps-I119
git status --porcelain     # should be empty; if not, STOP and inspect changes
git fetch origin
git switch --detach origin/feat/119-owned-items-cli
git rev-parse HEAD
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\acceptance\issue119-probe.ps1 -Mode Preflight -ExpectedHead (git rev-parse HEAD)
~~~

Share the generated fresh ZIP; the script will not modify processes or game.
If P0-07 BLOCKED, the JSON now identifies whether state is STOPPED, STALE,
WAITING_FOR_GAME, etc. Do not auto-start/stop any service to pass a preflight.

**Revision evidence (CI):** Windows runner syntax + missing-runtime BLOCKED
smoke PASS; two additional Windows regression cases PASS:
(a) valid status JSON and exit=2 -> P0-06 PASS, P0-07 BLOCKED with stderr/ZIP;
(b) malformed JSON and exit=0 -> P0-06 BLOCKED with original stdout.
The actual Windows A path has **not yet been verified**. Existing Python
synthetic SQLite probe tests remain independent.

## Automated tests

~~~powershell
python -m unittest discover -s utility/d4planner/tests -p test_issue119_probe.py -v
python -m pytest -q utility/d4planner/tests/test_issue119_probe.py
~~~

Tested locally on synthetic SQLite with CPython 3.13: **5/5 unittest PASS**,
\`python -m py_compile scripts/acceptance/issue119_probe.py\` PASS.
**Windows PowerShell and actual D4/NVDA integration have not yet been executed**,
so Real-A and runner-validation gates remain PENDING/BLOCKED until evidence.

Source: #119; existing dependencies #59 / #69 / #87 / #95.


## Owner rollback 2026-10-17: keep the original start flow

The extra `--uat-start-nvda` flag and the `issue119-prepare.ps1` helper
were removed after the owner confirmed the already supported startup flow.
**No new D4Planner startup CLI contract is required for #119.**

Use the installed D4Planner CLI on Windows A in its existing (non-UAT)
production HomeDir:

~~~powershell
Remove-Item Env:\D4PLANNER_HOME -ErrorAction SilentlyContinue
d4planner start -d --controller-profile xbox16
d4planner status
d4planner logs -f --raw --from-end
~~~

The regular start command already starts missing NVDA and attaches to a
running Diablo IV process, subject to its existing add-on, Tolk, Steam PATH
and interactive-console safety gates. `--controller-profile xbox16` is the
existing controller configuration for 16 digital keys, OBSERVE (not BLOCK)
unless `--block` is explicitly supplied. The supervisor's default
`silent` option does **not** disable raw NVDA capture.

**Safety:** this normal start can reconcile existing NVDA add-on/helper tasks,
or report `RESTART_REQUIRED` when Steam PATH is stale; do not force any
process restart, stop, or merge as part of read-only #119 evidence.
If it is already running with a different mode/profile, do not stop it
just to switch modes: report the status for decision.

The separate #119 Preflight/Capture runner remains a **read-only** probe;
its explicit `-HomeDir` is authoritative for the status CLI environment as
well as its event SQLite database. The pinned Windows CI regression verified
that a stale caller `D4PLANNER_HOME` cannot silently redirect this probe.

### UAT revision improvement / rollback record

- **Before:** newly added `--uat-start-nvda` duplicated the already present
  NVDA bootstrap ability, adding unnecessary CLI/scheduled-task/supervisor
  changes and a multi-step UAT installer.
- **After:** reverted all new launch-mode code/tests and deleted Prepare,
  keeping the original `d4planner start -d --controller-profile xbox16`
  contract. Restored prior #119 probe and its original validations, except
  for the independent explicit-HomeDir environment correction.
- **Evidence:** Windows regression for explicit `-HomeDir` and earlier
  P0-06 valid-JSON/nonzero exit behavior passed before rollback. The final
  rollback HEAD must pass its own CI; real A startup remains **not yet
  verified**, and capture/inventory ownership evidence remains BLOCKED.
- **Operator scope:** only run the existing normal CLI and report status;
  no need to re-run previously PASS P0-01..P0-06 solely due to this rollback.


## PR #120 implementation slice — `d4planner items` + isolated UAT

The existing `d4planner start -d --controller-profile xbox16 --block`
entrypoint is unchanged. The new implementation reads canonical
`state/events.db` incrementally by global SQLite event row ID and
materializes observations in the **existing** `state/character.db`.
The checkpoint and observed-item history commit atomically per 500-event
batch. Future queries read only events after that checkpoint (initial
bootstrap requires reading historical events once). Canonical
`events.db` is opened in read-only/query-only mode.

Queries (after installation on the desired environment):

~~~powershell
d4planner items
d4planner items --json
d4planner items --location inventory,stash --include-unverified --json
d4planner items --rarity Unique --include-unverified --json
d4planner items status --json
d4planner items history --json
d4planner items export --format jsonl --output .\observed-items.jsonl
~~~

**Ownership semantics:**

- `items` defaults to **confirmed** HIGH-confidence equipped records from
  the existing equipment projector. It does NOT claim to list every physical
  item in the inventory or stash.
- `--include-unverified` shows fingerprint-grouped candidate tooltips in the
  **list** (one row for matching repeated reads, with `fingerprint` and
  `observationCount`). Each candidate stays `NOT_CONFIRMED`, `pickedUpAt=null`;
  its representative preserves the original observation ID
  `obs:<session>:<sourceSeqStart>` and raw source lines. `items history` and
  JSONL export retain **every** observation, including repeats.
- `STASH` and `CHARACTER` text provide only a best-effort contextual
  observation `location.type`. `CHEST n` is preserved in
  `locationHints.spokenChestTabs`, **NOT** automatically assigned to
  `location.tab`, since a single tab-list speech burst may mention all tabs
  without selecting any. Slots remain unknown.
- Matching observations (same normalized name/type/power/rarity/ancestral,
  location and compatible parsed stats/effects) collapse by SHA-256 fingerprint
  only in the list. Short/partial tooltip reads can match a more complete read.
  Conflicting observed stat values remain separate. Two truly identical physical
  items may collapse: this explicitly accepted V1 simplification does **not**
  prove the physical item count or selected inventory slot. Equipment comparison
  tooltips may still be misclassified as `inventory` until panel evidence exists.
- All unverified scan/tab coverage remains `PARTIAL`/`NOT_SCANNED`.
  `SCANNED`/`COMPLETE`, pickup, move, removal and character GUID require
  evidence which Real-A #119 has not yet provided.
- `history` is append-only observations (not an invented transition ledger).
  Export refuses to overwrite an existing path. No HTTP, WebSocket, FE, or
  gameplay automation was added.

### Owner UAT — snapshot only (one command)

Use the separate PR worktree (not the production repository) on A:

~~~powershell
cd C:\Workspace\StreamOps-I119
git status --porcelain     # must be empty; stop if files differ
git fetch origin
git switch --detach origin/feat/119-owned-items-cli

pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\acceptance\issue119-items-uat.ps1 -ExpectedHead (git rev-parse HEAD)
~~~

The PowerShell runner uses Python's **online SQLite backup API** to create
an isolated snapshot under `%TEMP%`; it does not modify the active
D4Planner databases or processes. It runs the PR's new CLI module from its
worktree using `PYTHONPATH`, validates default list, unverified opt-in,
coverage, filters, append-only observation history, JSONL export and
idempotency. It preserves command outputs and exit codes, and ZIPs evidence.
`PASS_SNAPSHOT_CLI_PARTIAL_OWNERSHIP` is a successful **CLI mechanics**
check, *not* Real-A proof of complete owned inventory.

**Validation and limits:** The fixture-driven pytest checks include
same-name rings, multi-tab labels, uncertainty, incremental resume,
case-insensitive rarity filter and export; Windows UAT syntax / fail-closed
smoke are CI-gated. The snapshot happy path on real A remains pending
the Owner's generated ZIP. The earlier Real-A 2026-10-17 ZIP has no missing
eventSeq and 131 **unverified anchors** across 3 stages, but it does not
prove exhaustive inventory/stash enumeration or all 16 physical buttons.
After Real-A UAT evidence arrives, update ticket #119 acceptance
individually. Never mark partial ownership as complete.
