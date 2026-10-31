# D5 public SQLite and managed control contract

Revision: `d4planner-r1-contract/1.0.0-candidate.6`. Authority: #138 D5,
2026-10-31. Supersedes full-HUD `d4planner-ws/v1`; no dual wire mode.

## Discovery and ownership

Launcher supplies an absolute `D4PLANNER_DATA_DIR` to native FE independently
of bootstrap, credentials, Python, Node and Chromium. DB is exactly
`DataDir/hud.sqlite3`. Native code accepts no renderer-provided SQL/path.
Missing configuration is `CONFIGURATION_MISSING`, not permission to search cwd.
Viewer mode never starts BE to read DB. Integrated mode may start the existing
BackendProcessWrapper, but failure cannot abort FE startup. Native reader owns
no migrations, directory creation, writer connection or capture-DB access.

## Public projection

`hud-db.sql` defines the only stable SQL surface. All other tables are private.
`hud_public_meta` contains exactly one row, with format `d4planner-hud-db/v1`,
UUID DB identity and UUID epoch. `hud_current` has zero or one row with a
nonnegative monotonic revision and JSON conforming to `hud.schema.json`.
The decoded read result follows `hud-db.schema.json`; row revision must equal
payload revision. Character/Target/selection/hash/policy binding must agree
with context and assessment. NO_DATA differs from score zero. D1–D4 unchanged.

BE is the single writer. `BEGIN IMMEDIATE` serializes mutation; selected Target,
assessment binding and public projection become visible in one commit. Computation
for superseded bindings cannot commit. Raw capture is stored separately.
Publish only after successful COMMIT. A publish failure does not undo the commit;
readers recover latest state independently. Context switches invalidate old score
in the same projection, never relabel a prior score with a new Target.

DB identity/epoch survives BE restart and additive schema migrations. New DB gets
new identity. A supported restore/replacement operation assigns a new epoch
before serving writes, preserving content; FE also detects same-identity revision
regression as `REVISION_REGRESSION` and does not silently roll back. Backend
instance/generation is provenance, never authority to reset DB high-water.

Reader opens SQLite READ_ONLY, `query_only=ON`, bounded busy timeout, and one
read transaction covering metadata and current row. No `immutable=1` on live WAL.
Close connection after read so file replacement is detected on next event.
Incompatible format/schema, malformed JSON or binding returns typed error; no
partial score. Missing DB/row yields NO_DATA. BUSY/LOCKED is retryable on the next
explicit refresh/notification, with retained data marked STALE. Corrupt/unreadable
DB never triggers deletion, creation or migration from FE. No periodic polling.

Writer migration is transactional, validates version before mutation and rejects
newer versions. Existing v2 private HUD stores acquire public metadata without
losing history, Targets, settings or revision. Older readers reject an incompatible
public format. Upgrade/rollback preserves DB; never delete it to make startup pass.

## Notification-only WebSocket

`d4planner-notify/v1` accepts `hello` with credential and allowed native origin.
Server replies correlated `hello.accepted`, establishes bounded subscription and
sends latest `hud.committed` metadata. Events contain only kind, message ID,
DB ID, epoch, committed revision and protocol version. No Equipment, score,
Target lists, Target commands or full HUD payload. Unsupported messages fail
closed. Loopback URL, origin/auth, frame limits, backpressure remain mandatory.

Notification is a hint, not authority. Startup, reconnect, resume, manual refresh
and each notification read latest SQLite. Duplicate/out-of-order hints cannot
roll back data; lost intermediate revisions require no replay. Native/React read
requests must be serialized/coalesced or fenced so a late read cannot overwrite
a newer accepted read. Identity/epoch change invalidates old high-water and binding;
same identity/epoch preserves high-water even across BE restart. Offline last-known
is OFFLINE/STALE regardless of stored CURRENT. CURRENT requires online matching
producer identity/generation and valid current binding.

## Commands on the existing managed process pipe

`command.schema.json` defines `d4planner-control/v1`. Native wrapper supplies
requestId, ownerInstanceId, childInstanceId and generation from its owned READY
child. Renderer supplies only allowlisted method and parameters. `target.list`
returns safe entries/listRevision/folder status. `target.select` supplies targetId,
expectedSha256 and expectedListRevision; BE revalidates exact bytes and commits
selection plus public HUD before success. Result does not carry HUD; FE rereads DB.
Errors preserve active binding and report stable code/message/retryable fields.

Flow: Tauri → BackendProcessWrapper → private JSON-lines stdin/stdout →
managed_backend.py → ProductionBackendRuntime.handle_control(). No second Python
entrypoint, HTTP endpoint, WS business command, or SQLite command write.

READY/EXIT/lifecycle messages remain on that pipe. Dispatcher routes responses by
correlation and all three ownership fields; unmatched/late responses cannot settle
new requests. Bound line size 1 MiB, at most 32 pending commands, default deadline
10 seconds (finite deployment override). Invalid owner/generation, malformed params,
unknown method, offline/crashed child and queue exhaustion fail explicitly.
Deadline expiry removes pending waiter; it does not kill worker/session. A timed-out
selection may have committed, so FE refreshes DB and lists again before retrying;
never promise rollback/exactly-once. Shutdown fails all pending requests and waits
for owned child cleanup. Credentials never appear in argv/logs/public artifacts.
