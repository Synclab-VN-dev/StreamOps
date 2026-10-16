# Maxroll reference baseline — 3.2.1.73552 (Owner selected, 2026-10-16)

- **Oracle:** Maxroll only, UI/engine parity on captured fixtures; not independently verified against live game behavior.
- **Fixture URL:** https://maxroll.gg/d4/planner/1g1any0x#3
- **F1 evidence:** https://github.com/Synclab-VN-dev/StreamOps/issues/106#issuecomment-6196291714
- **Class/build:** Rogue Penetrating Shot Endgame, level 70, Season 15, Torment IV, Dual Wield.
- **Game patch/build observed in fixture UI:** `3.2.1.73552`.
- **Maxroll app semver:** unavailable; Owner explicitly authorized this pinned game-build baseline without waiting for a global latest-version claim.
- **Input snapshot SHA256 (Agent reported):** `3ae138cafe3aa4b3633744d0ea5e22b1bd8d92afab77be857906d0b6010cff07`.
- **Captured visible metric denominator:** 50 (2 Summary, 5 Core, 8 Resistances, 20 Offensive, 7 Defensive, 7 Utility, 1 PvP).
- **Candidate direct UI display metric values:** 50; **runtime raw observations:** 0; **approved Maxroll Goldens:** 0; **causally verified formulas in F1:** 0.
- **Known blockers:** unresolved sockets, full paragon path, passive and specialization mapping, dynamic conditions. Full local evidence artifacts are gitignored on Linux F and were not independently reviewed by ChatGPT.
- **Active parity:** `BLOCKED_NO_APPROVED_GOLDEN`. CI-03 validates structural contract / provenance rules, not numeric formula accuracy. #108 owns parity gate; #106 owns inventory/causal research; #110 owns graph output.
- **Historical legacy:** `game-mechanics-3.2.3.md` and `references/3.2.3/ci03-reference-vectors.json` are retained as ARCHIVED/HISTORICAL only and never counted as Maxroll expected.
- **Safety:** never fabricate a source or formula based on UI values or pass synthetic vectors as Maxroll goldens; no numeric fallback for unknown metric.

The Owner's patch pin overrides the need to establish a separate Maxroll app semantic version for this baseline. Exact game patch/build, fixture fingerprint, independent source snapshots and approval remain required for future Golden promotion. This does not alter DSL schema v1 or 15 action semantics.
