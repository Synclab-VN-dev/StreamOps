# Stage an immutable StreamOps wheel bundle without touching the running service.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$BundleRoot,
    [Parameter(Mandatory)][ValidatePattern('^[a-f0-9]{40}$')][string]$ExpectedCommit,
    [string]$DeploymentRoot
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$bundle = (Resolve-Path $BundleRoot).Path
$manifestPath = Join-Path $bundle 'deployment-manifest.json'
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw 'Deployment manifest is missing.' }
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($manifest.source_commit -ne $ExpectedCommit) { throw 'Deployment source commit mismatch.' }
if ($null -eq $manifest.files -or @($manifest.files).Count -eq 0) { throw 'Deployment manifest has no files.' }
foreach ($entry in @($manifest.files)) {
    $relative = [string]$entry.relative_path
    if ([IO.Path]::IsPathRooted($relative) -or $relative.Contains('..')) { throw 'Unsafe deployment manifest path.' }
    $path = Join-Path $bundle $relative
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Deployment file missing: $relative" }
    $item = Get-Item -LiteralPath $path
    if ([int64]$entry.length -ne $item.Length) { throw "Deployment file size mismatch: $relative" }
    if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne ([string]$entry.sha256).ToLowerInvariant()) {
        throw "Deployment file SHA-256 mismatch: $relative"
    }
}
if ([string]::IsNullOrWhiteSpace($DeploymentRoot)) {
    $DeploymentRoot = Join-Path $repoRoot ".streamops\deployments\$ExpectedCommit"
}
$DeploymentRoot = [IO.Path]::GetFullPath($DeploymentRoot)
$allowedRoot = [IO.Path]::GetFullPath((Join-Path $repoRoot '.streamops\deployments')).TrimEnd('\') + '\'
if (-not $DeploymentRoot.StartsWith($allowedRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "DeploymentRoot must stay under $allowedRoot"
}
if (Test-Path -LiteralPath $DeploymentRoot) { throw 'Deployment directory already exists; immutable deployments are never overwritten.' }
New-Item -ItemType Directory -Path $DeploymentRoot | Out-Null
Copy-Item -LiteralPath $bundle -Destination (Join-Path $DeploymentRoot 'bundle') -Recurse
$python = (Get-Command python.exe -ErrorAction Stop).Source
& $python -m venv (Join-Path $DeploymentRoot 'venv')
if ($LASTEXITCODE -ne 0) { throw 'Could not create deployment virtual environment.' }
$venvPython = Join-Path $DeploymentRoot 'venv\Scripts\python.exe'
$wheelhouse = Join-Path $DeploymentRoot 'bundle\wheelhouse'
$appWheel = @(Get-ChildItem -LiteralPath $wheelhouse -File -Filter 'streamops-*.whl')
if ($appWheel.Count -ne 1) { throw 'Expected exactly one StreamOps wheel.' }
& $venvPython -m pip install --no-index --find-links $wheelhouse ($appWheel[0].FullName + '[server]')
if ($LASTEXITCODE -ne 0) { throw 'Offline StreamOps deployment installation failed.' }
& $venvPython -c "import streamops, streamops.server.app"
if ($LASTEXITCODE -ne 0) { throw 'Installed StreamOps package validation failed.' }
Copy-Item -LiteralPath $manifestPath -Destination (Join-Path $DeploymentRoot 'deployment.json')
Write-Host "STAGED=$DeploymentRoot"
Write-Host "SOURCE_COMMIT=$ExpectedCommit"
