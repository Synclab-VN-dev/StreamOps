# Issue #119: All 38 acceptance statuses

Source: https://github.com/Synclab-VN-dev/StreamOps/issues/119
PR: https://github.com/Synclab-VN-dev/StreamOps/pull/120

| ID | Owner | Acceptance | State | Evidence / missing gate |
|---|---|---|---|---|
| P0-01 | CI/ChatGPT | Audit code hiện tại: NVDA events, parser whitelist, equipment pipeline, SQLite, CLI, character identity; lập gap/risk matrix và giữ backward comp | Done | Issue #119 comments + CI tests/evidence |
| P0-02 | CI/ChatGPT | Pin typed CLI/JSON schema, storage semantics, `CONFIRMED/NOT_CONFIRMED`, coverage states, error/exit codes, filters, versioning; contract tests đ | Done | Issue #119 comments + CI tests/evidence |
| P0-03 | CI/ChatGPT | Tạo probe/read-only one-shot script để xác nhận inventory UI, từng stash tab, navigation/tooltip, slot boundaries, empty slots, cùng source prove | Done | Issue #119 comments + CI tests/evidence |
| P0-04 | Dev F (A only) | Chạy probe trên Windows A khi có game/NVDA và quyền sử dụng môi trường; thu raw speech/event samples inventory + ít nhất 2 stash tabs, candidate/ | Pending | Requires Real-A, no CI duplicate |
| P0-05 | Owner manual | Thao tác điều hướng inventory/stash trong game theo **một** script/hướng dẫn ngắn nếu Dev F không thể automation 100%; không yêu cầu Owner làm nh | Done | Issue #119 comments + CI tests/evidence |
| P0-06 | CI/ChatGPT | Đưa evidence feasibility vào PR; nếu NVDA không chứng minh scan completeness/ownership, đề xuất bounded `PARTIAL` contract và blocker cụ thể, **k | Done | Issue #119 comments + CI tests/evidence |
| P1-01 | CI/ChatGPT | Refactor/reuse existing `ParsedItem` without changing current equipment semantics; recognize all observed supported item types, affixes, bases, e | Done | Issue #119 comments + CI tests/evidence |
| P1-02 | CI/ChatGPT | Implement `ItemObservationProjector`/resolver từ canonical `speech.raw`: segment → context (equipment/inventory/stash/tab) → typed observation +  | Done | Issue #119 comments + CI tests/evidence |
| P1-03 | CI/ChatGPT | Implement explicit ownership/location/identity evidence gate; cursor/slot enumeration + duplicate containment + unknown fallback; evidence needed | Blocked | No reliable selected tab/slot/full scan/move evidence from Real-A speech |
| P1-04 | CI/ChatGPT | Handle `move`/equip/unequip/removal as evidence-driven transitions; same-name/same-affix duplicates, gaps, retries, ambiguity, stale session rema | Blocked | No reliable selected tab/slot/full scan/move evidence from Real-A speech |
| P2-01 | CI/ChatGPT | Add versioned SQLite schema/migrations (owned-item observations, current placement projection, scan coverage, history, independent checkpoints) i | Blocked | No reliable selected tab/slot/full scan/move evidence from Real-A speech |
| P2-02 | CI/ChatGPT | Transactional event consumer with idempotent replay/dedupe, crash/restart checkpoint, no partial reads; preserve existing `character.db` behavior | Done | Issue #119 comments + CI tests/evidence |
| P2-03 | CI/ChatGPT | Implement `d4planner items`, `--json`, `--location`, `--rarity` with deterministic ordering, Unicode and stdout/stderr/exit contracts. | Done | Issue #119 comments + CI tests/evidence |
| P2-04 | CI/ChatGPT | Implement `d4planner items status --json` to show per-container/tab coverage, identity confidence, last scan and stale/capture-error signals. | Done | Issue #119 comments + CI tests/evidence |
| P2-05 | CI/ChatGPT | Implement `d4planner items history --json` and `items export --format jsonl --output` for item observation/move/removal audit; preserve raw event | Blocked | No reliable selected tab/slot/full scan/move evidence from Real-A speech |
| P2-06 | CI/ChatGPT | Document CLI examples and operational data location / schema / retention / migration / limitations; mark unobserved sections explicitly. | Done | Issue #119 comments + CI tests/evidence |
| UT-01 | CI/ChatGPT | Parse and retain item properties + raw fallbacks for observed inventory/stash/equipped fixtures, including unsupported/malformed. | Done | Issue #119 comments + CI tests/evidence |
| UT-02 | CI/ChatGPT | Resolver distinguishes `OBSERVED` vs `CONFIRMED OWNED`; hover/candidate/comparison not false-owned and `Equip` label not an action. | Done | Issue #119 comments + CI tests/evidence |
| UT-03 | CI/ChatGPT | Multi-tab stash, tab-switch, incomplete scan, empty slot, partial/stale identity: never false `COMPLETE`. | Done | Issue #119 comments + CI tests/evidence |
| UT-04 | CI/ChatGPT | Duplicate identical items in same/different locations are not incorrectly collapsed; uncertain moves not double-counted as verified ownership. | Done | Issue #119 comments + CI tests/evidence |
| UT-05 | CI/ChatGPT | No invented pickup/removal on partial scan; confirmed transitions preserve append-only history. | Blocked | No reliable selected tab/slot/full scan/move evidence from Real-A speech |
| UT-06 | CI/ChatGPT | SQLite migrations, transactions, restart/replay/idempotency, error/DB lock safety, checkpoint and original source events preservation. | Done | Issue #119 comments + CI tests/evidence |
| UT-07 | CI/ChatGPT | CLI filtering, JSON contract, Unicode output, sorting, empty/unknown state, invalid flags/error codes, status/history/export, shell redirection. | Done | Issue #119 comments + CI tests/evidence |
| E2E-01 | CI/ChatGPT | Existing #59 golden 929 events still yields exact 10 equipped, #62 empty-slot/ring regressions pass; no false current items. | Done | Issue #119 comments + CI tests/evidence |
| E2E-02 | CI/ChatGPT | Synthetic mixed fixture `equipment + inventory + >=2 stash tabs` → exact expected listing/coverage with duplicate and move cases. | Blocked | No reliable selected tab/slot/full scan/move evidence from Real-A speech |
| E2E-03 | CI/ChatGPT | Full CLI entrypoint + SQLite fixture end-to-end, concurrent reads during writes, resume after restart, history export and no full-event-history r | Done | Issue #119 comments + CI tests/evidence |
| E2E-04 | CI/ChatGPT | Ensure capture/supervisor behavior remains unchanged, errors degrade to partial/BLOCKED, no game control/injection/memory access. | Done | Issue #119 comments + CI tests/evidence |
| CI-01 | CI/ChatGPT | Link command logs, test summary, schema fixtures, covered matrix, HEAD SHA and remaining gaps in PR. CI green alone does not imply Real-A pass. | Pending | Required CI code/tests/report |
| DF-01 | Dev F (A only) | On real A validate NVDA/tooltips for equipped/inventory/stash and each accessible tab; archive fixture, process/PID, locale, runtime HEAD, timest | Pending | Requires Real-A, no CI duplicate |
| DF-02 | Dev F (A only) | Compare JSON listing against screenshots/manual enumeration for sampled inventory + stash tabs; verify same-named duplicates, missing context, so | Pending | Requires Real-A, no CI duplicate |
| DF-03 | Dev F (A only) | Validate state after changing item between inventory ↔ stash ↔ equip, after dropping/salvaging only if explicitly authorized and safe; otherwise  | Pending | Requires Real-A, no CI duplicate |
| DF-04 | Dev F (A only) | Capture failure/suspended game/unknown character or partial stash produces honest stale/partial output; restart D4Planner does not lose confirmed | Pending | Requires Real-A, no CI duplicate |
| UAT-01 | CI/ChatGPT | Build **one-shot PowerShell runner**, validate syntax/UT/error paths first; produce PASS/FAIL/BLOCKED/SKIP per case, expected/actual, paths to ra | Pending | Required CI code/tests/report |
| MAN-01 | Owner manual | Read-only visual walkthrough inventory/stash on game UI to establish whether the manually observed items appear correctly in CLI; record PASS/FAI | Pending | Owner approval/manual only |
| MAN-02 | Owner manual | Review acceptance evidence, decide any remaining contract changes/limitations, explicitly approve PR merge; deploy requires separate approval. | Pending | Owner approval/manual only |
| DONE-01 | CI/ChatGPT | Provide runbook `WHAT / WHO / HOW`: exact CLI commands to list/filter/export, status semantics, where logs live, what remains unobserved. | Done | Issue #119 comments + CI tests/evidence |
| DONE-02 | CI/ChatGPT | Post ticket/PR matrix of every checkbox `Done / Pending / Blocked`, owner, test/evidence link, stage progress % and next action; do not mark done | Pending | Required CI code/tests/report |
| DONE-03 | Owner manual | Final review + **explicit merge**; no auto-merge/auto-deploy. | Pending | Owner approval/manual only |

CI 20/29 Done; Dev F 0/5; Owner 1/4; overall 21/38 at creation. Never treat a synthetic CI pass as physical owned-item completeness or merge approval. Old Windows full-suite failure from unrelated Game Manager reconnect Playwright test remains to resolve or classify without bypass.
