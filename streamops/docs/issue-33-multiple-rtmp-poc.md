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
pwsh -NoProfile -File .\scripts\devices\a-windows\manage-obs-multi-rtmp.ps1 -Action Install
pwsh -NoProfile -File .\scripts\devices\a-windows\manage-obs-multi-rtmp.ps1 -Action Verify
```

The install root is:

```text
C:\ProgramData\obs-studio\plugins\obs-multi-rtmp\
├── bin\64bit\obs-multi-rtmp.dll
├── bin\64bit\obs-multi-rtmp.pdb
└── data\locale\*.ini                (71 files)
```

The script downloads only the pinned GitHub release artifact, verifies its
SHA-256 and 73-entry allowlist, and records ignored transaction evidence under
`.streamops\issue-33`. It never reads OBS service settings or prints an OBS
WebSocket password, RTMP URL, stream key, or token.

## Uninstall and rollback

Inspect the exact rollback first, then apply it while OBS is stopped:

```powershell
pwsh -NoProfile -File .\scripts\devices\a-windows\manage-obs-multi-rtmp.ps1 -Action Rollback -WhatIf
pwsh -NoProfile -File .\scripts\devices\a-windows\manage-obs-multi-rtmp.ps1 -Action Rollback
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

The sanitized observed result, exact before/after status, module-load evidence,
rollback/reinstall result, and final PASS/FAIL decision are added here after the
real-host run. Generated logs, screenshots, backups, and JSON evidence remain
ignored under `.streamops\issue-33`.
