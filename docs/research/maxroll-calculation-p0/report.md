# Maxroll Calculation Engine P0 Discovery

## Outcome

P0-NET is **PASS**. P0-CALC is **BLOCKED**. The overall discovery classification
is **BLOCKED**, not `API_AVAILABLE` or `UI_ONLY`.

The public profile-load route returned valid build JSON, but it is only a
Profile API. This run did not verify any Calculation API or automated Character
Stats result.

## Environment

- OS: Ubuntu Linux, kernel `6.8.0-146-generic`, x86_64.
- Evidence window: 2026-10-21T12:14:55+07:00 to
  2026-10-21T12:16:26+07:00 (Asia/Ho_Chi_Minh).
- Tested Git HEAD / `origin/master` after fetch:
  `9e1eec2838f73557853e2d017735b9d52533355e`.
- Branch: `research/maxroll-calculation-p0`.
- curl: 8.5.0 with OpenSSL 3.0.13.
- OpenSSL: 3.0.13.
- Node.js: v22.22.1; npm: 11.12.1.
- Python: 3.12.3 (`python3`; no `python` alias).
- Playwright Python package and Chromium/Chrome executable: not installed.
  Installation was unnecessary and intentionally not attempted after the
  verified access policy blocker.

## Test summary

| Status | Count |
|---|---:|
| PASS | 6 |
| FAIL | 0 |
| BLOCKED | 1 |
| NOT_RUN | 3 |

| ID | Status | Actual result |
|---|---|---|
| NET-01 | PASS | `maxroll.gg` resolved to IPv4 and IPv6 addresses. |
| NET-02 | PASS | `planners.maxroll.gg` resolved to IPv4 and IPv6 addresses. |
| NET-03 | PASS | TLS certificate verified; root returned HTTP 200 HTML. |
| NET-04 | PASS | TLS certificate verified; root returned HTTP 200 JSON. |
| API-01 | PASS | Public build profile returned HTTP 200 JSON, 18,240 bytes. |
| API-02 | PASS | Outer JSON and nested build-data JSON parsed; schema recorded. |
| CALC-01 | BLOCKED | Planner traffic inspection stopped at published automation restriction. |
| CALC-02 | NOT_RUN | Flat-modifier A/B prerequisite was blocked. |
| CALC-03 | NOT_RUN | Percentage-modifier A/B prerequisite was blocked. |
| CALC-04 | NOT_RUN | Conditional-effect A/B prerequisite was blocked. |

Machine-readable details are in `results.json`.

## Findings

1. DNS, TLS, and HTTP connectivity from this Linux environment worked for both
   hosts. This establishes P0-NET connectivity only.
2. `GET /profiles/load/d4/{buildId}` returned HTTP 200 for a build ID taken from
   a documented public planner link. The body was valid JSON; its `data` field
   was itself a JSON-encoded string containing build profiles, items, skills,
   paragon state, options, and related inputs.
3. The observed profile payload had no exact-named `calculated`,
   `characterStats`, `results`, `damage`, `armor`, or `life` calculation output
   key at any inspected nesting level. Absence in one payload is not proof that
   no Calculation API exists.
4. No Calculation API method, URL, request schema, response schema, or auth
   requirement was discovered. Profile API != Calculation API.
5. Browser automation feasibility is **NOT VERIFIED**. No UI modifier change,
   Character Stats A/B result, or three-run consistency evidence exists.

## Blockers and root cause

**Verified:** `https://maxroll.gg/robots.txt` stated that automated retrieval
requires written permission and its generic-agent section explicitly disallowed
`/d4/planner/*` at the evidence timestamp. Per the discovery safety constraints,
the run did not bypass this restriction. This blocked Playwright network
inspection and CALC-01, which in turn prevented CALC-02 through CALC-04.

**Suspected but not verified:** calculation may be client-side, server-side, or
hybrid. The profile response alone cannot distinguish these architectures.

Lack of Python/Playwright/Chromium is not classified as the root blocker:
installing them would not resolve the verified permission restriction.

## Feasibility assessment

- Profile ingestion for public build configuration: technically demonstrated
  for one build, but production support, licensing, stability, rate limits, and
  terms remain unverified.
- Reusing Maxroll for calculated Diablo IV Character Stats: not demonstrated.
- Final classification: **BLOCKED**.
- P0-NET: **PASS**.
- P0-CALC: **BLOCKED**.
- API discovered: **Profile API only; Calculation API NOT VERIFIED**.
- Browser automation feasibility: **NOT VERIFIED / policy-blocked**.

## Next actions

| WHAT | WHO | WHY | HOW |
|---|---|---|---|
| Obtain written automation/API permission | Product owner / legal or partnership owner | The published policy blocks the required planner automation | Contact Ziff Davis/Maxroll at the licensing contact published in `robots.txt`; request explicit scope for planner load, mutation, network inspection, screenshots, retention, and production usage |
| Request supported calculation integration documentation | Product owner with Maxroll contact | A profile route does not establish a supported Calculation API | Ask for endpoint contract, authentication, quotas, versioning, Diablo patch cadence, SLA, and commercial terms |
| Resume CALC-01 after permission | Dev F | Determine server-side vs client-side calculation with admissible evidence | Re-check live policies, install pinned Playwright/Chromium, capture a sanitized network trace for one authorized public/test build |
| Run CALC-02..04 after CALC-01 | Dev F | Meet P0-CALC acceptance criteria | Record baseline/input/output/delta for flat, percentage, and conditional changes; repeat the same condition three times and compare normalized outputs |
| Decide build-vs-partner path | Epic #105 owner | Avoid depending on an unsupported interface | Compare the authorized Maxroll contract against maintaining an internal formula engine; keep #106/#107 unchanged until this decision |

No production code, existing CI workflow, Epic #105, ticket #106/#107, or
protected utility/runtime directory was modified.
