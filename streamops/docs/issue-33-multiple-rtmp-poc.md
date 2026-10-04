# Issue #33 — Multiple RTMP Outputs installation/lifecycle POC

This POC installs only the OBS plugin on Windows host A. It does not create an
RTMP destination, start a stream, or add multistream behavior to StreamOps.

## Pinned upstream package

- Release: `sorayuki/obs-multi-rtmp` tag `0.7.4.3` (published as “for OBS 32.2.1”)
- Package version embedded in the artifact: `0.7.4.0`
- Artifact: `obs-multi-rtmp-0.7.4.0-windows-x64.zip`
- SHA-256: `5fc2a14a4222cef914d4703325853b1f97247abe76bbd1fccd0dbd40831affe5`
- Source: <https://github.com/sorayuki/obs-multi-rtmp/releases/tag/0.7.4.3>

The upstream EXE installer is intentionally not used. Its NSIS uninstall path
recursively removes the shared `C:\ProgramData\obs-studio\plugins` directory.
The pinned ZIP permits an allowlisted, plugin-specific install and rollback.

## Host-layer commands

Run these commands from a PowerShell 7 prompt in the repository on A. OBS must
be stopped through StreamOps before `Install` or `Rollback`.

```powershell
pwsh -NoProfile -File .\scripts\devices\a-windows\manage-obs-multi-rtmp.ps1 -Action Inspect
pwsh -NoProfile -File .\scripts\devices\a-windows\manage-obs-multi-rtmp.ps1 -Action Install -WhatIf
pwsh -NoProfile -File .\scripts\devices\a-windows\manage-obs-multi-rtmp.ps1 -Action Install -Confirm:$false
pwsh -NoProfile -File .\scripts\devices\a-windows\manage-obs-multi-rtmp.ps1 -Action Verify
```

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

The script downloads only the pinned GitHub release artifact, verifies its
SHA-256 and 73-entry allowlist, and records ignored transaction evidence under
`.streamops\issue-33`. It never reads OBS service settings or prints an OBS
WebSocket password, RTMP URL, stream key, or token.

## Uninstall and rollback

Inspect the exact rollback first, then apply it while OBS is stopped:

```powershell
pwsh -NoProfile -File .\scripts\devices\a-windows\manage-obs-multi-rtmp.ps1 -Action Rollback -WhatIf
pwsh -NoProfile -File .\scripts\devices\a-windows\manage-obs-multi-rtmp.ps1 -Action Rollback -Confirm:$false
```

Rollback removes only manifest-owned files whose hashes still match. It restores
the pre-install plugin directory when one was backed up. A newly created
`obs-multi-rtmp.json` is removed only when it was absent at baseline and contains
no targets or encoder configuration; OBS profiles and scene collections are
never removed. Do not invoke the upstream EXE as an uninstaller.

## OBS WebSocket boundary

OBS WebSocket 5.x has no plugin-install request. Runtime investigation uses
`GetVersion.availableRequests` to confirm that `InstallPlugin` is absent. Plugin
installation therefore remains a Windows host-layer operation; StreamOps is
used only for its existing safe OBS stop/start/readiness lifecycle.

## Machine-A acceptance result

Run on 2026-10-04 (Asia/Ho_Chi_Minh) against Windows 10 Pro build 19045.

| Check | Observed result |
| --- | --- |
| Baseline | OBS 32.2.1 was stopped; no plugin files or `obs-multi-rtmp.json` existed. StreamOps node had stale runtime state and was safely restarted with its existing script before the OBS lifecycle test. |
| Pre-install runtime | Existing StreamOps start flow reached `READY`; OBS WebSocket 5.7.4 connected; streaming and recording were false. |
| WebSocket boundary | `GetVersion` returned 151 available requests and no `InstallPlugin`. No plugin-install WebSocket request was implemented or attempted. |
| Install | Pinned ZIP hash and 73-entry allowlist passed. Files were installed under `C:\ProgramData\obs-studio\plugins\obs-multi-rtmp`. A second apply returned `already_installed`. |
| Plugin load | OBS log `2026-10-04 10-37-21.txt` reports `[obs-multi-rtmp] version: 0.7.4.0 by SoraYuki`; module enumeration contains `obs-multi-rtmp.dll`. |
| UI | The OBS **Docks** menu in the interactive desktop contains **Multiple output**, matching the upstream implementation. |
| Rollback | Dry-run was inspected, then real rollback removed only the 73 manifest-owned files and the new empty plugin profile config. Reinstall reproduced the same 73-file state. No pre-existing plugin backup was needed. |
| OBS state preservation | All 18 scene-collection JSON files matched their pre-install length and SHA-256 after rollback/reinstall. Active profile and collection remained `Untitled`; current program scene remained `StreamOps Scene 3bcd93ee-ad1a-4f31-9ec0-87f5eba72c9a` (8 scenes). |
| Final runtime | StreamOps reports `READY`, OBS PID 5760 running interactively from the expected path, WebSocket connected, OBS 32.2.1 / obs-websocket 5.7.4, streaming false, recording false. |
| Tests | Windows A: `272 passed, 60 warnings` in 80.21 seconds. The warnings are existing WebSocket client deprecation warnings. |

One existing lifecycle edge case was found: if an OBS popup menu is left open,
the stop flow can select the transient Qt popup window and time out instead of
closing the main window. Closing the popup and retrying the same StreamOps stop
flow succeeded. This did not prevent rollback or final readiness, but should be
handled separately from this plugin-only POC.

Generated logs, the Docks-menu screenshot, transactions, backups, and sanitized
JSON evidence remain ignored under `.streamops\issue-33`; no credential or
service-setting content is committed. Acceptance result: **PASS**.
