# S5 D5 notification and managed command transport

Contract: d4planner-r1-contract/1.0.0-candidate.6, issue #138.

`transport/core.py::HudHub` stores DB identity/epoch/revision metadata and fans
out bounded coalescing notifications. `D4PlannerWebSocketServer` remains the
loopback authenticated server; FE connects by URL. Only d4planner-notify/v1
hello/hello.accepted/hud.committed/error messages cross WS. No full HUD,
Target listing, selection commands or snapshots cross this boundary.

`ProductionBackendRuntime` publishes only after SQLite commits. Lost, duplicate
or reordered notifications cause no rollback: native FE rereads latest committed
SQLite on startup, reconnect, resume, notification and explicit refresh.

Target listing and selection use d4planner-control/v1 on the existing owned
stdin/stdout channel: Tauri → BackendProcessWrapper → managed_backend.py →
ProductionBackendRuntime.handle_control(). Rust dispatches correlated responses
instead of draining them; owner/child/generation must match. Pending commands
are bounded to 32 and timeout independently of worker/session lifetime. A timed-out
selection may have committed, so FE rereads DB before another attempt. Shutdown
and parent death retain existing owned-process cleanup. No second Python service.

Target validation rechecks exact bytes/hash/list revision. Selection journal
recovery preserves the existing active Target after commit failure and retains
a successful commit even if notification publication fails. D1–D4 scoring and
Rule Kit Application/Snapshot Management contracts are unchanged.

Local checks: Python test_realtime_transport.py, test_production_backend.py,
test_snapshot_backend.py; Rust lifecycle-tests includes real managed-process
request/response, timeout and foreign-generation rejection. Synthetic fixtures
are not Windows-native or live Diablo evidence. No periodic data polling.
