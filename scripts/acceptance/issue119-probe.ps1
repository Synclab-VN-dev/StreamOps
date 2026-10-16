# Issue #119: bounded, read-only NVDA + configured controller-marker evidence.
# Never starts, stops, or reconfigures Steam, Diablo IV, NVDA or D4Planner.
[CmdletBinding()]
param(
    [ValidateSet('Preflight','Capture')][string]$Mode = 'Preflight',
    [string]$Python = 'python',
    [string]$HomeDir = $(if ($env:D4PLANNER_HOME) { $env:D4PLANNER_HOME } else { Join-Path $env:LOCALAPPDATA 'd4planner' }),
    [string]$EvidenceDir = '',
    [string]$ExpectedHead = ''
)
$ErrorActionPreference = 'Stop'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptRoot '../..')).Path
$probe = Join-Path $scriptRoot 'issue119_probe.py'
$head = ''
$report = [ordered]@{ issue = 119; mode = $Mode; status = 'BLOCKED'; checks = [ordered]@{}; head = ''; evidenceDir = ''; problems = @() }
if ([string]::IsNullOrWhiteSpace($EvidenceDir)) {
    $EvidenceDir = Join-Path $env:TEMP ('d4planner-issue119-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
}
$EvidenceDir = [IO.Path]::GetFullPath($EvidenceDir)
$report.evidenceDir = $EvidenceDir
New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
function Check([string]$Id, [bool]$Pass, [string]$Detail) {
    $report.checks[$Id] = [ordered]@{ result = $(if($Pass){'PASS'}else{'BLOCKED'}); detail = $Detail }
    Write-Host "[$($report.checks[$Id].result)] $Id - $Detail"
    if (!$Pass) { throw ($Id + ": " + $Detail) }
}
function RunProbe([string[]]$ProbeArgs) {
    & $Python $probe @ProbeArgs
    if ($LASTEXITCODE -ne 0) { throw "issue119_probe.py exited $LASTEXITCODE ($($ProbeArgs -join ' '))" }
}
function Invoke-D4PlannerStatus([string]$Prefix) {
    # Preserve stdout, stderr and process exit independently, even when CLI returns
    # nonzero for a stale supervisor. A nonzero exit with valid JSON is a RUNTIME
    # BLOCKED (P0-07), not a missing-CLI / JSON-contract failure (P0-06).
    $stdoutFile = Join-Path $EvidenceDir ($Prefix + '.stdout.txt')
    $stderrFile = Join-Path $EvidenceDir ($Prefix + '.stderr.txt')
    $metadataFile = Join-Path $EvidenceDir ($Prefix + '.invocation.json')
    $command = Get-Command -Name d4planner -ErrorAction SilentlyContinue
    $commandPath = if ($null -ne $command) { [string]$command.Source } else { $null }
    $exitCode = $null
    $launchError = $null
    $previousNativePreference = $PSNativeCommandUseErrorActionPreference
    try {
        $PSNativeCommandUseErrorActionPreference = $false
        if ($null -eq $command) {
            $launchError = 'd4planner command not found on PATH'
        } else {
            & d4planner status --json 1> $stdoutFile 2> $stderrFile
            $exitCode = $LASTEXITCODE
        }
    } catch {
        $launchError = $_.Exception.Message
    } finally {
        $PSNativeCommandUseErrorActionPreference = $previousNativePreference
    }
    if (!(Test-Path -LiteralPath $stdoutFile)) { '' | Set-Content -LiteralPath $stdoutFile -Encoding utf8 }
    if (!(Test-Path -LiteralPath $stderrFile)) { '' | Set-Content -LiteralPath $stderrFile -Encoding utf8 }
    $out = Get-Content -LiteralPath $stdoutFile -Raw -Encoding utf8
    $err = Get-Content -LiteralPath $stderrFile -Raw -Encoding utf8
    $result = [ordered]@{
        command = 'd4planner status --json'
        resolvedCommand = $commandPath
        exitCode = $exitCode
        exception = $launchError
        stdout = $out
        stderr = $err
    }
    $result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $metadataFile -Encoding utf8
    return [pscustomobject]$result
}
try {
    Check 'P0-01' (Test-Path -LiteralPath $probe -PathType Leaf) 'Probe source exists in checked-out PR worktree'
    $head = (& git -C $repoRoot rev-parse HEAD 2>&1 | Out-String).Trim()
    Check 'P0-02' ($LASTEXITCODE -eq 0 -and $head -match '^[a-f0-9]{40}$') "Git HEAD: $head"
    $report.head = $head
    if ($ExpectedHead) { Check 'P0-03' ($head -eq $ExpectedHead) 'Exact HEAD pinned by operator' }
    $branch = (& git -C $repoRoot branch --show-current | Out-String).Trim()
    Check 'P0-04' ($branch -eq 'feat/119-owned-items-cli' -or ($ExpectedHead -and $head -eq $ExpectedHead)) "PR branch or pinned detached HEAD: $branch"
    & $Python --version
    Check 'P0-05' ($LASTEXITCODE -eq 0) "Python entrypoint: $Python"
    $invocation = Invoke-D4PlannerStatus -Prefix 'status-before'
    $status = $null
    try {
        if ($invocation.stdout) { $status = $invocation.stdout | ConvertFrom-Json -ErrorAction Stop }
    } catch {
        $report.problems += 'status JSON parse: ' + $_.Exception.Message
    }
    $validStatus = $null -ne $status -and $status -is [psobject] -and
        $null -ne $status.PSObject.Properties['state'] -and
        $null -ne $status.PSObject.Properties['supervisorAlive'] -and
        $null -ne $status.PSObject.Properties['captureEffective']
    Check 'P0-06' $validStatus ("D4Planner JSON contract; exit=$($invocation.exitCode); executable=$($invocation.resolvedCommand); exception=$($invocation.exception); stderr=$($invocation.stderr)")
    $status | ConvertTo-Json -Depth 32 | Set-Content -LiteralPath (Join-Path $EvidenceDir 'status-before.json') -Encoding utf8
    $runtimeReady = ($invocation.exitCode -eq 0 -and $status.supervisorAlive -eq $true -and
        $status.captureEffective -eq $true -and $status.state -eq 'RUNNING')
    Check 'P0-07' $runtimeReady ("Require RUNNING/alive/capture lease/CLI exit=0; observed state=$($status.state), alive=$($status.supervisorAlive), captureEffective=$($status.captureEffective), exit=$($invocation.exitCode), supervisorPid=$($status.supervisorPid)")
    $input = $status.extras.inputMarker
    $layoutOk = $null -ne $input -and $input.state -eq 'ACTIVE' -and $input.layoutId -eq 'xbox-steaminput-18-v1' -and $input.configuredDigitalCount -eq 16
    Check 'P0-08' $layoutOk 'All 16 configured controller marker keys ACTIVE (not all keyboard keys)'
    Check 'P0-09' ((Test-Path -LiteralPath (Join-Path $HomeDir 'state/events.db') -PathType Leaf)) "Canonical SQLite event file exists in $HomeDir"
    RunProbe @('begin','--home',$HomeDir,'--out',(Join-Path $EvidenceDir 'preflight-baseline.json'))
    $report.status = 'PASS'
    if ($Mode -eq 'Capture') {
        Write-Host ""
        Write-Host "CAPTURE: Run each stage in Diablo IV. Only mapped keys inside the D4 context are logged."
        Write-Host 'Do not type credentials or private chat. No service will be restarted or reconfigured.'
        $stages = @(
            [ordered]@{id='inventory';prompt='Open INVENTORY. Navigate across a selection of item slots; include one equipped and one unequipped tooltip if available.'},
            [ordered]@{id='stash-tab-1';prompt='Open STASH tab 1. Browse every accessible item slot and at least one empty slot, if possible.'},
            [ordered]@{id='stash-tab-2';prompt='Open STASH tab 2. Browse every accessible item slot; note whether tab switch speaks its index.'}
        )
        foreach ($stage in $stages) {
            Read-Host "Press ENTER to BEGIN $($stage.id)"
            $base = Join-Path $EvidenceDir ("$($stage.id)-start.json")
            $out = Join-Path $EvidenceDir $stage.id
            RunProbe @('begin','--home',$HomeDir,'--out',$base)
            Write-Host "[ACTION] $($stage.prompt)"
            Read-Host "Press ENTER when $($stage.id) navigation is FINISHED"
            RunProbe @('finish','--home',$HomeDir,'--baseline',$base,'--outdir',$out)
        }
        $endInvocation = Invoke-D4PlannerStatus -Prefix 'status-after'
        try {
            $endStatus = $endInvocation.stdout | ConvertFrom-Json -ErrorAction Stop
            $endStatus | ConvertTo-Json -Depth 32 | Set-Content -LiteralPath (Join-Path $EvidenceDir 'status-after.json') -Encoding utf8
        } catch {
            $report.problems += 'Post-capture status unavailable: ' + $_.Exception.Message
        }
        $report.status = 'PENDING_REAL_A_REVIEW'
    }
} catch {
    $report.problems += $_.Exception.Message
    Write-Warning $_.Exception.Message
} finally {
    $report | ConvertTo-Json -Depth 32 | Set-Content -LiteralPath (Join-Path $EvidenceDir 'report.json') -Encoding utf8
    $zip = "$EvidenceDir.zip"
    if (!(Test-Path -LiteralPath $zip)) {
        Compress-Archive -Path (Join-Path $EvidenceDir '*') -DestinationPath $zip -Force
    }
    Write-Host ""
    Write-Host "Issue #119 evidence: $zip"
    Write-Host "Status: $($report.status). No D4Planner/Steam/Diablo IV process was changed."
}
if ($report.status -eq 'BLOCKED') { exit 2 }
exit 0
