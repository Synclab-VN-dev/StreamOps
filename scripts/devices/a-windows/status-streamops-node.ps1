# StreamOps-managed repo-local status script.
[CmdletBinding()]
param(
    [string]$DataDir,
    [string]$TaskName = "StreamOps Node (repo-local)"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path

function Test-RepoOwnedProcess([int]$ProcessId) {
    $candidate = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($null -eq $candidate) {
        return $false
    }
    if (-not [string]::IsNullOrWhiteSpace($candidate.Path) -and
        $candidate.Path.StartsWith($repoRoot, [StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }
    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if ($null -eq $processInfo) {
        return $false
    }
    $parent = Get-Process -Id $processInfo.ParentProcessId -ErrorAction SilentlyContinue
    return $null -ne $parent -and -not [string]::IsNullOrWhiteSpace($parent.Path) -and
        $parent.Path.StartsWith($repoRoot, [StringComparison]::OrdinalIgnoreCase)
}

function Get-ProbeHost([string]$HostName) {
    if ($HostName -ne "0.0.0.0") {
        return $HostName
    }

    $routes = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix "0.0.0.0/0" `
        -ErrorAction SilentlyContinue | Sort-Object RouteMetric
    foreach ($route in $routes) {
        $address = Get-NetIPAddress -AddressFamily IPv4 -InterfaceIndex $route.InterfaceIndex `
            -AddressState Preferred -ErrorAction SilentlyContinue |
            Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
            Select-Object -First 1
        if ($null -ne $address) {
            return $address.IPAddress
        }
    }

    $address = Get-NetIPAddress -AddressFamily IPv4 -AddressState Preferred `
        -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
        Select-Object -First 1
    if ($null -ne $address) {
        return $address.IPAddress
    }
    return "127.0.0.1"
}
if ([string]::IsNullOrWhiteSpace($DataDir)) {
    $DataDir = Join-Path $repoRoot ".streamops\node"
}
elseif (-not [IO.Path]::IsPathRooted($DataDir)) {
    $DataDir = [IO.Path]::GetFullPath((Join-Path $repoRoot $DataDir))
}
$DataDir = [IO.Path]::GetFullPath($DataDir)
$repoPrefix = $repoRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
if (-not $DataDir.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "DataDir must stay inside the repository: $repoRoot"
}

$runtimePath = Join-Path $DataDir "runtime.json"
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
$taskState = if ($null -eq $task) { "NotRegistered" } else { [string]$task.State }
if (-not (Test-Path -LiteralPath $runtimePath)) {
    Write-Host "streamops-node is not running (task $taskState, no runtime state)."
    exit 1
}

$runtime = Get-Content -LiteralPath $runtimePath -Raw | ConvertFrom-Json
$process = Get-Process -Id $runtime.pid -ErrorAction SilentlyContinue
if ($null -eq $process -or -not (Test-RepoOwnedProcess $runtime.pid)) {
    Write-Host "streamops-node is not running (stale runtime state for PID $($runtime.pid))."
    exit 1
}

$probeHost = Get-ProbeHost $runtime.host
$healthUrl = "http://${probeHost}:$($runtime.port)/api/v1/health"
try {
    $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2
}
catch {
    Write-Host "streamops-node process $($runtime.pid) exists but health check failed: $healthUrl"
    exit 1
}

if ($health.session_id -ne $health.active_console_session_id) {
    Write-Host "streamops-node is in the wrong desktop session ($($health.session_id); active $($health.active_console_session_id))."
    exit 1
}
if (-not $health.capture_ready) {
    Write-Host "streamops-node is online in session $($health.session_id), but capture is unavailable."
    exit 1
}

Write-Host "streamops-node is running (PID $($runtime.pid), session $($health.session_id), port $($runtime.port), output $($runtime.output_index), capture $($health.capture_backend))."
Write-Host "Task: $TaskName ($taskState)"
Write-Host "Health: $healthUrl"
exit 0
