[CmdletBinding()]
param(
    [string]$DataRoot = (Join-Path $env:LOCALAPPDATA 'StreamOps\D4Planner'),
    [ValidateRange(1, 60)][int]$GraceSeconds = 8
)

$ErrorActionPreference = 'Stop'
$ownerState = Join-Path ([IO.Path]::GetFullPath($DataRoot)) 'private\hud-owner.json'
if (-not (Test-Path -LiteralPath $ownerState -PathType Leaf)) {
    throw "No owned D4Planner HUD run is recorded under $DataRoot"
}
$owner = Get-Content -LiteralPath $ownerState -Raw | ConvertFrom-Json
if ($owner.schemaVersion -ne 'd4planner-hud-owner/v1' -or -not $owner.pid -or -not $owner.executable) {
    throw 'Invalid HUD ownership record; refusing to stop any process'
}
$root = Get-Process -Id ([int]$owner.pid) -ErrorAction SilentlyContinue
if (-not $root) { Remove-Item -LiteralPath $ownerState -Force; exit 0 }
$actualPath = $root.Path
if (-not $actualPath -or [IO.Path]::GetFullPath($actualPath) -ne [IO.Path]::GetFullPath([string]$owner.executable)) {
    throw 'HUD PID no longer belongs to the recorded executable; refusing to stop it'
}
$actualStart = $root.StartTime.ToUniversalTime()
$recordedStart = [DateTimeOffset]::Parse([string]$owner.startedAt).UtcDateTime
if ([Math]::Abs(($actualStart - $recordedStart).TotalSeconds) -gt 2) {
    throw 'HUD PID start time does not match ownership record; refusing to stop it'
}

# WM_CLOSE gives Tauri its normal shutdown path, allowing its owned Backend to
# stop the Node/Chromium descendants. Recovery never searches by process name.
[void]$root.CloseMainWindow()
if (-not $root.WaitForExit($GraceSeconds * 1000)) {
    throw 'HUD did not exit gracefully; use Ctrl+Shift+F11 or collect the ownership record before escalation'
}
Remove-Item -LiteralPath $ownerState -Force -ErrorAction SilentlyContinue
