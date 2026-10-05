[CmdletBinding()]
param(
    [ValidateSet('Debug', 'RelWithDebInfo', 'Release', 'MinSizeRel')]
    [string] $Configuration = 'RelWithDebInfo'
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot '../..')
$SourceRoot = Join-Path $RepoRoot 'util/obs-multi-rtmp-websocket'
$BuildScript = Join-Path $SourceRoot '.github/scripts/Build-Windows.ps1'

if (-not (Test-Path $BuildScript)) {
    throw "Candidate build script missing: $BuildScript"
}
if ($PSVersionTable.PSVersion -lt [Version]'7.2.0') {
    throw "PowerShell 7.2+ is required. Run this helper with pwsh."
}
if (-not (Get-Command cmake -ErrorAction SilentlyContinue)) {
    throw "cmake is required on PATH."
}

$oldCi = $env:CI
try {
    $env:CI = 'true'
    & $BuildScript -Target x64 -Configuration $Configuration
    if ($LASTEXITCODE -ne 0) {
        throw "Candidate build failed with exit code $LASTEXITCODE"
    }
}
finally {
    if ($null -eq $oldCi) { Remove-Item Env:CI -ErrorAction SilentlyContinue }
    else { $env:CI = $oldCi }
}

$releaseRoot = Join-Path $SourceRoot "release/$Configuration"
$candidates = @(Get-ChildItem $releaseRoot -Recurse -File -Filter 'obs-multi-rtmp.dll' -ErrorAction Stop)
if ($candidates.Count -ne 1) {
    throw "Expected exactly one built obs-multi-rtmp.dll under $releaseRoot, found $($candidates.Count)."
}

$dll = $candidates[0]
$hash = (Get-FileHash $dll.FullName -Algorithm SHA256).Hash
Write-Host "ISSUE35_CANDIDATE_BUILD PASS"
Write-Host "CandidateDll=$($dll.FullName)"
Write-Host "SHA256=$hash"
