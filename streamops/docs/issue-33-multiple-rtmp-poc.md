# Issue #33 — Multiple RTMP Outputs installation/lifecycle POC

This Gate 1 implementation adds a StreamOps backend lifecycle boundary for one
allowlisted OBS plugin. It does not create an RTMP destination, start a stream,
add multistream runtime behavior, or add Web UI controls.

Runtime dependency direction is `api/obs_plugins.py -> services/obs_plugin.py
-> platform/windows/obs_plugin/host.py -> installer.py -> Windows APIs,
filesystem, and upstream network`. The installer and pinned manifest ship in
the wheel; the node never resolves the source checkout or root `scripts/`.

## Pinned upstream package

- Release: `sorayuki/obs-multi-rtmp` tag `0.7.4.3` (published as “for OBS 32.2.1”)
- Package version embedded in the artifact: `0.7.4.0`
- Artifact: `obs-multi-rtmp-0.7.4.0-windows-x64.zip`
- SHA-256: `5fc2a14a4222cef914d4703325853b1f97247abe76bbd1fccd0dbd40831affe5`
- Source: <https://github.com/sorayuki/obs-multi-rtmp/releases/tag/0.7.4.3>

The upstream EXE installer is intentionally not used. Its NSIS uninstall path
recursively removes the shared `C:\ProgramData\obs-studio\plugins` directory.
The pinned ZIP permits an allowlisted, plugin-specific install and rollback.

## Backend API

The API accepts no body or query parameters and never accepts a URL, path,
command, or binary from a caller:

```text
GET  /api/v1/obs/plugins/obs-multi-rtmp
POST /api/v1/obs/plugins/obs-multi-rtmp/install
POST /api/v1/obs/plugins/obs-multi-rtmp/verify
POST /api/v1/obs/plugins/obs-multi-rtmp/rollback
```

`ObsPluginService` owns the safety checks and OBS stop/start/readiness flow;
`WindowsObsMultiRtmpHost` delegates to the packaged Python installer and its
packaged manifest. Install and rollback are rejected while OBS is streaming or
recording. `LOADED` requires an exact file manifest, current-process OBS log
evidence for plugin version `0.7.4.0`, OBS `READY`, and a connected WebSocket.

Example operator acceptance (the same calls later used by Web UI):

```powershell
$base = "http://127.0.0.1:8765/api/v1/obs/plugins/obs-multi-rtmp"
Invoke-RestMethod $base
Invoke-RestMethod -Method Post "$base/install"
Invoke-RestMethod -Method Post "$base/verify"
Invoke-RestMethod -Method Post "$base/rollback"
Invoke-RestMethod -Method Post "$base/install"
Invoke-RestMethod -Method Post "$base/verify"
```

## Host-layer installer

All download, artifact validation, installation, inspection, verification, and
rollback code is shipped inside the `streamops` wheel. The API is the runtime
entry point. PowerShell remains only as operator bootstrap for one-time ACL
provisioning; the server never launches it.

CI builds the wheel, installs it into a clean virtual environment under a
temporary directory outside the checkout, starts the installed server, and
checks health, plugin status schema, and packaged manifest resolution.

The install root is:

```text
C:\ProgramData\obs-studio\plugins\obs-multi-rtmp\
├── bin\64bit\obs-multi-rtmp.dll
├── bin\64bit\obs-multi-rtmp.pdb
└── data\locale\*.ini                (71 files)
```

The exact locale basenames in the pinned archive are:

```text
an-ES ar-AR ar-SA az-AZ ba-RU be-BY bem-ZM bg-BG bn-BD ca-ES cs-CZ
da-DK de-DE el-GR en-GB en-US eo-UY es-ES et-EE eu-ES fa-IR fi-FI
fil-PH fr-FR gd-GB gl-ES he-IL hi-IN hr-HR hu-HU hy-AM id-ID it-IT
ja-JP ka-GE kab-KAB kmr-TR ko-KR lo-LA lt-LT lv-LV mn-MN ms-MY
nb-NO nl-NL nn-NO oc-FR pa-IN pl-PL pt-BR pt-PT ro-RO ru-RU si-LK
sk-SK sl-SI sq-AL sr-CS sr-SP sv-SE szl-PL ta-IN te-IN th-TH tl-PH
tr-TR uk-UA ur-PK vi-VN zh-CN zh-TW
```

Each basename above is installed as `data\locale\<basename>.ini`; together
with the DLL and PDB this is the complete 73-file manifest.

The limited interactive node account receives `Modify` only on this allowlisted
plugin root. Provision it explicitly once from an elevated deployment prompt;
the command does not trigger UAC itself:

```powershell
pwsh -NoProfile -File .\scripts\devices\a-windows\install-streamops-node.ps1 `
  -ConfigureObsPluginLifecycle
```

If this provisioning is absent, the API returns HTTP 403 with
`plugin_install_permission_denied`; it never opens a hidden UAC prompt.

The script downloads only the pinned GitHub release artifact, verifies its
SHA-256 and 73-entry allowlist, and records ignored transaction evidence under
`.streamops\issue-33`. It never reads OBS service settings or prints an OBS
WebSocket password, RTMP URL, stream key, or token.

## Uninstall and rollback

Rollback is invoked through the API and OBS lifecycle is orchestrated by
`ObsPluginService`.

Rollback removes only manifest-owned files whose hashes still match. It leaves
the allowlisted root empty so its narrow ACL survives; an empty root is reported
as `NOT_INSTALLED`. It restores pre-install contents when they were backed up. A newly created
`obs-multi-rtmp.json` is removed only when it was absent at baseline and contains
no targets or encoder configuration; OBS profiles and scene collections are
never removed. Do not invoke the upstream EXE as an uninstaller.

## OBS WebSocket boundary

OBS WebSocket 5.x has no plugin-install request. Runtime investigation uses
`GetVersion.availableRequests` to confirm that `InstallPlugin` is absent. Plugin
installation therefore remains a Windows host-layer operation; StreamOps is
used only for its existing safe OBS stop/start/readiness lifecycle.

## Machine-A acceptance result

Lower-layer acceptance before the package refactor ran on 2026-10-04 (Asia/Ho_Chi_Minh) against Windows 10 Pro build 19045. Package refactor acceptance is recorded in the PR review update.

| Check | Observed result |
| --- | --- |
| Baseline | OBS 32.2.1 / obs-websocket 5.7.4; StreamOps `READY`; streaming and recording false; current scene `StreamOps Scene 3bcd93ee-ad1a-4f31-9ec0-87f5eba72c9a`. |
| Pre-install runtime | Existing StreamOps start flow reached `READY`; OBS WebSocket 5.7.4 connected; streaming and recording were false. |
| WebSocket boundary | `GetVersion` returned 151 available requests and no `InstallPlugin`. No plugin-install WebSocket request was implemented or attempted. |
| API contract | GET status and POST install/verify/rollback returned only the safe public schema. Client-supplied bodies and query parameters are rejected. |
| Install | API fresh install stopped OBS, validated the pinned ZIP hash and 73-entry allowlist, installed under `C:\ProgramData\obs-studio\plugins\obs-multi-rtmp`, restarted OBS, and returned `LOADED`. Repeated API installs returned `already_installed` without a restart. |
| Plugin load | OBS log `2026-10-04 10-37-21.txt` reports `[obs-multi-rtmp] version: 0.7.4.0 by SoraYuki`; module enumeration contains `obs-multi-rtmp.dll`. |
| UI | The OBS **Docks** menu in the interactive desktop contains **Multiple output**, matching the upstream implementation. |
| Rollback | API rollback removed only the 73 manifest-owned files and returned `NOT_INSTALLED`; API verify then failed closed with `plugin_verify_failed`. API reinstall reproduced `LOADED`. |
| OBS state preservation | All 18 scene-collection JSON files matched their pre-install length and SHA-256 after rollback/reinstall. Active profile and collection remained `Untitled`; current program scene remained `StreamOps Scene 3bcd93ee-ad1a-4f31-9ec0-87f5eba72c9a` (8 scenes). |
| Permission behavior | Before the narrow ACL was provisioned, API rollback returned `plugin_install_permission_denied` (HTTP 403) and restored OBS to READY. No UAC prompt was attempted. |
| Final runtime | StreamOps reports `READY`; WebSocket connected; OBS 32.2.1 / obs-websocket 5.7.4; plugin `LOADED`; streaming and recording false; current scene unchanged. |
| Tests | Windows A final clean run: `316 passed, 85 warnings` in 72.39 seconds. The warnings are existing WebSocket client deprecation warnings. |

The existing OBS graceful-close flow was hardened to ignore transient Qt popup,
tooltip, and drop-shadow windows, so lifecycle calls target an OBS top-level
window rather than a menu popup.

Generated logs, the Docks-menu screenshot, transactions, backups, and sanitized
JSON evidence remain ignored under `.streamops\issue-33`; no credential or
service-setting content is committed. Backend Gate 1 acceptance result: **PASS**.
