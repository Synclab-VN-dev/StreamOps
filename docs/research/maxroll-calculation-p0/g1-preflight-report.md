# Maxroll JSON-to-Calculated-Stats PoC — G1 preflight

Captured on 2026-10-21 at 13:28:31+07:00 on Linux F. This is the required
progressive G1 report. No Maxroll planner automation, JSON input application,
modifier mutation, or Character Stats capture was performed after this gate.

## Result

**G1: BLOCKED_AUTHORIZATION.** The local browser stack is operational, but
current published policy does not authorize the automated planner access needed
to finish G1 or start the JSON provider experiment.

| Capability | Status | Evidence |
|---|---|---|
| `BROWSER_AVAILABLE` | PASS | Google Chrome for Testing 153.0.8010.12 launched headless in a fresh Playwright context. |
| `PLAYWRIGHT_AVAILABLE` | PASS | Retained `playwright-core` 1.64.1 loaded successfully. |
| `CDP_AVAILABLE` | PASS | `Runtime.enable` and `Runtime.evaluate` succeeded on `about:blank`; the returned object contained `ready=complete`, `href=about:blank`, and `sum=42`. |
| `MAXROLL_PAGE_ACCESS` | BLOCKED_AUTHORIZATION_NOT_TESTED | The planner URL was not automated during this run. |
| `STATS_READABLE` | NOT_RUN | Reading Character Stats requires opening the planner, which did not pass the authorization gate. |
| `AUTHORIZATION_STATUS` | BLOCKED_NEEDS_WRITTEN_PROVIDER_PERMISSION | Owner task scope permits repository work, but is not written permission from Ziff Davis/Maxroll. |
| `OVERALL_PREFLIGHT` | BLOCKED | Technical runtime ready; provider authorization missing. |

Machine-readable evidence is in [`poc/g1-preflight.json`](poc/g1-preflight.json).

## S0 — restored context

The historical evidence was reused instead of rerunning formula research:

- Issue #106 proved Linux F could launch isolated Chromium, attach CDP, read
  planner DOM/runtime, and capture Character Stats under phase-specific Owner
  approvals.
- Later phases captured a 50-ID Rogue Character Stats catalog and controlled
  disposable-fixture vectors. Those records establish technical feasibility,
  not a current license or supported provider contract.
- The retained Linux F environment contains Chrome for Testing
  153.0.8010.12, Playwright Core 1.64.1, and the previous browser harnesses in
  `/tmp/issue106-f4.Z3XkXq`.
- The unauthenticated Profile Load route remains an observed profile-state
  loader. No supported Maxroll Calculation API has been identified.
- The Windows A `maxroll-devtools`/SSH path is unnecessary for the local CDP
  capability check and was not accessed.

The previous report at `poc-report.md` incorrectly described the retained
browser runtime as unavailable to this shell. The new local probe supersedes
that infrastructure detail only. It does not change the earlier provider and
authorization blockers.

## Current policy gate

At capture time, `https://maxroll.gg/robots.txt` stated that automated
retrieval requires written permission from Ziff Davis and explicitly disallowed
generic user agents from `/d4/planner/*`. Its observed SHA-256 was
`f674cd9e454a65fd8ba752c6ccb013aa0fe16878457876ea06302044add5d909`.

The linked Ziff Davis Terms of Use identified themselves as effective September
2026. Section 2 restricts automated extraction and prohibits reverse
engineering of web-based software unless specifically authorized. The requested
`build.json -> Maxroll Calculation Engine -> stats.json` adapter would require
automated planner interaction and potentially runtime-interface inspection, so
the current StreamOps task instruction alone is not sufficient evidence of
provider permission.

No authentication, anti-bot mechanism, cookie, token, browser storage, or
private application interface was accessed or bypassed.

## Progressive gate disposition

| Gate/test | Status | Reason |
|---|---|---|
| G1 runtime ready | BLOCKED_AUTHORIZATION | Browser/Playwright/CDP PASS; Maxroll page and Stats checks not run. |
| G2 JSON-driven calculation | NOT_RUN | G1 authorization prerequisite is unresolved. |
| G3 50-metric coverage | NOT_RUN | No current calculation output exists. |
| Test A baseline | NOT_RUN | No provider invocation. |
| Test B modifier mutation | NOT_RUN | No mutation authorized or attempted. |
| Test C repeatability | NOT_RUN | No baseline calculation. |
| Test D invalid input | NOT_RUN | No adapter/schema implemented before the provider gate. |
| Test E metric coverage | NOT_RUN | Current calculated coverage is 0/50. |

No `build-a.json`, `build-b.json`, `stats-a.json`, `stats-b.json`, schema, or
adapter was created because doing so would not prove an executable provider
contract while the provider access gate is blocked.

## Required next step

| WHAT | WHO | WHY | HOW |
|---|---|---|---|
| Obtain written permission for the narrowly scoped PoC | Owner/legal liaison and Ziff Davis/Maxroll | Current published policy blocks automated planner retrieval and runtime-interface inspection | Confirm allowance for an isolated unsaved profile, UI-supported A -> B -> A application, CDP readout of the 50 IDs, sanitized evidence retention, run limits, and whether client runtime inspection is allowed. |
| Resume G1 page/Stats check | Dev F after permission is recorded | Separates technical reachability from authorization | Open the exact planner in a disposable context, read DOM/runtime only, record version and 50-ID visibility, then close the context. |
| Run G2 minimal JSON adapter | Dev F after G1 PASS | Proves that output depends on the invocation's JSON | Define the minimal native-state schema, apply A and one supported B modifier through the permitted interface, capture A -> B -> A, and verify rollback hashes. |

