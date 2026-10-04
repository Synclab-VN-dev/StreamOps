# StreamOps-managed repo-local bootstrap script.
[CmdletBinding()]
param(
    [switch]$Dev,
    [switch]$ConfigureFirewall,
    [switch]$ConfigureObsPluginLifecycle
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$venvRoot = Join-Path $repoRoot ".venv"
$python = Join-Path $venvRoot "Scripts\python.exe"

function Assert-Administrator([string]$Option) {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "$Option requires an explicitly elevated PowerShell session."
    }
}

if (-not (Test-Path -LiteralPath $python)) {
    Write-Host "Creating repo-local virtual environment: $venvRoot"
    & python -m venv $venvRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Could not create the repo-local virtual environment."
    }
}

$extras = if ($Dev) { "server,dev" } else { "server" }
Write-Host "Installing StreamOps from the current repository ($extras)..."
Push-Location $repoRoot
try {
    & $python -m pip install --editable ".[${extras}]"
    if ($LASTEXITCODE -ne 0) {
        throw "StreamOps installation failed."
    }
}
finally {
    Pop-Location
}

if ($ConfigureFirewall) {
    Assert-Administrator "-ConfigureFirewall"

    $ruleName = "StreamOps Node (repo-local)"
    $rule = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
    if ($null -eq $rule) {
        New-NetFirewallRule `
            -DisplayName $ruleName `
            -Direction Inbound `
            -Action Allow `
            -Enabled True `
            -Profile Private `
            -Program $python `
            -RemoteAddress LocalSubnet | Out-Null
    }
    else {
        $rule | Set-NetFirewallRule -Direction Inbound -Action Allow -Enabled True -Profile Private | Out-Null
        $rule | Get-NetFirewallApplicationFilter | Set-NetFirewallApplicationFilter -Program $python | Out-Null
        $rule | Get-NetFirewallAddressFilter | Set-NetFirewallAddressFilter -RemoteAddress LocalSubnet | Out-Null
    }
    Write-Host "Firewall rule ready: $ruleName"
}

if ($ConfigureObsPluginLifecycle) {
    Assert-Administrator "-ConfigureObsPluginLifecycle"
    $interactiveUser = (Get-CimInstance Win32_ComputerSystem).UserName
    if ([string]::IsNullOrWhiteSpace($interactiveUser)) {
        throw "No interactive Windows user is logged on."
    }
    $account = [Security.Principal.NTAccount]::new($interactiveUser)
    $sid = $account.Translate([Security.Principal.SecurityIdentifier]).Value
    $pluginRoot = Join-Path $env:ProgramData "obs-studio\plugins\obs-multi-rtmp"
    New-Item -ItemType Directory -Path $pluginRoot -Force | Out-Null
    & icacls.exe $pluginRoot /grant ("*{0}:(OI)(CI)M" -f $sid) | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Could not grant the interactive StreamOps user access to the managed plugin directory."
    }
    Write-Host "OBS plugin lifecycle directory ready: $pluginRoot"
}

Write-Host "Repo-local StreamOps node is ready."
Write-Host "Run: $python -m streamops.cli runserver --port 8765"
