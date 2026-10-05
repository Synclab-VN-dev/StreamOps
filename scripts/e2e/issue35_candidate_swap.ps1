[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('InstallCandidate', 'RestoreUpstream')]
    [string] $Action,
    [string] $CandidateDll,
    [string] $BackupDir,
    [string] $BaseUrl = 'http://127.0.0.1:8765',
    [int] $TimeoutSeconds = 30
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot '../..')
$TargetDll = Join-Path $env:ProgramData 'obs-studio/plugins/obs-multi-rtmp/bin/64bit/obs-multi-rtmp.dll'

function Get-Status {
    Invoke-RestMethod -Uri "$BaseUrl/api/v1/obs/process/status" -Method Get
}

function Assert-Idle {
    $status = Get-Status
    if ($status.state -ne 'READY') { throw "OBS must be READY before mutation; state=$($status.state)" }
    if ($status.output.streaming -eq $true) { throw 'Refusing plugin swap while streaming.' }
    if ($status.output.recording -eq $true) { throw 'Refusing plugin swap while recording.' }
}

function Wait-State([string] $Expected) {
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $state = (Get-Status).state
        if ($state -eq $Expected) { return }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "OBS state timeout: actual=$state expected=$Expected"
}

function Stop-Obs {
    Invoke-RestMethod -Uri "$BaseUrl/api/v1/obs/process/stop" -Method Post | Out-Null
    Wait-State 'STOPPED'
}

function Start-Obs {
    Invoke-RestMethod -Uri "$BaseUrl/api/v1/obs/process/start" -Method Post | Out-Null
    Wait-State 'READY'
}

if ($Action -eq 'InstallCandidate') {
    Assert-Idle
    if (-not $CandidateDll) { throw '-CandidateDll is required for InstallCandidate.' }
    $CandidateDll = (Resolve-Path $CandidateDll).Path
    if (-not (Test-Path $TargetDll)) { throw "Pinned upstream DLL not found: $TargetDll" }

    if (-not $BackupDir) {
        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        $BackupDir = Join-Path $RepoRoot ".streamops/issue-35/plugin-backup/$stamp"
    }
    New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
    $BackupDir = (Resolve-Path $BackupDir).Path
    $backupDll = Join-Path $BackupDir 'upstream-obs-multi-rtmp.dll'
    Copy-Item $TargetDll $backupDll -Force

    $manifest = [ordered]@{
        target_path = $TargetDll
        upstream_sha256 = (Get-FileHash $TargetDll -Algorithm SHA256).Hash
        candidate_path = $CandidateDll
        candidate_sha256 = (Get-FileHash $CandidateDll -Algorithm SHA256).Hash
        created_at = (Get-Date).ToString('o')
    }
    $manifest | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $BackupDir 'manifest.json') -Encoding UTF8

    Stop-Obs
    try {
        Copy-Item $CandidateDll $TargetDll -Force
    }
    catch {
        Copy-Item $backupDll $TargetDll -Force
        Start-Obs
        throw
    }
    Start-Obs

    $actual = (Get-FileHash $TargetDll -Algorithm SHA256).Hash
    if ($actual -ne $manifest.candidate_sha256) { throw 'Candidate DLL hash mismatch after copy.' }

    Write-Host 'ISSUE35_PLUGIN_SWAP InstallCandidate PASS'
    Write-Host "BackupDir=$BackupDir"
    Write-Host "CandidateSHA256=$actual"
    Write-Host 'Gate 1 pinned plugin status may report mismatch until RestoreUpstream.'
    exit 0
}

if (-not $BackupDir) { throw '-BackupDir is required for RestoreUpstream.' }
$BackupDir = (Resolve-Path $BackupDir).Path
$manifestPath = Join-Path $BackupDir 'manifest.json'
$backupDll = Join-Path $BackupDir 'upstream-obs-multi-rtmp.dll'
if (-not (Test-Path $manifestPath) -or -not (Test-Path $backupDll)) {
    throw "Backup is incomplete: $BackupDir"
}
$manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json

Assert-Idle
Stop-Obs
Copy-Item $backupDll $TargetDll -Force
Start-Obs

$restored = (Get-FileHash $TargetDll -Algorithm SHA256).Hash
if ($restored -ne $manifest.upstream_sha256) {
    throw "Restored upstream DLL hash mismatch: $restored"
}
$plugin = Invoke-RestMethod -Uri "$BaseUrl/api/v1/obs/plugins/obs-multi-rtmp" -Method Get
if ($plugin.state -ne 'LOADED' -or $plugin.loaded -ne $true) {
    throw "Upstream restore did not return Gate 1 LOADED state: $($plugin.state)"
}

Write-Host 'ISSUE35_PLUGIN_SWAP RestoreUpstream PASS'
Write-Host "RestoredSHA256=$restored"
