# Switch the StreamOps scheduled task to a staged deployment during an approved window.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$DeploymentRoot,
    [string]$RollbackDeploymentRoot,
    [Parameter(Mandatory)][switch]$MaintenanceApproved,
    [switch]$ExpectEmptyCatalog,
    [string]$TaskName = 'StreamOps Node (repo-local)',
    [string]$DataDir
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
if (-not $MaintenanceApproved) { throw 'Explicit -MaintenanceApproved is required.' }
# For the first migration, the original scheduled task XML is the rollback source.
$rootsToCheck = @($DeploymentRoot)
if (-not [string]::IsNullOrWhiteSpace($RollbackDeploymentRoot)) {
    $rootsToCheck += $RollbackDeploymentRoot
}
foreach ($root in $rootsToCheck) {
    $resolved = (Resolve-Path $root).Path
    if (-not (Test-Path -LiteralPath (Join-Path $resolved 'deployment.json') -PathType Leaf)) {
        throw "Validated deployment metadata missing: $resolved"
    }
}
$deployment = (Resolve-Path $DeploymentRoot).Path
$venvPython = Join-Path $deployment 'venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) { throw 'Staged deployment Python is missing.' }
if ([string]::IsNullOrWhiteSpace($DataDir)) { $DataDir = Join-Path $repoRoot '.streamops\node' }
$status = Invoke-RestMethod 'http://127.0.0.1:8765/api/v1/obs/process/status' -TimeoutSec 10
if ($status.output.streaming -or $status.output.recording) { throw 'Deployment is blocked while OBS output is active.' }
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
$backupRoot = Join-Path $deployment ('activation-backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $backupRoot | Out-Null
Export-ScheduledTask -TaskName $TaskName | Set-Content -LiteralPath (Join-Path $backupRoot 'task.xml') -Encoding Unicode
@{ collected_at_utc = (Get-Date).ToUniversalTime().ToString('o'); output = $status.output } |
    ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $backupRoot 'output-idle.json') -Encoding UTF8
$previousDeployment = if ([string]::IsNullOrWhiteSpace($RollbackDeploymentRoot)) {
    $null
} else {
    (Resolve-Path $RollbackDeploymentRoot).Path
}
@{ rollback_deployment = $previousDeployment; task_name = $TaskName; task_xml_authoritative = $true } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $backupRoot 'rollback.json') -Encoding UTF8
# Recheck immediately before switching the server; the initial preflight
# alone is stale if an OBS output started while we saved rollback evidence.
$statusBeforeStop = Invoke-RestMethod 'http://127.0.0.1:8765/api/v1/obs/process/status' -TimeoutSec 10
if ($statusBeforeStop.output.streaming -or $statusBeforeStop.output.recording) {
    throw 'OBS output became active after deployment preflight; aborting without switching server.'
}
& (Join-Path $PSScriptRoot 'stop-streamops-node.ps1') -DataDir $DataDir -TaskName $TaskName
try {
    & (Join-Path $PSScriptRoot 'start-streamops-node.ps1') -TaskName $TaskName -DataDir $DataDir `
        -PythonPath $venvPython -ObsPluginSourceProvider 'github-release' `
        -ObsPluginSourceLocation 'Synclab-VN-dev/StreamOps-OBS-Plugins'
    Invoke-RestMethod 'http://127.0.0.1:8765/api/v1/obs/plugins' -TimeoutSec 20 | Out-Null
    Invoke-RestMethod 'http://127.0.0.1:8765/api/v1/obs/plugins/obs-multi-rtmp' -TimeoutSec 20 | Out-Null
    $catalog = Invoke-RestMethod 'http://127.0.0.1:8765/api/v1/obs/plugins/available' -TimeoutSec 20
    if ($ExpectEmptyCatalog -and ($catalog.source_state -ne 'EMPTY' -or @($catalog.plugins).Count -ne 0)) {
        throw 'Managed repository is expected to be empty, but catalog did not fail closed as EMPTY.'
    }
}
catch {
    & (Join-Path $PSScriptRoot 'rollback-streamops-node-deployment.ps1') `
        -TaskXmlPath (Join-Path $backupRoot 'task.xml') -PreflightEvidencePath (Join-Path $backupRoot 'output-idle.json') `
        -DataDir $DataDir -TaskName $TaskName -MaintenanceApproved
    throw
}
Write-Host "ACTIVE_DEPLOYMENT=$deployment"
Write-Host "ROLLBACK_TASK_XML=$(Join-Path $backupRoot 'task.xml')"
