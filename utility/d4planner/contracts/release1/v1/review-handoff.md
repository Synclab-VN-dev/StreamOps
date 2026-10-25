# S1 review correction handoff

- Reviewed HEAD: `b6c7c901f8474414c78e895aa1176cf962e865e9`
- Regression base: `010e563daee0e037695aa506d160eedcf60ab43d`
- Corrected contract: `d4planner-r1-contract/1.0.0-candidate.2`
- Scope: schema/interfaces/docs/fixtures/contract-model tests only

| Finding | Root cause | Impact tới user nếu không sửa | Fix | Before/after evidence | Status |
| --- | --- | --- | --- | --- | --- |
| S1-REV-01 | HUD required non-null Target/character/binding even before those existed. | FE must invent IDs or cannot render normal startup; stale score can survive context loss. | Closed context union for STARTUP/TARGET_ONLY/CHARACTER_ONLY/BOUND/TARGET_UNAVAILABLE; atomic invalidation and selection-failure rules. | Before: reviewer could not validate null Target/character. After: five schema fixtures plus startup→target→character→equipment, target deletion and character-change tests. | FIXED / LOCAL PASS |
| S1-REV-02 | Snapshot and incremental update shared one predecessor rule; same-generation snapshot after a gap was rejected again. | HUD can remain stale through reconnect/resync until BE restarts. | Correlated authoritative snapshots use minimum revision/context anti-stale checks; updates retain strict predecessor/subscription rules. | Before probe: generation 3/rev 10 + snapshot rev 13 → RESYNC_GAP. After vectors: gap → same-generation snapshot 13 → update 14, reconnect/equal revision, stale/wrong/late/new-generation cases. | FIXED / LOCAL PASS |
| S1-REV-03 | Numeric comparators accepted string/bool, ranges were not semantically ordered, and criterion identity could not address occurrence/parameter. | Invalid Target or partial multi-value comparison can produce misleading score/issues. | Typed operands/comparator unions, source group+occurrence, stable parameter ID/index and `ALL` aggregation; semantic range/link/duplicate guards; raw-value vectors. | Before reviewer probes accepted `"not-a-number"`/`true` and rejected useful multi-value shape. After schema rejects wrong type/unit, semantic tests reject malformed range/missing/duplicate parameter and accept distinct occurrence/multi-parameter. | FIXED / LOCAL PASS |
| S1-REV-04 | Closed HUD payload carried IDs but lacked item/entity labels/text and observation provenance. | S6 must hardcode/lookup catalog or keep mock data. | Embedded BE-produced build/slot/item/entity/parameter labels, display text, typed values, observed timestamp/source and audit provenance. | Before additional display fields were rejected and no render source existed. After `hud.partial.synthetic.json` renders Equipment/Compare entirely from the payload; missing labels/untyped numeric data fail validation. | FIXED / LOCAL PASS |

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

GitHub Actions were not queried, triggered or rerun (`CI_NOT_CHECKED`).
