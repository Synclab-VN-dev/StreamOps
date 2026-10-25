# S1 review correction handoff

- Reviewed HEAD: `5b2956735b0e19775689b0cd1caf8db81c5f8c96`
- Regression base: `010e563daee0e037695aa506d160eedcf60ab43d`
- Corrected contract: `d4planner-r1-contract/1.0.0-candidate.3`
- Scope: schema/interfaces/docs/fixtures/contract-model tests only

| Finding | Root cause | Impact tới user nếu không sửa | Fix | Before/after evidence | Status |
| --- | --- | --- | --- | --- | --- |
| S1-REV-01 | HUD required non-null Target/character/binding even before those existed. | FE must invent IDs or cannot render normal startup; stale score can survive context loss. | Closed context union for STARTUP/TARGET_ONLY/CHARACTER_ONLY/BOUND/TARGET_UNAVAILABLE; atomic invalidation and selection-failure rules. | Before: reviewer could not validate null Target/character. After: five schema fixtures plus startup→target→character→equipment, target deletion and character-change tests. | FIXED / LOCAL PASS |
| S1-REV-02 | Snapshot and incremental update shared one predecessor rule; same-generation snapshot after a gap was rejected again. | HUD can remain stale through reconnect/resync until BE restarts. | Correlated authoritative snapshots use minimum revision/context anti-stale checks; updates retain strict predecessor/subscription rules. | Before probe: generation 3/rev 10 + snapshot rev 13 → RESYNC_GAP. After vectors: gap → same-generation snapshot 13 → update 14, reconnect/equal revision, stale/wrong/late/new-generation cases. | FIXED / LOCAL PASS |
| S1-REV-03 | Numeric comparators accepted string/bool, ranges were not semantically ordered, and criterion identity could not address occurrence/parameter. | Invalid Target or partial multi-value comparison can produce misleading score/issues. | Typed operands/comparator unions, source group+occurrence, stable parameter ID/index and `ALL` aggregation; semantic range/link/duplicate guards; raw-value vectors. | Before reviewer probes accepted `"not-a-number"`/`true` and rejected useful multi-value shape. After schema rejects wrong type/unit, semantic tests reject malformed range/missing/duplicate parameter and accept distinct occurrence/multi-parameter. | FIXED / LOCAL PASS |
| S1-REV-04 | Closed HUD payload carried IDs but lacked item/entity labels/text and observation provenance. | S6 must hardcode/lookup catalog or keep mock data. | Embedded BE-produced build/slot/item/entity/parameter labels, display text, typed values, observed timestamp/source and audit provenance. | Before additional display fields were rejected and no render source existed. After `hud.partial.synthetic.json` renders Equipment/Compare entirely from the payload; missing labels/untyped numeric data fail validation. | FIXED / LOCAL PASS |
| S1-REV-05 | Null expected IDs in one snapshot shape ambiguously meant discovery and exact absence; reducer therefore rejected the BE's active character on a fresh FE connection. | HUD can remain empty although BE already has the playing character and selected Target. | Split `DISCOVER_ACTIVE_CONTEXT` from `RESYNC_KNOWN_CONTEXT`; accept discovery only with pending correlation/runtime/generation/revision guards, keep exact known-context resync and single-active-character transitions. | Before reviewer probe returned `REJECT_CONTEXT`. After schema→reducer discovery applies BOUND context; STARTUP/TARGET_ONLY activation, reidentification, reconnect, stale/wrong correlation/generation/Target/late vectors pass. | FIXED / LOCAL PASS |
| S1-REV-06 | `EQUAL` returned boolean false for incompatible typed values; Python can also treat `True == 1`. | Incomparable evidence became WARN/evaluable weight and incorrectly lowered score. | Return non-evaluable before equality when type or unit differs; compare value only after both match. | Before NUMBER 1 vs BOOLEAN true produced WARN/SCORED/evaluable=3. After NUMBER↔BOOLEAN/TEXT and unit mismatch are UNKNOWN/NO_DATA/evaluable=0; same type/unit unequal is WARN and equal is PASS. | FIXED / LOCAL PASS |
| D3 sync | Ledger still treated latency and OBS/Steam Link scope as Owner blockers. | Downstream work could wait unnecessarily or build a duplicate capture adapter. | Apply ASAP pipeline policy and reuse existing StreamOps `window_capture`; retain stage telemetry and downstream real-window verification. | Owner decision `6396082595`; repository source catalog/input reconciliation referenced, no production capture code changed. | RESOLVED / CONTRACT PASS |

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

The candidate.3 delta changes only versioned contracts, fixtures, documentation
and their model tests, so the already-established Windows-only A/B was not
repeated. Final affected validation: 32 passed, 0 failed, 0 skipped in 0.25s
(0.37s wall); `compileall` passed in 0.02s wall.

GitHub Actions were not queried, triggered or rerun (`CI_NOT_CHECKED`).
