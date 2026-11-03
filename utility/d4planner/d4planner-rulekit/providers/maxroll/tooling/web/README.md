# Local frozen Maxroll Web UI — #173

**Comprehensive acceptance:** See [COMPLETE-UI.md](COMPLETE-UI.md) for the selectable catalog audit, full HTTP/visual/negative tests and one-command offline acceptance runner. Earlier limited icon checks are not full UI acceptance.

**Current scope:** Native JSON download and import are supported. See [EXPORT.md](EXPORT.md) for the native Save workflow, format, security, tests and Android acceptance. This supersedes earlier export-out-of-scope notes.

This provider-owned tool renders the captured Planner directly in the client browser. It starts one loopback Node HTTP server; it does not start Chromium, VNC, a remote desktop, a capture job, or a network proxy. This checkpoint supports UI experimentation, native JSON downloads; canonical export and cloud Save remain unsupported. Changes may be lost when closing/reloading the tab.

See [independent UI capture and acceptance](UI-CHECKPOINT.md) for the current checkpoint: separate UI trust pins, complete capture tooling, visual references and HTTP browser tests. The calculation-bound configuration below remains supported for existing installations.

## Run

Prerequisites: Linux, Python 3 with `pidfd_open`/`pidfd_send_signal`, Node >=20, the existing browser-infra dependencies installed (`npm ci --ignore-scripts` in `../../../../browser-infra`), and an already provisioned, approved compatible private snapshot. Startup never downloads or captures. A separately authorized UI capture may select its own version using the explicit `uiTrust` configuration documented above.

Create a private JSON config outside Git, using the configured snapshot binding from Rule Kit:

```json
{
  "snapshotRoot": "/absolute/private/snapshot-store",
  "snapshotId": "<configured snapshot ID>",
  "manifestSha256": "<configured manifest SHA-256>",
  "port": 6085
}
```

Run from this directory:

```bash
python3 cli.py start --config /absolute/private/editor.json --ssh-target USER@LINUX_F
python3 cli.py status --config /absolute/private/editor.json
python3 cli.py stop --config /absolute/private/editor.json
```

Start verifies legacy calculation compatibility or explicit UI trust pins, and every snapshot blob, before listening, prints readiness and the tunnel command. Repeated start reuses this CLI's live process. Runtime state/logs are in a private sibling `editor.runtime/` directory. Occupied ports fail without signalling their owner. Stop uses Linux process identity plus pidfd and SIGTERM; it never kills unrelated workers. Foreground alternative: `node server.js --config /absolute/private/editor.json`, stop with Ctrl+C.

In **a local Termux shell on Android**, keep this running:

```bash
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -L 127.0.0.1:6085:127.0.0.1:6085 USER@LINUX_F
```

Open **http://127.0.0.1:6085/** in Android Chrome. Port numbers may differ on the two ends: URLs are mapped using the forwarded localhost Host. The public/production Maxroll URL is not the entrypoint. Keep Termux awake; closing the SSH process disconnects the page. Use a dedicated localhost port/origin for this tool.

## Manual Android acceptance

1. Open the localhost URL and confirm the frozen version displayed in Planner.
2. Click **New Profile**, change level/class, choose **Equipment → Helm → Runic Skullcap**, close the item dialog.
3. Under **Skills**, choose the List icon (label may be hidden on narrow screens), assign Puncture; confirm the point counter changes.
4. Under **Paragon**, select the node adjacent to Start; confirm the point counter changes.
5. Repeat with Chrome's Desktop site/landscape if the original mobile layout makes controls difficult to reach. This tool does not redesign the third-party UI.
6. Check the local diagnostics link for missing resources/blocked external attempts. Use the header Export JSON workflow described in EXPORT.md. Cloud POST is never sent to production. Do not enter Maxroll credentials or rely on Sign In/My Profiles cloud functionality.
7. Close the tab/tunnel. Stop the server when UAT is finished and verify status is STOPPED.

Real Android render, touch/input, and owner-network tunnel access remain manual gates. Chromium mobile emulation is supplementary evidence only.

## Tests

```bash
node --test server.test.js
LOCAL_EDITOR_CONFIG=/absolute/private/editor.json python3 lifecycle-check.py
LOCAL_EDITOR_URL=http://127.0.0.1:6085/ \
LOCAL_EDITOR_EVIDENCE=/absolute/private/evidence \
CHROMIUM_EXECUTABLE=/absolute/pinned/chrome node browser-check.js
```

`browser-check.js` uses a normal HTTP client browser, with no Playwright request routes and no browser offline mode. It tests desktop and Pixel 7 emulation, actual downloaded JSON, native import/export round-trips and external request enforcement. Evidence includes screenshots and native JSON; keep it private and outside Git/Actions artifacts. Tests do not claim canonical JSON compatibility.

See [architecture and audit](ASSESSMENT.md) for boundaries and limitations. No snapshot bytes or generated evidence belong in this directory.


## Diagnosing a blank frame on a real device

Reload the localhost page and wait 10 seconds. Diagnostics now include `clientEvents` with a per-load session ID: `CLIENT_BOOT`, `DOM_READY`, `PAGE_SHOW`, `JS_ERROR`, `UNHANDLED_REJECTION`, `CONSOLE_ERROR`, `RESOURCE_ERROR`, and parent `FRAME_STATE`. Parent reports include viewport/frame dimensions and New Profile presence even when child initialization fails. The CLI's private `editor.runtime/server.log` also receives these events. Report the time/browser used so F can find the right session. No remote debugging app or external telemetry endpoint is required.

Missing/blocked counters are cumulative **server totals**, not per-page error counts. Rendering a frame or finding a button does not establish visual/interactivity success. Preserve the failing session before restarting; a restart/reload that recovers the UI does not by itself establish root cause. Keep logs private; do not upload raw browser logs or generated screenshots to Git.

Additional targeted diagnostic/security test:

```bash
CHROMIUM_EXECUTABLE=/absolute/pinned/chrome node --test diagnostics.test.js
```
