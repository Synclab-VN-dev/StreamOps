# Maxroll JSON-to-Calculated-Stats PoC

## Verdict

**BLOCKED** — the contract
`build.json → Maxroll Calculation → stats.json` could not be executed with the
currently available and permitted interfaces.

- Character Stats coverage produced by this PoC: **0/50**.
- Build input groups supported by an executable adapter: **none**.
- A/B delta verification: **not run**.
- A repeatability verification: **not run**.
- Maxroll UI comparison: **not run**.

This does not mean Maxroll cannot calculate the requested stats. Historical
evidence proves that Maxroll displays and internally evaluates Character Stats
for specific loaded fixtures. It does not establish a supported or currently
authorized provider interface that accepts an arbitrary JSON state.

## S1 — Reused evidence

Baseline checked on 2026-10-21, Asia/Ho_Chi_Minh:

- Branch: `research/maxroll-calculation-p0`.
- Starting HEAD for this PoC: `4c60b36170d04e0a7818e713ca2dfc00e50cecbb`.
- Remote research HEAD matched local and the working tree was clean.
- The original P0 evidence remains unchanged.
- P0-NET remains **PASS**.
- The observed Profile API remains a profile-state loader, not a verified
  Calculation API.

Issue [#106](https://github.com/Synclab-VN-dev/StreamOps/issues/106) and the
Phase 1 through F7.2 history were inspected rather than rerunning discovery:

1. Phase 1/2 reported that `maxroll-devtools` previously reached Edge on
   Windows A through a localhost SSH reverse tunnel and observed the loaded
   planner runtime.
2. Later Linux F work proved that temporary Playwright/CDP sessions could
   launch isolated Chrome for Testing and observe specific Maxroll runtime
   values under phase-scoped owner approvals.
3. F3 cataloged 50/50 metric IDs with 50 raw and 50 display candidates for one
   pinned Rogue fixture, but explicitly recorded partial input completeness and
   candidate-only, unapproved Golden status.
4. F4–F7.2 added bounded observations and controlled vectors for selected
   paths. They did not produce an arbitrary JSON calculation adapter.
5. The #106 closeout retained **0/50 real independent Graph parity PASS** and
   did not authorize later browser work outside each completed phase.

Relevant evidence anchors:

- [Phase 1 and Windows tunnel](https://github.com/Synclab-VN-dev/StreamOps/issues/106#issuecomment-6173451731)
- [Linux Playwright/CDP feasibility](https://github.com/Synclab-VN-dev/StreamOps/issues/106#issuecomment-6183958789)
- [Controlled runtime vectors](https://github.com/Synclab-VN-dev/StreamOps/issues/106#issuecomment-6186278085)
- [F3 50-ID/raw/display candidate capture](https://github.com/Synclab-VN-dev/StreamOps/issues/106#issuecomment-6205171703)
- [F7.2 bounded result](https://github.com/Synclab-VN-dev/StreamOps/issues/106#issuecomment-6212565234)
- [#106 closeout](https://github.com/Synclab-VN-dev/StreamOps/issues/106#issuecomment-6217965965)

## Current infrastructure check

The historical harness is not callable from this session:

- Cached Chrome for Testing exists at version `153.0.8010.12`.
- A temporary historical workspace contains `playwright-core 1.64.1`.
- There is no running `ssh` process and no active reverse tunnel identified.
- The active Codex process was started with
  `mcp_servers.maxroll-devtools.enabled=false`.
- No Maxroll, DevTools, browser, Chrome, or Playwright control tool is present
  in the active callable-tool registry.
- No authorized CDP endpoint connected to a disposable Maxroll fixture was
  identified.

Browser binaries and libraries alone are not a provider interface and do not
grant permission to automate Maxroll. The current policy evidence in
`evidence/client-calculation/policy-check.txt` still blocks substituting a new
automated planner session without the required authorization.

Sanitized capability evidence is recorded in
`evidence/poc-infrastructure-check.txt`.

## S2 — Candidate input contract

The earlier Profile API response establishes a native outer object whose
`data` field is a JSON-encoded string. The parsed state contains these observed
top-level fields:

| Field | Observed type | Candidate role |
|---|---|---|
| `profiles` | array | Per-variant character state |
| `items` | object | Shared item pool |
| `activeProfile` | number | Selected build variant |
| `options` | object | Calculation/condition options observed for the fixture |
| `pinnedStats` | object | UI stat selection, not proven calculation input |
| `season` | number | Season identifier |
| `embeds`, `activeEmbed` | array, number | Embedded view state |
| `globalNotes`, `lootFilters` | object, array | Non-calculation/profile metadata unless proven otherwise |

An observed profile entry can include `class`, `level`, `worldTier`, equipped
item references, skill tree, skill bar, Paragon, rotations, War Plans, world
state, elixirs, arsenal/technique, mercenary, and notes. Item-pool entries can
include item ID/power, implicit and explicit affixes, tempers, aspects, sockets,
upgrade state, and mythic state.

For a reproducible provider contract, the following envelope would be required:

```text
contractVersion
provider = "maxroll"
version:
  gamePatch, gameBuild, season
  maxrollAppVersion OR immutable runtime-resource fingerprint
profileState:
  exact native parsed `data` object
calculationContext:
  selected profile/variant, target/difficulty/world state
  conditional effects, active buffs, proc/stack/uptime state
provenance:
  source, capture timestamp, input SHA-256
```

This is a **candidate contract description**, not an implemented or validated
`build.json` schema. The mandatory fields cannot yet be closed because the
historical fixture had partial socket/Paragon/conditional-state reconstruction,
and no supported Maxroll interface has confirmed which transient runtime fields
must accompany the saved profile state.

Build B should be an exact deep copy of build A with one supported modifier
changed and a distinct input hash. That mutation path was not executed, so no
`build-a.json` or `build-b.json` was created.

## S3 — Adapter gate

The allowed adapter choices were evaluated:

| Choice | Result | Reason |
|---|---|---|
| Supported Calculation API | BLOCKED | No supported Calculation API contract was found; the Profile API does not return calculated stats |
| Authorized Maxroll client runtime | BLOCKED | Historical phase-scoped access existed, but no currently callable/authorized runtime is available in this session |
| Permitted browser adapter | BLOCKED | The only available browser execution path would be new automation against a restricted planner path |

Because all three provider choices are blocked, no adapter was implemented.
Creating a CLI that only replays saved outputs, hardcodes formulas, or returns
cached fixture values would not satisfy the objective and was rejected.

## S4 — Candidate output contract

A successful `stats.json` would need:

```text
contractVersion
provider
gamePatch, gameBuild, maxrollAppVersion/runtimeFingerprint
inputSha256, calculatedAt
coverage: {produced, denominator: 50, unsupported, unknown}
metrics[]:
  id, group, label, rawValue, displayValue, unit
  status, provenance
```

The pinned Rogue denominator is 50 metric IDs across Summary (2), Core (5),
Resistances (8), Offensive (20), Defensive (7), Utility (7), and PvP (1).
Those IDs are an historical inventory, not PoC output. This PoC produced no
metric values, did not substitute zeros, and marks all 50 unsupported by the
unavailable adapter.

Therefore `stats-a.json` and `stats-b.json` do not exist.

## S5 — POC-01 through POC-06

| ID | Test | Status | Actual |
|---|---|---|---|
| POC-01 | Load build A from editable JSON into Maxroll calculation provider | BLOCKED | No supported/authorized provider interface is callable |
| POC-02 | Calculate and export 50 Character Stats for A | BLOCKED | Calculation did not run; coverage 0/50 |
| POC-03 | Create B by changing exactly one modifier and apply it | BLOCKED | No validated input-application contract; no build B file created |
| POC-04 | Calculate B and prove a real A/B delta | BLOCKED | No A or B calculation output exists |
| POC-05 | Compare A/B outputs with Maxroll UI | BLOCKED | No authorized live fixture/session is connected |
| POC-06 | Recalculate A and verify repeatability | BLOCKED | Initial A calculation never ran |

Test results are machine-readable in `poc/poc-results.json`.

## Why this is not PARTIAL or FAIL

- Not `PASS`: arbitrary JSON was not calculated and no A/B/repeatability proof
  exists.
- Not `PARTIAL`: no current input was accepted by a provider and no stat was
  generated by this PoC. Historical fixture captures are not this PoC's output.
- Not `FAIL`: an adapter did not run and produce incorrect/inconsistent output.
- Correct verdict: **BLOCKED** by provider access/interface/authorization.

## Artifacts intentionally absent

The following requested files were not created because the corresponding
calculation did not run:

- `poc/build-a.json`
- `poc/build-b.json`
- `poc/stats-a.json`
- `poc/stats-b.json`
- `poc/maxroll_poc.py`

## Next actions

| WHAT | WHO | WHY | HOW |
|---|---|---|---|
| Provide a supported Maxroll calculation contract | Maxroll/provider contact with owner | The Profile API alone cannot execute calculations | Supply documented endpoint/SDK, auth scope, accepted complete state schema, 50-stat response schema, versioning and usage permission |
| Or provision an explicitly authorized disposable runtime | Owner plus Maxroll authorization, operated by Dev F | Historical phase approvals and cached binaries are not current provider access | Enable a dedicated `maxroll-devtools`/CDP session with a disposable unsaved fixture and written scope for JSON state application, 50-stat readout, A/B/UI comparison and repeatability |
| Close the native input schema | Dev F after provider access | Saved profile state may omit transient calculation context | Round-trip one complete native profile, enumerate missing runtime-only fields, and hash the exact applied state before calculation |
| Run POC-01–06 | Dev F | Establish provider feasibility without self-authored formulas | Calculate A, mutate one supported modifier to B, calculate B, compare UI delta, then rerun A and compare normalized raw/display results |
