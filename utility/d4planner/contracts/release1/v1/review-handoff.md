# S1 review correction handoff

- Reviewed HEAD: `157882f927930488013067be2984e262f5bc0fc4`
- Regression base: `010e563daee0e037695aa506d160eedcf60ab43d`
- Corrected contract: `d4planner-r1-contract/1.0.0-candidate.5`
- Scope: schema/interfaces/docs/fixtures/contract-model tests only

| Finding | Severity | Root cause | Impact tới user nếu không sửa | Fix | Before/after evidence | Status |
| --- | --- | --- | --- | --- | --- | --- |
| S1-REV-01 | P1 | HUD required non-null Target/character/binding even before those existed. | FE must invent IDs or cannot render normal startup; stale score can survive context loss. | Closed context union for STARTUP/TARGET_ONLY/CHARACTER_ONLY/BOUND/TARGET_UNAVAILABLE; atomic invalidation and selection-failure rules. | Before: reviewer could not validate null Target/character. After: five schema fixtures plus startup→target→character→equipment, target deletion and character-change tests. | FIXED / LOCAL PASS |
| S1-REV-02 | P1 | Snapshot and incremental update shared one predecessor rule; same-generation snapshot after a gap was rejected again. | HUD can remain stale through reconnect/resync until BE restarts. | Correlated authoritative snapshots use minimum revision/context anti-stale checks; updates retain strict predecessor/subscription rules. | Before probe: generation 3/rev 10 + snapshot rev 13 → RESYNC_GAP. After vectors: gap → same-generation snapshot 13 → update 14, reconnect/equal revision, stale/wrong/late/new-generation cases. | FIXED / LOCAL PASS |
| S1-REV-03 | P1 | Numeric comparators accepted string/bool, ranges were not semantically ordered, and criterion identity could not address occurrence/parameter. | Invalid Target or partial multi-value comparison can produce misleading score/issues. | Typed operands/comparator unions, source group+occurrence, stable parameter ID/index and `ALL` aggregation; semantic range/link/duplicate guards; raw-value vectors. | Before reviewer probes accepted `"not-a-number"`/`true` and rejected useful multi-value shape. After schema rejects wrong type/unit, semantic tests reject malformed range/missing/duplicate parameter and accept distinct occurrence/multi-parameter. | FIXED / LOCAL PASS |
| S1-REV-04 | P1 | Closed HUD payload carried IDs but lacked item/entity labels/text and observation provenance. | S6 must hardcode/lookup catalog or keep mock data. | Embedded BE-produced build/slot/item/entity/parameter labels, display text, typed values, observed timestamp/source and audit provenance. | Before additional display fields were rejected and no render source existed. After `hud.partial.synthetic.json` renders Equipment/Compare entirely from the payload; missing labels/untyped numeric data fail validation. | FIXED / LOCAL PASS |
| S1-REV-05 | P1 | Null expected IDs in one snapshot shape ambiguously meant discovery and exact absence; reducer therefore rejected the BE's active character on a fresh FE connection. | HUD can remain empty although BE already has the playing character and selected Target. | Split `DISCOVER_ACTIVE_CONTEXT` from `RESYNC_KNOWN_CONTEXT`; accept discovery only with pending correlation/runtime/generation/revision guards, keep exact known-context resync and single-active-character transitions. | Before reviewer probe returned `REJECT_CONTEXT`. After schema→reducer discovery applies BOUND context; STARTUP/TARGET_ONLY activation, reidentification, reconnect, stale/wrong correlation/generation/Target/late vectors pass. | FIXED / LOCAL PASS |
| S1-REV-06 | P2 | `EQUAL` returned boolean false for incompatible typed values; Python can also treat `True == 1`. | Incomparable evidence became WARN/evaluable weight and incorrectly lowered score. | Return non-evaluable before equality when type or unit differs; compare value only after both match. | Before NUMBER 1 vs BOOLEAN true produced WARN/SCORED/evaluable=3. After NUMBER↔BOOLEAN/TEXT and unit mismatch are UNKNOWN/NO_DATA/evaluable=0; same type/unit unequal is WARN and equal is PASS. | FIXED / LOCAL PASS |
| S1-REV-07 | P1 | A valid known-context resync snapshot with a changed character/Target returned `REJECT_CONTEXT`, leaving the old pending request without a recovery transition. | HUD could retain stale character/Target data after a missed update until backend restart or manual action. | Consume the mismatched request, invalidate old assessment, preserve the authoritative revision as a floor, then issue bounded `DISCOVER_ACTIVE_CONTEXT` with fresh correlation; atomically install the discovered context/subscription. | Fail-first TARGET_ONLY→BOUND vector returned `REJECT_CONTEXT` instead of `REQUEST_CONTEXT_DISCOVERY`. After: schema→reducer Target switch, TARGET_ONLY→BOUND, unchanged resync, stale/late/correlation/runtime/generation guards, post-recovery update and two-attempt timeout exhaustion pass. | FIXED / LOCAL PASS |
| S1-REV-08 | P1 | `HELLO_ACCEPTED` unconditionally reset revision/context even when runtime instance and generation were unchanged. | A same-backend transport reconnect could accept an older snapshot and roll HUD Target, Equipment and score backward. | Compare retained checkpoint with accepted backend identity; same identity preserves revision/context but clears connection state and marks assessment non-current, while changed identity performs fresh reset/discovery. | Fail-first sequence went through `HELLO_ACCEPTED` at revision 20 and returned `RESET_GENERATION` with revision -1. After: HELLO-driven stale/equal/newer/update/restart/old-traffic/context-change vectors pass. | FIXED / LOCAL PASS |
| D3 sync | Policy | Ledger still treated latency and OBS/Steam Link scope as Owner blockers. | Downstream work could wait unnecessarily or build a duplicate capture adapter. | Apply ASAP pipeline policy and reuse existing StreamOps `window_capture`; retain stage telemetry and downstream real-window verification. | Owner decision `6396082595`; repository source catalog/input reconciliation referenced, no production capture code changed. | RESOLVED / CONTRACT PASS |

## S1-REV-07 acceptance

| Test ID | Expected | Actual/evidence | Status |
| --- | --- | --- | --- |
| REV07-01 | Missed TARGET_ONLY→BOUND update recovers active character. | Known-context mismatch starts discovery at revision floor 7; correlated discovery installs BOUND and update 8 applies. | PASS |
| REV07-02 | Missed Target A→B update cannot retain/relabel A score. | Mismatch leaves A identity at revision 20 but clears assessment binding; discovery revision 22 atomically installs B and its binding. | PASS |
| REV07-03 | Unchanged known context still resyncs normally. | Existing same-generation gap and reconnect/equal-revision vectors apply snapshot/update without recovery. | PASS |
| REV07-04 | Stale/late/wrong-correlation snapshots cannot roll back. | Stale mismatch is ignored before context interpretation; consumed/incorrect correlation responses reject. | PASS |
| REV07-05 | Wrong runtime instance/generation rejects safely. | Separate instance and generation vectors reject without consuming valid recovery state. | PASS |
| REV07-06 | Incremental update continues after recovery. | Updates 8 and 23 join the new subscription/revision and return `APPLY_UPDATE`. | PASS |
| REV07-07 | Timeout/retry is finite. | Attempt 1 timeout retries once; attempt 2 exhausts; below-floor and attempt 3 reject, with no pending request/loop. | PASS |
| REV07-08 | REV-01…06 do not regress. | Complete schema/semantic/state-model contract suite passes. | PASS |

## S1-REV-08 acceptance

| Test ID | Expected | Actual/evidence | Status |
| --- | --- | --- | --- |
| REV08-01 | Same instance/generation preserves revision 20. | `HELLO_ACCEPTED` returns `RECONNECT_SAME_GENERATION`; high-water remains 20 while connection state clears. | PASS |
| REV08-02 | Snapshot revision 18 after reconnect is stale. | Snapshot rejects as `IGNORE_STALE_SNAPSHOT`; high-water remains 20. | PASS |
| REV08-03 | Equal revision 20 confirms idempotently. | Correct binding returns `CONFIRM_EQUAL_SNAPSHOT` and installs the new subscription. | PASS |
| REV08-04 | Newer revision 21 applies. | Authoritative same-context snapshot returns `APPLY_SNAPSHOT`. | PASS |
| REV08-05 | Incremental revision 22 continues. | New subscription plus predecessor 21 returns `APPLY_UPDATE`. | PASS |
| REV08-06 | Changed backend identity permits lower revision. | HELLO resets high-water/context; fresh discovery accepts new backend revision 1. | PASS |
| REV08-07 | Old connection traffic cannot apply. | Old correlation/subscription and old backend traffic reject without changing high-water. | PASS |
| REV08-08 | Context change during reconnect uses REV-07. | Old assessment remains non-current; mismatch starts bounded discovery which atomically installs Target/character B. | PASS |
| REV08-09 | Recovery remains bounded. | Existing attempt/floor/timeout/exhaustion sequence remains green. | PASS |
| REV08-10 | REV-01…07 do not regress. | Complete contract suite passes. | PASS |

## Base-vs-PR targeted regression

Both sides used `/tmp/streamops-issue138-venv`, the same Python/dependencies,
PATH and an explicit `PYTHONPATH` to the respective worktree source.

| Test | Base `010e563…` | Corrected PR worktree before final commit | Assertion/root cause | Classification |
| --- | --- | --- | --- | --- |
| `test_path_restore_refuses_while_runtime_active` | FAIL: expected 4, got 2 | Same FAIL | Linux `os.name != "nt"` guard returns “PATH management requires Windows” before active-runtime branch. | BASELINE_ENVIRONMENT_FAILURE |
| `test_supervisor_selects_exactly_one_marker_backend_for_each_mode` | FAIL: expected one factory call, got 0 | Same FAIL | Linux guard in `_start_marker_capture` returns before fake Windows hook/poll factories. | BASELINE_ENVIRONMENT_FAILURE |
| `test_e2e03_xbox16_session1_one_hook_end_to_end_to_sqlite` | FAIL: `entered.wait(2.0)` false | Same FAIL | Same Linux marker guard prevents synthetic hook `__enter__`; no runtime production change in S1. | BASELINE_ENVIRONMENT_FAILURE |

Base result: 3 failed in 2.21s (2.33s wall). PR comparison result: 3 failed
in 2.11s (2.23s wall). These results establish parity; they do not make the
full Linux suite PASS and do not replace Windows runtime gates in S2-S7.

The candidate.5 delta changes only versioned contracts, fixtures, documentation
and their model tests, so the already-established Windows-only A/B was not
repeated. Final affected validation is recorded in the PR and issue handoff for
the exact delivered HEAD.

GitHub Actions were not queried, triggered or rerun (`CI_NOT_CHECKED`).
