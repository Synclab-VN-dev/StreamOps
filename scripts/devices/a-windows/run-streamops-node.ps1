# StreamOps-managed repo-local Scheduled Task action.
[CmdletBinding()]
param(
    [string]$BindHost = "0.0.0.0",
    [ValidateRange(1, 65535)]
    [int]$Port = 8765,
    [ValidateRange(0, 2147483647)]
    [int]$OutputIndex = 0,
    [Parameter(Mandatory)]
    [string]$DataDir,
    [string]$PythonPath,
    [ValidateRange(0.01, 30)]
    [double]$CaptureTimeout = 3,
    [ValidateSet("critical", "error", "warning", "info", "debug", "trace")]
    [string]$LogLevel = "info"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$python = if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    Join-Path $repoRoot ".venv\Scripts\python.exe"
} elseif ([IO.Path]::IsPathRooted($PythonPath)) {
    [IO.Path]::GetFullPath($PythonPath)
} else {
    [IO.Path]::GetFullPath((Join-Path $repoRoot $PythonPath))
}
if (-not (Test-Path -LiteralPath $python)) {
    throw "Configured Python interpreter is missing: $python"
}

$DataDir = [IO.Path]::GetFullPath($DataDir)
$repoPrefix = $repoRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
if (-not $DataDir.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "DataDir must stay inside the repository: $repoRoot"
}
if (-not $python.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "PythonPath must stay inside the repository-managed runtime area: $repoRoot"
}

$logDir = Join-Path $DataDir "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$stdoutLog = Join-Path $logDir "node-$timestamp.stdout.log"
$stderrLog = Join-Path $logDir "node-$timestamp.stderr.log"
$arguments = @(
    "-m", "streamops.cli", "runserver",
    "--host", $BindHost,
    "--port", $Port,
    "--output-index", $OutputIndex,
    "--data-dir", $DataDir,
    "--capture-timeout", $CaptureTimeout.ToString([Globalization.CultureInfo]::InvariantCulture),
    "--log-level", $LogLevel
)

Push-Location $DataDir
try {
    & $python @arguments 1>> $stdoutLog 2>> $stderrLog
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
