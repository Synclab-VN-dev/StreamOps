# Decisions and dependency handoff

Decision authority: Owner comments
[`6394334041`](https://github.com/Synclab-VN-dev/StreamOps/issues/138#issuecomment-6394334041)
and [`6396082595`](https://github.com/Synclab-VN-dev/StreamOps/pull/145#issuecomment-6396082595).

## Applied decision ledger

| Decision | Status | Contract applied in candidate.5 | Remaining downstream evidence |
| --- | --- | --- | --- |
| D1 weights | `APPROVED` | Named `r1-equipment-weights/1.0.0`; core=3, non-core=1; user-authored core flag; approval link in Target policy | Production S4 implementation/E2E |
| D2 aggregation | `APPROVED` | Item PASS iff all criteria PASS; issues count distinct FAIL; Issues-only shows FAIL+WARN; exact transport score/final half-up display; recommendation order core FAIL → core WARN → non-core WARN → target order/ID | Production S4/S6 implementation/E2E |
| D3 Pin | `APPROVED` | Always-on-top only; no position lock and no persistence-after-restart implication | Native S6/S7 test |
| D3 latency | `RESOLVED — ASAP` | Evidence-ready work proceeds assess → commit → notification → native DB read → render without intentional delay/polling; preserve correctness, bounded queue/coalescing/backpressure and stage timestamps/P50/P95; no fixed SLA invented | S7 runtime measurement/optimization |
| D3 capture scope | `RESOLVED — EXISTING_WINDOW_CAPTURE` | HUD is a normal native window consumed by existing StreamOps `window_capture`; no new capture subsystem or OBS/Steam Link adapter | Actual HUD window selection/capture verification in S6/S7 |
| Active character scope | `APPROVED` | One currently playing character; initial discovery and bounded discovery recovery when known context changed, no selector/profile management | Production S5 integration/E2E |
| D4 design revision | `APPROVED` | Project `458763473602621440`, component `458765764401446912`, revision `464988421014827008`; Target menu replaces LIVE, Charms hidden, no Coverage HUD, Equipment/Compare/score/issues/Pin retained | Export/render/hash/Golden and missing-state visual acceptance are `NOT_RUN`, owned by S6 |
| Torment and non-Equipment scoring | `DEFERRED` | Outside Release 1; not an S1 blocker | Future release decision |

## Remaining Owner questions

None for the S1 contract. Runtime implementation, performance measurement,
existing-window capture verification and visual Golden evidence remain NOT_RUN
downstream gates, not unresolved S1 policy decisions.

## S1 acceptance mapping

| Gate | Deliverable/evidence | Status at candidate.5 |
| --- | --- | --- |
| S1-01 | ADR state machine/sequences, launch/driver/template interfaces, synthetic lifecycle traces/tests | PASS |
| S1-02 | Target/WS schemas, safe list/select, explicit initial discovery/known-context resync, same-backend reconnect high-water guard, bounded context-change recovery, startup/context transitions and changed-file vectors/tests | PASS |
| S1-03 | Display-complete Equipment HUD, discriminated partial/NO_DATA contexts, provenance/freshness/binding tests | PASS |
| S1-04 | Approved weighted formula, typed/multi-parameter truth vectors, issue/item/rounding/recommendation rules | PASS |
| S1-05 | Lifecycle/security/capacity/compatibility, ASAP latency policy, stage measurements and existing window-capture reuse boundary | PASS contract; runtime E2E/measurements NOT_RUN and owned by S2/S3/S6/S7 |
| S1-06 | Approved design revision/no-Coverage mapping and dependency ownership | PASS contract mapping; S6 Golden/visual acceptance NOT_RUN |

## S2-S7 ownership and non-duplication map

| Workstream | Owner/input | Output/acceptance owned there | Existing-ticket overlap (reference only) |
| --- | --- | --- | --- |
| S2 #139 | FE; lifecycle ADR/interfaces | Managed BE entrypoint, private bootstrap, READY/stop/parent-death wrapper | #100 shell/runtime; do not count #100 acceptance twice |
| S3 #140 | BE/Rule Kit; lifecycle + existing eight APIs | Reused worker, bounded contexts/sessions/leases, IPC, generation invalidation | Rule Kit #124/#127/#128/#132/#134/#136 remain source baselines |
| S4 #141 | BE; approved policy, typed Target/HUD schemas and raw truth vectors | Safe folder repository, activation hash, multi-parameter assessor and durable commit | #102 real data integration; #101 fixture adapters are not scorer acceptance |
| S5 #142 | BE+FE; WS schema/sequences | Authenticated loopback server/client, monotonic same-backend reconnect, initial active-context discovery, known-context resync, bounded mismatch→discovery recovery, push/backpressure | #102 transport integration; no periodic polling; startup/resume/reconnect/manual refresh read SQLite |
| S6 #143 | FE; display-complete HUD and approved MagicPath revision `464988421014827008` | Equipment-only native window, Target menu, always-on-top Pin; no Coverage HUD; existing `window_capture` compatibility and independent Golden | #97/#98/#99/#101; runtime capture/visual evidence still required |
| S7 #144 | Integration/release; all pinned contracts | Windows packaging, process/WS/equipment E2E, ASAP stage P50/P95 and actual existing-window capture verification | #103/#104/#76; report separately |

S1 defines compatibility and test vectors. It does not close/reopen #76 or
#97-#104, implement S2-S7, modify MagicPath, or claim their acceptance.

## D5 migration — 2026-10-31

D5 APPROVED supersedes the candidate.5 transport acceptance above. Those PASS entries
are historical contract evidence, not D5 runtime acceptance.

| Gate | Owner | Required evidence |
|---|---|---|
| S1-DB01 | #145/#147 | Versioned projection, identity, migration, atomic binding |
| S1-DB02 | #149/#151/#150 | Viewer without BE/WS/Node, last-known/NO_DATA/errors |
| S1-DB03 | #148/#151 | Notification only, reorder/loss/reconnect DB reread |
| S1-DB04 | #148 | Correlated Target commands on managed_backend pipe |
| S1-DB05 | #147/#151 | WAL read-only concurrency, replacement, schema errors |
| S1-DB06 | All seven PRs | Contract-to-source/package trace and native E2E |

True stack: #145 → #149 → #146 → #147 → #148 → #151 → #150.
#146 retains its owner and existing official APIs. No scoring or MagicPath redesign.
Golden/MAN/release gates are independent; source tests cannot discharge them.
