#requires -Version 7.0
<#
.SYNOPSIS
  Read-only issue #87 acceptance evidence on Windows A, one PowerShell command.
.DESCRIPTION
  Requires an already-running isolated D4Planner supervisor and an explicit
  -DataDir. Never starts/stops Steam, D4, OBS, NVDA, StreamOps Node or a hook.
  Owner physically presses each of 16 controller buttons ONCE in Review mode.
  Keyboard marker evidence is never mistaken for physical/gameplay approval.
.EXAMPLE
  pwsh -NoProfile -File .\scripts\acceptance\issue87-uat.ps1 -Mode Preflight -DataDir 'C:\test\pr95\d4planner'
.EXAMPLE
  pwsh -NoProfile -File .\scripts\acceptance\issue87-uat.ps1 -Mode Review -DataDir 'C:\test\pr95\d4planner' -CaptureSeconds 90
#>
[CmdletBinding()]
param(
    [ValidateSet('Preflight','Review')]
    [string] $Mode = 'Preflight',
    [Parameter(Mandatory)]
    [string] $DataDir,
    [string] $Python = 'python',
    [string] $EvidenceDir,
    [ValidateRange(5,600)]
    [int] $CaptureSeconds = 90
)
$ErrorActionPreference = 'Stop'
# Expected nonzero from the read-only status probe means BLOCKED, not a script crash.
$PSNativeCommandUseErrorActionPreference = $false
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$reporter = Join-Path $root 'utility/d4planner/tools/issue87_uat_evidence.py'
if (-not $EvidenceDir) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $EvidenceDir = Join-Path $root ".streamops/pr95/uat/issue87-$stamp"
}
New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
$reportPath = Join-Path $EvidenceDir 'preflight.json'
$checks = New-Object 'System.Collections.Generic.List[object]'

function Add-Check {
    param([string] $Id, [string] $Expected, [object] $Actual,
          [ValidateSet('PASS','FAIL','BLOCKED','SKIP')]
          [string] $Result)
    $checks.Add([ordered]@{
        id = $Id; expected = $Expected; actual = $Actual; result = $Result
    })
}

function Save-Preflight {
    $sha = ''
    try {
        $sha = (& git -C $root rev-parse HEAD 2>$null | Out-String).Trim()
    } catch { $sha = 'unavailable' }
    $summary = @{}
    foreach ($status in @('PASS','FAIL','BLOCKED','SKIP')) {
        $summary[$status] = @($checks.ToArray() | Where-Object { $_['result'] -eq $status }).Count
    }
    [ordered]@{
        ticket = 87; pr = 95; mode = $Mode;
        head = $sha
        dataDir = $DataDir
        evidenceDir = $EvidenceDir
        timestamp = (Get-Date).ToString('o')
        summary = $summary
        checks = $checks.ToArray()
        safety = 'readOnly; no Steam/D4/OBS/D4Planner start-stop; owner physical verification required'
    } | ConvertTo-Json -Depth 10 |
        Set-Content -LiteralPath $reportPath -Encoding utf8
}

try {
    if (-not (Test-Path -LiteralPath $reporter -PathType Leaf)) {
        Add-Check 'PF-01' 'UAT evidence analyzer exists in checked-out PR' $reporter 'FAIL'
        Save-Preflight
        exit 2
    }
    $dataPath = [System.IO.Path]::GetFullPath($DataDir)
    if (-not (Test-Path -LiteralPath $dataPath -PathType Container)) {
        Add-Check 'PF-02' 'Existing isolated D4Planner data directory' $dataPath 'BLOCKED'
        Save-Preflight
        exit 2
    }
    Add-Check 'PF-02' 'Existing isolated D4Planner data directory' $dataPath 'PASS'

    # Port is only informational: this script does not start a StreamOps Node.
    $listeners = @(Get-NetTCPConnection -LocalPort 18795 -State Listen -ErrorAction SilentlyContinue)
    $pids = @($listeners | ForEach-Object { $_.OwningProcess } | Sort-Object -Unique)
    Add-Check 'PF-PORT' 'No test node is started by this UAT script' @{
        port=18795; listenerCount=$listeners.Count; pids=$pids
    } 'PASS'

    $profilesLog = Join-Path $EvidenceDir 'controller-profiles.log'
    & $Python -m d4planner.cli controller profiles *> $profilesLog
    $profilesExit = $LASTEXITCODE
    $profilesFound = $profilesExit -eq 0 -and (
        (Get-Content -LiteralPath $profilesLog -Raw) -match 'xbox16'
    )
    Add-Check 'PF-03A' 'controller profiles includes xbox16' @{
        exitCode=$profilesExit; log=$profilesLog
    } $(if ($profilesFound) { 'PASS' } else { 'FAIL' })

    $validationLog = Join-Path $EvidenceDir 'controller-validate.log'
    & $Python -m d4planner.cli controller validate xbox16 *> $validationLog
    $validated = $LASTEXITCODE -eq 0
    Add-Check 'PF-03B' 'controller validate xbox16 exit=0' @{
        exitCode=$LASTEXITCODE; log=$validationLog
    } $(if ($validated) { 'PASS' } else { 'FAIL' })

    $savedPlannerHome = $env:D4PLANNER_HOME
    try {
        $env:D4PLANNER_HOME = $dataPath
        $statusLog = Join-Path $EvidenceDir 'status.json'
        & $Python -m d4planner.cli status --json *> $statusLog
        $statusExit = $LASTEXITCODE
        Add-Check 'PF-03C' 'CLI status --json available with isolated D4PLANNER_HOME' @{
            exitCode=$statusExit; log=$statusLog
        } $(if ($statusExit -eq 0) { 'PASS' } else { 'BLOCKED' })
    } finally {
        $env:D4PLANNER_HOME = $savedPlannerHome
    }

    $snapshot = Join-Path $EvidenceDir 'start.json'
    $snapshotLog = Join-Path $EvidenceDir 'snapshot.log'
    & $Python $reporter --home $dataPath --mode snapshot --out $snapshot *> $snapshotLog
    $snapshotCode = $LASTEXITCODE
    $active = $false
    if (Test-Path $snapshot) {
        $snapshotJson = Get-Content -LiteralPath $snapshot -Raw | ConvertFrom-Json
        $active = $snapshotJson.validForReview -eq $true
    }
    Add-Check 'PF-04' 'RUNNING BLOCK xbox16 ACTIVE hook with 16 configured keys' @{
        exitCode=$snapshotCode; snapshot=$snapshot
    } $(if ($active) { 'PASS' } else { 'BLOCKED' })

    Save-Preflight
    Write-Host "Issue #87 UAT preflight: $reportPath"
    if (-not $validated) {
        Write-Error 'Controller contract validation failed. No runtime action was attempted.'
        exit 2
    }
    if ($Mode -eq 'Preflight') {
        exit $(if ($active) { 0 } else { 2 })
    }
    if (-not $active) {
        Write-Error 'Supervisor not capture-ready; refusing review without starting anything.'
        exit 2
    }

    Write-Host 'Press each of the 16 physical controller buttons ONCE on C via Steam Link.'
    Write-Host 'Do not use a physical keyboard to simulate PASS. Check gameplay visually.'
    Write-Host 'No Steam/D4/OBS/Planner process will be started or stopped by this script.'
    Read-Host 'Press ENTER to begin capturing input evidence'
    Start-Sleep -Seconds $CaptureSeconds

    $analysis = Join-Path $EvidenceDir 'report.json'
    $analysisLog = Join-Path $EvidenceDir 'analysis.log'
    & $Python $reporter --home $dataPath --mode analyze --start $snapshot --out $analysis *> $analysisLog
    $analysisExit = $LASTEXITCODE
    Write-Host "Issue #87 review evidence: $analysis"
    Write-Host "Raw events: $(Join-Path $EvidenceDir 'report-events.jsonl')"
    if (Test-Path $analysis) {
        $result = Get-Content -LiteralPath $analysis -Raw | ConvertFrom-Json
        Write-Host ("Observed marker matrix: {0}/16 PASS; FAIL={1}; manual physical/gameplay still pending." -f
            @($result.matrix | Where-Object { $_.result -eq 'PASS' }).Count,
            @($result.matrix | Where-Object { $_.result -eq 'FAIL' }).Count)
    }
    exit $analysisExit
} catch {
    Add-Check 'PF-ERROR' 'UAT completed without script errors' @{
        message = $_.Exception.Message
        category = $_.CategoryInfo.ToString()
        stack = $_.ScriptStackTrace
    } 'FAIL'
    Save-Preflight
    Write-Error "UAT script error: $($_.Exception.Message). Evidence: $reportPath"
    exit 2
}
