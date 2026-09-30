# StreamOps-managed repo-local stop script.
[CmdletBinding()]
param(
    [string]$DataDir,
    [string]$TaskName = "StreamOps Node (repo-local)"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path

function Get-RepoOwnedProcess([int]$ProcessId) {
    $candidate = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($null -eq $candidate) {
        return $null
    }
    if (-not [string]::IsNullOrWhiteSpace($candidate.Path) -and
        $candidate.Path.StartsWith($repoRoot, [StringComparison]::OrdinalIgnoreCase)) {
        return $candidate
    }
    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if ($null -eq $processInfo) {
        return $null
    }
    $parent = Get-Process -Id $processInfo.ParentProcessId -ErrorAction SilentlyContinue
    if ($null -ne $parent -and -not [string]::IsNullOrWhiteSpace($parent.Path) -and
        $parent.Path.StartsWith($repoRoot, [StringComparison]::OrdinalIgnoreCase)) {
        return $candidate
    }
    return $null
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
if ($null -ne $task -and $task.State -eq "Running") {
    Stop-ScheduledTask -TaskName $TaskName
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        Start-Sleep -Milliseconds 250
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($null -eq $task -or $task.State -ne "Running") {
            break
        }
    }
}

if (-not (Test-Path -LiteralPath $runtimePath)) {
    Write-Host "streamops-node is already stopped."
    exit 0
}

$runtime = Get-Content -LiteralPath $runtimePath -Raw | ConvertFrom-Json
$runningProcess = Get-Process -Id $runtime.pid -ErrorAction SilentlyContinue
if ($null -eq $runningProcess) {
    Remove-Item -LiteralPath $runtimePath -Force
    Write-Host "Removed stale runtime state; streamops-node was not running."
    exit 0
}

if ($null -eq (Get-RepoOwnedProcess $runtime.pid)) {
    throw "Refusing to stop PID $($runtime.pid): its executable is not owned by this repository."
}

Stop-Process -Id $runtime.pid -Force
Wait-Process -Id $runtime.pid -Timeout 10 -ErrorAction SilentlyContinue
if (Test-Path -LiteralPath $runtimePath) {
    $current = Get-Content -LiteralPath $runtimePath -Raw | ConvertFrom-Json
    if ($current.pid -eq $runtime.pid) {
        Remove-Item -LiteralPath $runtimePath -Force
    }
}
Write-Host "streamops-node stopped (PID $($runtime.pid))."
