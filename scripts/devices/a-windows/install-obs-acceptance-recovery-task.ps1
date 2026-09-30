# Installs the opt-in, PID-bound OBS acceptance recovery task.
[CmdletBinding()]
param(
    [string]$TaskName = "StreamOps PR19 Close Idle OBS",
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$worker = (Resolve-Path (Join-Path $PSScriptRoot "invoke-obs-acceptance-recovery.ps1")).Path
$evidenceRoot = Join-Path $repoRoot ".streamops\pr19-acceptance"
$requestPath = Join-Path $evidenceRoot "recovery-request.json"
$resultPath = Join-Path $evidenceRoot "recovery-result.json"

if ($Remove) {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($null -ne $existing) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Removed OBS acceptance recovery task: $TaskName"
    }
    else {
        Write-Host "OBS acceptance recovery task is already absent: $TaskName"
    }
    exit 0
}

$interactiveUser = (Get-CimInstance Win32_ComputerSystem).UserName
if ([string]::IsNullOrWhiteSpace($interactiveUser)) {
    throw "No interactive Windows user is logged on."
}

$windowsPowerShell = (Get-Command powershell.exe -ErrorAction Stop).Source
New-Item -ItemType Directory -Path $evidenceRoot -Force | Out-Null

function ConvertTo-TaskArgument([string]$Value) {
    return '"' + $Value.Replace('"', '\"') + '"'
}

$actionArguments = @(
    "-NoLogo", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
    "-ExecutionPolicy", "Bypass",
    "-File", (ConvertTo-TaskArgument $worker),
    "-RequestPath", (ConvertTo-TaskArgument $requestPath),
    "-ResultPath", (ConvertTo-TaskArgument $resultPath)
) -join " "

$action = New-ScheduledTaskAction `
    -Execute $windowsPowerShell `
    -Argument $actionArguments `
    -WorkingDirectory $repoRoot
$principal = New-ScheduledTaskPrincipal `
    -UserId $interactiveUser `
    -LogonType Interactive `
    -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([TimeSpan]::FromMinutes(1)) `
    -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries
$definition = New-ScheduledTask `
    -Action $action `
    -Principal $principal `
    -Settings $settings `
    -Description "PID-bound graceful recovery for the opt-in StreamOps OBS acceptance harness."

Register-ScheduledTask -TaskName $TaskName -InputObject $definition -Force | Out-Null
Write-Host "OBS acceptance recovery task ready: $TaskName"
Write-Host "Interactive user: $interactiveUser"
Write-Host "Worker: $worker"
