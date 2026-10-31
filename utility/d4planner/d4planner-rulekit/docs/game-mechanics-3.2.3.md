# Diablo IV mechanics evidence register — baseline 3.2.3 (CI-03)

**As of 2026-10-14**, Blizzard lists 3.2.3 build #73883. This patch note does
**not** publish a complete damage/event execution algorithm. We DO NOT infer
snapshot order, exact event scheduling or proc inheritance from missing notes.

| ID | Blizzard evidence | What CI can assert | What it cannot assert |
|---|---|---|---|
| blizzard-gear-2026 | https://news.blizzard.com/en-us/article/24267729/prepare-for-the-reckoning-lord-of-hatred-draws-near | Eligible gear damage multipliers stack additively with themselves and stay multiplicative | All Aspect multipliers belong in this bucket |
| blizzard-storm-3-0-4 | https://news.blizzard.com/en-us/article/24271857/diablo-iv-patch-notes-3-0 | Storm Shephard set 5-piece stacks with its 2-piece after 3.0.4 | Universal charm stacking; exact numeric DPS of that set |
| blizzard-buckets-1-2 | https://news.blizzard.com/en-us/article/24014289/master-your-power-in-season-of-blood | Historical explicit 18% additive +20% Vulnerable baseline -> 41.6% bonus | Same formula is guaranteed unchanged for all 3.x contexts |
| blizzard-patch-3-2-3 | https://news.blizzard.com/en-us/article/24295395/diablo-iv-patch-notes | Patch 3.2.3 identity/build | Entire game math re-verified in 3.2.3 |
| blizzard-3-0-trigger-fixes | https://news.blizzard.com/en-us/article/24271857/diablo-iv-patch-notes-3-0 | Triggered and summoned skills have distinct inheritance applicability; 3.0 fixed several defects | Universal inherited crit roll, Lucky Hit, snapshot or proc recursion rule |

## Verification classes

- **OFFICIAL:** precise behavior or example in a Blizzard document with a concrete source.
- **SYNTHETIC VALUES:** illustrate officially documented operator behavior; expected arithmetic
  independently calculated by hand and stored as an explicit golden. Not Blizzard damage output.
- **HISTORICAL:** tied to the patch/season of the source. Never promoted to the 3.2.3 mechanics policy.
- **UNVERIFIED / UNKNOWN:** no supported rule-specific interpretation. Must not result in numeric
  performance estimates marked as verified.

These references are immutable inputs to CI (CI makes **no HTTP requests** and does not
scrape Blizzard). Ticket #109 will inventory/promote patch rule data with source snapshots.
