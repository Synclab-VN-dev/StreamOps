# D4Planner D5 Equipment HUD (#151 / S6)

Tauri `hud_reader.rs` opens `D4PLANNER_DATA_DIR/hud.sqlite3` read-only/query-only
with a bounded busy timeout and one consistent transaction. It validates the
public format, HUD JSON schema, row/payload revision and context binding.
It never creates, migrates or writes DB and never reads capture tables.

`TauriHudDataSource` reads native SQLite before attempting WS bootstrap. Startup,
reconnect, resume, notification and manual refresh reread authoritative DB.
Reads are serialized/coalesced; DB identity/epoch owns the revision high-water.
Backend instance/generation changes cannot reset it. Missing DB gives NO_DATA;
incompatible/corrupt data fails closed; a busy DB retains last-known stale data.

Viewer mode opens without BE, Node, Chromium, credentials or WS. Valid persisted
score and Equipment remain visible as last-known/OFFLINE/STALE; stored CURRENT
is not proof of live capture. The data source never starts/restarts BE merely to
view data. Integrated mode uses the existing native process wrapper.

Target list/select invokes `backend_command`; Rust sends correlated requests on
the same managed stdin/stdout pipe. WS sends only DB identity/epoch/revision
notifications. No scoring, Target parsing, catalog resolution or DB access in React.
Selection acknowledgement alone cannot relabel a prior score; the committed
matching SQLite snapshot is authoritative. A timeout still triggers reread.

Presentation remains the approved MagicPath project 458763473602621440,
component 458765764401446912, revision 464988421014827008: Equipment/Compare,
Target menu, no Charms/Coverage, Pin means always-on-top. NO_DATA differs from zero;
FAIL issues and WARN counts stay separate. No production actual is used as Golden.
Independent visual Golden, Owner MAN and real StreamOps window capture are separate
gates; unit/DOM tests and synthetic native data are not evidence of those gates.

Create Build adds an internal native/BE/Rule Kit control action. The existing Golden
above remains the approved baseline. Owner-selected v15 revision 468645150797758464
is the menu implementation reference; Visual Golden remains BLOCKED_OWNER_APPROVAL.
See [Planner architecture and gates](create-build-local-planner.md).

Local verification: `npm test`, `npm run build`; `cargo test --manifest-path
reader-tests/Cargo.toml` exercises production native reader without GUI dependencies.
The Windows reader test executable can also run in the isolated F2 VM. Full native
Tauri and root launcher builds are tested separately; Linux GTK dependency failures
are recorded distinctly from Windows cross-build and Windows-native execution.

## v18 Current workspace

MagicPath revision `471134434381406208` adds a default Current workspace alongside
Compare. Production omits preview scenario controls and sample character/items.
BE reads the capture producer's `state/character.db` projection in a consistent
read-only transaction and decorates the existing `state/hud.sqlite3` snapshot with
optional `currentEquipment`. Existing Compare bindings and scoring are unchanged.
No item payload crosses WebSocket; startup/reconnect/notification still rereads
`hud_current` through Tauri. Legacy snapshots without the additive field remain
readable and can show their observed item names with unavailable details omitted.

The capture producer exposes a durable revision, not a change-notification API.
The managed BE refreshes its display projection every 250 ms (1 s after source
failure), commits only changed views and then sends the existing notification.
Configured repository/scoring sources attach Current in their existing ingest
transaction instead of starting a second watcher. There is no renderer polling.
Persisted Current is retained across source failure and startup. It is not proof
of live capture; offline, unavailable capture and stopped runtime show last-known.

`equipment_current` has no verified character ownership. Current explicitly says
identity unverified, including for real equipment copied from a user's capture.
Unresolved rings are not assigned to Ring 1/2. The producer deletes empty-slot
rows without persisting absence evidence: a missing row remains Not observed,
never Confirmed empty. These limits are not bypassed by sample data or inference.
