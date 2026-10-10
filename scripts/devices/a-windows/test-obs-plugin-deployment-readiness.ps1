# Read-only deployment/provider/API evidence. Emits JSON and writes nothing.
[CmdletBinding()]
param([string]$TaskName = 'StreamOps Node (repo-local)')
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$base = 'http://127.0.0.1:8765'
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
$process = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'streamops\.cli.+runserver' }
$processEvidence = @($process | ForEach-Object {
    $deployment = Split-Path (Split-Path (Split-Path $_.ExecutablePath -Parent) -Parent) -Parent
    $metadataPath = Join-Path $deployment 'deployment.json'
    $sourceCommit = $null
    if (Test-Path -LiteralPath $metadataPath -PathType Leaf) {
        $sourceCommit = (Get-Content -LiteralPath $metadataPath -Raw | ConvertFrom-Json).source_commit
    }
    [ordered]@{ pid=$_.ProcessId; executable=$_.ExecutablePath; deployment_root=$deployment; source_commit=$sourceCommit }
})
$pluginRoot = Join-Path $env:ProgramData 'obs-studio\plugins\obs-multi-rtmp'
$files = @()
if (Test-Path -LiteralPath $pluginRoot) {
    $files = @(Get-ChildItem -LiteralPath $pluginRoot -Recurse -File | Sort-Object FullName | ForEach-Object {
        [ordered]@{ path=$_.FullName; length=$_.Length; sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash }
    })
}
$headers = @{'User-Agent'='StreamOps-Deployment-Readiness';'Accept'='application/vnd.github+json'}
$releases = Invoke-RestMethod 'https://api.github.com/repos/Synclab-VN-dev/StreamOps-OBS-Plugins/releases?per_page=100' -Headers $headers -TimeoutSec 20
[ordered]@{
    collected_at_utc=(Get-Date).ToUniversalTime().ToString('o')
    task=[ordered]@{name=$task.TaskName;state=[string]$task.State;actions=@($task.Actions|ForEach-Object{[ordered]@{execute=$_.Execute;arguments=$_.Arguments;working_directory=$_.WorkingDirectory}})}
    processes=$processEvidence
    obs_status=(Invoke-RestMethod "$base/api/v1/obs/process/status" -TimeoutSec 10)
    inventory=(Invoke-RestMethod "$base/api/v1/obs/plugins" -TimeoutSec 20)
    plugin=(Invoke-RestMethod "$base/api/v1/obs/plugins/obs-multi-rtmp" -TimeoutSec 20)
    catalog=(Invoke-RestMethod "$base/api/v1/obs/plugins/available" -TimeoutSec 20)
    managed_release_count=@($releases).Count
    plugin_files=$files
} | ConvertTo-Json -Depth 12
