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
