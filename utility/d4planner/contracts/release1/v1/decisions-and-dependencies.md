# Decisions and dependency handoff

This is the single decision table for unresolved S1 questions. Approved scope
(Equipment-only, WS, user-authored core flags, score formula, WARN/FAIL/UNKNOWN,
and deferred Torment) is deliberately not asked again.

| Decision | Câu hỏi còn thiếu | Phương án đề xuất | Tại sao cần quyết định | Impact tới user | Phần bị ảnh hưởng | Người duyệt |
| --- | --- | --- | --- | --- | --- | --- |
| D1 `PENDING_OWNER` | Production weight profile nào bảo đảm core > non-core? | Approve a named/versioned profile; candidate `core=3`, `non-core=1`. Until then all such fixtures are `TEST_ONLY` and production activation has no default. | Exact score changes with the ratio. | Same equipment could show a different score after a profile change; version must be visible/auditable. | S1-04, S4 scorer/activation, S5 HUD, S7 vectors | Owner |
| D2 `PENDING_OWNER` | Item x/y requires every criterion PASS or only core; “Issues only” includes WARN; score rounding, recommendation priority and tie-break? | Item PASS only when every evaluable target criterion PASS and none UNKNOWN; Issues-only shows FAIL+WARN; transport exact decimal, UI rounds half-up to integer; priority FAIL core → WARN core → WARN non-core, then target order/criterion ID. | Prevents FE/BE disagreeing on counts/filter/order while criterion statuses remain stable. | Controls x/y, which rows users see, displayed score and next action. | S1-03/04, S4, S5, S6, S7 | Owner |
| D3 `PENDING_OWNER` | OS Pin semantics; acceptable latency budgets; must Windows A acceptance include OBS and/or Steam Link? | Pin means explicit always-on-top toggle persisted per user with visible state; approve percentile budgets only after S7 baseline; require game+OBS recording, keep Steam Link as separately reported unless Owner makes it mandatory. | These are physical/runtime acceptance claims that contract tests cannot establish. | Determines overlay behavior and whether release feels responsive/works in the viewing path. | S1-05, S2, S6, S7, #76/#100/#103/#104 | Owner |
| D4 `PENDING_OWNER` | Which immutable visual reference covers selector, Equipment-only navigation, coverage and NO_DATA/stale/error states? | In S6 create the smallest MagicPath delta from revision `458808549301174272`, obtain Owner approval, then pin project/component/revision and independent captures. | Old revision does not contain these states; production FE cannot become its own Golden. | Prevents an unreviewed selector/status UX and false visual PASS. | S1-06, S6 visual gate, S7 | Owner |

Status legend: `APPROVED` is an explicit Owner decision; `PROPOSED` is a review
candidate; `PENDING_OWNER` needs Owner choice; `DEFERRED` is outside Release 1.
Torment/Skills/Paragon/Charms scoring and inventory/stash recommendation are
`DEFERRED`, not blockers. The architecture and Equipment rules recorded in
#137/#138 are `APPROVED`.

## S1 acceptance mapping

| Gate | Deliverable/evidence | Status at contract candidate |
| --- | --- | --- |
| S1-01 | ADR state machine/sequences, launch/driver/template interfaces, synthetic lifecycle traces/tests | PASS |
| S1-02 | Target + WS schemas, list/select hash contract, invalid/changed/deleted fixtures/tests | PASS |
| S1-03 | HUD schema/data dictionary, partial/NO_DATA/current-target/health bindings and tests | PASS |
| S1-04 | Formula/truth vectors pass; production weights and aggregation/format policy | PENDING (D1/D2) |
| S1-05 | Capacity/security/session invalidation specified; physical latency/pin/scope | PENDING (D3; Windows E2E NOT_RUN) |
| S1-06 | Baseline/delta and dependency mapping specified; immutable delta reference | PENDING (D4) |

## S2-S7 ownership and non-duplication map

| Workstream | Owner/input | Output/acceptance owned there | Existing-ticket overlap (reference only) |
| --- | --- | --- | --- |
| S2 #139 | FE; lifecycle ADR/interfaces | Managed BE entrypoint, private bootstrap, real READY/stop/parent-death wrapper | #100 shell/runtime; do not count #100 acceptance twice |
| S3 #140 | BE/Rule Kit; lifecycle + existing eight APIs | Reused worker, bounded contexts/sessions/leases, IPC, generation invalidation | Rule Kit #124/#127/#128/#132/#134/#136 remain source baselines |
| S4 #141 | BE; Target/HUD schemas and truth vectors | Safe folder repository, activation hash, equipment assessor and durable commit | #102 real data integration; #101 fixture adapters are not scorer acceptance |
| S5 #142 | BE+FE; WS schema/sequences | Authenticated loopback server/client, snapshot boundary, push, resync/backpressure | #102 transport integration; no DB/file fallback |
| S6 #143 | FE; HUD schema/data dictionary, MagicPath baseline | Equipment UI, selector and approved/pinned visual delta using real WS model | #97 epic, #98 Golden gate, #99 layout, #101 typed VM; keep ownership explicit |
| S7 #144 | Integration/release; all pinned contracts | Windows packaging, process/WS/equipment E2E, performance and manual evidence | #103 packaging/CI, #104 OBS/Steam Link, #76 final manual; report separately |

S1 defines compatibility and test vectors. It does not close/reopen #76 or
#97-#104, implement S2-S7, merge the design branch, or claim their acceptance.
