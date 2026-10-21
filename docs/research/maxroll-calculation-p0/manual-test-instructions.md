# MAN-CALC-01 — Manual Maxroll calculation verification

## Preconditions

This is a human-operated test. Do not turn it into Playwright, scripted browser
control, scraping, source extraction, or reverse engineering.

Before starting:

1. The owner/legal reviewer confirms that this narrow manual DevTools test and
   retention of sanitized evidence are permitted. If written permission is
   required, obtain it first.
2. Use a build the operator is authorized to view and modify. Do not use another
   person's private profile.
3. Use a normal supported browser and a clean profile. Do not bypass CAPTCHA,
   login, rate limits, security controls, or anti-bot measures.
4. Do not export or commit a full HAR. Never capture cookies, authorization
   headers, credentials, session IDs, account IDs, or unrelated personal data.

If any prerequisite is not satisfied, stop and report
`BLOCKED_NEED_MANUAL_EVIDENCE`.

## Run metadata

Record these fields before testing:

| Field | Value |
|---|---|
| Operator | |
| Timestamp and timezone | |
| Permission/approval reference | |
| Browser and exact version | |
| OS | |
| Build URL (public/test URL only) | |
| Diablo season/patch shown | |
| Planner version/build shown, if any | |
| Character class and level | |
| Selected item slot | |
| Selected flat affix | |

## DevTools setup

1. Open the valid build normally and wait until the planner and Character Stats
   are fully visible.
2. Open DevTools → Network and enable **Preserve log**.
3. Make all request types visible. Inspect Fetch/XHR, WebSocket frames, and
   Other—not only Fetch/XHR.
4. Keep the browser console closed unless needed; this test does not require
   source-code inspection.
5. Record the count and names of requests already present, then clear the log.
6. Start a screen recording or take timestamped, tightly cropped screenshots
   that show only the modifier control, Character Stats, Network state, and the
   relevant sanitized request rows.

## CALC-01A/B — Online A → B → A

Choose one flat primary-stat affix, preferably Strength or Intelligence. Use a
modifier whose exact value can be changed without changing any other field.

1. **A baseline:** record the affix value and every Character Stat selected for
   observation. Take screenshot `online-a.png`.
2. Clear the Network log.
3. **B mutation:** change only the chosen affix by a clear amount, such as +20.
4. Wait for the UI to settle. Record Character Stats B and timestamp. Take
   screenshot `online-b.png`.
5. Record every request or WebSocket message beginning between the input event
   and stats update. For each, retain only method/type, sanitized URL path,
   start time, duration, status, initiator category, and whether the payload or
   response visibly contains the changed input/calculated output. Do not retain
   headers or unrelated payload content.
6. **Reverse to A:** restore exactly the original modifier. Record the returned
   Character Stats and network activity. Take `online-revert-a.png`.

Do not label analytics, autosave, profile persistence, or advertising traffic
as a calculation request merely because its timing overlaps the mutation. A
server calculation claim requires a correlated input/output contract and UI
dependency, not just a new request.

## CALC-01C/D — Offline A → B → C → A, three runs

Complete all loading while online. Do not reload after going offline.

1. Confirm baseline A and visible Character Stats.
2. In DevTools → Network, select **Offline** and capture `offline-enabled.png`
   showing the offline control and baseline stats.
3. Clear the Network log.
4. Change the modifier to a previously unused value **B**. Record input,
   selected Character Stats, UI update timestamp, and any failed/queued network
   activity.
5. Change it to a different previously unused value **C** and record the same
   fields.
6. Restore **A** and verify every selected Character Stat returns to the exact
   baseline display value.
7. Repeat steps 3–6 two more times without returning online. Use the same A, B,
   and C values for all three runs.
8. Capture one tightly cropped screenshot per A/B/C state per run, or a single
   timestamped recording that clearly shows all transitions and the Offline
   indicator.

Novel B and C values reduce the chance of mistaking one cached display for a
recalculation. They do not by themselves prove the implementation mechanism.
If the UI displays only an old value, a loading state, or an error, record that
exactly and classify the architecture as `NOT_VERIFIED` pending further work.

## Result worksheet

| Run | Network state | Input A | Stats A | Input B | Stats B | Input C | Stats C | Revert matches A? | Calculation request/response? |
|---:|---|---:|---|---:|---|---:|---|---|---|
| Online | Online | | | | | n/a | n/a | | |
| 1 | Offline | | | | | | | | |
| 2 | Offline | | | | | | | | |
| 3 | Offline | | | | | | | | |

For every observed Character Stat, compute and record `B - A`, `C - A`, and the
revert delta. Keep displayed precision; do not invent hidden precision.

## Classification decision

- Use `CLIENT_CONFIRMED` only when novel offline B and C values produce
  consistent recalculated stats, exact reversion occurs, all three runs agree,
  and no server calculation response is required. Scope the claim to the tested
  stats.
- Use `SERVER_CONFIRMED` only when a directly observed server response supplies
  the calculated stats and the UI depends on it.
- Use `HYBRID_CONFIRMED` only when direct evidence shows both sides materially
  participating in the tested calculation.
- Otherwise use `NOT_VERIFIED` and describe the ambiguity. No request during the
  online test alone is insufficient for `CLIENT_CONFIRMED`.

## Evidence handoff

After sanitization, place only real artifacts under:

`docs/research/maxroll-calculation-p0/evidence/client-calculation/`

Recommended names:

- `manual-run-summary.json`
- `network-request-summary.json`
- `online-a.png`, `online-b.png`, `online-revert-a.png`
- `offline-enabled.png`
- `offline-run-1.mp4` through `offline-run-3.mp4`, if recording is approved

Before committing, verify that no artifact contains cookies, authorization
headers, tokens, session IDs, account identifiers, private build data, full HAR
content, or proprietary source code.
