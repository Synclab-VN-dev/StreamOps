# Issue #119 / Draft PR #120: one-shot read-only Unified Item Current UAT.
# Does not stop/start game, runtime or NVDA. Never deletes or writes character.db.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidatePattern('^[0-9a-f]{40}$')]
    [string]$ExpectedHead,
    [Parameter(Mandatory=$true)]
    [string]$DevHomeDir,
    [string]$Python = 'python',
    [string]$EvidenceRoot = $env:TEMP
)
$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = [IO.Path]::GetFullPath((Join-Path $scriptDir '..\..'))
$evidencePath = Join-Path ([IO.Path]::GetFullPath($EvidenceRoot)) 'StreamOps-PR120-UAT'
$archive = Join-Path ([IO.Path]::GetFullPath($EvidenceRoot)) 'StreamOps-PR120-UAT.zip'
$reportPath = Join-Path $evidencePath 'report.json'
$homePath = [IO.Path]::GetFullPath($DevHomeDir)
New-Item -ItemType Directory -Force -Path $evidencePath | Out-Null
$exitCode = 2

try {
    $actualHead = (& git -C $repoRoot rev-parse HEAD | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $actualHead -ne $ExpectedHead) {
        throw "HEAD mismatch: expected $ExpectedHead, actual $actualHead"
    }
    if (!(Test-Path -LiteralPath (Join-Path $homePath 'state\character.db'))) {
        throw "Missing character.db under the explicitly selected DEV HomeDir: $homePath"
    }
    # Validate that the source path exists before running a Python interpreter.
    $pythonScript = Join-Path $scriptDir 'issue119_item_current_uat.py'
    if (!(Test-Path -LiteralPath $pythonScript)) {
        throw "Missing UAT implementation: $pythonScript"
    }

    $oldPref = $PSNativeCommandUseErrorActionPreference
    try {
        $PSNativeCommandUseErrorActionPreference = $false
        & $Python $pythonScript --repo-root $repoRoot --home-dir $homePath `
            --expected-head $ExpectedHead --evidence-dir $evidencePath `
            1> (Join-Path $evidencePath 'runner.stdout.txt') `
            2> (Join-Path $evidencePath 'runner.stderr.txt')
        $exitCode = $LASTEXITCODE
    } finally {
        $PSNativeCommandUseErrorActionPreference = $oldPref
    }
    if (!(Test-Path -LiteralPath $reportPath)) {
        throw "UAT runner returned exit=$exitCode without report.json"
    }
} catch {
    $exitCode = 2
    $block = @{
        issue=119; pr=120; status='BLOCKED';
        expectedHead=$ExpectedHead; homeDir=$homePath;
        problems=@($_.Exception.Message);
        cases=@(@{ id='UAT-PREFLIGHT'; status='BLOCKED';
                   expected='Pinned PR HEAD, explicit existing DEV DB';
                   actual=$_.Exception.Message })
    }
    $block | ConvertTo-Json -Depth 8 |
        Set-Content -LiteralPath $reportPath -Encoding utf8
} finally {
    if (Test-Path -LiteralPath $archive) {
        Remove-Item -LiteralPath $archive -Force
    }
    $files = @(Get-ChildItem -LiteralPath $evidencePath -File)
    if ($files.Count -gt 0) {
        Compress-Archive -LiteralPath @($files | ForEach-Object FullName) `
            -DestinationPath $archive -Force
    }
    Write-Host "PR120 UAT ZIP: $archive"
    Write-Host "PR120 UAT report: $reportPath"
    Write-Host "Exit code: $exitCode. Game, NVDA, Engine, DB left unchanged."
}
exit $exitCode
