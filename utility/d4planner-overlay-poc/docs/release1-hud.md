# D4Planner Release 1 Equipment HUD (#143)

This package is the native Tauri presentation layer for the S1 HUD contract.
React renders only committed backend fields. It does not score Equipment, parse
Target files, read SQLite, resolve Maxroll identifiers, poll REST, or substitute
sample data when the backend WebSocket is unavailable.

## Data-source boundary

S5 installs an `IHudDataSource` at `window.__D4PLANNER_HUD_DATA_SOURCE__` before
React mounts. The source supplies authoritative snapshots, target lists, and
ID/hash selection results. Without it, production renders a disconnected state;
there is deliberately no demo fallback.

Target entries marked invalid are disabled. A valid selection sends only
`targetId` and its listed SHA-256. The old target remains labeled as the old
target until the server acknowledges and a matching authoritative snapshot
arrives. Rejection never relabels an old score. Same-generation snapshots below
the HUD revision high-water mark are ignored.

The UI displays backend score, FAIL issue count, WARN count, item x/y,
Equipment rows, typed Current/Target values, reasons and recommendation.
`NO_DATA` is rendered as `—`, distinct from a valid zero. Coverage metadata is
not rendered. Charms, Skills, Paragon and Torment are absent.

## Native behavior

The window is frameless, transparent, fixed-size and always-on-top. Panel state
sets a bounded logical extent (280–900 by 220–640) so transparent space does not
create a large interactive rectangle. Logical sizing lets Tauri apply the
monitor DPI scale; physical position is clamped to the current monitor after a
resize. Click-through remains recoverable through the existing global shortcut,
and safe exit remains `Ctrl+Shift+F11`. Pin only reconciles always-on-top and
cannot disable it in Release 1.

Physical in-game, mixed-DPI and `window_capture` verification remains MAN/S7.

## MagicPath reference gate

The checked-in Golden was retrieved read-only from MagicPath production:

- Project `458763473602621440`
- Component `458765764401446912`
- Revision `464988421014827008`
- Preview SHA-256 `8d0ad5dc6710b208884254479f6be8929a47dfcec73757a5c77103124088d86c`

`tests/visual/golden/manifest.json` pins the exported preview bytes and records
the code-context revision identity independently from product source. The stored preview covers the approved expanded summary/Equipment
baseline only. MagicPath did not expose independent rendered Goldens for the
selector-open, partial, NO_DATA, invalid-target, or disconnected states. Those
visual cases remain **BLOCKED**; product screenshots are not used as expected
images, and no threshold or mask is introduced.
