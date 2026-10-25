# Decisions and dependency handoff

Decision authority: Owner comment
[`6394334041`](https://github.com/Synclab-VN-dev/StreamOps/issues/138#issuecomment-6394334041).

## Applied decision ledger

| Decision | Status | Contract applied in candidate.2 | Remaining downstream evidence |
| --- | --- | --- | --- |
| D1 weights | `APPROVED` | Named `r1-equipment-weights/1.0.0`; core=3, non-core=1; user-authored core flag; approval link in Target policy | Production S4 implementation/E2E |
| D2 aggregation | `APPROVED` | Item PASS iff all criteria PASS; issues count distinct FAIL; Issues-only shows FAIL+WARN; exact transport score/final half-up display; recommendation order core FAIL → core WARN → non-core WARN → target order/ID | Production S4/S6 implementation/E2E |
| D3 Pin | `APPROVED` | Always-on-top only; no position lock and no persistence-after-restart implication | Native S6/S7 test |
| D3 latency | `PENDING_OWNER` | Metrics remain decomposed; no threshold invented | Owner threshold, then S7 measurement |
| D3 OBS/Steam Link | `PENDING_OWNER` | Neither mandatory nor exempted by S1 | Owner acceptance scope, then #76/#104/S7 |
| D4 design revision | `APPROVED` | Project `458763473602621440`, component `458765764401446912`, revision `464988421014827008`; Target menu replaces LIVE, Charms hidden, no Coverage HUD, Equipment/Compare/score/issues/Pin retained | Export/render/hash/Golden and missing-state visual acceptance are `NOT_RUN`, owned by S6 |
| Torment and non-Equipment scoring | `DEFERRED` | Outside Release 1; not an S1 blocker | Future release decision |

## Questions still requiring Owner answers

| Decision | Câu hỏi còn thiếu | Tại sao cần quyết định | Impact tới user | Phần bị ảnh hưởng | Người duyệt |
| --- | --- | --- | --- | --- | --- |
| D3 latency `PENDING_OWNER` | Ngưỡng acceptance cho capture → confirmed evidence → score commit → WS → render là bao nhiêu, theo percentile nào? | S1 can define timestamps but cannot invent a product threshold before Windows measurement. | Determines when delayed/stale feedback becomes a release failure. | S7 performance/UAT | Owner |
| D3 physical scope `PENDING_OWNER` | Windows A acceptance bắt buộc OBS, Steam Link, hay cả hai ở gate nào? | No current decision makes OBS mandatory or exempts Steam Link. | Determines which real viewing paths are release-blocking. | S7, #76, #104 | Owner |

## S1 acceptance mapping

| Gate | Deliverable/evidence | Status at candidate.2 |
| --- | --- | --- |
| S1-01 | ADR state machine/sequences, launch/driver/template interfaces, synthetic lifecycle traces/tests | PASS |
| S1-02 | Target/WS schemas, safe list/select, startup contexts, authoritative resync and changed-file vectors/tests | PASS |
| S1-03 | Display-complete Equipment HUD, discriminated partial/NO_DATA contexts, provenance/freshness/binding tests | PASS |
| S1-04 | Approved weighted formula, typed/multi-parameter truth vectors, issue/item/rounding/recommendation rules | PASS |
| S1-05 | Lifecycle/security/capacity/compatibility specified; latency and physical acceptance thresholds | PENDING (two D3 Owner questions; runtime E2E belongs S2/S3/S7) |
| S1-06 | Approved design revision/no-Coverage mapping and dependency ownership | PASS contract mapping; S6 Golden/visual acceptance NOT_RUN |

## S2-S7 ownership and non-duplication map

| Workstream | Owner/input | Output/acceptance owned there | Existing-ticket overlap (reference only) |
| --- | --- | --- | --- |
| S2 #139 | FE; lifecycle ADR/interfaces | Managed BE entrypoint, private bootstrap, READY/stop/parent-death wrapper | #100 shell/runtime; do not count #100 acceptance twice |
| S3 #140 | BE/Rule Kit; lifecycle + existing eight APIs | Reused worker, bounded contexts/sessions/leases, IPC, generation invalidation | Rule Kit #124/#127/#128/#132/#134/#136 remain source baselines |
| S4 #141 | BE; approved policy, typed Target/HUD schemas and raw truth vectors | Safe folder repository, activation hash, multi-parameter assessor and durable commit | #102 real data integration; #101 fixture adapters are not scorer acceptance |
| S5 #142 | BE+FE; WS schema/sequences | Authenticated loopback server/client, same-generation authoritative snapshot, push, resync/backpressure | #102 transport integration; no DB/file fallback |
| S6 #143 | FE; display-complete HUD and approved MagicPath revision `464988421014827008` | Equipment-only UI, Target menu, always-on-top Pin; no Coverage HUD; independent export/hash/Golden | #97/#98/#99/#101; visual states/Golden still require S6 evidence |
| S7 #144 | Integration/release; all pinned contracts | Windows packaging, process/WS/equipment E2E, latency evidence and Owner-selected OBS/Steam Link scope | #103/#104/#76; report separately |

S1 defines compatibility and test vectors. It does not close/reopen #76 or
#97-#104, implement S2-S7, modify MagicPath, or claim their acceptance.
