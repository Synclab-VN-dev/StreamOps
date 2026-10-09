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

- No `INTERNET`, `SYSTEM_ALERT_WINDOW`, recording, storage or shell permissions.
- Service returns `false` on every KeyEvent path.
- UI retains the last 512 digital raw observations only in memory.
- No screen text, password, window content, joystick motion or speech collected.
- Foreground Android package name is shown only as diagnostic context; this
  APK does not inspect other apps' UI.
- Disable the Accessibility service when finished with the POC.

**Milestone 2** (C→A WebSocket, clock sync, EventStore) is gated on
Milestone 1 Real-C/Real-A PASS and belongs to follow-up implementation.
