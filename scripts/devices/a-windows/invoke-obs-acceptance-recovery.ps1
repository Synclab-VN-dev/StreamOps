# Runs inside the interactive desktop session and closes only the OBS process
# identified by a fresh acceptance recovery request.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RequestPath,
    [Parameter(Mandatory = $true)]
    [string]$ResultPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Write-RecoveryResult([System.Collections.IDictionary]$Result) {
    $directory = Split-Path -Parent $ResultPath
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    $temporary = $ResultPath + ".tmp"
    $Result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $ResultPath -Force
}

$requestId = $null
try {
    if (-not (Test-Path -LiteralPath $RequestPath -PathType Leaf)) {
        throw "Recovery request is missing."
    }
    $request = Get-Content -LiteralPath $RequestPath -Raw | ConvertFrom-Json
    $requestId = [string]$request.request_id
    if ([int]$request.schema_version -ne 1 -or [string]::IsNullOrWhiteSpace($requestId)) {
        throw "Recovery request schema or request ID is invalid."
    }
    $expiresAt = [DateTimeOffset]::Parse([string]$request.expires_at)
    if ([DateTimeOffset]::UtcNow -gt $expiresAt.ToUniversalTime()) {
        throw "Recovery request has expired."
    }
    if ($request.idle_snapshot.streaming -ne $false -or $request.idle_snapshot.recording -ne $false) {
        throw "Recovery request does not contain a proven idle snapshot."
    }

    $expected = $request.expected_process
    $expectedPid = [int]$expected.pid
    $expectedSession = [int]$expected.session_id
    $expectedActiveSession = [int]$expected.active_console_session_id
    $expectedPath = [IO.Path]::GetFullPath([string]$expected.executable_path)
    $expectedStartedAt = [DateTimeOffset]::Parse([string]$expected.started_at).ToUniversalTime()

    if ($expectedPid -le 0 -or $expectedSession -lt 0 -or $expectedSession -ne $expectedActiveSession) {
        throw "Recovery request process identity is invalid."
    }
    if ([Diagnostics.Process]::GetCurrentProcess().SessionId -ne $expectedActiveSession) {
        throw "Recovery worker is not running in the expected active interactive session."
    }

    $process = Get-Process -Id $expectedPid -ErrorAction Stop
    $process.Refresh()
    if ($process.ProcessName -ine "obs64") {
        throw "Expected PID does not belong to obs64."
    }
    if ($process.SessionId -ne $expectedSession) {
        throw "OBS Windows session changed before graceful close."
    }
    $actualPath = [IO.Path]::GetFullPath($process.Path)
    if (-not [string]::Equals($actualPath, $expectedPath, [StringComparison]::OrdinalIgnoreCase)) {
        throw "OBS executable path changed before graceful close."
    }
    $actualStartedAt = [DateTimeOffset]$process.StartTime.ToUniversalTime()
    if ([Math]::Abs(($actualStartedAt - $expectedStartedAt).TotalSeconds) -gt 1) {
        throw "OBS process start time changed before graceful close."
    }

    # Re-read the same PID-bound process immediately before the only mutation.
    $process.Refresh()
    if ($process.HasExited -or $process.Id -ne $expectedPid -or $process.SessionId -ne $expectedSession) {
        throw "OBS process identity changed before graceful close."
    }
    $startedAtAgain = [DateTimeOffset]$process.StartTime.ToUniversalTime()
    if ([Math]::Abs(($startedAtAgain - $expectedStartedAt).TotalSeconds) -gt 1) {
        throw "OBS process was replaced before graceful close."
    }
    if (-not $process.CloseMainWindow()) {
        throw "OBS did not expose a main window for graceful close."
    }

    Write-RecoveryResult ([ordered]@{
        schema_version = 1
        request_id = $requestId
        status = "close_requested"
        pid = $expectedPid
        completed_at = [DateTimeOffset]::UtcNow.ToString("o")
    })
    exit 0
}
catch {
    Write-RecoveryResult ([ordered]@{
        schema_version = 1
        request_id = $requestId
        status = "refused"
        error = $_.Exception.Message
        completed_at = [DateTimeOffset]::UtcNow.ToString("o")
    })
    exit 1
}
