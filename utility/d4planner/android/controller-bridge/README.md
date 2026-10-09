# D4Planner Android Controller Bridge — Milestone 1 / Issue #79

Read-only Android feasibility APK. The **only goal** is to answer whether
AccessibilityService can observe Xbox digital key input **while Steam Link
is foreground**, without changing Steam Link input delivery.

**This is not a LAN bridge yet.** There is no INTERNET permission, WebSocket,
A-side receiver, clock synchronization, input injection, root, or DB writer.
Only APK/local observation, instrumentation and human evidence are in scope.
The launcher app is labeled **XC - Xbox Input Capture**; the service remains
**Controller Bridge Key Observer** to preserve its existing Accessibility identity.

## Build

Requires JDK 17, Android SDK platform 35 and Gradle 8.9 (or CI artifact).

```powershell
.\scripts\d4planner\issue79\build-android.ps1
.\scripts\d4planner\issue79\install-android.ps1
```

Debug APK: `utility/d4planner/android/controller-bridge/app/build/outputs/apk/debug/app-debug.apk`.
GitHub Actions workflow `d4planner-android-bridge.yml` runs JVM unit tests
and publishes `issue79-controller-bridge-debug-apk` on PR builds.

## Enable the service on Android C

1. Pair the Xbox Wireless Controller to Android C (Bluetooth).
2. Open **Controller Bridge POC** and tap **Open Accessibility settings**.
3. Enable **Controller Bridge Key Observer** explicitly. On Android 13+,
   sideloaded APKs may require **App info → three-dot menu → Allow restricted
   settings** before Accessibility can be enabled. Availability varies by OEM.
4. Return to the APK. Confirm `serviceActive=true` and controller name,
   VID/PID/sources in **Controller candidates**.
5. With APK foreground, press digital controls and check raw event lines.
6. Keep Accessibility service enabled; switch to Steam Link. Connect to A,
   open Diablo IV, verify gameplay control, press buttons, then return to APK.
7. Tap **Copy evidence** and paste into a private evidence note;
   include the device model, Android version, Steam Link version and precise
   topology. This copy action is the ONLY evidence export in Milestone 1.

To isolate a new test: while XC is visible tap **Clear log** (the Accessibility
service remains active); confirm `clientSeqHighWatermark=0`, `ringDropped=0`
and no recent events. Then switch to Steam Link and press the controls.
Return to XC using touch (not the Xbox pad) to view the new events.
`foreground=...` on each raw line is the last window-state-change package
known at capture; it is diagnostic context, not a cryptographic proof of focus.
Clearing resets the local POC sequence; Milestone 2 requires a session epoch or
client instance identifier for cross-session deduplication.

Do not enable competing key-filter AccessibilityServices while testing:
Android only grants key-filter delivery to one requesting service at a time.

## ACK-before-forward experiment (optional)

This is an **additional gated POC**, not the production C→A EventStore integration.
XC keeps `KeyEvent.eventTime` as `sourceTimestampC` and
`SystemClock.uptimeMillis()` as `captureTimestampC` on **C**,
plus `sendTimestampC` from the same uptimeMillis clock when sending to A.
The A receiver records its own receive clocks separately. **Do not subtract
C timestamps from A monotonic/wall timestamps**; future clock normalization
still needs a dedicated C↔A sync protocol.

### Start isolated ACK receiver on Windows A

Open PowerShell in the StreamOps checkout on A and run:

```powershell
$env:XC_ACK_TOKEN = ([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N"))
$env:XC_ACK_TOKEN
python .\utility\d4planner\android\controller-bridge\ack_poc\ack_server.py --bind 192.168.1.8 --port 18795 --db "$env:LOCALAPPDATA\d4planner\state\xc-ack-poc.sqlite"
```

**Keep the token private** and copy its value to XC on C. The example prints
it deliberately only for local setup; do not paste the token into issues/logs.
If firewall blocks connections, allow inbound TCP 18795 from **C's LAN IP only**
during the test, then remove the firewall exception. Do not expose this HTTP
endpoint to the Internet. It uses shared-token authentication, no encryption
and no production hardening. The Python receiver logs no token.

### Configure XC on Android C

1. Ensure the Xbox controller is paired and AccessibilityService is active.
2. In XC set A LAN IPv4 to `192.168.1.8`, port `18795`, and paste the secret
   `XC_ACK_TOKEN` from A.
3. Start with **WAIT_ACK OFF** (OBSERVE_ONLY), save settings, clear log.
   Switch to Steam Link, test a few presses, return and copy evidence.
4. Turn **WAIT_ACK ON**, save, clear log, repeat the exact same buttons/steps.
   Inspect `Recent ACK gate decisions`:
   `COMMITTED` means A confirmed committed before XC returned `false`.
   `TIMEOUT_UNCONFIRMED`, `NETWORK_ERROR_UNCONFIRMED`,
   `HTTP_*_UNCONFIRMED`, `INVALID_CONFIG`, and
   `WORKER_BUSY_UNCONFIRMED` **do not provide the ordering guarantee**.
5. Repeat with A server stopped to check that Steam Link still works and
   XC logs fail-open. Turn WAIT_ACK OFF at the end and stop A receiver.

The callback has a **35 ms maximum wait on the Android service thread**, with
a separate single I/O worker and 15 ms socket connect/read timeouts. Network
I/O itself runs off the callback thread. There is no infinite retry, no
consuming/intercepting input, and always `return false`; if the A receiver
accepts an event *after* XC times out, the event is **UNCONFIRMED** on C even
if it appears in A's POC database later. This experiment can add latency or
cause stutter; disable WAIT_ACK immediately if gameplay is affected. Keep
testing short and controlled. **The 35 ms limit is a POC deadline, not a
performance acceptance threshold.**

A only sends `COMMITTED` once SQLite has finished the transaction using
`journal_mode=WAL` and `synchronous=FULL`; retries with the same
`(sessionId, clientSeq)` and identical payload return the prior receipt,
while sequence collisions with different payloads are rejected. XC rotates
`sessionId` when Clear Log resets the local sequence, so test runs do not
collide. The separate `xc-ack-poc.sqlite` is **not** `events.db`.

Check the receiver tests without an Android device:

```powershell
python -m unittest discover -s .\utility\d4planner\android\controller-bridge\ack_poc -p "test_*.py" -v
```

### Important limits

- The causal ordering guarantee holds only for **COMMITTED** responses and
  only for a game reaction resulting from the forwarded `KeyEvent`.
  It does not prove which subsequent speech belongs to which input.
- Steam Link may receive other controller input via joystick MotionEvents;
  those are **not** gated by XC's `onKeyEvent`.
- Android may time out key filtering; the experiment cannot override Android
  dispatch rules or guarantee order on network failure.
- C capture time is preserved even on timeout and all ACK states.
- Never log or share the token; the debug client stores it in app-private
  preferences and sends it as a cleartext LAN HTTP header.
- New GitHub debug APKs can have different signing keys. For
  `INSTALL_FAILED_UPDATE_INCOMPATIBLE`, uninstall XC only, reinstall and
  re-enable its AccessibilityService; Steam Link need not be uninstalled.

## Expected evidence

A sample line is `#582 tC=9876543 captureC=9876547 DOWN key=96 scan=304 repeat=0 device=7 src=0x401 Example pad`.

- `sourceTimestampC` is KeyEvent.eventTime (Android uptimeMillis clock).
- `captureTimestampC` is SystemClock.uptimeMillis at capture.
- `clientSeq` is monotonic *within one APK process*, restarting on process death.
- `deviceId` is only stable within a running Android input configuration.
- `ringDropped` counts evictions from the last 512 buffered events, NOT
  necessarily OS dispatch loss. History is intentionally nonpersistent.
- `REPEAT` means repeated DOWN with repeatCount greater than zero.
- Raw keyCodes/scanCodes are evidence, **not** Xbox semantic mapping.
- Service emits no events when Android does not dispatch them to the callback;
  absence cannot be fixed by polling this UI.
- Background screen refresh only happens in MainActivity; service holds events
  in process memory while Steam Link is foreground. The service is not stopped
  when the UI goes into the background. Android may still kill the process;
  records are not persisted to disk in this feasibility POC.

## Feasibility gate

Record for **A, B, X, Y, LB, RB, LS, RS, VIEW, MENU,
DPAD_UP, DPAD_DOWN, DPAD_LEFT, DPAD_RIGHT**:
foreground APK result; Steam Link foreground result; raw keyCode/scanCode
or `NO_EVENT`; DOWN/UP count; game behavior; cursor/input-mode side effects.

Gate outcomes:
- `PASS_FULL`: Steam Link operates normally AND all 14 controls yield distinct
  reliable DOWN/UP on C with no interference.
- `PASS_PARTIAL`: simultaneous capture works for some but not all controls.
  Document unobservable controls; do NOT mark the ticket done.
- `NO_EVENTS`: gameplay works but Bridge receives no background key events.
- `INPUT_INTERFERENCE`: gameplay breaks, loses events, stutters, or cursor blinks.

If any capture path would require root, Steam Link hook, injection or
motion interception, STOP and report evidence. **Do not enable**
`AccessibilityService.onMotionEvent` interception as a workaround: it may
prevent forwarding MotionEvents to Steam Link. Some DPAD input can be emitted
as joystick hat axes instead of KeyEvents; such devices may be partial/NO-GO.

## Privacy and safety

- `INTERNET` permission is used only when WAIT_ACK is explicitly ON; no
  `SYSTEM_ALERT_WINDOW`, recording, storage or shell permissions.
- Service returns `false` on every KeyEvent path.
- UI retains the last 512 digital raw observations only in memory.
- No screen text, password, window content, joystick motion or speech collected.
- Foreground Android package name is shown only as diagnostic context; this
  APK does not inspect other apps' UI.
- Disable the Accessibility service when finished with the POC.

**Milestone 2** (C→A WebSocket, clock sync, EventStore) is gated on
Milestone 1 Real-C/Real-A PASS and belongs to follow-up implementation.
