# Runtime Manager (MagicPath v16)

Implementation reference: MagicPath production project `458763473602621440`,
component `458765764401446912`, revision `470699439103832064` (v16).
The existing Equipment Golden remains historical; it is not a Golden for this
new interaction. No MagicPath canvas content is changed by this implementation.

Open **HUD menu → Runtime Manager** even when no character/Target is available.
The modal uses native `get_backend_status` plus the authenticated, generation-bound
Backend pipe. `runtime.status` and `capture.start/stop/restart` accept empty params
only; the UI cannot supply a PID, executable, command line or data directory.
Backend lifecycle runs off the WebView thread and serializes with capture controls.
Start after an exited/failed Backend rotates the bootstrap generation. Explicit
service changes reset transport reconnect attempts; transport recovery never
starts a manually stopped Backend.

Stop/Restart require confirmation. Start/Retry spawn only a managed capture child,
using BLOCK/silent mode and the supported xbox16 profile. Capture Stop persists
`{"manualPause":true}` in `<DataRoot>/state/capture-preferences.json` atomically.
This survives Backend/HUD restart; explicit Start/Retry clears it. Invalid or
unreadable preferences block automatic capture startup until explicit Start.
Backend shutdown does not change that preference. A failed cleanup retains the
owned handle and blocks replacement. Controls never stop NVDA, Steam or Diablo IV.
The existing launcher job policy on exiting the entire HUD is unchanged.

Status accepts runtime.json only for the current capture owner token and PID.
A dead child wins over stale RUNNING state. Each retry gets a fresh token.
Dependencies are timestamped observations, not an independent process scan.
Speech count is the number of durably committed speech.raw events during this
capture lifetime; it resets on restart. Last capture event may be speech or input.
An observed controller marker does not claim physical layout verification.
NVDA DataRoot receipt validation checks root, PID and timestamp against the
owned runtime's NVDA observation. Missing evidence is Unavailable/Unknown.
No token, capture text or private receipt contents are sent to React.

View / Collect Logs opens the existing Support panel; opening it does not submit
an issue or upload logs. Manual runtime controls do not modify Targets or Rule Kit
configuration. Capture itself retains its normal event/equipment persistence.
