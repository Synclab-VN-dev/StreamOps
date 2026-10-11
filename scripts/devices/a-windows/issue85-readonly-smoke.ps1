# Issue #85 read-only status and two-WS-observer smoke. No lifecycle calls.
[CmdletBinding()]
param(
    [string]$BaseUrl = "http://127.0.0.1:8765",
    [ValidateRange(1,300)]
    [int]$ObserveSeconds = 20,
    [string]$PythonPath = "python"
)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
Write-Host "Read-only GameService REST / WS check: $BaseUrl"
$catalog = Invoke-RestMethod -Uri "$BaseUrl/api/v1/games" -TimeoutSec 8
$catalog | ConvertTo-Json -Depth 10
& $PythonPath (Join-Path $root "scripts\e2e\issue85_games_ws_readonly.py") --base $BaseUrl --seconds $ObserveSeconds
if ($LASTEXITCODE -ne 0) { throw "GameService WS read-only smoke failed ($LASTEXITCODE)" }
