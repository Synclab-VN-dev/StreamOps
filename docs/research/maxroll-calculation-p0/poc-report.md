# Maxroll JSON-to-Calculated-Stats Provider PoC

## Verdict

The bounded provider PoC is operational.

- **G1 — Maxroll browser runtime: PASS.**
- **G2 — JSON to calculated Character Stats: PASS_BOUNDED_POC.**
- **G3 — 50-ID coverage: PARTIAL_DISPLAY_34_OF_50.** Runtime raw coverage is
  50/50; this minimal blank fixture renders 34/50 values in the Character Stats
  UI.

This supersedes the earlier infrastructure-only blocker in this research
branch. The Owner subsequently attested in the task conversation that Maxroll
agreed to the scoped browser/CDP PoC. No general production-integration license
is inferred from that statement.

## Environment and runtime

| Component | Observed |
|---|---|
| Host | Linux F |
| Browser | Google Chrome for Testing 153.0.8010.12 |
| Playwright | `playwright-core` 1.64.1 |
| Python / Node | 3.12.3 / 22.22.1 |
| Maxroll patch | `3.2.1.73552` |
| Runtime asset identity | `/assets/export-DOjdL1l3.js` |
| Source fixture | `https://maxroll.gg/d4/planner/1g1any0x#3` |
| Calculation fixture | Unsaved, disposable `NEW_PROFILE_LOCAL` |

G1 opened the planner and reused the Issue #106 `heroDetails` breakpoint. It
captured 50/50 raw values and 50/50 displayed values on the published reference
fixture. The published fixture was not changed.

## Input contract

The PoC schema mirrors the native Maxroll separation between a profile and an
item pool, while retaining explicit UI identities needed to apply the state:

- Build A: Rogue level 50, Torment I, one Runic Skullcap, no modifier.
- Build B: exact copy of A plus one modifier, `Dampening / Of Dampening`, whose
  applied UI effect is `+2800 Fire Resistance`.
- Skills, Paragon, and conditional context are explicitly empty.

This is a versioned bounded contract, not a byte-for-byte saved-profile schema.
Unsupported fields fail validation rather than receiving inferred defaults.

| Input | Canonical input SHA-256 |
|---|---|
| A | `32fdcb90bbc054981d9cfc54fa369cdbc2452aef84e22037703f2fc77e742536` |
| B | `fa398c8b089eb7b6adcc336b6a77f35db9df76a5bfeeae54a55a90545ae5189c` |

## Adapter behavior

`maxroll_poc.py` validates the JSON input and invokes the browser adapter. Each
invocation:

1. creates a fresh isolated Chromium context;
2. verifies the observed Maxroll patch;
3. opens an unsaved New Profile;
4. applies level, item, and modifier through supported UI controls;
5. verifies the resulting UI state;
6. captures the 50 Issue #106 IDs from the active `heroDetails` runtime and all
   values rendered in the DOM;
7. exports a traceable JSON result and closes the context.

The adapter contains no Diablo IV formulas. Non-GET/HEAD/OPTIONS network
requests are blocked, Save/Publish is never invoked, and cookies, tokens, and
browser storage are not read.

## A/B/A results

Three complete A -> B -> A cycles were executed across nine disposable browser
contexts: six A calculations and three B calculations.

- Normalized unique A results: **1**.
- Normalized unique B results: **1**.
- Stale state: **not observed**.
- Every run: 50/50 raw, 34/50 display, 50 stable IDs, patch 3.2.1.73552.

Only three metric rows changed; 47 remained identical:

| Metric ID | A raw/display | B raw/display | Raw delta |
|---|---:|---:|---:|
| `maxroll.heroDetails.446` Fire Resistance | `22` / `22` | `2822` / `2,822` | `+2800` |
| `maxroll.heroDetails.901` Toughness | `693.0584806531045` / `693` | `967.0261283628205` / `967` | `+273.96764770971595` |
| `maxroll.heroDetails.2036494626` Toughness | `693.0584806531045` / `693` | `967.0261283628205` / `967` | `+273.96764770971595` |

These are Maxroll-observed deltas, not inferred formulas.

## Test results

| Test | Status | Actual |
|---|---|---|
| G1 runtime | PASS | Planner, patch, runtime breakpoint, 50 raw, and 50 display values observed |
| Baseline A | PASS | JSON applied; 50 raw and 34 display values exported |
| Modifier B | PASS | UI effect `+2800 Fire Resistance`; recalculated output differs from A |
| Three A/B/A cycles | PASS | All normalized A results identical; all normalized B results identical |
| Invalid input | PASS | Exit 2, explicit validation error, no output created |
| 50-ID catalog | PASS | 50/50 IDs emitted in every result |
| Raw coverage | PASS | 50/50 values captured in every result |
| Display coverage | PARTIAL | 34/50 rendered; 16 raw-only rows remain explicit |

Machine-readable details are in `poc/poc-results.json`. Representative outputs
are `poc/stats-a.json` and `poc/stats-b.json`; all repeat runs and screenshots
are under `evidence/poc-runs/`.

## Limitations and next scope

| WHAT | WHO | WHY | HOW |
|---|---|---|---|
| Expand the input mapping | Dev F after scope approval | Current PoC accepts only one bounded item/modifier flow | Add resolvers for additional slot/item/modifier identities and verify each with A/B/A |
| Close display coverage | Dev F | Sixteen zero/conditional rows are raw-only in the blank fixture | Use a fixture that legitimately renders those rows; do not synthesize display strings |
| Stabilize runtime instrumentation | Dev F with Maxroll integration guidance | The current breakpoint is asset-version-specific | Prefer a documented calculation interface or supported stable runtime hook if Maxroll provides one |
| Productionize provider contract | StreamOps/Owner after review | This research adapter is not production code | Review permission, versioning, rate limits, error contract, and complete native-state mapping separately |

No production code, CI workflow, formula implementation, third-party engine,
PR, merge, or deployment was created.
