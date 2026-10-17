# Issue #119: read-only snapshot UAT for PR #120 Owned Items CLI.
# Never stops, restarts, or configures NVDA, Diablo IV, Steam, or D4Planner.
# Snapshot SQLite via backup API; all migrations and projections run on the COPY.
[CmdletBinding()]
param(
    [string]$ExpectedHead = '',
    [string]$Python = 'python',
    [string]$HomeDir = $(if ($env:D4PLANNER_HOME) { $env:D4PLANNER_HOME } else { Join-Path $env:LOCALAPPDATA 'd4planner' }),
    [string]$EvidenceDir = ''
)
$ErrorActionPreference = 'Stop'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptRoot '../..')).Path
if (!$EvidenceDir) { $EvidenceDir = Join-Path $env:TEMP ('d4planner-i119-items-' + (Get-Date -Format 'yyyyMMdd-HHmmss')) }
$EvidenceDir = [IO.Path]::GetFullPath($EvidenceDir)
$HomeDir = [IO.Path]::GetFullPath($HomeDir)
$copyHome = Join-Path $EvidenceDir 'snapshot-home'
$sourceDir = Join-Path $repoRoot 'utility/d4planner/src'
$oldHome = $env:D4PLANNER_HOME
$oldPath = $env:PYTHONPATH
$oldEncoding = $env:PYTHONIOENCODING
$report = [ordered]@{issue=119; pr=120; head=''; status='BLOCKED'; sourceHome=$HomeDir; snapshotHome=$copyHome; checks=[ordered]@{}; problems=@()}
New-Item -ItemType Directory -Force -Path (Join-Path $copyHome 'state') | Out-Null
function Check([string]$Name, [bool]$Pass, [string]$Message) {
    $report.checks[$Name] = @{result=$(if($Pass){'PASS'}else{'BLOCKED'}); detail=$Message}
    Write-Host "[$($report.checks[$Name].result)] $Name $Message"
    if (!$Pass) { throw "$Name - $Message" }
}
function InvokeCli([string]$Name, [string[]]$CliArguments) {
    $stdout = Join-Path $EvidenceDir "$Name.stdout.json"
    $stderr = Join-Path $EvidenceDir "$Name.stderr.txt"
    $previousPref = $PSNativeCommandUseErrorActionPreference
    try {
        $PSNativeCommandUseErrorActionPreference = $false
        & $Python -m d4planner.cli @CliArguments 1> $stdout 2> $stderr
        $code = $LASTEXITCODE
    } finally {
        $PSNativeCommandUseErrorActionPreference = $previousPref
    }
    $errText = if (Test-Path $stderr) { (Get-Content -LiteralPath $stderr -Raw -Encoding utf8).Trim() } else { '' }
    Check $Name ($code -eq 0) "exit=$code; stderr=$errText; log=$stderr"
    $raw = Get-Content -LiteralPath $stdout -Raw -Encoding utf8
    $json = $raw | ConvertFrom-Json -ErrorAction Stop
    return $json
}
try {
    $head = (& git -C $repoRoot rev-parse HEAD 2>&1 | Out-String).Trim()
    $report.head = $head
    Check 'HEAD' ($LASTEXITCODE -eq 0 -and $head -match '^[0-9a-f]{40}$' -and
        (!$ExpectedHead -or $head -eq $ExpectedHead)) "PR worktree HEAD=$head"
    $branch = (& git -C $repoRoot branch --show-current | Out-String).Trim()
    Check 'BRANCH' ($branch -eq 'feat/119-owned-items-cli' -or
        ($ExpectedHead -and $head -eq $ExpectedHead)) "PR branch/detached pinned HEAD=$branch"
    Check 'SOURCE' (Test-Path (Join-Path $sourceDir 'd4planner/character/owned_items.py')) 'PR Owned Items code exists'
    Check 'EVENTS' (Test-Path (Join-Path $HomeDir 'state/events.db')) 'Canonical input events.db exists'
    & $Python --version
    Check 'PYTHON' ($LASTEXITCODE -eq 0) "Python interpreter $Python"
    # Snapshot database files using SQLite online backup, not raw file copying;
    # raw copying can miss uncheckpointed events.db WAL and disrupt consistency.
    $backupScript = Join-Path $EvidenceDir 'snapshot.py'
    @'
import sqlite3, sys
from pathlib import Path
source, target = (Path(x) for x in sys.argv[1:])
with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True, timeout=10) as src:
    with sqlite3.connect(target, timeout=10) as dst:
        src.backup(dst, pages=256, sleep=.1)
'@ | Set-Content -LiteralPath $backupScript -Encoding utf8
    foreach ($dbName in @('events.db','character.db')) {
        $source = Join-Path $HomeDir "state/$dbName"
        if (Test-Path $source) {
            $target = Join-Path $copyHome "state/$dbName"
            & $Python $backupScript $source $target
            Check "SNAPSHOT_$dbName" ($LASTEXITCODE -eq 0 -and (Test-Path $target)) "SQLite backup completed"
        } else {
            Check "SNAPSHOT_$dbName" ($dbName -eq 'character.db') 'character.db missing: empty projection expected'
        }
    }
    $env:D4PLANNER_HOME = $copyHome
    $env:PYTHONPATH = if ($oldPath) { "$sourceDir;$oldPath" } else { $sourceDir }
    $env:PYTHONIOENCODING = 'utf-8'
    $baseline = InvokeCli 'LIST' @('items','--json')
    Check 'LIST_SCHEMA' ($baseline.schemaVersion -eq 1 -and $null -ne $baseline.coverage -and
        $null -ne $baseline.items -and $baseline.observedTotal -eq @($baseline.items).Count) 'Default confirmed-only list and coverage JSON'
    $candidates = InvokeCli 'CANDIDATES' @('items','--json','--include-unverified')
    Check 'CANDIDATE_POLICY' ($candidates.observedTotal -ge $baseline.observedTotal -and
        @($candidates.items | Where-Object { $_.ownershipStatus -eq 'NOT_CONFIRMED' -and $_.pickedUpAt }).Count -eq 0) 'Unconfirmed observations never invent pickedUpAt'
    $status = InvokeCli 'STATUS' @('items','status','--json')
    Check 'STATUS_SCHEMA' ($null -ne $status.coverage.stash.tabs -and $status.coverage.overall -in @('PARTIAL','NOT_SCANNED')) 'Stash tabs PARTIAL/NOT_SCANNED, no fake completeness'
    $history = InvokeCli 'HISTORY' @('items','history','--json')
    Check 'HISTORY_SCHEMA' ($history.schemaVersion -eq 1 -and $null -ne $history.observations) 'Append-only source-provenance observations'
    $filtered = InvokeCli 'FILTER' @('items','--json','--include-unverified','--location','stash')
    Check 'FILTER_LOCATION' (@($filtered.items | Where-Object {$_.location.type -ne 'stash'}).Count -eq 0) 'Stash filter only'
    $export = Join-Path $EvidenceDir 'items-history.jsonl'
    $exportOut = Join-Path $EvidenceDir 'EXPORT.stdout.txt'
    $exportErr = Join-Path $EvidenceDir 'EXPORT.stderr.txt'
    $previousPref = $PSNativeCommandUseErrorActionPreference
    try {
        $PSNativeCommandUseErrorActionPreference = $false
        & $Python -m d4planner.cli items export --format jsonl --output $export 1> $exportOut 2> $exportErr
        $code = $LASTEXITCODE
    } finally {
        $PSNativeCommandUseErrorActionPreference = $previousPref
    }
    Check 'EXPORT' ($code -eq 0 -and (Test-Path $export)) 'JSONL generated on isolated snapshot'
    $lines = @(Get-Content -LiteralPath $export -Encoding utf8 | Where-Object { $_.Trim() })
    Check 'EXPORT_COUNT' ($lines.Count -eq @($history.observations).Count) 'Exported lines equal observed history'
    $after = InvokeCli 'IDEMPOTENT' @('items','--json','--include-unverified')
    Check 'IDEMPOTENT_SCHEMA' ($after.observedTotal -eq $candidates.observedTotal) 'No new candidates on rerun of same copied source'
    $report.status = 'PASS_SNAPSHOT_CLI_PARTIAL_OWNERSHIP'
} catch {
    $report.problems += $_.Exception.Message
    Write-Warning $_.Exception.Message
} finally {
    $env:D4PLANNER_HOME = $oldHome
    $env:PYTHONPATH = $oldPath
    $env:PYTHONIOENCODING = $oldEncoding
    $report | ConvertTo-Json -Depth 15 | Set-Content -LiteralPath (Join-Path $EvidenceDir 'report.json') -Encoding utf8
    # DB snapshot may include raw speech/private game text; explicitly do not
    # ship copied DBs, and do not include the snapshot-home directory in ZIP.
    $archive = "$EvidenceDir.zip"
    $exportFiles = @(Get-ChildItem -Path $EvidenceDir -File | Where-Object { $_.Name -ne 'snapshot.py' })
    if ($exportFiles.Count -gt 0) {
        Compress-Archive -LiteralPath @($exportFiles | ForEach-Object FullName) -DestinationPath $archive -Force
    }
    Write-Host "Issue #119 items UAT evidence: $archive"
    Write-Host "Status: $($report.status). Live D4Planner/Steam/Game/NVDA unchanged."
}
if ($report.status -ne 'PASS_SNAPSHOT_CLI_PARTIAL_OWNERSHIP') { exit 2 }
exit 0
