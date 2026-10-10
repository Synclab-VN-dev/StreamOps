# Restore a previously captured StreamOps scheduled-task definition.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$TaskXmlPath,
    [Parameter(Mandatory)][string]$PreflightEvidencePath,
    [Parameter(Mandatory)][switch]$MaintenanceApproved,
    [string]$TaskName = 'StreamOps Node (repo-local)',
    [Parameter(Mandatory)][string]$DataDir
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if (-not $MaintenanceApproved) { throw 'Explicit -MaintenanceApproved is required.' }
$xmlPath = (Resolve-Path $TaskXmlPath).Path
$evidencePath = (Resolve-Path $PreflightEvidencePath).Path
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$allowedRoot = [IO.Path]::GetFullPath((Join-Path $repoRoot '.streamops\deployments')).TrimEnd('\') + '\'
if (-not $xmlPath.StartsWith($allowedRoot, [StringComparison]::OrdinalIgnoreCase) -or
    -not $evidencePath.StartsWith($allowedRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Rollback task evidence must be under the managed deployments directory.'
}
$idleEvidence = Get-Content -LiteralPath $evidencePath -Raw | ConvertFrom-Json
if ($null -eq $idleEvidence.output -or $idleEvidence.output.streaming -or $idleEvidence.output.recording) {
    throw 'Rollback preflight does not prove idle OBS outputs.'
}
$status = $null
try {
    $status = Invoke-RestMethod 'http://127.0.0.1:8765/api/v1/obs/process/status' -TimeoutSec 5
} catch {
    # The new server may not have started. The activation-owned, local evidence
    # above was captured immediately before the server switch.
}
if ($null -ne $status -and ($status.output.streaming -or $status.output.recording)) {
    throw 'Rollback is blocked while OBS output is active.'
}
& (Join-Path $PSScriptRoot 'stop-streamops-node.ps1') -DataDir $DataDir -TaskName $TaskName
$xml = Get-Content -LiteralPath $xmlPath -Raw
Register-ScheduledTask -TaskName $TaskName -Xml $xml -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    Start-Sleep -Milliseconds 500
    try {
        $health = Invoke-RestMethod 'http://127.0.0.1:8765/api/v1/health' -TimeoutSec 2
        if ($health.status -eq 'ok') { Write-Host 'SERVER_ROLLBACK=PASS'; exit 0 }
    } catch {}
}
throw 'Rolled-back StreamOps task did not become healthy.'
