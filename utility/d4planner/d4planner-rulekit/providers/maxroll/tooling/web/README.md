# Local frozen Maxroll Web UI — #173

This provider-owned tool renders the captured Planner directly in the client browser. It starts one loopback Node HTTP server; it does not start Chromium, VNC, a remote desktop, a capture job, or a network proxy. This checkpoint supports UI experimentation, not canonical export or durable native Save. Changes may be lost when closing/reloading the tab.

## Run

Prerequisites: Linux, Python 3 with `pidfd_open`/`pidfd_send_signal`, Node >=20, the existing browser-infra dependencies installed (`npm ci --ignore-scripts` in `../../../../browser-infra`), and an already provisioned, approved compatible private snapshot. Do not download/capture another version to satisfy startup.

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

Start verifies compatibility and every snapshot blob before listening, prints readiness and the tunnel command. Repeated start reuses this CLI's live process. Runtime state/logs are in a private sibling `editor.runtime/` directory. Occupied ports fail without signalling their owner. Stop uses Linux process identity plus pidfd and SIGTERM; it never kills unrelated workers. Foreground alternative: `node server.js --config /absolute/private/editor.json`, stop with Ctrl+C.

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
6. Check the local diagnostics link for missing resources/blocked external attempts. Save/export is unavailable: native POST is rejected locally with 405 and never sent to production. Do not enter Maxroll credentials or rely on Sign In/My Profiles cloud functionality.
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

`browser-check.js` uses a normal HTTP client browser, with no Playwright request routes and no browser offline mode. It tests desktop and Pixel 7 emulation, edits a real build, checks the native Save payload, asserts local rejection, and checks every external request attempt fails due to CSP. Evidence includes screenshots and native JSON; keep it private and outside Git/Actions artifacts. Tests do not claim canonical JSON compatibility.

See [architecture and audit](ASSESSMENT.md) for boundaries and limitations. No snapshot bytes or generated evidence belong in this directory.
